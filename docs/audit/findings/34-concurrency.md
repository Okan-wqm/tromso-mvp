# 34 - Eşzamanlılık denetimi

## Özet
Repo eşzamanlılığı büyük ölçüde bilinçli ele alıyor: servis katmanında `select_for_update` (çoğunlukla pk sıralı), advisory kilitler (`core/codes.py:7`, `inventory/services.py:74`), DB seviyesinde exclusion/unique kısıtları (`hr/models/attendance.py:59`, `tasks/models.py:403`), idempotency anahtarları (`entry_key`), optimistik sürüm kilidi (`core/crud.py:725`). Süreç-içi paylaşılan durum neredeyse yok. Bulunan sorunlar çoğunlukla düşük/orta: tekrarlayan görev `withdraw` yolunda kilitsiz bayat liste, GET isteklerinde yazma ve satır kilidi, sürüm kontrolünü atlayan toplu `update()` çağrıları, kilit sıralaması tutarsızlığı, silme/geri yüklemede kilit eksikliği. Dağıtım (gunicorn, çoklu worker, cron) bu repoda tanımlı değil; yalnızca README ve ayar yorumları var.

## İncelenen alanlar
tasks/services.py (materialise, replan, withdraw, durum geçişleri), core/crud.py (Create/Update/Delete), core/softdelete.py, core/codes.py, core/models.py, core/admin.py, config/settings.py (DB_CONN_MAX_AGE), hr/services.py, inventory/services.py, messaging/services.py, farm/stock/services.py, farm/feeding/services.py, farm/water/services.py, experiments/services.py (kısmen), monitoring/read.py (FAILED_AT, _optional), farm/placements.py, farm/water/chemistry.py (lru_cache), docker-compose.yml.

## İncelenmeyen alanlar
Testler çalıştırılmadı; gerçek çoklu-bağlantı yarış testi yapılmadı (yalnızca statik okuma). reports/, knowledge/, farm/health ve farm/handling içi ayrıntılı kilit akışları, frontend TypeScript, migration'lar, Timescale hypertable'a özgü kilit davranışları derin incelenmedi. `tasks.places`/`clocks()` tanımı doğrulanmadı.

## Bulgular

### 34-1 - `withdraw` kilitsiz, bayat "planlı" listeyle görevleri kalıcı siler (cascade ile not/checklist kaybı)
- Önem: medium | Güven: medium
- Dosyalar: tasks/services.py:267-273, tasks/services.py:276-287, tasks/models.py:426-435, tasks/models.py:463,491
- Açıklama: `replan` yalnızca seri satırını kilitler. `withdraw`, `Task.planned()` ile (kilitsiz, `list()`) aday listesini okur, sonra her birini `task.delete()` ile SERT siler (AuditedModel soft-delete değil; `Task`'ta `delete` override'ı yok). Bu arada başka bir istek `start/complete/tick/add_note` ile (`_locked(task)` satır kilidi) aynı görevi değiştirmiş olabilir; `delete()` kilidi bekler ve sonra bayat listedeki görevi yine siler. TaskNote ve TaskChecklistItem `CASCADE` olduğu için "kalıcı tutulur" denen notlar (tasks/services.py:~125) ve işaretli checklist silinir; denetim kaydı da ancak silmeden önce yazılmış olur.
- Kanıt: `withdraw` döngüsü `for task in Task.planned(...): audit.record_delete(...); task.delete()`; `planned` koşulu `version=1, status=OPEN`, notsuz/işaretsiz sadece sorgu anında değerlendirilir. Silme sırasında görev kilidi alınmaz veya koşullar yeniden doğrulanmaz.
- Öneri: Silmeden önce görevi `select_for_update` ile kilitleyip `planned` koşullarını yeniden doğrulamak (ya da `planned` sorgusunu `select_for_update(skip_locked=True)` ile yapmak).

### 34-2 - Silme yolu (`DeleteView.post`) yalnızca silinen satırı kilitler; çocuk/bağımlı kayıt eklemeleriyle yarış
- Önem: low | Güven: low
- Dosyalar: core/crud.py:768-781, core/softdelete.py:98-190
- Açıklama: `select_for_update(of=('self',))` ile sadece hedef kilitlenir; `plan_delete` çocukları/blocker'ları kilitsiz okur. Hedefin FOR UPDATE kilidi, çocuk INSERT'ünün FK (KEY SHARE) kilidiyle çakıştığı için çoğu durumda seri hale gelir; ancak silme önce kilidi alırsa bekleyen çocuk insert'i commit sonrası soft-delete edilmiş ebeveyne canlı çocuk olarak eklenebilir (form/servis insert sırasında ebeveynin `is_deleted` durumunu kilit altında tekrar kontrol etmiyorsa). Tüm yazma yollarında doğrulanmadı.
- Kanıt: crud.py:770 yalnızca `obj` kilidi; `plan_delete(obj)` 774.
- Öneri: Bağımlı kayıt yazan servislerin ebeveyni kilitleyip `is_deleted` kontrolü yaptığını doğrulayın (stock/inventory/water bunu yapıyor, CRUD formları için ayrıca bakın).

### 34-3 - `softdelete.restore` kilitsiz ve yalnızca `ValidationError` yakalanıyor
- Önem: low | Güven: medium
- Dosyalar: core/softdelete.py:189-210, core/admin.py:40-55
- Açıklama: `restore` kaydı kilitlemeden (bayat örnek) `full_clean()` ile canlı kısıtları kontrol edip `save()` eder. `full_clean` ile `save` arasında aynı kod/ad başka kayıtla alınırsa DB kısıtı `IntegrityError` verir; admin eylemi yalnızca `ValidationError` yakaladığından sunucu hatası (500) ve işlem tümü iptal olur. Tam `save()` bayat alanları da yazar ve `version += 1` bayat değerden hesaplanır.
- Kanıt: admin.py:44-48 `except ValidationError`; softdelete.py:204-209 kilit yok.
- Öneri: `select_for_update` ile yeniden okuyun, `IntegrityError`'ı kullanıcıya mesaja çevirin.

### 34-4 - Sayfa GET'lerinde yazma: `materialise_due()` liste/özet okumalarında çağrılıyor
- Önem: medium | Güven: high
- Dosyalar: tasks/resources.py:92, tasks/resources.py:226, tasks/views.py:142, tasks/services.py:257-262
- Açıklama: Görev listesi, seri listesi ve üretim özeti her okumada seri başına transaction açıp `select_for_update` ile kilitler ve görev satırları ekler. Çoklu worker/eşzamanlı kullanıcıda her sayfa yüklemesi seri satırlarında bloklanır. Bir serideki hata (örn. kısıt ihlali, bozuk veri) `materialise_due` içinde yakalanmadığından tüm görev sayfalarını ve üretim özetini (tasks/views.py:142) düşürür; seri başına `try/except` yok.
- Kanıt: `return [task for series in behind for task in materialise(series)]` hata izolasyonsuz. Cron komutu `generate_tasks` var (tasks/management/commands/generate_tasks.py) ama tetikleyen zamanlayıcı repoda tanımlı değil.
- Öneri: Üretimi zamanlanmış işe taşıyın ya da GET'te en azından `skip_locked` + seri başına hata izolasyonu kullanın.

### 34-5 - Her GET'te boşuna seri satır kilidi: `behind` filtresi en geç saat dilimine göre
- Önem: low | Güven: low
- Dosyalar: tasks/services.py:257-262, tasks/services.py:228-233
- Açıklama: `latest = max(clock.today ...) + HORIZON`; bir sitenin kendi "bugün"ü daha geriyse `generated_until = site_today+HORIZON` her zaman `latest`'ten küçük kalır. Seri "behind" sayılır, kilitlenir, `first > last` ile `[]` döner ve hiçbir şey yazılmaz. Sonuç: o seriler için her sayfa yükünde gereksiz FOR UPDATE ve serileşme. `clocks()` tanımı doğrulanamadığı için güven düşük.
- Kanıt: materialise satır 231-235 `if first > last: return []`.
- Öneri: Filtre için seri başına site gününü kullanın ya da kilitsiz ön kontrol yapın.

### 34-6 - Tekrarlayan görev üretiminin yinelenmeye karşı korumaları (olumlu) ve kalan tek zayıflık
- Önem: info | Güven: high
- Dosyalar: tasks/services.py:214-254, tasks/models.py:403
- Açıklama: Aynı gün için çift görev üretimi üç katmanla engelleniyor: seri satır kilidi (kilit altında `generated_until` yeniden okunur), `taken` kümesi (silinmişler dahil) ve `uq_tasks_series_occurrence` unique kısıtı. Çoklu worker + cron + sayfa tetikleyicisi birlikte güvenli. Kalan: kısıt ihlali olursa (örn. başka yoldan eklenmiş) `IntegrityError` yakalanmaz (bkz. 34-4).
- Kanıt: yukarıdaki satırlar.
- Öneri: Değişiklik gerekmez; 34-4 ile birlikte hata izolasyonu ekleyin.

### 34-7 - `ReplicateUnit` ve `_touch` toplu `update()` çağrıları `version`'ı artırmıyor (optimistik kilidi atlatır)
- Önem: low | Güven: medium
- Dosyalar: experiments/services.py:199-200, experiments/services.py:584-585, experiments/services.py:196-197, experiments/services.py:814-816
- Açıklama: `_touch`, `move_span` (584) ve `_park` kayıtları `QuerySet.update()` ile değiştirir; `updated_by/updated_at` güncellenir ama `version` güncellenmez (814'te `row.version + 1` bayat Python değerinden, F() değil). Optimistik kilit (`core/crud.py:726`) bu değişiklikleri algılamaz; aynı kaydı eşzamanlı düzenleyen biri sessizce üzerine yazabilir. Deney tasarım kaydetme yolu `locked_draft` ile deney sürümünü kontrol ettiği için çoğu yolda korunuyor.
- Kanıt: `_touch`: `.update(updated_by=user, updated_at=..., **values)`.
- Öneri: `version=F('version')+1` ekleyin.

### 34-8 - Su ölçümü kilitleme sırası pk sıralı garantisine dayanmıyor (olası kilit sırası tutarsızlığı)
- Önem: low | Güven: low
- Dosyalar: farm/water/services.py:69-86, farm/stock/services.py:119-126
- Açıklama: Stock `locked()` sorguya `order_by('pk')` ekler; su servisinin `_locked_points` ise `in_bulk(sorted(pks))` kullanır: Python'da sıralama yalnızca `pk__in` listesini sıralar, SQL'de ORDER BY yok (yapıya göre PG kilitleri tarama sırasıyla alır; `Meta.ordering` de olabilir). İki eşzamanlı tur (round) farklı sırada kilitlerse deadlock mümkün; PG tespit edip birini iptal eder (500). Sahipler (units/systems/equipment) ile Tank kilitleri stock `locked(Tank)` ile aynı satırlara denk gelir, sıra farkı karşılıklı bekleme yaratabilir.
- Kanıt: water/services.py:80-83 (`in_bulk(sorted(...))`, `order_by` yok) ve stock/services.py:125 (`order_by('pk')`).
- Öneri: `.order_by('pk')` ekleyin; kilit sırasını tek yardımcıda toplayın.

### 34-9 - `leave_company` istemciden sürüm almadan çalışıyor (kayıp güncelleme)
- Önem: low | Güven: medium
- Dosyalar: hr/services.py:95-110
- Açıklama: Satır kilitlenip taze okunuyor, `version += 1` yapılıyor ama çağıran formun gördüğü sürümle karşılaştırılmıyor; aynı çalışan kaydını açmış başka kullanıcının düzenlemesi (CRUD yolu sürüm kontrollü) ile yarışta "son yazan kazanır"; ayrıca `align_placements` sonrası alt kayıtlar (Posting/ShiftAssignment/Leave) sürüm kontrolsüz değiştirilir. Eylem niteliğinde olduğu için bilinçli olabilir.
- Kanıt: hr/services.py:96-103.
- Öneri: Gerekirse beklenen sürümü parametre alın.

### 34-10 - `messaging.post`: silinmiş konuşmada `DoesNotExist` (500); kilit sırası tutarlı
- Önem: low | Güven: medium
- Dosyalar: messaging/services.py:231-246
- Açıklama: `Conversation.objects.select_for_update().get(pk=...)` (yalnızca canlı yöneticisi) konuşma eşzamanlı silinmişse `DoesNotExist` fırlatır; `author` yeniden okunması için `PermissionDenied` hazırlanmış ama bu ilk istisna önce çıkar. Olumlu: gönderi ve üyelik değişiklikleri aynı konuşma kilidini kullanıyor (`_locked`, `owner(lock=True)`), mesaj kimlikleri commit sırasına uyuyor; `mark_read` tek UPDATE ile atomik ve geriye gitmez (286).
- Kanıt: messaging/services.py:236.
- Öneri: `get_object_or_404`/`Http404`/`PermissionDenied` eşlemesi yapın.

### 34-11 - `DB_CONN_MAX_AGE` varsayılanı 0; kalıcı bağlantı + advisory xact kilitleri güvenli, ancak ayar belgesi/dağıtım tanımı yok
- Önem: info | Güven: high
- Dosyalar: config/settings.py:117-123, README.md:2991, docker-compose.yml
- Açıklama: Varsayılan 0, `CONN_HEALTH_CHECKS=True` (bağlantı yeniden kullanımdan önce kontrol). Advisory kilitler `pg_advisory_xact_lock` (transaction kapsamlı) olduğundan kalıcı bağlantıda kilit sızıntısı olmaz. Repoda gunicorn/worker sayısı/pool için yapılandırma yok; `DB_CONN_MAX_AGE>0` ile worker×thread sayısı Postgres `max_connections` ile ilişkilendirilmemiş (yalnızca runserver uyarısı var). Uygulama `ATOMIC_REQUESTS` kullanmıyor; servisler kendi `atomic` bloklarını açıyor.
- Kanıt: settings.py:121-122.
- Öneri: Dağıtım dokümanına worker/thread/max_connections hesabı ekleyin.

### 34-12 - `core.codes.next_code`: 32 bitlik `hashtext` advisory anahtarı, tek global kilit sınıfı
- Önem: info | Güven: medium
- Dosyalar: core/codes.py:7-16, inventory/services.py:74-79
- Açıklama: Kilit anahtarı `hashtext('<tablo>.code')` / `hashtext('inventory_items')`; farklı anahtarların hash çakışması ya da uygulama dışı başka advisory kullanımı gereksiz bekleme yaratabilir (yalnızca performans, doğruluk bozulmaz). Doğru kullanım: Batch kodu `_commit` transaction'ı içinde (stock/services.py:153), Experiment kodu CRUD atomic içinde (experiments/forms.py:97 `save` -> core/crud.py:679 atomic) alınıyor; benzersizlik ayrıca `uq_experiments_code` ile korunuyor.
- Kanıt: codes.py:13-14.
- Öneri: Gerekmiyor; bilgi amaçlı.

### 34-13 - Süreç-içi paylaşılan durum: `monitoring.read.FAILED_AT` ve `lru_cache`
- Önem: info | Güven: high
- Dosyalar: monitoring/read.py:86, monitoring/read.py:270-278, farm/water/chemistry.py:344
- Açıklama: `FAILED_AT` sözlüğü her worker'da ayrı ve kilitsiz (GIL altında güvenli, yalnızca log hız sınırı; çoklu worker'da dakikada bir yerine worker başına bir log). `equilibria` `lru_cache`'i saf fonksiyon, güvenli. Uygulamada `CACHES`, `threading`, global değişken durumu başka yok.
- Kanıt: ilgili satırlar.
- Öneri: Gerekmez.

### 34-14 - Olumlu doğrulamalar (eşzamanlılık kontrolleri)
- Önem: info | Güven: high
- Dosyalar: hr/services.py:365-400, hr/models/attendance.py:52-62, inventory/services.py:129-160, farm/stock/services.py:119-150, tasks/services.py:104-190, core/crud.py:719-740, messaging/services.py:93-125
- Açıklama: clock_in/out çalışan satırı kilidi + `excl_attendance_employee_span` DB dışlama kısıtı; inventory/stock `_commit` pk sıralı kilit + `entry_key` unique ile idempotency; görev durum geçişleri satır kilidi altında kontrol-sonra-yaz; `start_direct` `IntegrityError` ile yarışı çözüyor; `CreateView` çift gönderimi `sent_before`/IntegrityError ile ele alıyor. Bu bölümlerde yarış bulunmadı.
- Kanıt: ilgili dosyalar.
- Öneri: Yok.
