# 14 - Migrations denetimi

## Özet

12 uygulamanın 7 tanesinde (core, farm, hr, reports, monitoring, experiments, messaging) elle yazılmış RunSQL/RunPython adımları var; toplam ~60 migration dosyası incelendi. Genel kalite yüksek: tetikleyici (trigger) migration'larının hepsinin `reverse_sql`'i var, veri migration'larının çoğu (farm 0019/0021/0022, reports 0005) gerçek bir geri dönüş yazıyor ve geri dönülemeyen durumda veriyi değiştirmeden `IrreversibleError` ile duruyor; bunlar için TransactionTestCase testleri var. Bağımlılık grafında merge migration gerekmiyor (her uygulamada tek, ardışık numaralı yaprak; sadece reports 0005 -> farm 0024 için bilinçli `run_before`). Kalan riskler: (1) migration'ların canlı uygulama kodunu import etmesi (tekrarlanabilirlik), (2) `BtreeGistExtension` geri alma / hr uzantı sahipliği tutarsızlığı, (3) büyük tablolarda (audit_log, hypertable) kilitleme riski ve dağıtım yönergesi yokluğu, (4) bazı geri alma yollarının sessizce veri kaybettirmesi (noop reverse), (5) test kapsamı boşlukları, (6) frozen/append-only trigger'ların gelecekteki veri migration'larını engellemesi. Django kurulu olmadığından `makemigrations --check` ve testler çalıştırılamadı.

## İncelenen alanlar
- Tüm `*/migrations/0*.py` (core 0001-0007, farm 0001-0026, hr 0001-0008, reports 0001-0012, monitoring 0001-0004, experiments 0001-0002, inventory/knowledge/messaging/tasks 0001)
- RunSQL/RunPython adımlarının ileri/geri yönleri, uygulamalar arası `dependencies`/`run_before` grafı
- Trigger'lı (frozen/append-only) tablolarla veri migration'ı etkileşimi
- TimescaleDB hypertable adımı (farm 0014), uzantı (extension) migration'ları
- Migration testleri (`MigrationExecutor` kullanan 8 test dosyası), README migrate talimatı

## İncelenmeyen alanlar
- `makemigrations --check` ve testler çalıştırılmadı (ortamda Django/PostgreSQL yok); model-migration durum uyuşmazlığı doğrulanmadı.
- farm 0005/0016/0018 gibi salt şema (CreateModel) migration'larının her alanı satır satır doğrulanmadı.
- Gerçek prod veri hacmi bilinmediği için kilit süreleri tahmin edilmedi, yalnızca yapısal risk kaydedildi.

## Bulgular

### 14-1 - BtreeGistExtension geri alma ve hr 0002'nin uzantıya sahipliği tutarsız
- Önem: medium - Güven: medium
- Dosyalar: farm/migrations/0015_feeding_protocols.py:25, hr/migrations/0002_people.py:21, hr/migrations/0005_leave.py:139, experiments/migrations/0001_initial.py:2
- Açıklama: `btree_gist` uzantısını farm 0015 `BtreeGistExtension()` ile (geri alınca `DROP EXTENSION`) oluşturuyor; hr 0002 ise aynı uzantıyı `CREATE EXTENSION IF NOT EXISTS` ile, `reverse_sql=noop` olarak ayrıca oluşturuyor ve hr 0002/0005/0006 exclusion constraint'leri uzantıya bağlı. hr, farm 0015'e bağımlı değil (yalnızca farm 0004). farm 0015 geri alınırsa `DROP EXTENSION` hr'nin exclusion constraint'lerine bağımlılık nedeniyle hata verir (hr geri alınmadıkça). Uzantının "sahibi" belirsiz; sıra bağımsız olduğundan taze kurulumda hangisinin oluşturduğu rastgele.
- Kanıt: farm 0015:25 `BtreeGistExtension()`; hr 0002:21 `RunSQL('CREATE EXTENSION IF NOT EXISTS btree_gist', reverse_sql=migrations.RunSQL.noop)`; experiments 0001:2 yorumu "farm 0015 creates the extension ... reversing that would drop it".
- Öneri: Uzantıyı tek yerde (örn. core, timescaledb gibi) oluşturup farm 0015 ve hr 0002'yi ona bağımlı yapmak; farm 0015'in reverse'ünü noop yapmak.

### 14-2 - Veri migration'ları canlı uygulama kodunu import ediyor (tekrarlanabilir değil)
- Önem: medium - Güven: high
- Dosyalar: farm/migrations/0007_equipment_types.py:3,15, farm/migrations/0019_water_points.py:27, farm/water/points.py:18-30, farm/equipment_types.py:217
- Açıklama: farm 0007 `farm.equipment_types.sync` içinde GÜNCEL `TYPES` kataloğunu yazar; katalog sonradan değişince taze kurulumda 0007 bugünün kataloğunu yazar (docstring de "sonradan değişiklik aynı sync'i çağıran yeni migration ile gelir" diyor), tarih içindeki şema ile uyumsuz alan eklenirse eski migration kırılır. farm 0019 `farm.water.points.template_for`'u import eder; bu modül canlı `farm.models.water_point` ve `Tank.Kind` import eder, bu modüller yeniden adlandırılırsa/taşınırsa tüm migration yükleyicisi (import anında) kırılır. Ayrıca `sync` her çalışmada `is_active=True` zorlar ve yönetici düzenlemelerini `update_or_create` ile ezer.
- Kanıt: 0007:3 `from farm.equipment_types import sync`; 0019:27 `from farm.water.points import template_for`; points.py:36 docstring "migration farm/0019 reads it ... so keep its shape" (kırılganlık bilinen ama kodla korunmuyor).
- Öneri: Migration içinde veriyi dondurulmuş sabit olarak kopyalamak; en azından import edilen modüllerin kararlı API'sini test ile sabitlemek.

### 14-3 - Migration'lar farm.models.feeding_protocol ve hr.models.scheduling gibi canlı model modüllerini import ediyor
- Önem: low - Güven: high
- Dosyalar: experiments/migrations/0001_initial.py:9,362, farm/migrations/0015_feeding_protocols.py:8, hr/migrations/0003_scheduling.py:5
- Açıklama: experiments 0001 `farm.models.feeding_protocol.DateRange` kullanıyor; bu isim orada yalnızca `from core.ranges import DateRange` yeniden-export'u (feeding_protocol.py:29). farm 0015 ise doğrudan `core.ranges.DateRange` kullanıyor. Aynı fonksiyonun iki farklı yoldan referansı; yeniden-export kaldırılırsa experiments 0001 import hatası verir. hr 0003 `hr.models.scheduling` import eder (bases/validators için).
- Kanıt: feeding_protocol.py:29; experiments 0001:362 `farm.models.feeding_protocol.DateRange(...)`; farm 0015:133 `core.ranges.DateRange`.
- Öneri: experiments 0001 deconstruct yolunu `core.ranges.DateRange`'e çevirmek (ifade ayni).

### 14-4 - Geri alma sessizce no-op: veri dönüşümü kayıpsız geri dönmüyor
- Önem: low - Güven: high
- Dosyalar: farm/migrations/0023_reports_fields.py:45,91, farm/migrations/0004_production_departments.py:43, hr/migrations/0003_scheduling.py:120, monitoring/migrations/0002_card_templates.py:243
- Açıklama: farm 0023 `organisation_numbers` serbest metni dokuz haneye çevirip anlamsız olanı `notes`'a taşıyor; reverse noop (kolon adı geri döner, ama değer artık 9 haneli ve notlara eklenen metin kalır, `provenance` kolonu düşer). farm 0004 `administration` -> `other` dönüşümü geri alınmaz (bilgi kaybı: eski değer yok). Bu kayıplar dokümante edilmemiş (0023 docstring'i geri alma davranışını söylemiyor).
- Kanıt: 0023:45 `RunPython(organisation_numbers, noop)`; 0004:43 `RunPython(administration_becomes_other, noop)`.
- Öneri: Geri alma kısıtlarını docstring'e yazmak veya `IrreversibleError` ile açıkça belirtmek.

### 14-5 - 0023: veri RunPython'ı ile şema değişikliği aynı transaction'da, SET CONSTRAINTS ALL IMMEDIATE yok
- Önem: low - Güven: low
- Dosyalar: farm/migrations/0023_reports_fields.py:34-45,90-95
- Açıklama: 0019/0021/0022 migration'ları veri güncellemesinden sonra "tablo bekleyen FK tetikleyici olaylarıyla değiştirilemez" hatasına karşı `SET CONSTRAINTS ALL IMMEDIATE` çalıştırıyor. 0023 `Site.save()` ve `Batch.update()` sonrası aynı tablolara (`sites` RenameField/AlterField/AddConstraint, `batches` AddConstraint) DDL yapıyor ama bu önlemi uygulamıyor. Yalnızca FK sütunu değişirse sorun olur (burada değişmiyor), bu yüzden muhtemelen çalışır; tutarsız önlem.
- Kanıt: 0023:45 ve 91'de RunPython sonrası 46-/92- satırlarında hemen AlterField/AddConstraint var; 0019:186-197'deki desenle kıyas.
- Öneri: Tutarlılık için aynı `SET CONSTRAINTS ALL IMMEDIATE` çağrısını eklemek veya veri adımlarını ayrı migration'a bölmek. (Doğrulanmadı: gerçek DB'de çalıştırılmadı.)

### 14-6 - audit_log üzerinde tam-tablo taramalı DDL ve append-only trigger kilitleme/engel riski
- Önem: medium - Güven: medium
- Dosyalar: core/migrations/0007_audit_severity.py:18-27, core/migrations/0003_audit_log_append_only.py:4-24
- Açıklama: `audit_log` en hızlı büyüyen, silinemez tablodur. 0007 `AddIndex` (CONCURRENTLY değil: yazmaları bloklar) ve `AddConstraint(CheckConstraint)` (tüm tabloyu tarayıp ACCESS EXCLUSIVE tutar) çalıştırıyor. Ayrıca 0003 tetikleyicisi her UPDATE/DELETE'i reddettiği için audit_log üzerinde herhangi bir gelecek veri migration'ı (backfill, `severity` düzeltme) trigger'ı geçici devre dışı bırakmadan başarısız olur; bunun için standart bir yardımcı/yönerge yok (yalnızca monitoring 0002 ve reports 0005 elle çözüyor).
- Kanıt: 0007:20-27 AddIndex+AddConstraint; 0003:10-12 `BEFORE UPDATE OR DELETE ... RAISE EXCEPTION`.
- Öneri: Büyük tabloda `NOT VALID` + ayrı `VALIDATE CONSTRAINT`, `AddIndexConcurrently` (atomic=False) kullanmak; trigger'lı tablolar için veri migration kılavuzu yazmak.

### 14-7 - Hypertable dönüşümü (farm 0014) geri alınamaz birincil anahtar değişikliği içeriyor; model durumu veritabanından ayrışıyor
- Önem: medium - Güven: high
- Dosyalar: farm/migrations/0014_water.py:91-103, farm/migrations/0019_water_points.py:186-205
- Açıklama: PK elle `(id, measured_at)` yapılıyor, Django durumu `id` PK diyor (state_operations yok). Bu bilinçli ve yorumlu, ancak (a) migration sonrası `water_measurements` üzerinde sonraki şema değişiklikleri (0019: AlterField NOT NULL, RemoveField, FK) hypertable'ın chunk'larında kilit ve tam tarama gerektirir; (b) `reverse_sql=noop` yalnızca CreateModel'in tabloyu düşürmesine güvenir: 0014 geri alınmadan, tablo veri taşırken tek başına RunSQL geri alınırsa PK/hypertable durumu kalır; (c) `FK` → `water_measurements.point` hypertable üzerinde `DO_NOTHING` ve `db_index=False`. 0019 sonrası tablo büyük hacimliyse tek transaction'da 3 ALTER + UPDATE içerir.
- Kanıt: 0014:96-103 RunSQL listesi; README.md:1065 aynı ayrışmayı not ediyor.
- Öneri: Hypertable adımının ve sonraki ALTER'ların prod'da boş/küçük tabloya yapıldığını belgelemek; docs'a TimescaleDB sürüm/yedek gereksinimini (12-backup-restore bulgusuna bağlı) eklemek.

### 14-8 - farm 0019 tek transaction'da bütün sample'ları güncelliyor; büyük hacimde uzun kilit
- Önem: low - Güven: medium
- Dosyalar: farm/migrations/0019_water_points.py:36-52,186-205
- Açıklama: İleri yön, tüm birim/sistemler için nokta oluşturup (bulk_create) `water_measurements` hypertable'ında tüm satırları tek `UPDATE ... Subquery` ile güncelliyor, ardından NOT NULL AlterField, kolon/index düşürme; hepsi bir transaction ve tablo üzerinde ACCESS EXCLUSIVE. Docstring "tek transaction, hata veritabanını olduğu gibi bırakır" diyor (olumlu), ancak kilit süresi/dağıtım penceresi hakkında yönerge yok. Ayrıca `template_for(owner_type, owner.kind)` bilinmeyen birim türünde `KeyError` verir (DEFAULTS yalnızca tank/pond/cage); şu an `Tank.kind` seçenekleri bunlarla sınırlı olduğundan düşük.
- Kanıt: 0019:36-52 (create_points_and_move_samples), points.py:21-27 DEFAULTS.
- Öneri: Prod'da bakım penceresi notu; büyük hacim için parçalı UPDATE.

### 14-9 - reports 0005: kullanıcısı bilinmeyen olaylar migration'ı durduruyor (veri bağımlı başarısızlık) ve geri alma audit kayıtlarını bırakıyor
- Önem: medium - Güven: high
- Dosyalar: reports/migrations/0005_notified_moved_into_notices.py:52-70,97-118,119-122
- Açıklama: Kullanıcısı (AuditLog, updated_by, created_by) çıkarılamayan her `authority_notified_at` olayı `RuntimeError` ile tüm migration'ı durduruyor; prod'da bu veri bir dağıtımı bloklar (kullanıcı silinmişse tüm üç alan NULL olabilir: FK SET NULL). Hata mesajı yönlendirici ama çözüm elle SQL gerektirir (alan düşürülmeden önce). Geri alma `format_version=0` ile ayırt edilen raporları ve snapshot'ları siliyor (trigger'ları geçici devre dışı bırakarak) ama yazılan `AuditLog` kayıtları kalıyor (docstring'te belirtilmiş) — geri-ileri döngüde audit'te çift kayıt oluşur. Ayrıca `run_before` ile farm 0024 sıralanıyor: farm 0024 artık dolaylı olarak reports 0004/0005'e bağımlı, farm'ın reports'a ters bağımlılığı mimari olarak sıkı.
- Kanıt: 0005:52-70 (`unknown` -> `RuntimeError`), 112 `ALTER TABLE ... DISABLE TRIGGER`, 119-122 `run_before`.
- Öneri: Bilinmeyen kullanıcı için sistem kullanıcısı/atlama seçeneği; `DISABLE TRIGGER`'ın try/finally ile sarılması (başarısızlıkta transaction zaten geri alır, yine de açık olsun).

### 14-10 - Frozen/append-only trigger'ları için veri migration'ı kılavuzu yok; trigger'ı devre dışı bırakma deseni kopyalanmış
- Önem: low - Güven: high
- Dosyalar: reports/migrations/0002_filed_reports_frozen.py, experiments/migrations/0002_design_frozen.py, monitoring/migrations/0002_card_templates.py:3-8,82-85, reports/migrations/0005_notified_moved_into_notices.py:97-118
- Açıklama: Beş farklı veritabanı katmanı koruması var (audit_log, filed reports/snapshots/cevaplar, experiments, built-in card templates). Gelecekte bu tablolarda veri düzeltmesi gerektiğinde her migration `ALTER TABLE ... DISABLE TRIGGER` adımını yeniden yazmak zorunda; yalnızca monitoring docstring'i bunu ("A later change to a built-in is a migration that disables the trigger around its own update") söylüyor, ortak bir yardımcı yok. Reports 0005 yetkisiz devre dışı bırakma deseninin tek örneği.
- Kanıt: monitoring 0002:7-8; reports 0005:114-118.
- Öneri: `core` içinde `without_trigger(schema_editor, table, trigger)` yardımcı bağlam yöneticisi ve docs/ altında kılavuz.

### 14-11 - Test kapsamı: bazı elle yazılmış migration'ların hiç testi yok
- Önem: low - Güven: medium
- Dosyalar: farm/migrations/0004_production_departments.py, farm/migrations/0007_equipment_types.py, farm/migrations/0017_handling_rules.py, farm/migrations/0023_reports_fields.py, reports/migrations/0009_open_questions_listed.py, hr/migrations/0003_scheduling.py
- Açıklama: `MigrationExecutor` kullanan testler yalnızca monitoring (2), hr/test_hardening, experiments, reports/test_notices (0005), farm 0019/0021/0022 için var. 0023 (`organisation_numbers` regex dönüşümü, geri dönüşsüz), 0004 (RenameModel + RunPython), 0017 (`write`/`remove`), reports 0009 için migration seviyesinde test bulunamadı. `makemigrations --check` yalnızca core/tests.py:108 ve monitoring/tests/test_boards.py:264'te (monitoring'e özel).
- Kanıt: `grep -l MigrationExecutor` çıktısı 8 dosya; 0023 için `organisation_numbers` referansı testlerde yok.
- Öneri: 0023 için veri dönüşüm testi (rakamlı/NO...MVA/anlamsız giriş), 0017 reverse testi.

### 14-12 - CI / dağıtım yönergesi yok: migrate tek satır, yedek/kilit/geri alma planı belirtilmemiş
- Önem: medium - Güven: medium
- Dosyalar: README.md:2984, docker-compose.yml, (yok) .github/workflows
- Açıklama: Depoda CI iş akışı dizini (.github/workflows) yok; README yalnızca `manage.py migrate` ve "timescaledb extension'ı etkinleştirir" diyor. `CREATE EXTENSION timescaledb`/`btree_gist` süper kullanıcı veya trusted yetkisi gerektirir (core 0001:9, hr 0002:21, farm 0015:25); uygulama kullanıcısı kısıtlıysa migrate yarım kalır. Prod için migrate öncesi yedek, `sqlmigrate` incelemesi, `lock_timeout`, `makemigrations --check` ve `migrate --check` adımları dokümante edilmemiş. 12-backup-restore bulgularıyla ilişkili.
- Kanıt: README.md:2984 `manage.py migrate   # also enables the timescaledb extension`; `ls .github/workflows` yok.
- Öneri: Dağıtım kılavuzu + CI'da (taze DB'ye migrate, geri alma döngüsü, `makemigrations --check`).

### 14-13 - core 0001 timescaledb: uzantı geri alma noop, kullanıcı yetkisi varsayımı
- Önem: info - Güven: high
- Dosyalar: core/migrations/0001_timescaledb.py:9-12
- Açıklama: `CREATE EXTENSION IF NOT EXISTS timescaledb` ve `reverse_sql=noop`. Uzantı sürümü migration'da sabitlenmemiş (README/compose'taki imaj sürümüne bağlı); uzantı yükseltmesi migration dışında. Bilgi amaçlı.
- Kanıt: 0001_timescaledb.py:9-12.
- Öneri: Beklenen minimum TimescaleDB sürümünü (by_range API: >=2.13) migration'da veya system check'te doğrulamak. (farm 0014'te `by_range` kullanılıyor.)

### 14-14 - reports 0009 / farm 0017 / farm 0007 seed geri alma verilerini kullanıcı düzenlemeleri nedeniyle eksik siliyor veya fazla siliyor
- Önem: low - Güven: medium
- Dosyalar: reports/migrations/0009_open_questions_listed.py:49-52, farm/migrations/0017_handling_rules.py:49-52, farm/migrations/0007_equipment_types.py:15
- Açıklama: reports 0009 `remove` kodu `Q1..Q12`'ye sahip her satırı siliyor; kullanıcı bu sorulara cevap girdiyse (status/answer) cevap kaybolur. farm 0017 `remove` yalnızca not metni değişmemiş satırları siliyor (kullanıcı düzenlediyse kalır, tutarlı). farm 0007 reverse noop: tipler kalır. Üç seed için üç farklı geri alma stratejisi.
- Kanıt: 0009:50-52 `filter(code__in=...).delete()`; 0017:49-52 `note__in=...`, `created_by__isnull=True`.
- Öneri: Seed geri almasını tek ilkeye bağlamak (yalnızca dokunulmamış satırı sil).

### 14-15 - monitoring: eski `mode` kolonları "bir sürüm" kalacak denmiş ama kaldırma migration'ı yok
- Önem: info - Güven: medium
- Dosyalar: monitoring/migrations/0003_template_pointers.py:1-3, monitoring/migrations/0004_backfill_modes.py:1-3, monitoring/models.py:39
- Açıklama: 0003/0004 docstring'leri eski `default_mode`/`mode` kolonlarının "bir sürüm" kalacağını söylüyor; bunları düşüren migration yok (modelde `CardMode` hâlâ var). İki kaynak (mode ve template) birlikte yaşıyor; 0004 geri yönü mod sütununa yalnızca built-in şablonlar için yazıyor, kullanıcı şablonuna geçmiş satırlarda `mode` eskir. Sürüm çevrimi planı açık değil.
- Kanıt: 0003:1-3 "The old modes stay for one release"; 0004:19-21 backward yalnızca MODE_OF.
- Öneri: Kaldırma migration'ı için tarih/sürüm sınırını belgelemek veya TODO bırakmak.

### 14-16 - Migration yaşam döngüsü: birleştirilmemiş squash yok, 26 farm migration'ı ve elle düzenlenmiş "Generated" migration'lar
- Önem: info - Güven: high
- Dosyalar: farm/migrations/0001..0026, experiments/migrations/0001_initial.py:1, farm/migrations/0014_water.py:1, farm/migrations/0015_feeding_protocols.py:1
- Açıklama: Merge migration ihtiyacı yok (tek yaprak/uygulama; `replaces` yok). Birçok migration "Generated by Django ... elle düzenlendi" notu taşıyor; elle düzenlenen kısımlar (hypertable, composite FK, trigger) `makemigrations`'ın bunları fark etmeyeceği nesneler: composite FK'ler (experiments 0001:364, messaging 0001:170) Django durumunda yok, şema/DB sapması yalnızca testle yakalanır (experiments/tests/test_migrations.py).
- Kanıt: experiments 0001:364 `RunSQL(COMPOSITE_KEYS, DROP_COMPOSITE_KEYS)`; messaging 0001:170.
- Öneri: Bu "Django dışı" nesneler için tek bir şema-katalog testi (pg_constraint/pg_trigger) ve docs listesi.
