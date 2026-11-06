# 16 - Transactions (sınırlar, atomicity, select_for_update, tutarlılık, yan etkiler, kısmi başarısızlık)

## Özet
Repo genelinde yazma yolları disiplinli: her servis fonksiyonu kendi `transaction.atomic()` bloğunu açıyor, satır kilitleri birincil anahtar sırasıyla alınıyor (`farm/stock/services.py:122-125`), tekrar gönderimler `entry_key` + `AlreadyRecorded` ile karşılanıyor, Django signal'ı (`post_save` vb.) hiç kullanılmıyor, tek `on_commit` kullanımı doğru yerde. `ATOMIC_REQUESTS` yok (ayarlarda geçmiyor); sınır servis katmanına bırakılmış. Bulunan sorunlar çoğunlukla kenar durumlar: işlem dışı yan etkiler (depolamaya yazılan dosya, işlem dışı oluşturulan kalem), kilitsiz "oku-karar ver-yaz" yolları (rapor kapatma/açma, tedavi son günü), READ COMMITTED altında tutarsız okuma (rapor dondurma) ve `on_commit` sonrası istisna. Önceki denetimlerle (10, 11) örtüşenler çapraz referansla belirtildi.

## İncelenen alanlar
- `core/crud.py` (Create/Update/Delete/RowList görünümleri), `core/softdelete.py`, `core/models.py`, `core/audit.py`, `core/codes.py`, `core/admin.py`
- `farm/stock`, `farm/feeding`, `farm/health`, `farm/water` servisleri (kilit sırası, token ile idempotans)
- `inventory/services.py`, `experiments/services.py`, `hr/services.py`, `tasks/services.py`, `messaging/services.py`, `reports/services.py`, `knowledge/models/document.py`, `knowledge/views.py`, `monitoring/views.py`, `monitoring/read.py`
- Signal/on_commit kullanımı, `ATOMIC_REQUESTS`/izolasyon ayarları, DB trigger migration'ları (varlığı)

## İncelenmeyen / sınırlı incelenen alanlar
- Testler çalıştırılmadı; yarış durumları kod okuyarak çıkarıldı (gerçek eşzamanlılık denenmedi).
- `farm/handling`, `farm/stock/read.py`, `reports/compute` içindeki okuma yolları ve trigger SQL gövdeleri satır satır incelenmedi.
- TimescaleDB hypertable özel davranışları (sıkıştırma, chunk kilitleri) incelenmedi.

## Bulgular

### 16-1 | Orta | Güven: orta
**Tedavi son günü değişikliği tank kilidi almıyor: hasat çekilme (withdrawal) kontrolüyle yarışır**
- Dosyalar: farm/health/services.py:218-242, farm/stock/services.py:143-146, 200-210
- Açıklama: Hasat (`_commit`) tankları kilitleyip ilaç çekilme süresini bu kilit altında değerlendiriyor; `record_treatment` de tankları kilitliyor. Fakat `change_last_day` yalnızca `Treatment` satırını kilitliyor, tankları değil. Eşzamanlı bir hasat, çekilme süresi uzatılmadan önceki durumu görüp kaydedilebilir; sonuç yasal/gıda güvenliği açısından yanlış onaylı hasat.
- Kanıt: `Treatment.all_objects.select_for_update(of=('self',)).get(...)` (health/services.py:220-221); `locked(Tank, ...)` hasatta (stock/services.py:144-145), `check.assess(...)` kilit sonrası (stock/services.py:208).
- Öneri: `change_last_day` ve `void_treatment` içinde de aynı sırayla (`locked(Tank, ...)`) tankları kilitle.

### 16-2 | Orta | Güven: yüksek
**Yüklenen dosya DB işlemi içinde depolamaya yazılıyor; rollback'te yetim dosya kalıyor**
- Dosyalar: knowledge/models/document.py:217-243, core/crud.py:676-687
- Açıklama: `Document.save` içindeki `super().save()` FileField'ı depoya yazar. Eski dosyanın silinmesi `on_commit` ile korunmuş, ama yeni yazılan dosya için ters işlem yok: sonrasında `IntegrityError`, audit hatası vb. ile rollback olursa dosya MEDIA_ROOT'ta yetim kalır. Ayrıca `pages.all().delete()` + `bulk_create` kendi `atomic`'i olmadan çağrılıyor; `Document.save` işlem dışında (shell, script) çağrılırsa sayfalar silinip yeniden yazılana kadar kısmi durum görülebilir.
- Kanıt: `super().save(...)` (document.py:232), `self.pages.all().delete()` (234), `transaction.on_commit(partial(self.file.storage.delete, stored))` yalnızca `stored` için (241).
- Öneri: Yeni dosya adı için rollback'te silen bir temizlik yolu ekle (ör. işlem hatasında silme) ve sayfa yenilemeyi `transaction.atomic()` içine al.

### 16-3 | Orta | Güven: orta
**Rapor dondurma (`submit`) READ COMMITTED altında yalnızca rapor satırını kilitliyor; çok sorgulu hesap tutarsız okuyabilir**
- Dosyalar: reports/services.py:41-100, config/settings.py:121
- Açıklama: `compute.compute(current)` birçok tabloyu ayrı sorgularla okur; izolasyon seviyesi varsayılan (READ COMMITTED), kaynak kayıtlar kilitli değil. İçerik özeti (`content_sha256`) kullanıcının gördüğüyle karşılaştırılıyor, ama hesap sırasında araya giren geriye dönük bir kayıt aynı hesabın iki parçasını farklı durumlarda okutabilir; dondurulan snapshot hiçbir tekil zamanı temsil etmeyebilir.
- Kanıt: `current = Report.objects.select_for_update().get(...)` (50-51), `result = compute.compute(current)` (61), izolasyon ayarı yok (settings.py:121 civarı yalnızca `CONN_MAX_AGE`).
- Öneri: `submit` içinde `REPEATABLE READ` kullan (ya da hesabı tek anlık görüntüde çalıştır) ve `compute`'un iki kez çalıştırılmasını (satır 70) tek hesapla birleştir.

### 16-4 | Orta | Güven: yüksek
**`reopen` ve `undo_duty_done`: kilitsiz silme + önce audit yazma; çift tıklamada iki DELETE audit satırı**
- Dosyalar: reports/services.py:131-139, 168-175
- Açıklama: İkisi de satırı kilitlemeden, mevcut olup olmadığını yeniden doğrulamadan önce DELETE audit kaydı yazıp sonra `delete()` çağırıyor. İki eşzamanlı istek ikisi de audit satırı yazar; ikinci `delete()` 0 satır etkiler ama hata vermez. Audit'te gerçekte olmayan ikinci bir silme görünür.
- Kanıt: `audit.record(..., AuditLog.Action.DELETE, closure ...)` ardından `closure.delete()` (136-138); aynı kalıp 172-174.
- Öneri: `select_for_update` ile satırı yeniden oku, yoksa sessizce dön; `delete()` dönüş sayısı 0 ise audit yazma.

### 16-5 | Düşük | Güven: yüksek
**`close_due`/`record_duty_done`: ön koşul kontrolü işlem ve kilit dışında (10-13 ile örtüşür)**
- Dosyalar: reports/services.py:111-128, 141-165
- Açıklama: `due.due()` ve `duties.applies` kontrolleri `atomic` bloğundan önce yapılıyor; iki eşzamanlı istek ikisi de kontrolü geçer, ikincisi unique constraint'ten `IntegrityError` alır ve yakalanmadığı için 500 döner (veri bozulmaz, kullanıcı deneyimi ve hata sınıfı sorunu).
- Kanıt: `if not any(row.kind == kind ... for row in due.due().rows)` (116) `with transaction.atomic()` (118) öncesinde; `UniqueConstraint` reports/models.py:411 ve 373.
- Öneri: `IntegrityError`'ı yakalayıp `_refuse` ile aynı mesajı ver.

### 16-6 | Orta | Güven: orta
**Yumuşak silme planı alt kayıtları kilitlemiyor; bayat nesneler `save()` ile tüm alanları geri yazıyor**
- Dosyalar: core/softdelete.py:171-186, core/models.py:52-58, core/crud.py:769-790
- Açıklama: `DeleteView.post` yalnızca üst kaydı kilitler; `plan_delete` çocuk kayıtları kilitsiz okur, `execute` bunlara `soft_delete` (tam `save()`, `version += 1`) uygular. Eşzamanlı çocuk düzenlemesi sessizce ezilebilir (son yazan kazanır, sürüm kontrolü yok) ve plan sonrası eklenen çocuk üstte silinmiş ebeveyne bağlı kalır (10-6 ve 11-7 ile ilgili).
- Kanıt: `plan = plan_delete(obj)` / `softdelete.execute(plan, request.user)` (crud.py:779-784); `self.save()` (models.py:58).
- Öneri: Plandaki kayıtları `select_for_update` ile yeniden oku ve `soft_delete`'i `update_fields` ile sınırla; `restore` içinde de kilit + `is_deleted` yeniden doğrulama ekle.

### 16-7 | Düşük | Güven: yüksek
**`receive`/`count`: `item_for` ana işlemden ayrı işleme yazıyor; reddedilen işlemde yetim `InventoryItem` + audit kalır**
- Dosyalar: inventory/services.py:71-81, 274-276, 326-328
- Açıklama: `item_for` kendi `atomic` bloğunda öğe ve audit CREATE satırı oluşturur. `receive` ve `count` bunu `_commit` çağrısından önce, dışarıda çalıştırır; `_commit` doğrulamada reddederse (görünüm `atomic` sarmıyor) yeni öğe ve audit satırı kalıcı olur. Zararı sınırlı, ama "başarısız işlem iz bırakmaz" beklentisini bozar. Ayrıca her `item_for` çağrısı tüm kiracı için tek global advisory lock (`hashtext('inventory_items')`) alır.
- Kanıt: `entries = [Entry(NewLot(item_for(feed, user), ...` (276, 327), `_commit` ayrı `atomic` (138).
- Öneri: `receive`/`count` gövdesini tek `transaction.atomic()` altında çalıştır.

### 16-8 | Düşük | Güven: yüksek
**`messaging.post`: `on_commit` içinde `Signal.send`; alıcı istisnası commit sonrası çağırana sızar (mesaj yazılmış, istek 500)**
- Dosyalar: messaging/services.py:246-247, messaging/events.py:14, messaging/views.py:96-100
- Açıklama: `events.message_posted.send` alıcı hatasını yutmaz; commit tamamlandıktan sonra yükselen istisna kullanıcıya hata gösterir, kullanıcı yeniden gönderince çift mesaj oluşur. Şu an alıcı yok (yalnızca testte), yani gizli bir tuzak.
- Kanıt: `transaction.on_commit(lambda: events.message_posted.send(...))`.
- Öneri: `send_robust` kullan ve hataları logla.

### 16-9 | Düşük | Güven: orta
**`messaging.post`: kilit sorgusu `get()` ile; konuşma aradan silinirse `DoesNotExist` (500), diğer yollar 404**
- Dosyalar: messaging/services.py:236 (karşılaştır: 79)
- Açıklama: `_locked` `get_object_or_404` kullanır; `post` ise `Conversation.objects.select_for_update().get(...)` (yalnızca canlı kayıtları döndüren ActiveManager). Konuşma `member()` ile `post` arasında silinirse yakalanmayan `DoesNotExist` oluşur.
- Kanıt: `Conversation.objects.select_for_update().get(pk=author.conversation_id)`.
- Öneri: `_locked(...)` kullan veya `PermissionDenied`/404'e çevir.

### 16-10 | Düşük | Güven: orta
**`tasks.materialise_due` okuma isteklerinde çalışıyor ve seri başına hata izolasyonu yok**
- Dosyalar: tasks/services.py:257-262, tasks/views.py:142, tasks/resources.py:92, 226
- Açıklama: Sayfa görüntüleme (GET) yazma işlemi tetikliyor (10-5 ile örtüşür). Ek olarak liste kavrayışı seriler arasında `try/except` içermez: tek bir bozuk seri (örn. silinmiş yer) tüm görev sayfalarını 500 yapar; önceki seriler commit olmuş, kalanlar olmamış kısmi ilerleme kalır.
- Kanıt: `return [task for series in behind for task in materialise(series)]`.
- Öneri: Her seriyi ayrı `try/except` + loglama ile çalıştır veya üretimi yalnızca `generate_tasks` komutuna taşı.

### 16-11 | Düşük | Güven: orta
**`audit.revision()` 5 dakikalık `LATE_COMMIT` penceresi varsayımına dayanıyor**
- Dosyalar: core/audit.py:125-141, core/models.py:171
- Açıklama: `created_at` satır oluşturulurken (`auto_now_add`, uygulama saati) damgalanır, görünürlük commit'te başlar. 5 dakikadan uzun süren bir işlem ya da kilit beklemesi, geç commit olan satırı belirteçte görünmez kılar; sayfa "değişiklik yok" sanabilir.
- Kanıt: `LATE_COMMIT = timedelta(minutes=5)`; `created_at__gte=newest - LATE_COMMIT`.
- Öneri: Pencereyi belgele veya sıra numarası (sequence/xmin tabanlı) bir belirteç kullan.

### 16-12 | Düşük | Güven: orta
**`record_feeding` yem satırını kilitlemiyor; yem pasifleştirmesiyle yarışır**
- Dosyalar: farm/feeding/services.py:46-56
- Açıklama: Tank kilitleniyor ama `Feed.all_objects.get(pk=...)` kilitsiz. Yem aynı anda "active" dışı yapılırsa yeni besleme pasif yemle kaydedilebilir (küçük tutarsızlık; stok servislerindeki "kilit sonrası doğrula" desenine uymuyor).
- Kanıt: `feed = Feed.all_objects.get(pk=feed.pk)`; `if feed.is_deleted or feed.status != Feed.Status.ACTIVE`.
- Öneri: `select_for_update(of=('self',))` kullan.

### 16-13 | Bilgi | Güven: yüksek
**İşlem sınırı politikası belgesiz: `ATOMIC_REQUESTS` yok, izolasyon varsayılan; doğruluk her servisin kendi `atomic`'ine bağlı**
- Dosyalar: config/settings.py:121, core/crud.py:678, 723, 769, 811
- Açıklama: `core/crud` her yazma görünümünde açıkça `atomic` açıyor (iyi), fakat `Document.save`, `softdelete.restore`, `align_placements`, `withdraw` gibi genel fonksiyonlar çağıranın işleminde olduğunu varsayıyor ve belgede (docstring) bu her yerde yazmıyor. Yeni bir çağıran işlem açmazsa kısmi yazma oluşur.
- Kanıt: `softdelete.execute` docstring "inside the caller's transaction" (softdelete.py:175) yalnızca bunda var; `align_placements` (hr/services.py) kendi `atomic`'ini açar ama `restore` açmaz.
- Öneri: Çağıranın işlemde olmasını gerektiren fonksiyonlara `transaction.get_connection().in_atomic_block` doğrulaması veya `@transaction.atomic` ekle.

### 16-14 | Bilgi | Güven: yüksek
**Olumlu doğrulama: kilit sırası tutarlı, signal yok, `on_commit` doğru yerde**
- Dosyalar: farm/stock/services.py:122-125, experiments/services.py (`_lock_tanks`, `save_places`, `replace_unit`), inventory/services.py:138-144, messaging/services.py:76-80
- Açıklama: Kilitler birincil anahtar sırasıyla ve hep aynı model sırasıyla (batch, tank, deney; öğe, konum) alınıyor; `grep` ile `post_save/pre_save/m2m_changed` alıcısı bulunmadı, gizli yan etki yok; `bulk_create` yolları audit'i açıkça yazıyor. Kod tabanında kilit sırası kaynaklı deadlock riski bulunamadı.
- Kanıt: `order_by('pk').in_bulk()` (stock/services.py:125); deneyde "tanklar önce, deney en son" (`save_places` docstring, experiments/services.py).
- Öneri: Yok; bu sırayı bir mimari notuna yaz.
