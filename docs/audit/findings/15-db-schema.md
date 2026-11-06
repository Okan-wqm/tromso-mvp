# 15 - Veritabanı şeması denetimi (db-schema)

## Özet
Şema genel olarak olgun: soft-delete'e duyarlı kısmi unique kısıtları, çok sayıda CHECK, ExclusionConstraint (hr/farm), GeneratedField, tetikleyiciyle korunan append-only/donmuş tablolar ve belgelenmiş bir TimescaleDB hypertable var. Bulunanlar çoğunlukla ince tutarsızlıklar: tekrarlayan indeksler, audit_log'un TRUNCATE'e açık olması ve eksik action CHECK'i, büyük `AuditedModel` tabanından gelen düşük seçicilikli `is_deleted` indeksi, büyüyen tablolar (audit_log, stock_movements, messages) için bölümleme/saklama stratejisinin olmaması, case-duyarlı/duyarsız unique kuralı tutarsızlığı ve hypertable'a özgü riskler (retention/compression yok, geri alma noop).

## İncelenen alanlar
core/models.py, core/migrations/0001-0003, farm/models (water, tank, stock, site, equipment, feeding_protocol, species, supplier, feed), farm/migrations/0014 ve 0019, inventory/models.py, messaging/models.py, knowledge/models (common, document), reports/models.py ve migrations/0002, tasks/models.py, hr/models (posting) ve ilgili migrasyonlar, monitoring/models.py.

## İncelenmeyen alanlar
Canlı veritabanı (EXPLAIN, gerçek indeks kullanımı, pg_stat) incelenmedi; `makemigrations --check` ile model/migrasyon sapması doğrulanmadı (ortamda Django yok); experiments/models.py, hr/models'in kalanı, knowledge/models/entry.py, farm/models'in health/harvest/handling/feeding dosyaları ve çoğu migrasyonun içeriği yalnızca yüzeysel/gözle taranmadı.

## Bulgular

### 15-1 | orta | güven: yüksek - audit_log tetikleyicisi TRUNCATE'i engellemiyor
- Dosyalar: core/migrations/0003_audit_log_append_only.py:4-14, reports/migrations/0002_filed_reports_frozen.py
- Açıklama: Değişmezlik `BEFORE UPDATE OR DELETE ... FOR EACH ROW` tetikleyicisiyle sağlanıyor; `TRUNCATE audit_log` (ve donmuş rapor tabloları) satır tetikleyicisini çalıştırmaz. Tablo sahibi/süper kullanıcı tüm geçmişi tek komutla silebilir. `reverse_sql=DROP` de tetikleyiciyi kaldırır.
- Kanıt: `CREATE TRIGGER trg_audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW` (0003:11-13); TRUNCATE için ifade düzeyi tetikleyici yok.
- Öneri: `BEFORE TRUNCATE ... FOR EACH STATEMENT` tetikleyicisi ekle; uygulama rolünden TRUNCATE/DROP yetkisini al.

### 15-2 | düşük | güven: yüksek - audit_log'da gereksiz (tekrarlayan) indeks
- Dosyalar: core/models.py:180,193
- Açıklama: `entity_type` için tek sütunlu `db_index=True` var; ayrıca `(entity_type, entity_id)` bileşik indeksi var. Bileşik indeksin öndeki sütunu aynı sorguları karşılar; tek sütunlu indeks yazma maliyeti ve disk ekler (append-only büyüyen tablo).
- Kanıt: `entity_type = models.CharField(max_length=50, db_index=True)` ve `models.Index(fields=['entity_type', 'entity_id'])`.
- Öneri: `db_index=True`'yu kaldır.

### 15-3 | düşük | güven: yüksek - audit_log.action için CHECK yok (severity için var)
- Dosyalar: core/models.py:172-199
- Açıklama: `severity` `chk_audit_log_severity` ile kısıtlı ama `action` (create/update/delete/restore/void) serbest 10 karakter; migrasyon 0002'de `void` seçeneği yok (seçenek sonradan eklendi), yani seçim listesi ile veri bütünlüğü tutarsız ele alınmış.
- Kanıt: `constraints = [CheckConstraint(severity__in=...)]` tek kısıt; `action = CharField(max_length=10, choices=...)`.
- Öneri: `chk_audit_log_action` ekle. (Değişmez tabloda ihlal eden eski satır olmadığını doğrula.)

### 15-4 | düşük | güven: yüksek - `AuditedModel.is_deleted` her tabloda tek sütunlu indeks
- Dosyalar: core/models.py:35
- Açıklama: Boolean, çok düşük seçicilikli sütuna her kayıt tablosunda B-tree indeksi açılıyor. Çoğu sorgu `is_deleted=False` ile birlikte başka sütunlara filtre uygular; kısmi unique indeksler zaten `is_deleted=False` koşullu. Sorgu planlayıcı bu indeksi nadiren kullanır, yazmada maliyet getirir.
- Kanıt: `is_deleted = models.BooleanField(..., default=False, db_index=True)` (tüm AuditedModel alt sınıfları).
- Öneri: İndeksi kaldır; gerekirse kısmi/örtük indeksler kullan.

### 15-5 | düşük | güven: yüksek - Meta indeksleri FK'nin otomatik indeksiyle çakışıyor
- Dosyalar: farm/models/stock.py:399, inventory/models.py:125,390
- Açıklama: Django her ForeignKey'e otomatik indeks açar. `StockMovement` `Index(fields=['batch'])` (batch FK db_index varsayılan True), `StorageLocation` `Index(fields=['site'])`, `InventoryLine` `Index(fields=['location'])` aynı sütunu ikinci kez indeksler. (Karşıt örnek: water.py:104 `db_index=False` ile bu hatadan kaçınmış.) Migrasyonda ayrıca `AddIndex` olarak oluşuyor (inventory/migrations/0001_storage.py:189-191,257-259).
- Kanıt: `indexes = [models.Index(fields=['unit', 'batch']), models.Index(fields=['batch'])]`; `batch = ForeignKey(Batch, ...)` db_index=False verilmemiş.
- Öneri: FK'ye `db_index=False` ver veya fazladan Meta indeksini sil. Not: `(unit, batch)` bileşik indeksi `unit` FK indeksini kısmen gereksiz kılar.

### 15-6 | orta | güven: orta - büyüyen defter/log tabloları için saklama/bölümleme stratejisi yok
- Dosyalar: core/models.py:162, farm/models/stock.py:341, messaging/models.py:112, farm/migrations/0014_water.py
- Açıklama: Tek hypertable `water_measurements` (90 günlük chunk). Retention/compression politikası yok; `audit_log` UUIDv4 PK'lı sade tablo ve silinemez olduğu için budanamaz; `stock_movements`, `messages` sınırsız büyür. UUIDv4 PK rastgele B-tree ekleme maliyeti getirir. Ölçek MVP için küçük olabilir (güven orta).
- Kanıt: `create_hypertable('water_measurements', by_range(...))` tek çağrı; `add_retention_policy`/`add_compression_policy` aramasında sonuç yok; audit_log için hypertable/partition yok.
- Öneri: Gereksinime göre compression/retention kararını belgele; audit_log için zaman bölümleme (partition) düşün.

### 15-7 | orta | güven: yüksek - Hypertable dönüşümü geri alınamaz ve PK ile Django durumu ayrışık
- Dosyalar: farm/migrations/0014_water.py:91-103, farm/models/water.py:62-66
- Açıklama: Fiziksel PK `(id, measured_at)`, Django modeli `id` PK'sını görüyor. Sonuçlar: `reverse_sql=noop`; `bulk_create(update_conflicts)`, `update_or_create`, FK ile bu tabloya başvuru (zaten yasak, yalnızca docstring'de) kırılgan; id ile tek başına get/update tüm chunk'lara bakar. Sınırlama kodda sadece açıklama olarak duruyor, otomatik test/kısıt yok.
- Kanıt: `ALTER TABLE water_measurements DROP CONSTRAINT water_measurements_pkey` / `ADD CONSTRAINT ... PRIMARY KEY (id, measured_at)`; docstring "no foreign key points at this table".
- Öneri: Bu tabloya FK eklenmesini engelleyen bir test ekle; geri yükleme (timescaledb_pre/post_restore) prosedürünü belgele.

### 15-8 | düşük | güven: yüksek - `uq_water_measurements_entry` (entry_key, measured_at) idempotansı zayıf
- Dosyalar: farm/models/water.py:121-124, farm/water/services.py:135,170
- Açıklama: Diğer tablolarda `entry_key` tek başına `unique=True` iken burada hypertable gereği `measured_at` ile birleşik. Aynı form farklı `measured_at` ile gönderilirse DB iki kayda izin verir; korumanın tamamı uygulama kontrolüne (`filter(entry_key=token, measured_at=...)`) bağlı. NULL `entry_key` için de benzersizlik yok.
- Kanıt: `UniqueConstraint(fields=['entry_key', 'measured_at'])`; services.py:135 `filter(entry_key=token, measured_at=measured_at)`.
- Öneri: Bilinen sınırlama olarak belgele; formun zamanı sabit gönderdiğini testle doğrula.

### 15-9 | düşük | güven: yüksek - unique kuralı büyük/küçük harf duyarlılığı tutarsız
- Dosyalar: farm/models/site.py:134-137, farm/models/species.py:135, farm/models/supplier.py:168, farm/models/feed.py:181
- Açıklama: Supplier/Feed/Board/Template adları `Lower('name')` ile benzersiz; `Site.name` ise `fields=['name']` (büyük/küçük harf duyarlı): "Tromso" ve "tromso" iki ayrı site olabilir. Kodlar (`code`) büyük harfe zorlanıyor ama `uq_*_code_live` doğrudan eşitlik.
- Kanıt: `models.UniqueConstraint(fields=['name'], condition=Q(is_deleted=False), name='uq_sites_name_live')`.
- Öneri: `Lower('name')` kullan.

### 15-10 | düşük | güven: yüksek - kod benzersizliği tüm çiftlik genelinde (site/bölüm kapsamı yok)
- Dosyalar: farm/models/tank.py:389-393, inventory/models.py:97-100
- Açıklama: `Tank.code` ve `StorageLocation.code` yalnızca `is_deleted=False` koşuluyla global benzersiz; çok lokasyonlu çiftlikte iki site aynı birim kodunu kullanamaz. Kod yorumları (tank.py:394-396) regulatory_unit_id'nin site kapsamlı olması gerektiğini söylüyor ama DB yalnızca production_department kapsamında tutuyor (site kapsamı clean()'de).
- Kanıt: `UniqueConstraint(fields=['code'], condition=Q(is_deleted=False), name='uq_tanks_code_live')`; `uq_tanks_regulatory_unit_id_live` `production_department` ile.
- Öneri: İş kararını belgele; site düzeyi benzersizlik DB'de tutulamıyorsa (join gerekir) tetikleyici/denormalize site_id düşün.

### 15-11 | düşük | güven: yüksek - Site.facilities/settings/metadata JSONField null=True (iki boş durum)
- Dosyalar: farm/models/site.py:111-114
- Açıklama: `null=True, blank=True` ile NULL ve `{}`/`null` JSON değerleri ayrı boş durumlar; JSON `null` ile SQL NULL karıştırılabilir. Şema/tip denetimi (CHECK jsonb_typeof) yok, oysa monitoring.CardTemplate bunu yapıyor. Ayrıca `settings` alan adı Django `settings` ile karışmaya açık.
- Kanıt: `facilities = models.JSONField(_('Facilities'), null=True, blank=True)` x3.
- Öneri: `default=dict`, null=False ve jsonb_typeof CHECK.

### 15-12 | düşük | güven: yüksek - Uzun metinler için CharField(max_length=10000/5000)
- Dosyalar: knowledge/models/document.py:99-100, reports/models.py:~89-94
- Açıklama: `Document.abstract` max_length=10000, `authors` 5000 gibi uzun varchar'lar; PostgreSQL'de TextField+CHECK ile eşdeğer ama migrasyon maliyeti (limit değişimi ALTER) fazla. Aynı projede başka yerlerde `TextField` kullanımı var (tutarsızlık).
- Kanıt: `abstract = models.CharField(_('Abstract'), max_length=10000, blank=True)`.
- Öneri: TextField + CHECK(char_length) tutarlı yaklaşım.

### 15-13 | düşük | güven: orta - `uq_tasks_series_occurrence` soft-delete'e duyarsız
- Dosyalar: tasks/models.py:~397-399
- Açıklama: Diğer tüm unique kısıtlar `is_deleted=False` koşullu iken (series, occurrence_date) koşulsuz; silinmiş (soft-deleted) bir görev aynı günün yeniden üretilmesini sonsuza kadar engeller. Kasıtlı olabilir (yeniden üretimi önlemek), ancak yorumla belirtilmemiş.
- Kanıt: `UniqueConstraint(fields=['series','occurrence_date'], condition=Q(series__isnull=False))`.
- Öneri: Niyeti yoruma yaz veya restore akışında çakışmayı test et.

### 15-14 | düşük | güven: orta - Çok-sütunlu null'lanabilir FK ile polimorfik bağ (tasks, monitoring, sampling points)
- Dosyalar: tasks/models.py:337-342, monitoring/models.py (CardTemplateAssignment), farm/migrations/0019_water_points.py
- Açıklama: Yer bilgisi 5 ayrı nullable FK + "tek yer" CHECK ile tutuluyor (site, bölüm, sistem, birim, ekipman). Bütünlük DB'de güvenceli ama sütun sayısı arttıkça şema ve kısıt ifadeleri çoğalıyor; yeni yer türü eklemek migrasyon + CHECK + unique'leri değiştirmeyi gerektirir.
- Kanıt: `chk_tasks_one_place`, `chk_monitor_card_assignments_one_scope`, `chk_water_sampling_points_one_owner`.
- Öneri: Bilgilendirme; ortak "place" tablosu düşünülebilir.

### 15-15 | bilgi | güven: yüksek - Güçlü yanlar
- Dosyalar: core/models.py, farm/models/stock.py, hr/models/posting.py, reports/models.py, messaging/models.py
- Açıklama: Defter satırlarında işaret/ödeme CHECK'leri, tarih aralığı ExclusionConstraint'leri (btree_gist), mesaj-konuşma bileşik FK mantığı (`participant_in_conversation`), donmuş rapor tetikleyicileri, GeneratedField'lar (Tank hacmi, search_vector), `period_start` takvim CHECK'leri iyi düşünülmüş. Eksiklik değil, doğrulandı.
- Kanıt: ilgili model Meta.constraints blokları.
- Öneri: Yok.
