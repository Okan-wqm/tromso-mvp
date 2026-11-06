# 31 - Mimari denetimi (app sınırları, bağımlılık yönü, katmanlama)

## Özet
Uygulama sınırları genel olarak sağlıklı: bağımlılık yönü tek yönlü (hr/inventory/knowledge/monitoring/reports/tasks/experiments -> farm -> core), farm hiçbir yan uygulamayı import etmiyor, `core` üretim kodunda farm'a bağımlı değil (yalnız testler). Ters yönlü kayıt mekanizmaları (`farm.placements`, `farm.health.notices`, `core.audit.restrict`) bilinçli kullanılmış. Zayıf noktalar: farm içinde paket-düzeyi döngüler, farm'ın fiilen "platform" olması (yardımcılar farm altında), katman atlama (monitoring -> başka app'in views'i, inventory -> farm.templatetags/forms), `core` testlerinin farm'a bağımlılığı ve config'in app'leri adla bilmesi.

## İncelenen
Uygulamalar arası import grafiği (grep ile), farm alt paketleri arası import grafiği, config/settings/access/views, core/access/audit/people, monitoring, placements/notices kayıt desenleri.
## İncelenmeyen
Frontend (TS) mimarisi derinlemesine, şablon (templates) bağımlılıkları, migration bağımlılık grafiği, runtime import-cycle testi (çalıştırılmadı).

## Bulgular

### 31-1 - farm alt paketleri arasında paket-düzeyi döngüsel bağımlılık
Önem: medium | Güven: high
Dosyalar: farm/stock/services.py, farm/stock/integrity.py, farm/feeding/services.py, farm/feeding/read.py, farm/handling/check.py, farm/water/degree_days.py, farm/health
Açıklama: stock -> feeding/handling/health ve feeding/handling/water/health -> stock yönleri birlikte var; katmanlama yok.
Kanıt: farm/stock/services.py:59-62 (`from farm.feeding import read`, `farm.handling import check`, `farm.health import read`); farm/feeding/services.py:18 (`from farm.stock.services import ...`); farm/feeding/read.py:42 (`farm.stock.read`); farm/handling/check.py:39 (`farm.feeding.read`); farm/water/degree_days.py:28 (`farm.stock.read`). Betikle çıkarılan grafik: stock->{feeding,handling,health}, feeding->{handling,stock,water}, handling->{feeding,stock,water}, health->{feeding,handling,stock,water}.
Öneri: stock.read/fold/dates gibi alt katmanı (ledger) ayır; services -> read yönünü tek yönlü tut; import-linter benzeri kontrol ekle.

### 31-2 - Model katmanı üst katmana (read) lazy import ile bağımlı
Önem: low | Güven: high
Dosyalar: farm/models/harvest.py
Açıklama: `clean()` içinde fonksiyon-içi import, model -> stock.read bağımlılığını ve döngüyü gizliyor.
Kanıt: farm/models/harvest.py:339-340 (`from farm.stock.dates import earliest`, `from farm.stock.read import fish_of_batch`).
Öneri: İş kuralını services katmanına taşı ya da saf yardımcıyı models'ın altına çıkar.

### 31-3 - Servis katmanı sunum katmanına (templatetags) bağımlı
Önem: low | Güven: high
Dosyalar: farm/stock/services.py, inventory/services.py, inventory/templatetags/inventory.py
Açıklama: Biçimleme fonksiyonları (`number`, `amount`) templatetags içinde durduğu için servis ve başka app'ler onları import ediyor.
Kanıt: farm/stock/services.py:74 (`from farm.templatetags.stock import number`); inventory/services.py:34, inventory/views.py:34, inventory/forms.py:20 (`farm.templatetags.feeding import amount`).
Öneri: Biçimleme yardımcılarını `core` altında nötr bir modüle taşı.

### 31-4 - farm fiilen "platform" katmanı: genel yardımcılar farm altında
Önem: medium | Güven: high
Dosyalar: farm/stock/dates.py, farm/clocks.py, farm/forms/stock.py, farm/forms/water.py, hr/*.py, tasks/*.py
Açıklama: Saat/gün hesabı gibi alan-bağımsız işler `farm.stock.dates`/`farm.clocks` içinde; HR ve tasks bu yüzden farm'a bağımlı. `farm.stock.dates` stok alt paketinin içinde, ama hr tarafından 11 yerde kullanılıyor. Formlar (VoidForm, DATE, DECIMAL, NOTES, SiteClockField, AcknowledgeInput) da farm.forms içinde ama inventory/experiments/reports kullanıyor.
Kanıt: hr/scope.py:19, hr/checks.py:6, hr/services.py:15, hr/views.py:21, hr/read.py:15-18 (`site_today`, `clocks`); inventory/forms.py:16, inventory/views.py:29, inventory/screens.py:5, reports/forms.py:8, experiments/forms.py:15. Sayım: hr -> farm.stock.dates 11, inventory -> farm.stock.dates 5.
Öneri: Zaman/saat dilimi, ortak form alanlarını `core`'a (veya ayrı `platform`/`common` app'ine) çıkar; farm'ın şişmesini azalt.

### 31-5 - Farm app'i aşırı büyük (şişme)
Önem: medium | Güven: high
Dosyalar: farm/
Açıklama: farm ~37 bin satır py (migrations/testler dahil), diğer app'lerin her biri 1,7-8 bin satır. Üretim kodu ~21,5 bin satır; stock, feeding, water, health, handling, harvest tek app'te. Tek migration grafiği ve tek AppConfig.
Kanıt: `wc -l` çıktısı: farm 37123, hr 8101, reports 7657, experiments 7761, core 7722; farm üretim kodu 21575 satır (farm/stock/services.py 760, farm/water/deffeyes.py 749).
Öneri: Alt alanları (water chemistry/calculator, stock ledger, feeding) ayrı Django app'lerine bölmeyi değerlendir; önce 31-1 döngüleri çözülmeli.

### 31-6 - monitoring başka app'lerin view modüllerini veri kaynağı olarak import ediyor
Önem: medium | Güven: high
Dosyalar: monitoring/read.py, monitoring/views.py, monitoring/cards/render.py
Açıklama: "composition only" olan monitoring, farm ve tasks'ın `views` modüllerine (sunum katmanı) ve templatetag'ine bağlı; read katmanı view katmanına bağlanıyor, bağımlılık yüzeyi geniş.
Kanıt: monitoring/read.py:48-56 (`farm.feeding views`, `farm.harvest views`, `farm.health views`, `farm.stock views`, `farm.water views`, `tasks views`); monitoring/views.py:30 (`farm.stock.views VIEW`); monitoring/cards/render.py:13 (`farm.templatetags.water`). Ayrıca monitoring -> tasks yatay bağımlılığı (tek yatay bağ).
Öneri: Her app'in `views` içindeki ortak sözleşmeyi (VIEW, overview_tiles) ayrı bir `contracts`/`read` yüzeyine çıkar.

### 31-7 - Dashboard (config/views.py) birçok app'in views modülüne doğrudan bağlı
Önem: low | Güven: high
Dosyalar: config/views.py
Açıklama: Genel bakış, farm/reports/tasks'ın view fonksiyonlarını elle import ediyor; yeni app eklemek config'i değiştirmeyi gerektiriyor (kayıt/registry yok).
Kanıt: config/views.py:5-10 (`farm.feeding.views overview_tiles`, `farm.stock.views`, `reports.views overview_upcoming`, `farm.water.views`, `tasks.views overview_tiles`).
Öneri: placements/notices'taki kayıt desenini overview için de kullan.

### 31-8 - Merkezi izin alanları listesi app'leri string adlarla tanıyor (core/config ters bağ)
Önem: low | Güven: medium
Dosyalar: config/access.py, core/access.py
Açıklama: `AREAS` tüm app'lerin modellerini ('farm.Site', 'inventory.StorageLocation', 'monitoring.MonitorBoard' vb.) tek yerde tutuyor; `core.access` `apps.get_model` ile çözüyor. Yeni app/model eklemek merkezi dosyayı düzenlemeyi gerektirir, bozuk bir ad ancak çalışma anında (get_model) patlar.
Kanıt: config/access.py:8-41; core/access.py:36,40.
Öneri: Her app kendi alanını kayıt etsin (apps.ready), ya da en azından bir test tüm AREAS adlarının çözüldüğünü doğrulasın (varlığı doğrulanmadı).

### 31-9 - core testleri farm'a bağımlı (alt katman test olarak üst katmanı biliyor)
Önem: low | Güven: high
Dosyalar: core/tests.py, core/tests_crud_mount.py, core/tests_scope.py, core/tests_workspaces.py, core/test_languages.py, core/test_database.py, core/test_codes.py, core/tests_schema.py
Açıklama: `core` üretim kodunda farm importu yok (iyi), ama testleri farm modellerini ve `farm.tests.helpers`'ı import ediyor; core bağımsız test edilemiyor ve dağılım/ayırma zorlaşıyor. `core` içinde test dosyaları üretim modülleriyle aynı dizinde.
Kanıt: core/tests.py:19-20; core/tests_crud_mount.py:13-16; core/tests_scope.py:11-13; core/test_database.py:14; core/test_languages.py:16-19.
Öneri: Entegrasyon testlerini üst düzey bir `tests/` altına ya da config'e taşı; core için bağımsız fixture modelleri kullan.

### 31-10 - Tutarsız app iç düzeni
Önem: info | Güven: high
Dosyalar: farm/, hr/, experiments/, inventory/, monitoring/, reports/
Açıklama: farm alt paketlere (feeding/stock/water...), hr kısmen (models/, forms/, resources/), experiments/inventory/monitoring tek dosya modüllerle düzenlenmiş; "read/services/views/screens/resources/integrity" adlandırma kalıbı ortak ama paketleme farklı.
Kanıt: `ls` çıktıları: experiments/models.py, inventory/models.py, monitoring/models.py (dosya) vs hr/models/, farm/models/ (paket); experiments/services.py 886 satır.
Öneri: Büyüyen tek dosyalı modülleri (experiments/services.py) bölmek için eşik belirle.

### 31-11 - Ters yönlü kayıt desenleri (olumlu, ama hata yutma riski)
Önem: info | Güven: high
Dosyalar: farm/placements.py, experiments/apps.py, reports/apps.py, core/audit.py
Açıklama: farm, experiments/reports'u import etmeden `placements.register` ve `notices.register` ile genişletiliyor; bağımlılık yönü korunuyor. Ancak placements sağlayıcı hatası `logger.exception` ile yutuluyor (fail-open); sürekli bozuk sağlayıcı sadece log'da görünür.
Kanıt: farm/placements.py:41-52; experiments/apps.py:12; reports/apps.py:12-15; core/audit.py:24.
Öneri: Desen doğru; başarısızlık sayacı/izleme ekle ve tüm yeni app'lerde aynı yaklaşımı kullan (31-7 ile birlikte).

### 31-12 - reports -> farm bağımlılığı çok geniş (50 import, iç modüllere)
Önem: low | Güven: high
Dosyalar: reports/ (compute/, health.py, forms.py)
Açıklama: reports farm'ın modellerine, fold/read/handling.fasting/forms.water gibi iç modüllerine doğrudan uzanıyor; farm'ın iç yeniden düzenlemesi reports'u kırar. Docstring "farm raporları okur, farm okumaz" söylüyor ve bu doğrulandı (farm -> reports importu yok), ama genel API yok.
Kanıt: reports/apps.py:8-9 (docstring); import sayımı reports->farm 50; reports farm.stock.fold, farm.handling.fasting, farm.forms.water:8 kullanımı.
Öneri: farm için dışa açık `farm.api`/read sözleşmesi tanımla.

### 31-13 - Fonksiyon-içi (lazy) cross-app import'lar
Önem: info | Güven: high
Dosyalar: hr/scope.py, monitoring/read.py, farm/health/notices.py
Açıklama: Döngüyü/yükleme sırasını aşmak için lazy import'lar var (hr/scope.py:188, monitoring/read.py:285 `from farm import placements`); izlenmesi zor, statik analizle görülmez.
Kanıt: hr/scope.py:188 (`from farm.models import ProductionDepartment`), hr/scope.py:213 (`from core.crud import mount_of`), monitoring/read.py:285.
Öneri: Mümkünse üst-seviyeye taşı veya import kuralı testi ekle.
