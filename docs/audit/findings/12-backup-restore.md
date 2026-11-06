# 12 - Yedekleme / Geri Getirme (backup-restore) Denetimi

## Özet

Depoda hiçbir yedekleme mekanizması (script, cron, pg_dump/pg_basebackup, WAL arşivleme, yedek servisi, geri yükleme prosedürü, felaket kurtarma planı) yoktur. Tek ilgili belge README.md:2991-2993'teki bir cümledir ("back it up with the database"). Uygulama düzeyinde geri alma ise yumuşak silme (soft delete) + `void` + `AuditLog` ile kurulmuştur; bu mekanizma tutarlı ve iyi düşünülmüştür, ancak (a) silinen kaydın alt kayıtlarını geri getirmez, (b) SET_NULL ile koparılan bağları geri bağlamaz, (c) AuditLog'daki eski değerlerden otomatik geri alma yoktur, (d) yönetici dışında kullanıcı arayüzünde geri getirme yoktur. Docker volume tek bir adlandırılmış `pgdata` volume'üdür; medya dosyaları (PDF) ayrı bir yerde, veritabanından bağımsız yaşar ve tutarlı bir anlık görüntü garantisi yoktur. TimescaleDB hypertable (`water_measurements`) için geri yükleme prosedürü (`timescaledb_pre_restore/post_restore`) hiçbir yerde belgelenmemiştir.

## İncelenen alanlar

- docker-compose.yml (volume, imaj sürümü, restart politikası)
- config/settings.py (DB, MEDIA_ROOT, ATOMIC_REQUESTS yokluğu)
- core/models.py (AuditedModel, AuditLog), core/softdelete.py, core/audit.py, core/admin.py (restore eylemi), core/crud.py (silme akışı)
- Sert silme (hard delete) noktaları: tasks/services.py, reports/services.py, core/crud.py, experiments/services.py, farm/feeding/protocols.py, farm/forms/equipment.py
- knowledge/models/document.py (dosya yaşam döngüsü)
- farm/migrations/0014_water.py (hypertable), core/migrations/0003 (append-only trigger), reports/migrations/0002 (donmuş rapor trigger'ları), geri dönüş (reverse) migrasyonları
- README.md "Local setup", docs/ içinde backup/dump araması

## İncelenmeyen alanlar

- Gerçek üretim dağıtımı (repoda yok; Dockerfile, CI, Kubernetes, systemd yok)
- Testlerin çalıştırılması ve geri yükleme provası (yıkıcı işlem yasaktı)
- Frontend tarafındaki geri alma (frontend/grid/history.ts) yalnızca istemci içi undo, yedekle ilgisi yok; ayrıntılı incelenmedi
- Uygulamayla ilgisiz altyapı (TLS, ağ)

## Bulgular

### 12-1 - Hiçbir yedekleme mekanizması veya geri yükleme prosedürü yok
- Önem: high | Güven: high
- Dosyalar: docker-compose.yml, README.md:2975-2993, scripts/ (yalnızca mark-esm.mjs), docs/
- Açıklama: Repoda pg_dump/pg_basebackup/WAL arşivleme/pgBackRest/cron/yedek konteyneri yok; docs/ altında backup, dump, recover geçen hiçbir belge yok. Çiftlik üretim kayıtları, tıbbi ilaç bekleme süreleri ve resmi rapor verisi (filed reports) tek bir PostgreSQL örneğinde duruyor.
- Kanıt: `ls scripts` -> yalnızca `mark-esm.mjs`; `grep -iE "backup|dump|recover" docs/*.md` boş; docker-compose.yml yalnızca `db` servisi içerir.
- Öneri: Yazılı bir yedekleme politikası (RPO/RTO), otomatik mantıksal (pg_dump -Fc) ve fiziksel/WAL yedek, yedeğin tatbikatlı geri yükleme testi ve docs/ altında bir runbook ekleyin.

### 12-2 - Tek adlandırılmış Docker volume, redundancy ve yedek yok
- Önem: high | Güven: high
- Dosyalar: docker-compose.yml:15-19
- Açıklama: Veri `pgdata` adlı tek yerel volume'de. `docker compose down -v`, `docker volume prune` veya disk arızası tüm veriyi kaybettirir. Komutlar arasında koruma/uyarı yok. Dosya "Local development database" diye başlıyor, ama README aynı yapıyı kurulum yolu olarak sunuyor; üretim için ayrı bir tanım yok.
- Kanıt: `volumes: [pgdata:/var/lib/postgresql/data]`, `volumes: pgdata: {}`; varsayılan parola `balik` (docker-compose.yml:10-11).
- Öneri: Üretim için ayrı compose/yönergede volume'ü hostta bilinen bir yola bağlayın veya yönetilen veritabanı kullanın; yedek servisi ve volume snapshot ekleyin; dev/prod ayrımını belgeleyin.

### 12-3 - Yüklenen PDF'ler (MEDIA_ROOT) veritabanı yedeğinden ayrı; tutarlılık garantisi yok
- Önem: high | Güven: high
- Dosyalar: config/settings.py:180, knowledge/models/document.py:52-55,115-118, README.md:2992-2993, .gitignore
- Açıklama: Belge dosyaları yerel dosya sistemindeki `MEDIA_ROOT`'ta (varsayılan checkout içinde `media/`), kayıtlar ise veritabanında. docker-compose'da medya için volume yok. README yalnızca "back it up with the database" der; nasıl, hangi sırayla, tutarlı anlık görüntü nasıl alınır anlatılmaz. DB geri yüklenip medya eski/eksik olursa `Document.file` kayıtları yok dosyaya işaret eder; tersi durumda artık dosyalar kalır.
- Kanıt: `MEDIA_ROOT = Path(os.environ.get('DJANGO_MEDIA_ROOT', BASE_DIR / 'media'))`; dosya adı `knowledge/documents/{uuid}.pdf`.
- Öneri: Medyayı kalıcı volume/obje depolamaya taşıyın (sürümlemeli), DB yedeğiyle birlikte aynı zaman noktasında alın, bir bütünlük kontrol komutu (kayıt <-> dosya) ekleyin.

### 12-4 - Belge dosyası değiştirilince eski dosya geri dönülemez biçimde silinir
- Önem: medium | Güven: high
- Dosyalar: knowledge/models/document.py:239-241 (ve 90-91)
- Açıklama: Dosya değiştirildiğinde/temizlendiğinde eski PDF commit sonrası `storage.delete` ile fiziksel olarak silinir. Belge yumuşak silinirse dosya kalır, ama düzenleme sonrası eski sürüm için geri alma yok; AuditLog yalnızca dosya adı/boyutu gibi meta verileri tutar. Yanlış dosya yüklenirse orijinal yedek yoksa kaybolur.
- Kanıt: `transaction.on_commit(partial(self.file.storage.delete, stored))`.
- Öneri: Eski dosyayı hemen silmeyin; gecikmeli temizlik (örn. 30 gün) veya depolama sürümlemesi kullanın.

### 12-5 - Silinen kaydı geri getirmek yalnızca kaydın kendisini geri getirir; CASCADE ile silinen çocuklar elle geri getirilmeli
- Önem: medium | Güven: high
- Dosyalar: core/softdelete.py:185-203 (restore), 168-182 (execute), core/admin.py:39-53
- Açıklama: `execute` CASCADE çocuklarını kendi kayıtlarıyla siler; `restore` ise "Only the record itself returns, not what was deleted with it" der. Admin eylemi yalnızca seçilen kayıtları geri getirir; hangi çocukların birlikte silindiğine dair bir bağ (silme grubu/aynı `deleted_at` ile eşleme/işlem kimliği) tutulmaz. Yönetici, bir sistemi geri getirdiğinde silinen alt kayıtları tek tek bulmak zorundadır; `deleted_at` aynı olmadığı için (her kayıt kendi `timezone.now()`'ını alır) toplu bulma da güçtür.
- Kanıt: `soft_delete` her kayıtta ayrı `timezone.now()`; `restore(record, user)` tek kaydı işler; docstring'de açık beyan.
- Öneri: Silme işlemine ortak `deletion_batch` kimliği/zaman damgası ekleyin; restore bu gruptaki kayıtları isteğe bağlı birlikte geri getirsin ve ne getirildiğini kaydetsin.

### 12-6 - SET_NULL ile koparılan bağlar restore'da geri bağlanmaz
- Önem: medium | Güven: high
- Dosyalar: core/softdelete.py:168-174 (detach), 185-203, core/models.py:55-60
- Açıklama: Silinen kaydın SET_NULL çocukları (ör. silinen sitenin üretim departmanları) `detach` ile bağını kaybeder ve yeni bir UPDATE audit satırı yazılır; kaydı geri getirmek bu bağları yeniden kurmaz. Eski değer yalnızca AuditLog.changes içinde metin etiketi (`str(getattr(record, link))`) olarak durur, kimlik (pk) saklanmaz, dolayısıyla otomatik geri bağlama da yapılamaz.
- Kanıt: `before = str(getattr(record, link))`; `audit.record(user, UPDATE, record, {label: [before, None]})`; `restore` içinde detach'lerin tersi yok.
- Öneri: Audit satırına bağlı kaydın pk'sini de yazın veya silme planını (detach/cascade listesi) saklayıp geri getirmede tersini uygulayın.

### 12-7 - AuditLog'dan "geri al" (değişiklik geri alma) yok; değerler görüntü metni olarak saklanır
- Önem: medium | Güven: high
- Dosyalar: core/audit.py:78-104, core/models.py:105-115
- Açıklama: Güncelleme geçmişi `{etiket: [eski, yeni]}` olarak tutulur ama değerler `str(...)`/yerelleştirilmiş görünüm metni, FK'lar için `str(nesne)`, ondalıklar biçimli metin, özel (private) metinler yalnızca HMAC özeti ("Private text"). Bu yüzden audit log bir kaydı önceki sürüme döndürmek veya veritabanı yedeği olmadan kaybolan bir alanı kurtarmak için kullanılamaz. Düzenleme (UPDATE) hatasında geri almanın tek yolu elle yeniden girmektir.
- Kanıt: `_display()` FK için `str(value)`; `snapshot(..., private=...)` metni asla saklamaz.
- Öneri: Belgeleyin ki audit log kurtarma kaynağı değildir; kritik modeller için sürüm tablosu/ham değer anlık görüntüsü düşünün.

### 12-8 - AuditLog yalnızca DB trigger'ı ile korunuyor; DB yedeği olmadan log kendisi tek noktadır ve süresiz büyür
- Önem: low | Güven: medium
- Dosyalar: core/migrations/0003_audit_log_append_only.py, core/models.py:81-125
- Açıklama: Trigger UPDATE/DELETE'i engeller (iyi), fakat tablo tüm silmeleri engellediği için arşivleme/saklama süresi (retention) politikası uygulanamaz; trigger kaldırılmadan satır budanamaz. Log tablosu hypertable değildir ve bölümlenmemiştir. Log ayrıca ana veritabanıyla aynı volume'de olduğundan yedek yoksa "değişmez" olması felakette bir koruma sağlamaz. Süper kullanıcı trigger'ı kaldırabilir (migration geri alma da bunu yapar: reverse_sql=DROP).
- Kanıt: `CREATE TRIGGER ... BEFORE UPDATE OR DELETE ON audit_log`; `reverse_sql=DROP`; AuditLog için `create_hypertable` yok.
- Öneri: Log'u ayrı yere akıtın (WAL/dış arşiv), saklama/arşiv stratejisi belirleyin (örn. bölümleme veya ayrı rol ile arşiv işlemi).

### 12-9 - Yönetici arayüzünde geri getirme yok ("void" sınıfı) ve bazı kayıt türleri için hiç geri alma yok
- Önem: low | Güven: high
- Dosyalar: README.md:568, 1004, 1276, 1497, 1844; core/admin.py:39-53
- Açıklama: Void'lanmış operasyonlar, besleme, su örnekleri, tedaviler, olaylar ve sayımlar için yönetici geri getirme "bilerek" yok (kontrolleri atlayacağı için). Bu tutarlı bir tasarım, ancak yanlış void yapıldığında bunun tek çaresi "yeniden girmek"tir; su örneklerinde `entry_key` aynı olduğundan aynı form yeniden gönderilirse unique constraint nedeniyle de engellenebilir (kontrol edilmedi; confidence düşük).
- Kanıt: README satırları yukarıda; `uq_water_measurements_entry` (entry_key, measured_at) farm/models/water.py:125.
- Öneri: Void'u geri alan, kontrolleri çalıştıran bir "unvoid" servisi düşünün veya düzeltme yolunu (yeni giriş) belgeleyin.

### 12-10 - Sert silme (hard delete) kullanan yerler audit ile kurtarılamaz
- Önem: medium | Güven: high
- Dosyalar: tasks/services.py:267-271, reports/services.py:130-138, 169-174, core/crud.py:782-785, farm/feeding/protocols.py:65, farm/forms/equipment.py:186, experiments/services.py:231,444, core/crud.py:364
- Açıklama: AuditedModel olmayan satırlar (DueClosure, OutsideDutyDone, bazı RowList satırları, protokol bantları, ekipman-sistem bağları, deney yerleşimleri) fiziksel silinir. Audit satırı yalnızca etiket metni yazar; kayıt geri getirilemez. Ekipman-sistem bağlarında `_save_m2m` tüm bağları silip yeniden oluşturur; silinmiş sistemlerin bağlarının da kaybolduğu kodda açıkça yazılı (feature olarak) ama bu, silinmiş sistem geri getirilince bağın geri gelmeyeceği anlamına gelir; README:162 ise "Saving the equipment drops its links to deleted systems" diyerek bunu kabul eder.
- Kanıt: `closure.delete()`, `record.delete()`, `self.instance.system_links.all().delete()`.
- Öneri: Bu kayıtlar için "kurtarılamaz" olduğunu belgeleyin; kritik olanlarda (rapor kapanışları) yumuşak silme veya silinen değerleri audit'e tam yazma.

### 12-11 - Silme akışında tek işlemde (transaction) atomiklik: ATOMIC_REQUESTS yok, bazı akışlar atomic dışında olabilir
- Önem: low | Güven: low
- Dosyalar: config/settings.py (ATOMIC_REQUESTS ayarı yok), core/crud.py:770-785, core/audit.py:1-2
- Açıklama: audit.py "değişiklik ve log satırı aynı işlemde" kuralını çağırana bırakır. `ATOMIC_REQUESTS` tanımlı değildir; crud.py'deki silme görünüm kodu `select_for_update` kullandığı için bir `transaction.atomic` içinde olduğu anlaşılıyor, ancak tüm servislerin bu kurala uyduğu tek merkezden zorlanmaz. Bir servis unutulursa kayıt-log tutarsızlığı oluşabilir ve yedekten geri yüklemede fark edilmez. Tüm çağrı noktalarını doğrulamadım.
- Kanıt: grep `ATOMIC` -> sonuç yok; `softdelete.execute` "inside the caller's transaction" der.
- Öneri: `execute`/`record` içinde `transaction.get_connection().in_atomic_block` iddiası (assert) veya kendi `atomic` bloğu ekleyin.

### 12-12 - TimescaleDB hypertable (water_measurements) için yedek/geri yükleme özel adımları belgelenmemiş
- Önem: medium | Güven: medium
- Dosyalar: farm/migrations/0014_water.py:91-103, core/migrations/0001_timescaledb.py, docker-compose.yml:6
- Açıklama: Hypertable'lı veritabanı pg_dump ile geri yüklenirken `timescaledb_pre_restore()`/`timescaledb_post_restore()` gerekir; imaj sürümü (`2.17.2-pg17`) sabitlenmiş ama yedek/geri yükleme aynı veya uyumlu TimescaleDB sürümü gerektirir; bu hiçbir yerde yazılı değil. Ayrıca birincil anahtar (id, measured_at) olarak elle değiştirildi (Django durumu `id` der), yedekten geri yüklenen şema ile `makemigrations` uyumu test edilmeli. Veri saklama (retention) ve sıkıştırma politikası yoktur; 90 günlük chunk'lar süresiz büyür (miktar düşük, sadece bilgi).
- Kanıt: `create_hypertable('water_measurements', by_range('measured_at', INTERVAL '90 days'))`; `reverse_sql=migrations.RunSQL.noop` (geri alma sırasında hypertable ayrıca dönüştürülmez, CreateModel tersi tabloyu siler); 'timescaledb_pre_restore' için repo araması boş.
- Öneri: Runbook'a pre/post_restore adımlarını, sürüm eşleşmesi gereksinimini ve bir geri yükleme testini ekleyin.

### 12-13 - Migrasyon geri dönüşü (rollback) bazı veri dönüşümlerinde kayıplı veya engelli
- Önem: low | Güven: medium
- Dosyalar: farm/migrations/0022_purging_degree_days.py:18-31,89, farm/migrations/0021_medicine_withdrawals.py, farm/migrations/0019_water_points.py:186-197, farm/migrations/0023_reports_fields.py:45,91, hr/migrations/0003_scheduling.py:120, farm/migrations/0004_production_departments.py:43
- Açıklama: Birçok RunPython geri yönü `noop`'tur (0023, 0007, 0004, hr/0003); veri geri dönüşte yeniden üretilmez. 0022 geri dönüşte `IrreversibleError` ile bilinçli reddeder (iyi), 0019 ve 0021 gerçek bir geri yön yazmış. Monitoring 0004 README:719 "a rollback loses nothing" iddiası var; bu kontrol edilmedi. Sonuç: şema geri alma güvenilir bir felaket kurtarma yolu değildir; tek gerçek yol yedektir ve bu da 12-1'e bağlıdır.
- Kanıt: `RunPython(provenances, migrations.RunPython.noop)` vb.
- Öneri: Yıkıcı migrasyon öncesi zorunlu yedek adımı ekleyin (deploy runbook).

### 12-14 - Donmuş (filed) rapor trigger'ları geri yükleme/veri yükleme sırasında engel olabilir ve yönetici düzeltme yolu yok
- Önem: low | Güven: medium
- Dosyalar: reports/migrations/0002_filed_reports_frozen.py, reports/models.py:162-163, monitoring/migrations/0002_card_templates.py (README.md:707-711)
- Açıklama: Gönderilmiş raporlar, snapshot'lar ve audit_log için UPDATE/DELETE trigger'ları var. Bu, `pg_restore --clean`, `TRUNCATE` dışı yeniden yükleme veya satır bazlı veri onarımı yaparken engel çıkarır ve yedekten tek satır kurtarma işlemi için trigger'ların devre dışı bırakılması gerekir. Bu prosedür belgesiz. (Tam veri yükleme için `session_replication_role = replica` gerekebilir; denenmedi.) Olumlu yan: donmuş rapor korumaları veri bütünlüğü açısından güçlüdür.
- Kanıt: `RAISE EXCEPTION 'regulatory report % was filed: it is never deleted'`.
- Öneri: Geri yükleme runbook'unda trigger ve `session_replication_role` yönetimi sırasını belirtin.

### 12-15 - Üst düzey geri yükleme kontrolü: restore() yalnızca doğrudan FK ebeveynlerini ve full_clean'i kontrol eder
- Önem: low | Güven: medium
- Dosyalar: core/softdelete.py:185-203
- Açıklama: `restore` kaydın kendi FK'larında silinmiş hedef olup olmadığına bakar; fakat `delete_blockers()`'a eşdeğer bir "geri getirme engeli" yok, M2M bağlı silinmiş kayıtlar (ör. ekipmanın silinmiş sistemleri) kontrol edilmez, ve geri getirilen kaydın model düzeyindeki iş kuralları (ör. kayıt kapasite, kodun başka kayıtta alınması dışında) `full_clean` kapsamıyla sınırlıdır. Ayrıca `restore` içinde `select_for_update` yok; eşzamanlı restore ve düzenleme yarışabilir (version artırılıyor ama karşılaştırma yok).
- Kanıt: `record.version += 1`, `record.full_clean()`, `record.save()`; sürüm karşılaştırması yok.
- Öneri: Restore'da satır kilidi ve `restore_blockers()` kancası ekleyin.

### 12-16 - Yönetici geri getirmesi yalnızca Django admin içinde; uygulama arayüzünde çöp kutusu yok
- Önem: info | Güven: high
- Dosyalar: core/admin.py:27-53, core/crud.py:770-789
- Açıklama: Silme (silmeden önce onay ekranı ile) kullanıcı arayüzünde var, geri getirme yalnızca `change_<model>` iznine sahip admin kullanıcısı için Django admin'inde. Üretimde Django admin'in açık olup olmadığı (URL yönlendirmesi) bu denetimde incelenmedi. Kullanıcı hatalı silmeyi kendi başına geri alamaz.
- Kanıt: `actions = ['restore']`; has_restore_permission yalnızca change yetkisine bağlı.
- Öneri: Çöp kutusu ekranı veya (güvenli kısa süre içinde) "geri al" bağlantısı düşünün.

### 12-17 - Veritabanı kimlik bilgileri varsayılan, `restart: unless-stopped` ile yedek yokken tek örnek
- Önem: info | Güven: high
- Dosyalar: docker-compose.yml:8-12, config/settings.py:113-117
- Açıklama: Varsayılan kullanıcı/parola `balik/balik`; yedek istemcisinin kullanacağı ayrı salt-okunur yedek rolü yok. Yedekleme tasarlanırken bir `pg_dump` rolü ve `.pgpass` gerekir; bu hazırlık yok. Sağlık kontrolü (`healthcheck`) tanımı da yok.
- Kanıt: `POSTGRES_PASSWORD: ${DB_PASSWORD:-balik}`; healthcheck anahtarı yok.
- Öneri: Yedek rolü ve healthcheck ekleyin.
