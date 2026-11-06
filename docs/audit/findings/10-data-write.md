# 10 - Veri yazma (data-write) denetimi

## Özet

Kapsam: formlar, validasyon, create/update/delete view'ları (`core/crud.py`), RowList toplu satır kaydı, `resources` (tab bildirimleri), servis katmanları (inventory, hr, tasks, messaging, reports, experiments, feeding), toplu işlemler (HR vardiya planı, sayım, tasarım/yer kaydı) ve yarış durumları. Kod ve veri değiştirilmedi; yalnızca okuma yapıldı.

Genel izlenim: Yazma yolu olgun. Ortak CRUD katmanı iyimser kilit (`version`), `select_for_update`, aynı transaction'da audit satırı, `entry_key` ile çift gönderim koruması ve koşullu constraint doğrulaması içeriyor; stok/envanter/su/besleme/HR servisleri tek yazma yolu ve kilit sırası ile tasarlanmış. Bulgular çoğunlukla ortak katmandaki (`core/crud.py`) bir kaç yarış penceresi, kota kontrolü gibi kilitsiz "oku-sonra-yaz" kontrolleri, GET isteğinin yazma yapması ve birkaç tutarsızlıktan oluşuyor. Kritik/yüksek bulgu yok.

Bulgu sayısı: 14 (orta: 5, düşük: 8, bilgi: 1).

## İncelenen alanlar

- `core/crud.py` (CreateView/UpdateView/DeleteView/RowListView, TabbedForm, RowList), `core/softdelete.py`, `core/audit.py`, `core/codes.py`, `core/forms.py`, `core/resources.py`, `core/admin.py`, `core/models.py` (AuditedModel)
- `inventory/services.py`, `inventory/forms.py`, `inventory/views.py`
- `hr/services.py`, `hr/views.py`, `hr/forms/leave.py`, `hr/forms/employee.py`, `hr/forms/attendance.py`, `hr/leave.py`, `hr/resources/*`
- `tasks/services.py`, `tasks/forms.py`, `tasks/resources.py`, `tasks/views.py`
- `messaging/services.py`
- `reports/services.py`, `reports/forms.py`, `reports/resources.py`, `reports/models.py` (constraint/clean)
- `experiments/services.py` (kısmen), `experiments/resources.py`, `experiments/forms.py` (kısmen)
- `monitoring/forms.py`, `monitoring/resources.py`, `monitoring/views.py`
- `knowledge/views.py`, `knowledge/resources/entry.py`
- `farm/feeding/services.py`, `farm/feeding/views.py`, `farm/stock/services.py` (`locked`, `_commit` başı)

## İncelenmeyen / sınırlı incelenen alanlar

- `farm/forms/*` (stok, su, sağlık, hasat, yem protokolü, ekipman) ve `farm/health`, `farm/water/services.py`, `farm/handling`, `farm/harvest` servisleri: yalnızca ortak desen düzeyinde; satır satır okunmadı.
- `experiments/services.py` ve `experiments/forms.py` büyük bölümü; `knowledge` dosya yükleme/çıkarma (dosya yükleme alanı başka uzmanın kapsamı).
- Testler çalıştırılmadı, gerçek veritabanı üzerinde yarış senaryosu denenmedi: yarış bulguları kod okumasına dayanır.
- `reports/exports.py`, `reports/compute/*` (hesaplama okuma yolu), TypeScript ön yüz.

## Bulgular

### 10-1 - UpdateView ve RowListView, kilit altında kayıt bulunamazsa 500 verir
- Önem: orta, Güven: yüksek
- Dosyalar: `core/crud.py:724`, `core/crud.py:815`
- Açıklama: `UpdateView.post` ve `RowListView.post`, kaydı önce `get_object` (404 üretir) ile okur, sonra kilit için `r.visible(request).select_for_update(of=('self',)).get(pk=pk)` çağırır. Bu iki okuma arasında kayıt başka biri tarafından silinirse (soft delete) ikinci sorgu `DoesNotExist` fırlatır ve yakalanmaz. `DeleteView` aynı yerde `get_object_or_404` kullanıyor, yani üç view tutarsız.
- Kanıt: `current = r.visible(request).select_for_update(of=('self',)).get(pk=pk)   # not the joined rows` (satır 724) ve satır 815; ikisinde de `try/except ObjectDoesNotExist` ya da `get_object_or_404` yok.
- Öneri: İki yerde de `get_object_or_404(r.visible(request).select_for_update(of=('self',)), pk=pk)` kullanın veya kayıt silinmişse "başkası sildi" mesajı gösterin.

### 10-2 - UpdateView ve RowListView veritabanı constraint ihlalini (IntegrityError) yakalamıyor
- Önem: orta, Güven: yüksek
- Dosyalar: `core/crud.py:715-757`, `core/crud.py:801-833`, karşılaştırma: `core/crud.py:687-702`
- Açıklama: `CreateView` yarışta oluşan unique/exclusion ihlalini yakalayıp `constraint_error` ile forma yazıyor. `UpdateView` aynı yarışı (iki kişi aynı kodu/ismi aynı anda başka kayıtlara veriyor, iki izin talebi çakışıyor) korumasız bırakıyor: form kontrolleri kilit öncesinde yapıldığından ikisi de geçer, ikinci `obj.save()` IntegrityError ile 500 döner. Satır kilidi yalnızca aynı kaydı korur; başka kayıtla çakışma (kısmi unique, `excl_leave_requests_employee_days`, `excl_attendance_employee_span`) korunmaz.
- Kanıt: `UpdateView.post` içinde `try/except IntegrityError` yok; `CreateView.post` satır 687'de var ve `constraint_error` (satır 262 civarı) hazır bir yardımcı.
- Öneri: `UpdateView` kaydını `CreateView` gibi `IntegrityError` -> `constraint_error(form, error)` ile sarın (transaction dışına çıkarak), formu 200 ile yeniden gösterin.

### 10-3 - İzin kotası kontrolü kilitsiz: eşzamanlı talepler yıllık hakkı aşabilir
- Önem: orta, Güven: orta
- Dosyalar: `hr/forms/leave.py:90-100`, `hr/leave.py:60-67`
- Açıklama: `LeaveRequestForm.clean` kalan günleri `leave.used(...)` ile okuyup `used + days > kind.annual_days` ile karşılaştırıyor; bu form doğrulama aşamasında, çalışan satırı kilitlenmeden yapılıyor. Aynı çalışan için iki farklı talep aynı anda gönderilirse (tarihleri çakışmasa da, örn. iki ayrı hafta) ikisi de eski toplamı görür ve ikisi de geçer; toplam `annual_days` aşılabilir. Çakışma için DB exclusion constraint var, kota için yok; kota yalnızca form katmanında.
- Kanıt: `used = leave.used(employee, kind, year, site, exclude=None if adding else self.instance)` / `if used + days > kind.annual_days:` formda; `CreateView` içinde `employee` satırı kilitlenmiyor (`hr/services.py` içindeki servisler `Employee.select_for_update` kullanırken talep oluşturma CRUD yolundan geçiyor).
- Öneri: `LeaveRequestResource.after_save` veya form kaydı içinde çalışan satırını kilitleyip kotayı yeniden kontrol edin (sistemin diğer yerlerindeki "kilit altında yeniden doğrula" deseni).

### 10-4 - Görev kontrol listesi "başlamış mı" kontrolü kilit öncesinde: tik ile eşzamanlı kayıt işaretli satırları siler
- Önem: orta, Güven: orta
- Dosyalar: `tasks/forms.py:224-232`, `core/crud.py:801-833`, `core/crud.py:362-367`, `tasks/services.py:170-186`
- Açıklama: `TaskChecklistFormSet.clean` "satırlardan biri işaretlendiyse liste değiştirilemez" kuralını formset doğrulamasında (kilit öncesi) kontrol ediyor. `RowListView` formset'i doğruladıktan sonra görevi kilitler ve `RowList.save` tüm satırları `delete()` + `bulk_create` ile değiştirir. Doğrulama ile kilit arasında biri `tasks.services.tick` ile bir satırı işaretlerse (tick de aynı görevi kilitler, ama sırada beklemez) görev sürümü `tick` tarafından arttırılmadığı için (`item.save(update_fields=['done_at','done_by'])`, task.version değişmiyor) `RowListView`'in sürüm kontrolü de bunu yakalamaz; işaretleyen kişi ve zaman bilgisi silinir. Bu, kodun kendi yorumunda anlatılan TSK-11 hatasının geri dönüşü.
- Kanıt: `tick` yalnızca `item.save(update_fields=['done_at', 'done_by'])` yapar ve `Task.version` arttırmaz; `TaskChecklistFormSet.clean` kontrolü kilit dışındadır; `RowList.save` satır 364 `cls.rows(obj).delete()`.
- Öneri: "başlamış mı" kontrolünü `RowList.save` içinde (kilit altında) tekrarlayın veya `tick`'te görev sürümünü arttırın.

### 10-5 - GET isteği yazma yapıyor: görev listeleri ve genel bakış `materialise_due()` çağırıyor
- Önem: orta, Güven: yüksek
- Dosyalar: `tasks/resources.py:91-92`, `tasks/resources.py:225-226`, `tasks/views.py:138-142`, `tasks/services.py:256-262`
- Açıklama: Görev listesi, tekrarlayan görev listesi ve üretim genel bakışı kutucukları her açılışta `materialise_due()` ile yeni görev satırı, kontrol listesi satırı, atama ve denetim kaydı yazıyor. Yalnızca "okuma" izni olan bir kullanıcının GET'i bile veritabanına yazar (`created_by` boş, denetim kaydı `user=None`). Bir serinin üretimi hata verirse (örn. unique ihlali) sayfa tamamen 500 olur. Eşzamanlı GET'ler seri satırı kilidinde sıraya girer (bu iyi) ama her sayfa açılışında kilit/yazma maliyeti oluşur. Dosyanın kendisi bunu belgelemiş (`generate_tasks` komutu da var), yani bilinçli ama yan etkili GET.
- Kanıt: `services.materialise_due()` doğrudan `filter_list` ve `overview_tiles` içinde.
- Öneri: Üretimi `generate_tasks` zamanlanmış komutuna bırakın veya GET'te yalnızca bayat olduğunu belirleyip istek dışı bir tetikleyiciyle çalıştırın; hata durumunda sayfayı düşürmeyin.

### 10-6 - Silme planı ile uygulama arasında alt kayıt eklenmesi kilitlenmiyor (yetim kayıt)
- Önem: düşük, Güven: orta
- Dosyalar: `core/crud.py:767-790`, `core/softdelete.py:98-171`, `core/softdelete.py:174-187`
- Açıklama: `DeleteView.post` yalnızca silinen kaydı kilitler (`select_for_update(of=('self',))`). `plan_delete` çocukları kilitsiz okur; `CreateView` ise FK hedefini (örn. üst birim, site) kilitlemez. Silme transaction'ı sürerken başka biri o üst kayda bağlı yeni bir canlı kayıt eklerse (form seçenekleri yarış öncesi canlıydı), plan bunu görmez; sonuçta silinmiş (soft) bir üst kaydı gösteren canlı alt kayıt oluşur. Ayrıca `execute` çocuklara `record.soft_delete(user)` ile tam `save()` yapar; çocuk kayıtlar kilitli olmadığından aynı anda düzenlenen çocuğun değişikliği ezilebilir (sürüm artar ama alanlar eski değerlerle yazılır).
- Kanıt: `_collect` içinde `list(model.objects.filter(**{link: obj}))` kilitsiz; `execute` içinde `record.soft_delete(user)` -> `self.save()` (`core/models.py:52-58`).
- Öneri: Plan çocuklarını `select_for_update` ile alın veya silmede `blockers` kontrolünü aynı transaction'da yeniden yapın; `soft_delete`'i `update_fields` ile sınırlayın.

### 10-7 - RowList her kayıtta satırları silip yeniden yaratıyor: kimlik, oluşturan ve oluşma zamanı kaybolur
- Önem: düşük, Güven: yüksek
- Dosyalar: `core/crud.py:360-372`
- Açıklama: `RowList.save` eski satırları `delete()` edip `bulk_create` ile `created_by=user` olarak yeniden yazar. Değişmeyen satırlar bile yeni kimlik, yeni `created_by` ve yeni `created_at` alır; bir satıra dışarıdan verilen referans (varsa) kopar, satırların kim tarafından ne zaman eklendiği bilgisi her kaydedende kaydedene devredilir. `bulk_create` model `save()` ve `full_clean()` çağırmaz; doğrulama yalnızca formset'e güveniyor. Denetim kaydı satır bazında değil metin özeti olarak tutuluyor. Monitoring board kartlarında silinmiş birimlere ait satırlar da sessizce düşer (`monitoring/forms.py` docstring: "saving the list drops it"), oysa soft-delete belgesi "geri yüklenince kart döner" diyor.
- Kanıt: `cls.rows(obj).delete()` ve `model(**{link: obj, 'created_by': user}, ...)` (satır 364-366).
- Öneri: Değişmeyen satırları koruyup yalnızca farkı yazın (id ile eşleştirme); en azından `created_by/created_at` değerlerini koruyun.

### 10-8 - Kullanıcı ve rol düzenlemesinde sürüm (iyimser kilit) yok; rol silme etkilenen kullanıcıları göstermiyor
- Önem: düşük, Güven: yüksek
- Dosyalar: `core/forms.py:36-80`, `core/resources.py:15-50`, `core/crud.py:767-790`, `templates/crud/confirm_delete.html`
- Açıklama: `User` ve `Group` `AuditedModel` değil; `TabbedForm` `version` alanını modelde yoksa siliyor (`core/crud.py:155`). İki yönetici aynı rolün izin matrisini aynı anda düzenlerse sonuncu kazanır (kayıp güncelleme, uyarı yok). `RoleResource` silmeye açık (`actions` varsayılan): `DeleteView` AuditedModel olmayanlar için `plan=None` ile "kalıcı olarak kaldırır" der ve `Group` sert silinir; role sahip kullanıcılar sayısı/listesi gösterilmez, hepsi sessizce izinlerini kaybeder. `Group.name` unique ama büyük/küçük harf duyarlı.
- Kanıt: `RoleResource` `actions` tanımsız (`core/resources.py:15-24`), `queryset` `user_set` prefetch eder ama silme onayında kullanılmaz; onay şablonu `plan` yoksa yalnızca "This removes it permanently" der.
- Öneri: Rol silmede kullanıcı sayısını gösterin veya kullanımda olan rolü engelleyin; roller için güncelleme zamanı/sürüm kontrolü ekleyin.

### 10-9 - Yeni kullanıcı daveti transaction içinde e-posta gönderiyor ve sonucunu kontrol etmiyor
- Önem: düşük, Güven: yüksek
- Dosyalar: `core/resources.py:62-69`, `core/crud.py:690-700`
- Açıklama: `UserResource.after_save` kayıt transaction'ı içinde çalışır; `invitation.is_valid()` sonucu yok sayılıyor, `invitation.save(...)` SMTP hatasında istisna fırlatırsa tüm kullanıcı oluşturma geri alınır ve kullanıcı 500 görür; tersine commit sonrası başarısız olursa e-posta zaten gitmiş olur (`on_commit` yok). `is_active` işaretsiz yeni kullanıcı için `get_users` hiç kullanıcı bulmaz ve davet sessizce gönderilmez; kullanıcıya uyarı çıkmaz. E-posta tekliği `clean_email` ile uygulanıyor, DB unique yok (yarış mümkün).
- Kanıt: `invitation.is_valid()` dönüş değeri kullanılmıyor; `core/forms.py:120-124` `clean_email` yalnızca form düzeyinde.
- Öneri: Gönderimi `transaction.on_commit` ile yapın, hatayı yakalayıp mesajla bildirin, pasif kullanıcı için uyarı verin.

### 10-10 - İzin talebi formu: "tür oluşturulurken seçilir" belgesi ile kod uyuşmuyor
- Önem: düşük, Güven: yüksek
- Dosyalar: `hr/forms/leave.py:39-42`
- Açıklama: Sınıf açıklaması "the person and the type are chosen once" diyor, ama `fixed_after_creation = ('employee',)` yalnızca çalışanı sabitliyor. Bekleyen talebin türü sonradan değiştirilebiliyor; bu durumda kota yeni türe göre yeniden hesaplanıyor (iyi) ama `needs_approval=False` olan bir türe geçmek talebi otomatik onaylamaz (yalnızca `adding` iken `APPROVED` yapılıyor). Ayrıca `leave_type` kümesi yalnızca `status='active'`: türü sonradan pasifleşen bekleyen bir talep düzenlenirken mevcut tür seçeneklerde bulunmadığı için form hata verir ve talep düzenlenemez.
- Kanıt: `self.fields['leave_type'].queryset = LeaveType.objects.filter(status='active')` (satır 66), `if adding and not kind.needs_approval:` (satır 102).
- Öneri: Ya türü de `fixed_after_creation`'a ekleyin ya da mevcut türü kümeye dahil edip belgeyi düzeltin.

### 10-11 - Otomatik onaylanan izinler çalışanın planlı vardiyalarını bildirmiyor / değiştirmiyor
- Önem: düşük, Güven: orta
- Dosyalar: `hr/forms/leave.py:101-104`, `hr/views.py:119-131`, `hr/services.py` (`decide_leave`)
- Açıklama: Onay gerektiren izinde onay penceresi `read.leave_impact` ile planlı vardiyaları listeler. `needs_approval=False` olan türde talep, form içinde `status=APPROVED`, `decided_at=now` ile doğrudan yaratılır; `decided_by` boş kalır ve izin gününe denk gelen vardiya planları ne listelenir ne uyarı üretir. Çalışan hem izinli hem planlı görünür. Ayrıca `after_save` tarafında denetim kaydı "oluşturuldu" der ama onay izi (kim onayladı) yoktur.
- Kanıt: `self.instance.status = LeaveStatus.APPROVED; self.instance.decided_at = timezone.now()` (satır 102-103); `decide_leave` yolunu kullanmıyor.
- Öneri: Otomatik onayı `services` içinde tek yoldan yapın, çakışan vardiyaları aynı şekilde bildirin.

### 10-12 - Ayrılan çalışan için ayrılış tarihinden sonra yazma engellenmiyor (izin, devam, vardiya)
- Önem: düşük, Güven: düşük
- Dosyalar: `hr/forms/leave.py`, `hr/forms/attendance.py`, `hr/services.py:174-204` (`plan_shifts`), `hr/services.py:92-110` (`leave_company`)
- Açıklama: `left_on` yalnızca çalışan formunda ve `align_placements`/`move` içinde kullanılıyor. İzin, devam kaydı ve vardiya yazma yollarında (`LeaveRequestForm.clean`, `AttendanceRecordForm.clean`, `plan_shifts`) ayrılış tarihinden sonraki günler kontrol edilmiyor; `scope.can_reach` yerleşim (posting) olmayan günde takım üyeliğini düşürdüğü için çoğu lead engellenir, fakat "Everyone" yetkisi olan kullanıcı için `can_reach` her güne izin veriyorsa bu yollar ayrılmış çalışana kayıt yazabilir. `leave_company` ayrıca çalışanın `left_on` sonrasına uzanan onaylı izinlerini/devam kayıtlarını kısaltmaz (yalnızca bekleyen izinleri iptal eder).
- Kanıt: `grep left_on hr/forms/leave.py hr/forms/attendance.py hr/services.py` yalnızca `leave_company`, `align_placements` ve `move` içinde sonuç verir. `scope.can_reach` ALL için davranışı tam doğrulanmadı.
- Öneri: İlgili yazma yollarına `left_on` kontrolü ekleyin; `align_placements`'ın onaylı izinleri de ele alıp almayacağına karar verin.

### 10-13 - `copy_template` ve `close_due`/`record_duty_done`: ön kontrol sonra yaz, yarışta 500
- Önem: düşük, Güven: orta
- Dosyalar: `monitoring/views.py:149-170`, `reports/services.py:114-124`, `reports/services.py:144-166`
- Açıklama: Kopya adı `_copy_name` ile bir sorguda hesaplanıp ayrı `create` ile yazılıyor; iki kişi aynı anda kopyalarsa aynı ad üretilir ve unique ihlali yakalanmadan 500 olur. `close_due` "bu rapor hâlâ borç mu" kontrolünü (`due.due()`) transaction ve kilit dışında yapıyor; `record_duty_done` salmonid kontrolünü de dışarıda yapıyor. `full_clean()` yarışı kapatmaz, IntegrityError sarılmamış. Etkisi küçük (nadir, sonuç 500, veri bozulmaz).
- Kanıt: `copy_template` içinde yalnızca `transaction.atomic()` var, `IntegrityError` yakalanmıyor; `close_due` satır 117'de kontrol, satır 119'da atomic.
- Öneri: Ad çakışmasında yeniden deneme/`IntegrityError` yakalama; borç kontrolünü transaction içine alın.

### 10-14 - Mesajlaşma: `start_direct` silinmiş sohbeti de döndürüyor; küçük tutarsızlıklar
- Önem: bilgi, Güven: düşük
- Dosyalar: `messaging/services.py:92-110`, `core/language.py:25-26`, `core/views.py:22-28`
- Açıklama: (a) `start_direct` var olan sohbeti `Conversation.all_objects` ile arıyor; sohbet yumuşak silinmişse (`is_deleted`) o döndürülür ve sonraki `member()` çağrısı `conversation__is_deleted=False` yüzünden 404 verir; kullanıcı yeni sohbet başlatamaz (direct_key unique). Şu an hizmet katmanında sohbeti silen bir yol görünmüyor, yalnızca yönetici/aracıyla silinirse ortaya çıkar. (b) `set_language` oturumdaki kullanıcının dilini `save_account_language` ile denetim kaydı olmadan yazıyor, oysa aynı alan kullanıcı formundan değişince denetlenip kaydediliyor (`UserResource.snapshot` dili içeriyor). (c) `post()` yazarın hâlâ üye olduğunu kontrol ediyor ama `USE` iznini/aktifliği yeniden doğrulamıyor (yalnızca `post_as` içindeki `member` yapıyor).
- Kanıt: `found = Conversation.all_objects.filter(direct_key=key).first()` (satır 102).
- Öneri: Yok sayılabilir; silinmiş sohbet durumunu belgeleyin veya geri getirin; dil değişikliğini denetim dışı bırakma kararını belgeleyin.
