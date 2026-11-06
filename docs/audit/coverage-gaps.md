# Kapsam boşlukları ve denetimin sınırları

Bu belge (1) uzmanların kendi raporlarında "incelenmeyen alanlar" olarak bildirdiği kısımları aynen derler ve (2) denetim sürecinin ortak sınırlarını listeler. Uzmanların metni kısaltılmadan, yalnızca madde işaretleri düzleştirilerek aktarılmıştır.

## Denetimin ortak sınırları

- **Doğrulama kapsamı dar**: 957 ham kaydın yalnızca 24'ü (yaklaşık %2,5) iki bağımsız doğrulayıcıdan geçti. Kalan kayıtlar tek uzmanın okumasına ve (çapraz görüş aşamasında) komşu uzmanın incelemesine dayanır. Doğrulanan 24 kaydın 22'sinde önem aşağı çekildi (21'i Yüksek idi, 1'i Orta), yukarı çekilen olmadı; bu, doğrulanmamış kayıtlardaki Orta/Düşük etiketlerinin de abartılı olabileceğine işaret eder.
- **Canlı çalıştırma yok**: uygulama çalıştırılmadı; PostgreSQL/TimescaleDB gerektiren davranışlar (EXPLAIN planları, kısıt davranışı, hypertable/chunk, kilit ve yarış) birçok uzmanın bildirdiği gibi gerçek veritabanında sınanmadı. Performans bulguları ölçülmemiş kod okumasıdır.
- **Testler çoğunlukla çalıştırılmadı**: bazı uzmanlar (ör. 22, 29, 36, 50) testleri çalıştırmadığını açıkça belirtti; Django kurulu olmadan yapılan değerlendirmeler de var (çapraz kayıt 05-X4: `check --deploy` hiç koşulmadı). Testlerin yeşil olduğu iddiası bu denetimden çıkarılamaz.
- **Tarayıcıda çalıştırma yok**: erişilebilirlik, responsive görünüm ve TypeScript davranışları kod okumasıyla değerlendirildi (43 numaralı uzman bunu açıkça belirtti); gerçek ekran okuyucu/klavye testi yapılmadı.
- **Dağıtım ortamı repoda yok**: proxy, TLS, ortam değişkenleri, yönetilen PostgreSQL, zamanlayıcı ve yedekleme altyapısı depoda tanımlı değil; bu nedenle üretimde nasıl çalıştırıldığı değerlendirilemedi. "Eksik" denilen bazı şeyler depo dışında bulunuyor olabilir.
- **Önem tutarlılığı**: 50 uzman bağımsız ölçek kullandı; aynı kök neden Yüksek/Orta/Düşük olarak farklı kaydedildi. Konsolidasyonda yalnızca doğrulanmış kayıtların önemi hakem kararıyla düzeltildi; doğrulanmamış kayıtlarda kümedeki en yüksek önem alındı.
- **Birleştirme kısmen elle**: 62 küme elle seçilen kimlik listeleriyle birleştirildi; kaçırılmış mükerrerler olabilir ve benzer ama ayrı sonuçlar doğuran kayıtlar bilinçli olarak ayrı bırakıldı. Tekil sayı (838) bu nedenle üst sınıra yakın bir tahmindir.
- **Çapraz görüş kayıtları**: 126 yeni kayıt güven düzeyi ve ayrıntılı kanıt olmadan, başlık/önem/dosya düzeyinde konsolide edildi; ayrıntıları `crosstalk/NN-*.md` dosyalarındadır ve bu etiketler (NN-Xn) dosyalardaki yerel numaralarla örtüşmeyebilir.
- **Ayrıştırma notu**: 831 uzman kaydı markdown dosyalarından programla ayrıştırıldı; başlıkları olmayan 32 kaydın başlığı açıklamanın ilk cümlesinden türetildi (master dosyada "başlık türetilmiştir" notuyla işaretli). Kaynak dosyalardaki biçim farkları nedeniyle bazı alanlarda (kanıt, öneri) kısaltma/boş alan olabilir; asıl metin için `findings/NN-*.md` esas alınmalıdır.
- **Zamansal kapsam**: denetim tek bir depo durumu üzerinde yapıldı (docs/audit raporları da takipsiz, bkz. çapraz kayıt 40-X2); sonraki değişikliklerle bulgular bayatlayabilir.
- **Tarihsel veri**: git geçmişinde sır taraması yapılmadı (40-9).

## Uzman bazında incelenmeyen alanlar

### 01-authn

Ortam/proxy/dağıtım yapılandırması (repoda yok), yetkilendirme matrisi (ayrı uzman), Django admin içi, frontend TS.

### 02-authz

Her farm Resource alt sınıfının tek tek `scoped/allowed` override'ı, şablonlardaki `perms` kullanımı ve düğme gizleme, frontend TypeScript, test kapsamı (testler çalıştırılmadı), reports/compute içeriğinin hangi alanlardan veri okuduğunun satır satır doğrulanması, dbgrid SQL güvenliği (başka uzmanın alanı).

### 03-csrf-xss

Çalışma zamanı HTTP başlıkları (uygulama çalıştırılmadı, `check --deploy` koşulamadı), Django admin'in kendi şablonları, derlenmiş static/js çıktısı, reverse proxy/TLS dağıtım yapılandırması (repoda yok), her şablonun satır satır taranması (örnekleme + grep ile yapıldı), THIRD_PARTY.md'deki üçüncü parti JS'in içeriği.

### 04-injection

Şablon motoruna kullanıcı verisiyle `Template(...)`/`from_string` çağrısı bulunmadı (yalnız testlerde). pypdf/bağımlılık sürüm zafiyetleri (requirements) incelenmedi; dinamik test/exploit denenmedi; `farm/` ve `hr/` alt modüllerinin tamamı satır satır okunmadı, grep tabanlı tarama yapıldı.

### 05-secrets-config

Gerçek dağıtım ortamı (nginx/gunicorn, sunucu env'leri), frontend bağımlılıklarının (package-lock) sır/tedarik zinciri incelemesi, entropi tabanlı tam secret-scan aracı çalıştırılmadı.

### 06-file-upload

Gerçek dağıtım (nginx client_max_body_size, gunicorn zaman aşımı, dosya sistemi izinleri), pypdf'in gerçek kötü niyetli PDF'lerle davranışı (fuzz/zip-bomb denemesi yapılmadı), testlerin çalıştırılması (PostgreSQL gerekir), tarayıcı PDF görüntüleyici davranışı, antivirüs altyapısı.

### 07-deps-supply

CVE veritabanı sorgusu (ağ/araç yok, sürümler tek tek doğrulanmadı), geçişli bağımlılıkların gerçek lisans metinleri, imaj içi paket taraması, static/ ve templates/ içindeki gömülü üçüncü taraf varlıklar (yazı tipi, ikon) ayrıntılı lisans incelemesi, gerçek dağıtım ortamı.

### 08-privacy-pii

- Frontend TypeScript (localStorage/tarayıcıda PII), şablonlar (`templates/`) içindeki maskeleme
- `knowledge` PDF yüklemeleri ve `media/` içeriği, `inventory`, `experiments` ekip üyeleri ayrıntısı
- Dağıtım/yedekleme/DB düzeyi şifreleme (repoda yok), reverse proxy erişim logları
- Çerez/oturum/CSRF (başka uzman alanı)
- Hukuki yeterlilik (KVKK/GDPR maddeleri doğrulanmadı; yalnızca kodda var olan/olmayan mekanizmalar)

### 09-data-read

Gerçek veri hacmiyle ölçüm (EXPLAIN, sorgu sayısı) yapılmadı; performans bulguları kod okumasına dayanır. farm/health, farm/harvest, farm/handling, farm/feeding/projection, experiments/services, her Resource'un `search` alanlarındaki indeks kapsamı, şablonlarda tek tek alan sızıntısı, frontend TypeScript, migrations'daki indeksler tek tek incelenmedi. SQL enjeksiyonu/yetki konuları 02/04 numaralı uzmanların alanıdır.

### 10-data-write

- `farm/forms/*` (stok, su, sağlık, hasat, yem protokolü, ekipman) ve `farm/health`, `farm/water/services.py`, `farm/handling`, `farm/harvest` servisleri: yalnızca ortak desen düzeyinde; satır satır okunmadı.
- `experiments/services.py` ve `experiments/forms.py` büyük bölümü; `knowledge` dosya yükleme/çıkarma (dosya yükleme alanı başka uzmanın kapsamı).
- Testler çalıştırılmadı, gerçek veritabanı üzerinde yarış senaryosu denenmedi: yarış bulguları kod okumasına dayanır.
- `reports/exports.py`, `reports/compute/*` (hesaplama okuma yolu), TypeScript ön yüz.

### 11-data-modify

Gerçek eşzamanlılık testi yapılmadı (yarışlar kod okumasına dayanır; PostgreSQL READ COMMITTED varsayıldı). farm/health, farm/handling, farm/water/services (void akışı yalnızca başlık düzeyi), farm/feeding projeksiyonları, reports/compute, monitoring views (kart kopyalama), knowledge/entry iş akışı, TypeScript frontend (sürüm alanını gönderme), migrasyon tetikleyicilerinin SQL gövdeleri tek tek incelenmedi. Yetki konuları 02, SQL enjeksiyonu 04, veri yazma yolları 10 numaralı uzmanların alanıdır.

### 12-backup-restore

- Gerçek üretim dağıtımı (repoda yok; Dockerfile, CI, Kubernetes, systemd yok)
- Testlerin çalıştırılması ve geri yükleme provası (yıkıcı işlem yasaktı)
- Frontend tarafındaki geri alma (frontend/grid/history.ts) yalnızca istemci içi undo, yedekle ilgisi yok; ayrıntılı incelenmedi
- Uygulamayla ilgisiz altyapı (TLS, ağ)

### 13-audit-log

Testler ve uygulama çalıştırılmadı (Django ortamda kurulu değil); gerçek PostgreSQL rol yetkileri ve üretim dağıtımındaki DB kullanıcısı bilinmiyor (yalnızca geliştirme docker-compose ve settings varsayılanları okundu). Tüm 96 `audit.*` çağrı noktası tek tek izlenmedi; farm/water/points, farm/health/withdrawal, reports/compute, frontend TypeScript, config/database.py ve core/dbview.py tabloları satır düzeyinde incelenmedi. Veritabanı yedek/geri yükleme (12 numaralı alan) ve yetki matrisi (02) başka uzmanların alanıdır.

### 14-migrations

- `makemigrations --check` ve testler çalıştırılmadı (ortamda Django/PostgreSQL yok); model-migration durum uyuşmazlığı doğrulanmadı.
- farm 0005/0016/0018 gibi salt şema (CreateModel) migration'larının her alanı satır satır doğrulanmadı.
- Gerçek prod veri hacmi bilinmediği için kilit süreleri tahmin edilmedi, yalnızca yapısal risk kaydedildi.

### 15-db-schema

Canlı veritabanı (EXPLAIN, gerçek indeks kullanımı, pg_stat) incelenmedi; `makemigrations --check` ile model/migrasyon sapması doğrulanmadı (ortamda Django yok); experiments/models.py, hr/models'in kalanı, knowledge/models/entry.py, farm/models'in health/harvest/handling/feeding dosyaları ve çoğu migrasyonun içeriği yalnızca yüzeysel/gözle taranmadı.

### 16-transactions

- Testler çalıştırılmadı; yarış durumları kod okuyarak çıkarıldı (gerçek eşzamanlılık denenmedi).
- `farm/handling`, `farm/stock/read.py`, `reports/compute` içindeki okuma yolları ve trigger SQL gövdeleri satır satır incelenmedi.
- TimescaleDB hypertable özel davranışları (sıkıştırma, chunk kilitleri) incelenmedi.

### 17-timeseries

- Canlı veritabanı üzerinde chunk/indeks planları (EXPLAIN), testlerin çalıştırılması, üretim dağıtım yapılandırması (repoda yok), farm/health/withdrawal.py ve handling/fasting.py iç ayrıntıları.

### 18-data-integrity

Canlı DB, TimescaleDB hypertable davranışı, testlerin çalıştırılması, farm/health ve farm/handling hesapları (withdrawal, fasting), farm/feeding/fold.py ayrıntıları, knowledge/ ve hr/scheduling/attendance, monitoring kart JSON şeması, çoğu migrasyonun gövdesi, locale/ frontend (TypeScript) tarafı. Diğer denetçilerle örtüşen konular (izin kotası kilidi, silme planı yarışı) burada yalnızca çapraz referansla anıldı (10-3, 10-6).

### 19-biz-feeding

- Testler çalıştırılmadı (PostgreSQL/TimescaleDB bağlantısı yok); eşzamanlılık ve exclusion kısıtı davranışları gerçek DB ile denenmedi.
- `farm/stock/fold.py` ve `farm/stock/read.py` (defter katlama) yalnızca `feeding/fold.py` kancaları üzerinden okundu.
- `experiments/` ve `monitoring/` içindeki yemleme tüketicileri yüzeysel tarandı (`experiments/design.py`, `read.py`); ayrıntılı denetim ilgili uzman alanlarına bırakıldı.
- Şablonlar (`templates/farm/feeding_*.html`, `meal_board.html`) ve TypeScript frontend incelenmedi.
- `farm/water/read.py` (`water_sources`, `Series`) sıcaklık kaynağı sıralaması varsayıldı, okunmadı.

### 20-biz-health

- Testlerin çalıştırılması (veritabanı yok).
- `farm/harvest/` plan sayfaları, `monitoring/` kartları ve `tasks/`, `messaging/` içindeki sağlık göstergeleri yalnızca
  grep düzeyinde tarandı.
- Şablonlar (`templates/farm/*.html`) yalnızca `lice_list.html` ilgili satırlar kadar.
- Yetkilendirme ayrıntıları ve denetim günlüğü (RowList üzerinden MedicineWithdrawal değişikliklerinin günlüğe nasıl
  yazıldığı) derinlemesine doğrulanmadı.
- Yönetmelik metinlerinin (lakselusforskriften, dyrehelseforskriften) Lovdata ile yeniden doğrulanması yapılmadı; kod
  içindeki yorumlara güvenildi.

### 21-biz-stock-prod

- Testlerin çalıştırılması (PostgreSQL yanıt vermiyordu); eşzamanlılık davranışı yalnızca kod okumayla değerlendirildi.
- farm/feeding (biz-feeding alanı), farm/health, farm/water iç mantığı; yalnızca stok ile arayüzleri okundu.
- Frontend TypeScript, şablonlar (templates/farm/*), çeviri katalogları.
- Migration dosyaları ve DB'deki gerçek kısıtlar (modeldeki Meta.constraints esas alındı).
- reports/compute/{smolt,cleaner,lice}.py ve rapor gönderim akışı.

### 22-biz-water

- Testler çalıştırılmadı (PostgreSQL/TimescaleDB yok); DB check kısıtlarının (Round, num_nonnulls) gerçek davranışı denenmedi.
- `farm/water/charts.py`, `deffeyes.py` çizim/geometri kısmı (clip, layers), `dosing.py` recipes/simulate gövdesi ve `farm/water/points.py` ayrıntılı okunmadı; yalnızca sabitleri ve sınıfları kontrol edildi.
- Kimya sabitlerinin (Millero, Dickson katsayıları) literatürle satır satır karşılaştırması yapılmadı; yalnızca O₂ çözünürlüğü ve NH₃ payı sayısal olarak kontrol edildi.
- TypeScript frontend (`frontend/designer.ts`, `poll.ts`) ve çeviri katalogları incelenmedi.
- `docs/aquaculture-platform-bugs.md` içeriğinin tamamı (WQ-xx satırları) kodla tek tek eşlenmedi.
- Rol/yetki (water görme izni) ve veri okuma/yazma güvenliği ilgili başka uzman alanlarına bırakıldı.

### 23-biz-inventory

Testlerin fiilen çalıştırılması (DB yok), migration SQL'inin satır satır doğrulanması, şablonlar (templates/inventory), frontend TS, `farm` FeedingRecord yazma yolu (feeding uzmanının alanı), yetki matrisinin (config/access.py) derin analizi, i18n çevirileri.

### 24-biz-tasks

- Şablonlar (`templates/tasks/*`), `tasks/templatetags`, migration SQL ayrıntıları (yalnızca kısıt sayısı karşılaştırıldı)
- Testlerin çalıştırılması (Django ortamda yok), canlı DB davranışı
- Yetki matrisinin (`config/access.py`) ayrıntıları, bildirim/AI/otomatik kural entegrasyonları (MVP dışı)

### 25-biz-hr

Testler çalıştırılmadı (DB gerekir), bulgular kod okumasına dayanır. core.crud/Resource iç işleyişi, farm tarafı (zone_of, site_today), şablonlar (templates/hr), frontend TS, hr/management/commands/seed_hr_demo.py, resources/department.py ve scheduling.py ayrıntıları, i18n.

### 26-biz-reports

Testler (reports/tests/*) çalıştırılmadı (Django kurulu değil: `ImportError`). farm/health/read.py (lice_weeks), farm/feeding/read.py (project/fed), farm/water/read.py ve farm/stock/read.py `Presence` içi doğrulanmadı; şablonların tamamı, frontend TypeScript, docs/regulatory-reports.md'nin resmî alan eşleştirmeleri (Mattilsynet/Fiskeridirektoratet şeması) dış kaynakla karşılaştırılmadı. Yetki/kapsam konusu 02-authz uzmanına bırakıldı (26-18'de yalnızca çapraz referans).

### 27-biz-experiments

- Testlerin fiilen çalıştırılması (Docker/PostgreSQL yok), şablon (templates/experiments/*) HTML içerikleri, frontend TypeScript, çeviri dosyaları (locale)
- farm.feeding.read / farm.stock.read içi hesaplar (yalnızca çağrı sözleşmeleri okundu)
- Kullanıcı rolleri matrisi (Roles verisi) ve gerçek yetki dağılımı

### 28-biz-knowledge

Calisan DB uzerinde sorgu planlari/gercek arama davranisi, testlerin kosulmasi, frontend TS, core.crud ic
ayrintilari (transaction sarmali), nginx/medya depolama dagitimi, migration SQL'in model ile birebir karsilastirmasi.

### 29-biz-messaging

Gerçek PostgreSQL çalışma planları (EXPLAIN), testlerin çalıştırılması, poll.ts'nin tamamı/CSS, mobil API (yok), çeviri katalogları, yük testi.

### 30-biz-core-facility

Testler çalıştırılmadı; migrations içeriği, frontend TypeScript, water_point.py, feeding/health modelleri, ekipman tipi kataloğunun tamamı, izin/erişim (core/access.py) derinlemesine incelenmedi.

### 31-architecture

Frontend (TS) mimarisi derinlemesine, şablon (templates) bağımlılıkları, migration bağımlılık grafiği, runtime import-cycle testi (çalıştırılmadı).

### 32-code-quality

Frontend TypeScript kalitesi (yüzeysel), şablonlar (templates), migration'lar, test kodunun kalitesi (yalnız sayısal ruff çıktısı), tüm 74 PLR2004 magic-value uyarısının tek tek incelenmesi, ölü fonksiyon taraması (vulture yok; kapsamlı yapılmadı).

### 33-error-handling

- Testlerin hata yolu kapsamı ayrıntılı incelenmedi
- Çalışma zamanında gerçek 500/404 cevapları denenmedi (salt-okunur kural)
- tasks, inventory, experiments view'ları tek tek taranmadı
- Şablonlarda form hata gösterimi ve erişilebilirlik ayrıntısı

### 34-concurrency

Testler çalıştırılmadı; gerçek çoklu-bağlantı yarış testi yapılmadı (yalnızca statik okuma). reports/, knowledge/, farm/health ve farm/handling içi ayrıntılı kilit akışları, frontend TypeScript, migration'lar, Timescale hypertable'a özgü kilit davranışları derin incelenmedi. `tasks.places`/`clocks()` tanımı doğrulanmadı.

### 35-performance

- Gercek veri hacmi ve EXPLAIN ANALYZE planlari: veritabani calistirilmadi; tum olceklenme degerlendirmeleri kod okumasina dayanir.
- TimescaleDB ayarlari (compression, retention, continuous aggregate): migrations/0014_water.py yalnizca hypertable olusturuyor; baska politika bulunmadi.
- hr/scope.py, hr/services.py, experiments/design.py/services.py, tasks/services.py, farm/stock/integrity.py, reports/compute/* icindeki hesaplarin ayrintili sorgu sayimi.
- Sablon (template) render maliyetleri ve frontend paket boyutu (TypeScript derlenmis cikti repoda yok).
- Uretim dagitimi (gunicorn/ters vekil/CDN): repoda Dockerfile ya da sunucu yapilandirmasi yok.

### 36-testing

Testlerin gercek calistirilmasi (Django/DB yok), her test dosyasinin satir satir kalitesi, kapsam (coverage) olcumu, locale/template testleri derinligi.

### 37-ci-devops

- Çalışan uygulama/Docker üzerinde canlı test (yıkıcı çalıştırma yasak, docker yok)
- Testlerin tam çalıştırılması ve süresi; frontend testleri (node_modules kurulu değil)
- Tüm templates/ ve frontend/ içeriği; yalnızca build/asset yolu bakıldı
- Yedekleme/geri yükleme ayrıntısı: 12-backup-restore.md; sır/ayar: 05-secrets-config.md

### 38-api-contracts

experiments view'larının (start/copy/release/replace) tek tek metod davranışı; hr/resources ve farm/resources içindeki özel create_view'lar; şablonların tamamı; testlerin çalıştırılması; çalışan uygulamaya karşı canlı HTTP denemesi (Django ortamda kurulu değil).

### 39-docs-consistency

Her tab bolumunun (1000+ satir) madde madde davranis dogrulamasi; data-map.md/json'in guncelligi (komut calistirilamadi); i18n.md ayrintilari; aquaculture-platform-bugs.md'nin dis kaynak (aquaculture_platform) atiflari.

### 40-git-hygiene

Uzak (GitHub) tarafındaki branch protection / PR geçmişi, tarihsel dosya içeriklerinde sır taraması (yalnızca dosya adı ve silinen dosya listesi bakıldı), uygulama kodu.

### 41-frontend-ts

- Testlerin gerçek çalıştırılması ve `tsc` çıktısı (bağımlılık kurulu değil)
- Sunucu tarafı HTML'in kaçışlanması (XSS; başka uzmanın alanı), `monitoring/cards/validate.py` ile tam eşdeğerlik
- Tarayıcı içi davranış (gerçek ekran okuyucu, dokunmatik), CSS'in tamamı
- `static/js` derleme çıktısı, `{% asset %}` / import map mekanizması

### 42-templates

Şablon etiketleri/filtrelerinin (templatetags) iç mantığı, CSS/TS tarafı, çeviri (.po) tamlığı, tarayıcıda render, erişilebilirlik testi, her şablonun satır satır tam okunması (örneklem + grep).

### 43-ux-flows

Tarayıcıda gerçek çalıştırma/erişilebilirlik testi, CSS/responsive görünüm, .po çevirileri, deneyler (experiments) ve rapor (reports) akışlarının tamamı, roster/monitoring/pencere TS kodu, her liste şablonunun tek tek boş durumu.

### 44-accessibility

- Gerçek tarayıcı / NVDA / VoiceOver / TalkBack testi, axe/Lighthouse taraması yapılmadı
- 149 şablonun tamamı satır satır okunmadı; `farm`, `inventory`, `knowledge`, `reports`, `experiments` şablonları yalnızca desen taraması (grep) ile incelendi
- `components.css`'in tamamı ve `messages.css`, `tasks.css`, `auth.css` ayrıntılı incelenmedi
- PDF çıktıları, e-posta şablonu, `water_calculator_report.html` erişilebilirliği
- Çeviri (`locale/`) kalitesi

### 45-i18n

- Testler/derleme çalıştırılmadı (Django ve bağımlılıklar ortamda yok), `.mo` derleme çıktısı doğrulanmadı.
- 4241 çevirinin dil kalitesi (anlam doğruluğu) satır satır değerlendirilmedi; yalnızca sözlük/tutarlılık örnekleme.
- Tarayıcıda gerçek render, yazdırma CSS'i, `docs/data-map.*` ve diğer denetim dosyaları.

### 46-css-static

- Tarayicida gorsel/render dogrulamasi (ekran goruntusu, gercek cihaz) yapilmadi; responsive ve kontrast bulgulari kod ve hesaba dayanir.
- TypeScript davranisi (`frontend/`) yalnizca CSS ile ilgili kisimlariyla okundu; JS mantik denetimi baska uzmanin alani.
- Sunucu tarafi SVG uretimi (`farm/water/charts.py`) yalnizca boyut sabitleri icin okundu.
- `static/js/` repoda yok (derlenmedi); derlenmis cikti denetlenemedi.
- Uretim web sunucusu/CDN yapilandirmasi repoda bulunmadigindan Cache-Control basliklari denetlenemedi.

### 47-workflows-e2e

- Gerçek veritabanı üzerinde çalıştırma, test paketi çalıştırması, eşzamanlı yarış testleri
- Frontend (TypeScript) ve şablonların uçtan uca davranışı; yetki matrisi (`config/access.py`) ayrıntıları
- `reports/compute/*` hesaplarının doğruluğu, `monitoring` kart içerikleri, `knowledge` modülünün iç akışı
- Zaman serisi (TimescaleDB) tarafı ve su kalitesi -> arınma derece-gün hesabının sayısal doğruluğu (yalnız akış okundu)

### 48-state-machines

messaging modeli (durum alanı yok/çalışmadı), monitoring, core, farm Equipment/Supplier/Feed/Medicine/Species/SlaughterFacility status alanları (ayrıntılı geçiş incelenmedi), frontend TS durum gösterimi, testlerin çalıştırılması.

### 49-permissions-matrix

Uygulama çalıştırılmadı (DB gerekli), testler koşulmadı; bulgular statik kod okumasına dayanır. Her farm/ `Resource` alt sınıfının form düzeyindeki alan yetkileri, frontend TypeScript, şablonlardaki her düğme gizleme kararı, dbgrid SQL güvenliği, reports/compute içeriği tek tek incelenmedi.

### 50-failure-modes

hr/leave ve roster servisleri (yüzeysel), experiments servisleri (yalnızca atomic kullanımı sayıldı), farm/water hesaplama modülleri, migration geri alma yolları, testler çalıştırılmadı, gerçek DB kopması canlı denenmedi (salt-okunur analiz), kilit sırası kaynaklı deadlock analizi derinlemesine yapılmadı.

