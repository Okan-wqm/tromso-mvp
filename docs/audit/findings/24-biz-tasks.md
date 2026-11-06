# 24 - biz-tasks: Görevler, tekrarlayan görevler, zamanlama, durum geçişleri, atama

## Özet

`tasks/` uygulaması (models, services, read, forms, resources, views, places) baştan sona okundu. Genel kalite yüksek:
durum geçişleri yalnızca `tasks/services.py` üzerinden, satır kilidi (`select_for_update`) ve DB CHECK kısıtlarıyla
korunuyor; gecikme (overdue) saklanmıyor, site saatine göre okuma anında hesaplanıyor; tekrar kuralı (`TaskSeries.dates`)
ilk güne çıpalı ve drift etmiyor. Başlıca bulgu: tekrarlayan görev silinip geri yüklendiğinde planlı görevlerin
kalıcı olarak kaybolması (soft-delete + `materialise` "taken" mantığı çakışması). Ayrıca tek bir bozuk serinin tüm
Görevler sayfasını/overview'ı düşürebilmesi, GET ile yazma, `withdraw` yarışı ve bazı küçük tutarsızlıklar kaydedildi.
Testler ortamda Django kurulu olmadığı için çalıştırılamadı (kod okuması yapıldı).

## İncelenen alanlar

- `tasks/models.py` (kısıtlar, `dates`, `next_date`, `planned`, `deleted_with`), `tasks/services.py` (start/complete/cancel/reopen/tick/add_note/materialise/withdraw/replan)
- `tasks/read.py` (overdue/due_today/done_today, görünümler, sayımlar), `tasks/forms.py`, `tasks/resources.py`, `tasks/views.py`, `tasks/places.py`, `tasks/screens.py`, `generate_tasks` komutu
- `core/softdelete.py`, `core/models.py` (AuditedModel), `core/crud.py` (Create/UpdateView), `farm/clocks.py`, `farm/stock/dates.py`, `core/people.py`, `core/fields.py`
- README "Operations > Tasks" bölümü ve `docs/aquaculture-platform-bugs.md` TSK-01..23 ile karşılaştırma

## İncelenmeyen alanlar

- Şablonlar (`templates/tasks/*`), `tasks/templatetags`, migration SQL ayrıntıları (yalnızca kısıt sayısı karşılaştırıldı)
- Testlerin çalıştırılması (Django ortamda yok), canlı DB davranışı
- Yetki matrisinin (`config/access.py`) ayrıntıları, bildirim/AI/otomatik kural entegrasyonları (MVP dışı)

## Bulgular

### 24-1 - Tekrarlayan görev silinip geri yüklenince planlı görevleri kalıcı kaybolur
- Önem: medium, Güven: high
- Dosyalar: `tasks/services.py:234`, `core/softdelete.py:174-203`, `tasks/models.py:445-449`, `core/admin.py:39-51`
- Açıklama: Seri silinince (yer silme veya seri silme) dokunulmamış planlı görevler `Task.deleted_with` ile soft-delete edilir. `softdelete.restore` yalnızca kaydın kendisini geri getirir. `materialise` ise `Task.all_objects` ile soft-delete edilmiş günleri de "taken" sayıp atlar (README: "bir kişinin sildiği görev tekrar yapılmaz"). Sistemin sildiği ile kişinin sildiği ayrımı yok.
- Kanıt: `taken = set(Task.all_objects.filter(series=series, occurrence_date__in=days)...)` (services.py:234); restore "Only the record itself returns" (softdelete.py:190-193).
- Öneri: Seriyle birlikte silinen görevleri ayırt et (deleted_by/neden) ve restore'da geri getir ya da `taken` hesabında yalnızca kişi tarafından silinenleri say.

### 24-2 - Tek bir bozuk seri tüm Görevler sayfalarını ve overview'ı düşürebilir
- Önem: medium, Güven: medium
- Dosyalar: `tasks/services.py:257-262`, `tasks/resources.py:92,226`, `tasks/views.py:142`
- Açıklama: `materialise_due` her seri için `materialise` çağırır, istisna yakalanmaz. Bir serideki hata (ör. IntegrityError, veri bozukluğu) liste sayfalarında ve üretim overview'ında 500'e yol açar; TSK-14 "bir şablon koşuyu zehirlemesin" hedefi yalnızca transaction düzeyinde karşılanmış, hata izolasyonu yok.
- Kanıt: `return [task for series in behind for task in materialise(series)]` try/except yok.
- Öneri: Seri başına try/except + log; hatalı seri sayfaları engellemesin.

### 24-3 - Okuma (GET) sırasında yazma: yalnızca görüntüleme yetkisi olan kullanıcı görev üretir
- Önem: low, Güven: high
- Dosyalar: `tasks/resources.py:92,226`, `tasks/views.py:142`, `tasks/services.py:228-255`
- Açıklama: Her liste/overview GET isteği kilit alıp görev, checklist ve audit satırı yazabilir; salt okuma yetkili kullanıcı da tetikler. Cron (`generate_tasks`) varken istek yolunda üretim gecikme/kilit çekişmesi yaratır.
- Kanıt: `filter_list` içinde `services.materialise_due()`; `overview_tiles` içinde aynısı.
- Öneri: Üretimi cron/arka plana al; sayfada yalnızca gerekirse (yaşlanmış `generated_until`) tetikle.

### 24-4 - `materialise_due` "geride" ölçütü farklı saat dilimlerinde sürekli yeniden çalıştırır
- Önem: low, Güven: medium
- Dosyalar: `tasks/services.py:260-262`
- Açıklama: `latest = max(clock.today) + horizon`; her seri kendi site gününe göre `generated_until = site_today + horizon` yazar. Günü daha geride olan saat dilimindeki seriler `generated_until < latest` kalır ve saatlerce her sayfa yüklemesinde kilitlenip `save` edilir.
- Kanıt: `exclude(generated_until__gte=latest)` ile `materialise` içindeki `last = today(site) + horizon` farklı gün tabanları kullanır.
- Öneri: Karşılaştırmayı serinin kendi site gününe göre yap.

### 24-5 - `withdraw` kilitsiz aday listesiyle sert silme yapar (yarış)
- Önem: medium, Güven: medium
- Dosyalar: `tasks/services.py:265-271`, `tasks/models.py:424-437`
- Açıklama: `Task.planned` adayları (`version=1`, dokunulmamış) kilitsiz okur; sonra her biri `task.delete()` (sert silme, checklist/atamalar CASCADE) ile silinir. Aradaki sürede biri görevi başlatır/tamamlarsa (`start`/`complete` task'ı kilitler ve version artırır) görev yine silinir, kaydı yalnızca audit'te kalır.
- Kanıt: `for task in Task.planned(...)`: `audit.record_delete`; `task.delete()` yeniden `version`/status doğrulamadan.
- Öneri: Silmeden önce görevi `select_for_update` ile kilitleyip planned koşulunu tekrar doğrula.

### 24-6 - Planlı görevlerin serisi değişince sert silinip yeniden oluşturulması: kimlik ve geri alınabilirlik kaybı
- Önem: low, Güven: high
- Dosyalar: `tasks/services.py:265-285`, `tasks/resources.py:36-38,258-260`
- Açıklama: Seride yalnızca başlık gibi bir alan değişse (veya yalnız checklist kaydedilse) tüm gelecekteki planlı görevler sert silinip yeni UUID ile tekrar yaratılır. `?task=<pk>` bağlantıları kırılır; kişi silmeleri soft-delete/restore edilebilirken bunlar geri getirilemez.
- Kanıt: `withdraw` -> `task.delete()`; `replan` her kayıtta çağrılır (`after_save`, `SeriesChecklist.save`).
- Öneri: Yerinde güncelle (diff) ya da sert yerine soft-delete uygula.

### 24-7 - Atanan kişiler yetkisini kaybedince yeni görevler sessizce atamasız üretilir
- Önem: low, Güven: high
- Dosyalar: `tasks/services.py:236,242`
- Açıklama: `people` yalnızca `read.readers()` ile kesişen atananlardır; hepsi pasif/yetkisiz ise görevler atamasız oluşur, uyarı/log yok. Formda en az bir atanan zorunlu olduğu halde otomatik üretilen görevlerde bu değişmez bozulur.
- Kanıt: `task.assignees.set(people)` boş listeyle çalışabilir; testi `test_people_who_can_no_longer_read_tasks_get_no_new_tasks` davranışı belgeler ama bildirim yok.
- Öneri: Atamasız kalan görevi işaretle/seri listesinde uyar.

### 24-8 - Serinin atanan/başlık değişikliği dokunulmuş görevlere yayılmaz (kasıtlı, fakat belgesiz sapma)
- Önem: info, Güven: medium
- Dosyalar: `tasks/models.py:424-437`, `tasks/services.py:274-287`
- Açıklama: Not eklenmiş, tikli, düzenlenmiş veya başlatılmış görevler eski kural ve atananlarla kalır; kural değiştiğinde (ör. günlük -> haftalık) bugünden önceki dokunulmamış gecikmiş görevler de olduğu gibi kalır. Kullanıcıya hangi görevlerin eski kuralda kaldığı gösterilmiyor.
- Kanıt: `planned` yalnızca `version=1`, açık, notsuz, tiksiz ve bugün/sonrası görevleri alır.
- Öneri: Seri kaydında "N görev değişmedi" bilgisi göster.

### 24-9 - Görev "not eklendi/tik" version'ı artırmaz; edit formundaki iyimser kilit bunları yakalamaz
- Önem: low, Güven: medium
- Dosyalar: `tasks/services.py:190-203`, `tasks/services.py:158-187`, `core/crud.py:725-735`
- Açıklama: `tick` ve `add_note` görevin `version`'ını artırmaz; bu yüzden aynı anda açık edit formu kaydında ikisi de fark edilmez. Etkisi sınırlı (notlar append-only, düzenleme tikleri silmez), ancak edit sırasında checklist'in ilk tiki yarışırsa `TaskChecklistFormSet.clean` kontrolü ile satır değiştirme arasında pencere kalır (kilitsiz kontrol).
- Kanıt: `tick` yalnızca `item.save(update_fields=...)`; formset `clean` kilitsiz `exists()`.
- Öneri: Checklist satırı değişimini görev kilidi altında doğrula.

### 24-10 - Tamamlanan/iptal edilen görevler düzenlenebilir ve checklist'i değişebilir
- Önem: low, Güven: medium
- Dosyalar: `tasks/forms.py:243-250`, `tasks/resources.py:58-72,166-180`
- Açıklama: Edit formu durumdan bağımsızdır: kapalı görevin başlık, due_date, atananları değiştirilebilir (audit'li). Tik hiç atılmamış kapalı görevin checklist'i tamamen değiştirilebilir. "Tamamlandı" kaydının tarihsel doğruluğu yalnız audit'e bağlı.
- Kanıt: `TaskForm.Meta.fields` durum alanı yok ama kapalı durum kontrolü de yok; `TaskChecklistFormSet.clean` yalnızca tik kontrolü yapar.
- Öneri: Kapalı görevi salt-okunur yap veya düzenlemeden önce reopen iste.

### 24-11 - Tamamlama, açık checklist satırlarını denetlemez
- Önem: info, Güven: high
- Dosyalar: `tasks/services.py:117-133`
- Açıklama: `complete` tikli olmayan satırlar varken de görevi tamamlar; uyarı yok. İş kuralı olarak tanımlı olmayabilir ama checklist'in amacıyla (saha kontrol listesi) çelişir.
- Kanıt: `complete` yalnızca durum ve yetkiyi kontrol eder.
- Öneri: Karar belgele; en azından UI'da onay uyarısı.

### 24-12 - `reopen` orijinal başlangıç bilgisini siler ve durum geçişi tek yönlü
- Önem: info, Güven: high
- Dosyalar: `tasks/services.py:151-169`, `tasks/models.py:326-332`
- Açıklama: Devam ediyor görevi tamamlanıp yeniden açılınca `started_at/by` sıfırlanır (yalnız audit'te kalır); "in_progress -> open" geri dönüş yolu yok (yanlış Start geri alınamaz, yalnız cancel+reopen).
- Kanıt: `task.started_at = task.started_by = ... = None` (reopen).
- Öneri: İhtiyaca göre "stop/unstart" ekle veya karar belgele.

### 24-13 - `add_note` servisinde yetki kontrolü yok; yalnız view'a bağlı
- Önem: low, Güven: high
- Dosyalar: `tasks/services.py:190-203`, `tasks/views.py:62-72`
- Açıklama: Diğer servislerin aksine `add_note` kullanıcı yetkisine bakmaz ("view checks it"); gelecekteki API/asistan çağrıları (modül başlığı bunları öngörüyor) kontrolü atlayabilir. Ayrıca silinmiş göreve yarış durumunda `_locked` DoesNotExist (500) verir.
- Kanıt: `add_note` içinde `has_perm` çağrısı yok; `_locked` `Task.objects` (silinmişleri gizler).
- Öneri: Yetkiyi serviste zorunlu kıl.

### 24-14 - `complete`/`cancel` servisleri not ve neden uzunluğunu doğrulamaz
- Önem: low, Güven: medium
- Dosyalar: `tasks/services.py:117-148`, `tasks/models.py:317-325`
- Açıklama: Sınır (1000/500) yalnız `CompleteForm`/`CancelForm`'da; servis doğrudan (API/asistan) çağrılırsa PostgreSQL `DataError` (500) oluşur, `add_note` ise uzunluğu servis içinde kontrol ediyor: tutarsız.
- Kanıt: `add_note` `len(body) > MAX_LENGTH` kontrolü var; `complete`/`cancel` yok.
- Öneri: Uzunluk kontrolünü servise taşı.

### 24-15 - `shared_today()` ve `clocks()` farklı site kümelerini kullanır
- Önem: info, Güven: medium
- Dosyalar: `tasks/forms.py:29-34`, `farm/clocks.py:37-40`
- Açıklama: Form varsayılan günü `Site.objects` (silinmemiş) saat dilimlerinden, okuma ise `Site.all_objects` kümesinden hesaplar; ayrıca çok dilimli kurulumda forma şirket saati verilir. Yalnız varsayılan tarihi etkiler.
- Kanıt: `zones = {zone_of(site) for site in Site.objects.all()}` ile `Site.all_objects.only(...)`.
- Öneri: Aynı kaynağı kullan.

### 24-16 - Atama filtresi, artık seçilemeyen kullanıcıların görevlerini süzemez
- Önem: info, Güven: high
- Dosyalar: `tasks/resources.py:112-117`
- Açıklama: `assignee` filtresi yalnızca `read.readers()` içindeki kullanıcıları kabul eder; yetkisi alınmış/pasif kullanıcıya atanmış görevler (README: "kalır, işaretli") kişiye göre filtrelenemez.
- Kanıt: `params['assignee'] in {str(pk) for pk in people.values_list('pk', flat=True)}`.
- Öneri: Filtre seçeneklerine mevcut atananları da ekle.

### 24-17 - Yalnızca silinmemiş görev sayıları/overview satır kapsamı yok
- Önem: info, Güven: low
- Dosyalar: `tasks/views.py:138-146`, `tasks/resources.py:76-81`
- Açıklama: Görev kaynağı `scoped` ile satır kapsamı uygulamaz; yalnız rol matrisi var. Site bazlı sınırlama istenirse overview sayıları (`Task.objects.all()`) ve tüm aksiyon view'ları (`_task(pk)`) tüm sitelerin görevlerini görür. Mevcut tasarım (HR dışında scope yok) ile tutarlı olduğu için bilgi amaçlı.
- Kanıt: `read.counts(Task.objects.all())`; `_task` yalnızca `get_object_or_404`.
- Öneri: Çok-site yetkilendirmesi gelirse buraya da uygula.
