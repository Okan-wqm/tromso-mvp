# 13 - Aktivite logu denetimi (audit-log)

## Özet
Aktivite logu genel olarak özenle kurulmuş: `core/audit.py` tek yazım noktası, jenerik CRUD (`core/crud.py`), soft delete planı (`core/softdelete.py`) ve servis katmanlarının büyük çoğunluğu log satırını değişiklikle aynı `transaction.atomic()` bloğunda yazıyor; `audit_log` tablosunda satır düzeyinde UPDATE/DELETE tetikleyicisi var; kişisel metinler `private` ile hash'lenerek saklanıyor; HR kayıtları `audit.restrict` ile kısıtlı. Bulunan zayıflıklar ağırlıkla şunlar: (1) değiştirilemezlik yalnızca satır düzeyi UPDATE/DELETE tetikleyicisine dayanıyor, TRUNCATE/DROP TRIGGER/INSERT ile sahte kayıt engellenmiyor ve uygulama DB sahibi/superuser hesabıyla bağlanıyor, (2) kimlik doğrulama olayları (giriş, hatalı giriş, şifre sıfırlama) ve `hr_roles` ile rol/izin oluşturma loglanmıyor, (3) hard delete edilen kayıtlar (rol, kapatılmış rapor, dış görev kaydı, planlı görev) log'a değerleri olmadan düşüyor; restore satırı da boş, (4) `critical` işareti yalnızca handling uyarısı onayında kullanılıyor, benzer onaylar (kapasite aşımı, yüksek yemleme) normal kalıyor ve severity'yi okuyan bir alarm henüz yok, (5) `revision()` ile izleme duvarının değişiklik belirteci audit log'un eksiksizliğine bağlanmış, (6) "aynı transaction" kuralı yalnızca konvansiyon, kodla zorlanmıyor, (7) log'a erişim kısıtı (`restrict`) kayıt sayfası geçmişinde ve veritabanı görüntüleyicide uygulanmıyor. Kritik bulgu yok. Testler çalıştırılmadı (ortamda Django kurulu değil; salt-okunur statik inceleme).

## İncelenen alanlar
core/audit.py, core/models.py (AuditLog, AuditedModel, AuditSeverity), core/migrations/0002, 0003, 0006, 0007, core/crud.py (Create/Update/Delete/RowList görünümleri, geçmiş sekmesi), core/softdelete.py, core/admin.py, core/views.py (activity_log), templates/core/_audit_entries.html, core/resources.py (Rol/Kullanıcı), core/forms.py (UserForm), core/language.py, hr/services.py, hr/apps.py (restrict), hr/roles.py, hr/management/commands, tasks/services.py, messaging/services.py, inventory/services.py, farm/stock/services.py, farm/health/services.py, farm/feeding/*, farm/water/*, experiments/services.py, reports/services.py, knowledge/views.py + models/document.py, monitoring/views.py + read.py (change_token), config/settings.py (DATABASES), docker-compose.yml, docs/hr-launch-checklist.md, docs/audit/findings/11-data-modify.md, core/tests.py (AuditLogTests, RevisionTests), core/tests_scope.py (RestrictedLogTests).

## İncelenmeyen / sınırlı incelenen alanlar
Testler ve uygulama çalıştırılmadı (Django ortamda kurulu değil); gerçek PostgreSQL rol yetkileri ve üretim dağıtımındaki DB kullanıcısı bilinmiyor (yalnızca geliştirme docker-compose ve settings varsayılanları okundu). Tüm 96 `audit.*` çağrı noktası tek tek izlenmedi; farm/water/points, farm/health/withdrawal, reports/compute, frontend TypeScript, config/database.py ve core/dbview.py tabloları satır düzeyinde incelenmedi. Veritabanı yedek/geri yükleme (12 numaralı alan) ve yetki matrisi (02) başka uzmanların alanıdır.

## Bulgular

### 13-1 | Orta | Güven: yüksek
**Değiştirilemezlik yalnızca satır düzeyi UPDATE/DELETE tetikleyicisine dayanıyor: TRUNCATE, DROP/DISABLE TRIGGER ve sahte INSERT engellenmiyor; uygulama DB sahibiyle bağlanıyor**
- Dosyalar: core/migrations/0003_audit_log_append_only.py:4-14, core/models.py:154-157, config/settings.py:110-117, docker-compose.yml:7-10, monitoring/tests/test_templates_db.py:121-125
- Açıklama: Tetikleyici `BEFORE UPDATE OR DELETE ... FOR EACH ROW`; `TRUNCATE` (satır tetikleyicisi çalışmaz), `ALTER TABLE audit_log DISABLE TRIGGER` veya `DROP TRIGGER` korunmuyor. Uygulama `DB_USER` (varsayılan `balik`) ile bağlanıyor; docker-compose'ta bu kullanıcı `POSTGRES_USER`, yani veritabanı sahibi ve superuser. Dolayısıyla uygulama kodunda (ör. SQL enjeksiyonu, ele geçirilmiş süreç) veya DB'ye erişimi olan biri log'u sessizce silebilir. `AuditLog` docstring'i "platform yöneticisi bile değiştiremez" diyor; bu iddia DB sahibi için doğru değil. Test kodu TRUNCATE'in tetikleyiciyi atladığını zaten kullanıyor (testlerde serileştirilmiş geri alma).
- Kanıt: `CREATE TRIGGER trg_audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW` (0003:11-13); `TRUNCATE monitor_card_templates CASCADE` "no row trigger" yorumu (test_templates_db.py:121-125); `'USER': os.environ.get('DB_USER', 'balik')` ve `POSTGRES_USER: ${DB_USER:-balik}`.
- Öneri: Üretimde uygulama için ayrı, tablo sahibi olmayan bir rol kullan (audit_log üzerinde yalnızca INSERT/SELECT, `REVOKE TRUNCATE, UPDATE, DELETE`); ek olarak `BEFORE TRUNCATE ... FOR EACH STATEMENT` tetikleyicisi ve olay tetikleyicisi (event trigger) ile DDL'i izle; docstring'i gerçek garantiyle hizala.

### 13-2 | Düşük | Güven: yüksek
**Log satırının bütünlüğü/özgünlüğü doğrulanamıyor: zincir/imza yok, `created_at` uygulama saatinden, INSERT serbest**
- Dosyalar: core/models.py:170-189, core/audit.py:144-158, core/test_languages.py:169, core/tests_scope.py:190
- Açıklama: `created_at` `auto_now_add` (uygulama sunucusunun saati); veritabanı `now()` değil. `user_name`, `action`, `entity_type` üzerinde veritabanı kısıtı yok (yalnızca `severity` için CHECK var), `action` seçimleri yalnızca Django düzeyinde. `AuditLog.objects.create(...)` ile herhangi bir kod yolu serbestçe sahte satır ekleyebilir (testler bunu yapıyor); hash zinciri veya imza olmadığından eklenen/silinen satır sonradan fark edilemez (13-1 ile birleşince).
- Kanıt: `created_at = models.DateTimeField(auto_now_add=True, db_index=True)` (models.py:171); `constraints = [CheckConstraint(... name='chk_audit_log_severity')]` tek kısıt (models.py:198-201).
- Öneri: Zaman damgasını DB varsayılanıyla (`clock_timestamp()`) ata, `action` için CHECK ekle, isteğe bağlı olarak önceki satırın hash'ini içeren zincir veya periyodik dış arşiv/imza.

### 13-3 | Orta | Güven: yüksek
**Kimlik doğrulama olayları loglanmıyor: giriş, hatalı giriş, çıkış, şifre sıfırlama/değiştirme**
- Dosyalar: config/urls.py:18-31, core/resources.py:61-69, core/forms.py:77-118
- Açıklama: Projede `user_logged_in`, `user_login_failed`, `user_logged_out` sinyallerini dinleyen kod yok; şifre sıfırlama ve değiştirme Django'nun stok görünümleriyle yapılıyor ve log yazmıyor. Kullanıcı oluşturma/değiştirme (alanlar, roller, `is_active`) loglanıyor, ama bir hesabın şifresinin ne zaman sıfırlandığı veya brute-force denemeleri hiçbir yerde kayıtlı değil. Süper kullanıcı oluşturma/yetki değişikliği (shell, `createsuperuser`) de log dışı (`is_superuser` formda yok, "platform admin status is not set here").
- Kanıt: `grep user_logged_in|user_login_failed|user_logged_out` sonucu boş; `path('accounts/', include('django.contrib.auth.urls'))` (urls.py:31); `PasswordResetView.as_view(form_class=PasswordResetForm)` (urls.py:29).
- Öneri: Üç oturum sinyali ve `password_changed`/reset tamamlanması için `audit.record` (kullanıcı, IP olmadan en azından olay) yaz; hatalı girişleri hız sınırı/izleme ile birlikte logla.

### 13-4 | Orta | Güven: yüksek
**Hard delete edilen kayıtlar log'a değerleri olmadan düşüyor (rol, kapatılmış rapor, dış görev kaydı, planlı görev)**
- Dosyalar: core/crud.py:781-785, reports/services.py:132-138, reports/services.py:168-174, tasks/services.py:265-271, core/audit.py:175-176, docs/audit/findings/11-data-modify.md (11-5)
- Açıklama: `record_delete(user, instance)` `changes` vermediği için `{}` yazar. Soft delete olmayan modellerde (Rol/`Group`, `DueClosure`, `OutsideDutyDone`, planlı `Task`) satır gerçekten silindiği için log'da yalnızca tür ve etiket kalır; silinen rolün izinleri, kapatma gerekçesi (`reason`), dış görev tarihi/referansı, görevin içeriği kurtarılamaz. 11 numaralı bulgu notu "silinen rolün izinleri audit'te snapshot ile kayıtlı" diyor, kodda bu doğru değil (crud.py:784 snapshot geçmiyor). Karşıt örnek: `hr/services._write_cell` silmeden önce `before` değerlerini `[value, None]` olarak yazıyor, yani kalıp var ama uygulanmamış.
- Kanıt: `audit.record_delete(request.user, obj, entity_type=r.entity_type()); obj.delete()` (crud.py:784-785); `audit.record(user, AuditLog.Action.DELETE, closure, entity_type=..., label=...)` + `closure.delete()` (reports/services.py:136-138); `audit.record_delete(user, task); task.delete()` (tasks/services.py:270-271).
- Öneri: Hard delete yollarında silmeden önce `r.recorded(obj)` / snapshot'ı `[değer, None]` olarak yaz (jenerik `DeleteView`'da tek yerde çözülür), `DueClosure`/`OutsideDutyDone` için de aynısını yap.

### 13-5 | Düşük | Güven: yüksek
**Soft delete ve RESTORE satırlarında değişiklik içeriği yok**
- Dosyalar: core/softdelete.py:177-203, core/audit.py:175-176
- Açıklama: `execute` her kayıt için `audit.record_delete(user, record)` çağırır, `changes` boş; `restore` da `audit.record(user, RESTORE, record)` ile boş yazar. Hangi alanların (ör. `version`, `is_deleted`, `deleted_at`) değiştiği ve restore edilen kaydın o anki değerleri log'dan okunamaz; restore'un `full_clean()` ile kod değişikliği gibi yan etkileri de belirtilmez. Silinen kaydın son hali yalnızca soft delete edilmiş satırdan okunabilir (o da sonradan değişebilir).
- Kanıt: `audit.record_delete(user, record)` (softdelete.py:184-185); `audit.record(user, AuditLog.Action.RESTORE, record)` (softdelete.py:203).
- Öneri: Silme/restore satırlarına kaydın snapshot'ını (ve restore'da varsa değişen alanları) ekle.

### 13-6 | Orta | Güven: yüksek
**Rol/izin oluşturma ve toplu yazma yolları log dışı: `hr_roles` komutu ve `seed_hr_demo`**
- Dosyalar: hr/roles.py:38-46, hr/management/commands/hr_roles.py:11, hr/management/commands/seed_hr_demo.py:60-77, farm/equipment_types.py:217-225
- Açıklama: `roles.create()` `Group.objects.get_or_create` + `group.permissions.set([...])` ile rol ve izinlerini audit satırı yazmadan oluşturur; uygulamanın en hassas verisi olan izin atamaları bu yolla log'suz verilebilir. `seed_hr_demo` bilinen şifreli hesaplar, roller ve İK kayıtları açar (yalnızca `DEBUG` açıkken çalışıyor, bu iyi bir koruma). `EquipmentType` kataloğu migration'la `update_or_create`/`.update(is_active=False)` yapılır (referans veri, bilinçli). Genel kural: audit yalnızca `crud`/servis yollarında var, model düzeyinde zorlama yok.
- Kanıt: `group.permissions.set([permission(name) for name in preset.permissions])` (roles.py:44) çevresinde `audit` çağrısı yok.
- Öneri: `roles.create()` içinde grup ve izin özeti için `audit.record_create(None/"system", group, ...)` yaz (RoleResource.snapshot yeniden kullanılabilir).

### 13-7 | Orta | Güven: yüksek
**`critical` işareti yalnızca handling uyarısı onayında kullanılıyor; kapasite aşımı ve yüksek yemleme onayları normal kalıyor; severity'yi okuyan alarm yok**
- Dosyalar: farm/stock/services.py:174-177, farm/stock/services.py:493-495, farm/health/services.py:208-214, farm/feeding/services.py:66-77, core/models.py:146-152, core/views.py:50-52
- Açıklama: `AuditSeverity` açıklaması "balık veya gıdayı koruyan uyarının üstünden geçmek" diyor ve "sonraki alarmlar bunu okur" diyor. Kodda tek `critical` üretim yeri handling (açlık/ilaç bekleme) onayı: `critical = assessment is not None and bool(assessment.warnings)` ve tedavi için `checked.warnings`. Aynı türde bilinçli aşımlar, `over_capacity_ack` (stok operasyonu) ve `high_rate_ack` (yüksek yemleme oranı), log'da `normal` kalıyor; `over_capacity_ack` yalnızca değişiklik listesine ekleniyor. Ayrıca `severity` alanını okuyan hiçbir alarm/rapor yok; yalnızca etkinlik logu rozeti ve filtre var (grep: models, views, template). Kritik bir işlemin void'i (VOID satırı) normal yazılıyor, aşılan uyarıyla bağı log'da kopuyor.
- Kanıt: `critical = assessment is not None and bool(assessment.warnings)` (stock/services.py:493); `operation.over_capacity_ack = True; operation.save(update_fields=['over_capacity_ack'])` (stock/services.py:174-176); `record.high_rate_ack = True` (feeding/services.py:72).
- Öneri: Hangi onayların `critical` sayılacağını tek bir tabloda tanımla (kapasite aşımı, yüksek yemleme dahil mi karar ver), void'in aşılan satıra bağlandığını belirt; "sonraki alarmlar" gerçekleşene kadar docstring'i "henüz okunmuyor" şeklinde düzelt.

### 13-8 | Düşük | Güven: yüksek
**"Aynı transaction'da yaz" kuralı yalnızca konvansiyon: `audit.record` bir transaction içinde olup olmadığını denetlemiyor**
- Dosyalar: core/audit.py:1-3, core/audit.py:144-158, config/settings.py (ATOMIC_REQUESTS yok), core/softdelete.py:177-186
- Açıklama: Modül başlığı "Call these inside the same transaction as the change"; ancak `record()` `connection.in_atomic_block` kontrolü yapmıyor, `ATOMIC_REQUESTS` tanımlı değil, `softdelete.execute` da "çağıranın transaction'ında" diyor. Bugün incelenen tüm yazma yolları (`crud`, hr, tasks, stock, inventory, experiments, reports, messaging) atomic blok içinde; ama yeni bir çağıran bloğu unutursa değişiklik logsuz kalır veya log satırı değişiklik olmadan yazılır (autocommit). Bunu yakalayan test de yok.
- Kanıt: `return AuditLog.objects.create(...)` koruma olmadan (audit.py:147); `grep ATOMIC_REQUESTS config/settings.py` boş.
- Öneri: `record()` başında `assert connection.in_atomic_block` (veya `transaction.get_connection().in_atomic_block` ile `RuntimeError`) ekle; testlerde `TestCase` zaten atomic olduğundan `TransactionTestCase` ile bir kontrol testi yaz.

### 13-9 | Düşük | Güven: yüksek
**Log kapsamı model düzeyinde zorlanmıyor; bazı yazmalar bilinçli veya istemsiz log dışı**
- Dosyalar: messaging/services.py:101-112, messaging/services.py:268-276, tasks/services.py:253, tasks/services.py:286, core/language.py:22-23, core/tests.py:198-200
- Açıklama: Doğrulanan log'suz yazmalar: mesaj silme (`delete_message`: `is_deleted/deleted_by` yazılıyor, audit yok; mesaj gönderme de yok), doğrudan konuşma ve katılımcı oluşturma (`start_direct`), `TaskSeries.generated_until` güncellemesi (üretim cursor'ı, `materialise` GET sayfa okumasında bile çalışıyor), `Profile` dil kaydı (`update_or_create`). Bunlar kısmen bilinçli (mesaj içeriği, işlemsel durum), ama hiçbiri "log dışı" olarak belgelenmemiş; `core/tests.py` açıkça "a write that is not logged is not seen: the token test of the writers is what guards that" diyor, yani her yazıcı için ayrı test var ama genel güvence yok. `delete_message` özellikle bir "silme" işlemi olup kimin sildiğini yalnızca satırın kendisi tutuyor.
- Kanıt: `message.is_deleted, message.deleted_at, message.deleted_by = True, timezone.now(), user; message.save(...)` ve audit çağrısı yok (messaging/services.py:271-275).
- Öneri: Log dışı bırakılan yazmaları `docs/data-map` içinde "log yok, nedeni" olarak belgele; mesaj silme için en azından silme eylemi log'lansın (içerik olmadan).

### 13-10 | Düşük | Güven: orta
**Görev "planlı görev" üretimi (`materialise`) GET okumasında log yazıyor ve `system` adı gerçek bir kullanıcıyla çakışabilir**
- Dosyalar: tasks/services.py:211-254, core/audit.py:147-158, core/forms.py:92
- Açıklama: `audit.record(None, ...)` kullanıcı yokken `user_name='system'` yazar. Kullanıcı adı alanında `system` yasak değil; böyle bir kullanıcı oluşturulursa gerçek kullanıcı eylemleri ile sistem eylemleri log'da ayırt edilemez (`user` FK'si `NULL` olduğu için `user_id` ile ayrılabilir, ama arayüz `user_name` filtresi kullanır: `entries.filter(user_name=filters['user'])`). `materialise_due` görev sayfalarını okurken çalıştığından, bir GET isteği yazma ve audit üretir.
- Kanıt: `user_name=user.get_username() if user and user.is_authenticated else 'system'` (audit.py:149); `entries.filter(user_name=filters['user'])` (views.py:44).
- Öneri: Sistem satırlarını `user_name` yerine ayrı bir işaretle ayırt et (ör. `user IS NULL` filtresi) ve `system` kullanıcı adını rezerve et.

### 13-11 | Düşük | Güven: orta
**Erişim kısıtı (`audit.restrict`) kayıt sayfası geçmişinde ve veritabanı görüntüleyicide uygulanmıyor; tür adı karakter dizisi eşlemesine bağlı**
- Dosyalar: core/crud.py:651-653, core/audit.py:25-43, hr/apps.py:9-14, core/views.py:38, core/dbview.py:34
- Açıklama: Etkinlik logu listesi `audit.readable(user)` ile kısıtlı ama kayıt sayfasındaki "History" sekmesi `AuditLog.objects.filter(entity_type=..., entity_id=...)` ile doğrudan okuyor; korumayı yalnızca sayfaya erişimin kendisi (ekip kapsamı) sağlıyor (hr/apps.py yorumu "which the team scope already guards"). `core.browse_database` izni olanlar `audit_log` tablosunu görüntüleyicide tüm satırlarıyla (HR dahil) görür (`audit_log` DB görüntüleyicide listeleniyor). Ayrıca kısıt, İngilizce `verbose_name` metinlerine ("plan", "placement", ...) göre eşleşir; model adı değişirse veya aynı ada sahip başka tür eklenirse ("plan" genel bir sözcük) kısıt sessizce bozulur veya yanlış gizler.
- Kanıt: `history = AuditLog.objects.filter(entity_type=r.entity_type(), entity_id=str(obj.pk))[:20]` (crud.py:652); `_restricted[entity_type] = perm` (audit.py:31).
- Öneri: Geçmiş sorgusunu `audit.readable(request.user, ...)` üzerinden geçir, kısıtı model sınıfına (content type) bağla, görüntüleyicide audit_log HR satırlarını gizle veya izni kısıtla.

### 13-12 | Düşük | Güven: orta
**Kişisel verinin silinmezliği: append-only log ile KVKK/GDPR silme talebi çatışması çözülmemiş; log'da e-posta/ad kalıcı**
- Dosyalar: docs/hr-launch-checklist.md:59, core/models.py:154-157, core/resources.py:56-62, hr/resources/employee.py:84-87
- Açıklama: Log'da kullanıcı adı, e-posta (UserForm snapshot), çalışan adı/numarası, yerleştirme ve izin durumları saklanıyor; tetikleyici silmeyi/anonimleştirmeyi engelliyor. Kontrol listesi 4.2 çatışmanın nasıl çözüleceğine "owner karar verir" diyor ve açık bırakılmış. Teknik tarafta anonimleştirme yolu (ör. `user_name`/etiket pseudonymize eden denetimli bir yordam) yok. Olumlu: kişinin kendi metinleri (`private_fields`) saklanmıyor, yalnızca 8 hex karakterlik HMAC.
- Kanıt: hr-launch-checklist 4.2 satırı "Whether this conflicts with 4.1, and how, is decided by the owner. ☐"; snapshot `fields` içinde `email` (core/forms.py:93 labels).
- Öneri: Silme/anonimleştirme politikasını belirle ve (gerekirse) kontrollü, kendisi de loglanan bir SECURITY DEFINER anonimleştirme fonksiyonu tasarla; tetikleyiciyi buna izin verecek şekilde değiştir.

### 13-13 | Düşük | Güven: orta
**`private` alanlar için kısaltılmış (32 bit) ve `SECRET_KEY`'e bağlı HMAC özeti**
- Dosyalar: core/audit.py:95-100
- Açıklama: Kişisel metin yerine `hmac(SECRET_KEY, text)[:8]` hex saklanıyor. 8 hex = 32 bit: iki farklı metnin aynı özete düşme ihtimali (~1/4 milyar) "değişiklik yok" gibi görünmesine yol açar (düşük risk). `SECRET_KEY` döndürülünce bütün eski özetler yeni değerle farklılaşır, yani anahtar rotasyonundan sonra ilk kaydetmede sahte "değişti" satırı oluşur. Anahtarı bilen biri kısa metinleri kaba kuvvetle sınayabilir.
- Kanıt: `hmac.new(settings.SECRET_KEY.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:8]` (audit.py:98-99).
- Öneri: Ayrı bir `AUDIT_PRIVATE_KEY` kullan, rotasyonu belgele; özeti uzat veya sürüm numarası ekle.

### 13-14 | Orta | Güven: orta
**İzleme duvarının `change_token`/`audit.revision()` mekanizması audit log'un eksiksizliğine ve uygulama saatine bağlı**
- Dosyalar: core/audit.py:127-141, monitoring/read.py:459-470, core/tests.py:198-200
- Açıklama: Duvar sayfası "bir şey değişti mi?" sorusunu yalnızca `audit_log` üzerinden (en yeni `created_at` + son 5 dakikadaki satır sayısı) yanıtlıyor. Bu, audit log'u bir değişiklik veriyolu yapıyor: log'lanmayan bir yazma (13-9) veya log satırı üretmeyen değişiklik (`record_update` fark yoksa `None` döner) duvarı güncellemez; `created_at` uygulama saatinden ve satır oluşturulurken verildiği için, 5 dakikadan (`LATE_COMMIT`) uzun süren bir transaction'ın geç commit olan satırı belirteci hiç değiştirmez (kod yalnızca "5 dakika içindeki geç commit"i yakalıyor); birden çok sunucu arasında saat kayması da sıralamayı bozar. Test dosyası bu sınırı kabul ediyor.
- Kanıt: `LATE_COMMIT = timedelta(minutes=5)` ve `recent = AuditLog.objects.filter(created_at__gte=newest - LATE_COMMIT, ...)` (audit.py:127, 140); test: "a write that is not logged is not seen" (tests.py:198).
- Öneri: Değişiklik belirteci için `audit_log` yerine ayrı bir sayaç/sequence (ör. `pg_current_xact_id`/versiyon tablosu) kullan; en azından zaman damgasını DB'den ata ve sınırı belgele.

### 13-15 | Düşük | Güven: orta
**`entity_type` sütunu 50 karakterle sınırlı ama `label`'ın aksine `bounded()` uygulanmıyor**
- Dosyalar: core/models.py:180, core/audit.py:118-124, core/audit.py:151-155
- Açıklama: `entity_label` taşmasını önlemek için `bounded()` var (EXP-01 hatası sonrası), fakat `entity_type` (`max_length=50`) ve `user_name` (150) aynı korumayı almıyor. Uzun bir `Resource.name`/`verbose_name` (veya İngilizce kaynak metin) eklenirse `DataError` fırlar ve loglanan işlemin kendisi başarısız olur. Bugün mevcut adlar 50 altında (inceleme sırasında en uzunu ~26 karakter), yani yalnızca gelecekteki bir regresyon riski; bunu yakalayan test de yok.
- Kanıt: `entity_type = models.CharField(max_length=50, db_index=True)` (models.py:180); `entity_type=english(entity_type or entity_type_of(type(instance)))` kesme yok (audit.py:151).
- Öneri: `entity_type` için de `bounded` veya sistem kontrolü (`check`) ile tüm model/Resource adlarının ≤50 olduğunu doğrula.

### 13-16 | Düşük | Güven: orta
**Belge dosyası değiştirilince eski dosya commit'te silinir, log yalnızca dosya adını tutar**
- Dosyalar: knowledge/models/document.py:222-242, knowledge/resources/document.py:79-88
- Açıklama: Yeni PDF yüklenince `transaction.on_commit(storage.delete(stored))` eski dosyayı kalıcı siler ve eski `DocumentPage` satırları da silinip yeniden yazılır. Log yalnızca `file_name`, durum ve sayfa sayısı değişimini kaydediyor; içerik özeti/hash yok. Böylece belgenin önceki sürümü hiçbir yerde tutulmuyor ve değişikliğin içeriği denetlenemez (log "dosya X'ten Y'ye" der, ama aynı adlı farklı içerik fark edilmez).
- Kanıt: `transaction.on_commit(partial(self.file.storage.delete, stored))` (document.py:238-239); `values[str(label('file'))] = document.file_name or None` (resources/document.py:85).
- Öneri: Log'a dosya SHA-256 özetini ekle; sürüm geçmişi gerekiyorsa eski dosyayı arşivle.

### 13-17 | Düşük | Güven: orta
**Etkinlik logu sayfası büyüyen tabloda pahalı sorgular çalıştırır; saklama/arşiv politikası yok**
- Dosyalar: core/views.py:35-72, core/models.py:189-197
- Açıklama: Her istekte `Paginator` `COUNT(*)`, `readable.order_by('user_name').values_list(...).distinct()` ve `entity_type` için `DISTINCT` çalıştırır; `user_name` üzerinde indeks yok, `entity_label__icontains` indeksiz tarama yapar. Tablo yalnızca büyür (silme yasak, bölümleme/saklama yok), yani log büyüdükçe sayfa yavaşlar. Tabloda TimescaleDB hypertable/bölümleme kullanılmıyor.
- Kanıt: `'users': readable.order_by('user_name').values_list('user_name', flat=True).distinct()` (views.py:70-71); indeksler yalnızca `created_at`, `entity_type`, `(entity_type, entity_id)`, kısmi critical (models.py:171,180,192-197).
- Öneri: Kullanıcı/tür listesini önbellekle veya ayrı arama tablosundan al, `user_name` için indeks ve arama için `pg_trgm` ekle, saklama/arşiv politikası belirle.

### 13-18 | Bilgi | Güven: yüksek
**Görev notunun tam metni log'a yazılıyor ve `restrict` kapsamında değil**
- Dosyalar: tasks/services.py:192-203
- Açıklama: `add_note` metni olduğu gibi `{NOTE: [None, body]}` olarak log'a yazar (docstring: "logged with its text"). `private_fields` kullanılmayan bu alan, `view_auditlog` iznine sahip herkesin okuyabileceği kalıcı (silinemez) bir kopya olarak kalır; HR notları için yapılan gizleme burada yok. Bilinçli bir tasarım olabilir ama kişisel yorum içerebilir.
- Kanıt: `audit.record(user, AuditLog.Action.UPDATE, task, {str(NOTE): [None, body]})` (tasks/services.py:202).
- Öneri: Not metnini özetle/`private` yap veya görev notlarını `restrict` ile ilgili izne bağla; kararı belgele.
