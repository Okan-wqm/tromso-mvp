# 32 - Kod kalitesi denetimi (tekrar, ölü kod, karmaşıklık, isimlendirme, tutarsız kalıplar, magic number)

## Özet
Kod tabanı genel olarak okunaklı, docstring'li ve yorumlu. Ruff ile (F, C901, PLR, B, SIM kuralları) 291 uyarı çıktı; bunların büyük kısmı testlerde. Üretim kodunda asıl sorunlar: (1) aynı küçük yardımcıların (`_day`, `_back`, `_is_uuid`, `_refused`, `_number`) app'ler arasında kopyalanması, (2) üç `integrity.py` ile `reports/compute/*` içinde 15-33 karmaşıklıklı dev fonksiyonlar, (3) kullanılmayan importlar, (4) kimyada tekrar eden sabitler. Hiçbir dosya değiştirilmedi.

## İncelenen alanlar
ruff çıktıları (C901, PLR0915, PLR2004, F401, F841, B007, B008, B023, B904, F402), yardımcı fonksiyon adı tekrarları (grep), integrity.py x3, reports/compute/cleaner.py, farm/water/chemistry.py, views içindeki `_day/_back/_is_uuid`, `except Exception` kullanımları, core test dosya adlandırması.
## İncelenmeyen alanlar
Frontend TypeScript kalitesi (yüzeysel), şablonlar (templates), migration'lar, test kodunun kalitesi (yalnız sayısal ruff çıktısı), tüm 74 PLR2004 magic-value uyarısının tek tek incelenmesi, ölü fonksiyon taraması (vulture yok; kapsamlı yapılmadı).

## Bulgular

### 32-1 - `_day(value)` tarih ayrıştırıcısı 6 yerde tekrar (ve farklı davranışlı)
Önem: medium | Güven: high
Dosyalar: farm/harvest/views.py, farm/health/views.py, farm/feeding/views.py, inventory/views.py, farm/resources/harvest_plan.py, core/views.py, farm/water/views.py
Açıklama: Aynı 5 satırlık `date.fromisoformat` + `ValueError -> None` fonksiyonu birebir 5 kez kopyalanmış; `core/views.py` `strptime` + aware datetime ve `end` parametresiyle farklı semantik, `farm/water/views.py` ise `parse_date` kullanan, farklı imzalı (request, name, default) bir `_day` tanımlıyor. Aynı ad, üç farklı davranış. Ayrıca `date.fromisoformat(None)` `TypeError` verir (yalnız `ValueError` yakalanıyor), core sürümü `TypeError`'ı da yakalıyor: tutarsız dayanıklılık.
Kanıt: farm/harvest/views.py:49, farm/health/views.py:63, farm/resources/harvest_plan.py:31, inventory/views.py:69, farm/feeding/views.py:71 (aynı gövde); core/views.py:27-31; farm/water/views.py:214-215.
Öneri: tek bir `core` yardımcısına (ör. `core/dates.py: parse_day`) topla; aware-datetime varyantını farklı adla ayır.

### 32-2 - `_is_uuid` 3 kez kopya, `_back`/`_refused` aileleri benzer kopyalar
Önem: low | Güven: high
Dosyalar: knowledge/resources/entry.py, reports/resources.py, farm/stock/views.py, hr/views.py, inventory/views.py, farm/stock/views.py, farm/feeding/views.py, tasks/views.py, messaging/views.py, farm/water/views.py
Açıklama: `_is_uuid` üç dosyada aynı (biri `str()` sarmalayıp biri sarmalamıyor). `_back` en az 4 app'te "next parametresini `url_has_allowed_host_and_scheme` ile doğrula, yoksa varsayılan" mantığını tekrarlıyor; `farm/feeding/views.py` bunu `stock_views._back`'e devrederek doğru yapmış, inventory ve stock ise kendi kopyasını tutuyor. `_refused` 5 modülde farklı imzalarla (request,template,context / error / *messages) tanımlı.
Kanıt: knowledge/resources/entry.py:94-99, reports/resources.py:278-283, farm/stock/views.py:308-313; farm/stock/views.py:257-265 ile inventory/views.py:57-62 aynı `next` doğrulaması; farm/feeding/views.py:60-64 delegasyon; `_refused`: tasks/views.py:37, messaging/views.py:42, farm/water/views.py:123, farm/stock/views.py:267, experiments/services.py:76.
Öneri: `core`'da `safe_next(request, default)` ve `is_uuid` yardımcısı; `_refused` isimleri anlamlı ayrışsın (`render_refused` vs `refusal_error`).

### 32-3 - `_number` aynı adla 3 farklı anlam
Önem: low | Güven: high
Dosyalar: reports/exports.py, farm/equipment_types.py, farm/feeding/protocols.py
Açıklama: Üç modülde `_number` birbiriyle ilgisiz işler yapıyor: JSON sayıya çevirme, alan tanımı üretme (`_number(name,label,unit)`), Decimal'i metne normalize etme. İsimlendirme belirsiz ve arama/yeniden düzenlemeyi zorlaştırıyor.
Kanıt: reports/exports.py:31-36, farm/equipment_types.py:21, farm/feeding/protocols.py:21-22.
Öneri: ad ver: `json_number`, `number_field`, `decimal_text`.

### 32-4 - Devasa fonksiyonlar: `core/datamap.py columns` (33), `experiments/services.py _check` (26), `reports/compute/cleaner.py compute` (25)
Önem: medium | Güven: high
Dosyalar: core/datamap.py, experiments/services.py, reports/compute/cleaner.py, farm/stock/integrity.py, inventory/integrity.py, inventory/read.py, reports/compute/smolt.py, reports/forms.py, farm/water/deffeyes.py, tasks/resources.py
Açıklama: ruff C901 eşik 10'a karşı 47 üretim fonksiyonu aşıyor; en kötüleri: `columns` 33 (64 ifade), `_check` 26, `cleaner.compute` 25 (58 ifade, iç içe `row()` kapanışı + 8 kind dalı + doğrulama + biçimleme tek fonksiyonda), `farm/stock/integrity.problems` 23, `inventory/integrity._operation_problems` 19, `inventory/read.overview` 19, `smolt.compute` 19, `reports/forms.__init__` 19. PLR0915 (>50 ifade): `experiments/services._check`, `deffeyes.geometry`, `tasks/resources.filter_list`, `cleaner.compute`, `datamap.columns`.
Kanıt: core/datamap.py:504; experiments/services.py:119; reports/compute/cleaner.py:30-100 (hesap + problem metni + uyarı aynı gövde); farm/stock/integrity.py:72; inventory/integrity.py:18; reports/forms.py:68; farm/water/deffeyes.py:487; tasks/resources.py:91.
Öneri: toplama/doğrulama/biçimleme aşamalarını ayır; `cleaner.compute` içindeki kind->alan eşlemesini tabloya çevir.

### 32-5 - Üç `integrity.py` aynı iskeleti kopyalıyor; ileti metinleri çeviri dışı f-string
Önem: low | Güven: medium
Dosyalar: farm/stock/integrity.py, inventory/integrity.py, reports/integrity.py
Açıklama: Üçü de "`problems()`: found=[], satırları gruplayıp operasyon başına kuralları if/elif zinciriyle kontrol et, cümle listesi dön" kalıbını ve `name = f'{kind} {pk} ...'` önekini tekrarlıyor; ortak çerçeve yok. Ayrıca iletiler `_()` içermiyor, oysa `reports/compute/*` aynı türden iletileri `_()` ile çeviriyor: iki farklı kalıp.
Kanıt: farm/stock/integrity.py:33-35,68 ve inventory/integrity.py:18-60 (aynı yapı); reports/integrity.py:14-20; karşılaştırma: reports/compute/cleaner.py:45-46 (`_()` kullanımı).
Öneri: bunların kasıtlı olarak yalnız yönetici/komut çıktısı olduğu belgelensin ya da ortak bir `Problems` yardımcısı çıkarılsın.

### 32-6 - `reports/integrity.py` döngü içinde sorgu (N+1)
Önem: low | Güven: high
Dosyalar: reports/integrity.py
Açıklama: Her rapor için döngüde `EscapeRecord.all_objects.get(...)` ve ilişkili `movements` sorgusu yapılıyor; ayrıca `report.corrects`/`health_event` select_related ile iyi ama escape için değil.
Kanıt: reports/integrity.py:41-46.
Öneri: kaçış kayıtlarını önceden `in_bulk` ile al.

### 32-7 - Kullanılmayan importlar (üretim kodunda 12, toplam 60)
Önem: low | Güven: high
Dosyalar: farm/feeding/temperature.py, farm/health/views.py, farm/water/points.py, hr/management/commands/seed_hr_demo.py, hr/resources/employee.py, hr/services.py, monitoring/cards/validate.py, monitoring/read.py
Açıklama: ruff F401, test ve `__init__` dışında 12 kullanılmayan import: `farm.water.read.SYSTEM`/`UNIT`, `timedelta` (iki yerde), `AuditLog`, `scope.covering`, `read`, `Q`, `Holiday`, `farm.water.parameters`. Hiçbiri otomatik lint ile yakalanmıyor (repo'da ruff yapılandırması bulunmadı).
Kanıt: farm/feeding/temperature.py:23; farm/health/views.py:10; farm/water/points.py:16; hr/services.py:8,18; hr/resources/employee.py:9; monitoring/cards/validate.py:23; monitoring/read.py:38; hr/management/commands/seed_hr_demo.py:14.
Öneri: `ruff --fix` ve CI'da F401/F841 zorunluluğu. (Bazıları yan etki/yeniden dışa aktarma amaçlı olabilir; silmeden önce kontrol et.)

### 32-8 - Kullanılmayan değişkenler / döngü değişkenleri (üretim kodu)
Önem: info | Güven: high
Dosyalar: experiments/forms.py, experiments/services.py, monitoring/cards/resolve.py
Açıklama: B007: kullanılmayan döngü değişkenleri `group`, `replicate`, `why`; testlerde ayrıca 5 F841 (atanmış ama kullanılmayan `response`, `late`, `low`, `unit`).
Kanıt: experiments/forms.py:491; experiments/services.py:428; monitoring/cards/resolve.py:134; hr/tests/test_employees.py:28, tasks/tests/test_pages.py:269, experiments/tests/test_pages.py:299, farm/tests/test_protocols.py:885.
Öneri: `_` öneki ya da silme.

### 32-9 - Kimya sabitleri satır içi ve tekrar ediyor
Önem: low | Güven: high
Dosyalar: farm/water/chemistry.py, farm/water/deffeyes.py, farm/water/dosing.py
Açıklama: Klorinite çevirimi `1.80655` 3 kez ve `0.001005` (yoğunluk) 3 kez ham sayı olarak geçiyor; ayrıca `0.1400/96.062`, `0.000067/18.998`, `0.000232/10.811` gibi kaynak sabitleri adlandırılmamış. Yorumlar kaynağı açıklıyor ama sabit adı yok; yanlış yerde değişiklik riski. `deffeyes.py` içinde `* 1000`, çizim sabitleri `arm = 7`.
Kanıt: farm/water/chemistry.py:69,73,78 (1.80655); :94,101,130 (0.001005); farm/water/deffeyes.py:474,667.
Öneri: `CHLORINITY_PER_SALINITY = 1.80655`, `SEAWATER_DENSITY_SLOPE = 0.001005` gibi modül sabitleri.

### 32-10 - Magic number: ruff PLR2004 74 karşılaştırma
Önem: info | Güven: medium
Dosyalar: tüm repo (testler dahil)
Açıklama: 74 yerde adsız sayısal karşılaştırma var; dosyaların çoğunda sabitler iyi adlandırılmış (ör. `LEFT_OUT_G`, `AT_TARGET`, `HISTORY_DAYS`), yani sorun dağınık. Tek tek sınıflandırılmadı; kısmen testlere ait olabilir.
Kanıt: `ruff check --select PLR2004 --statistics .` -> 74.
Öneri: üretim kodundaki alt kümeyi ayıklayıp adlandır.

### 32-11 - Mutable/çağrı içeren varsayılan argümanlar (B008) ve `zip` strict eksik
Önem: low | Güven: high
Dosyalar: farm/water/calculation.py, farm/water/deffeyes.py
Açıklama: `judge_step(..., ph_bounds=PhBounds())` ve `Limits()` import zamanında bir kez oluşturuluyor; nesneler değişmez (dataclass/namedtuple) ise sorun yok ama doğrulanmadı. Ayrıca 37 `zip()` çağrısı `strict=` belirtmeden kullanılıyor (B905); uzunluk uyuşmazlığı sessizce kırpılır.
Kanıt: farm/water/calculation.py:75,159; farm/water/deffeyes.py:177; B905: 37 adet (ruff).
Öneri: değişmezliği doğrula; `strict=True` ekle.

### 32-12 - `raise ... from` eksik (B904) ve `except Exception` kalıpları
Önem: low | Güven: high
Dosyalar: experiments/services.py, farm/models/equipment.py, monitoring/read.py, farm/placements.py, knowledge/extraction.py
Açıklama: Dört `except` içinde `raise` yeni istisna `from` olmadan atılıyor (zincir kaybı). Geniş `except Exception` "fail open" olarak bilinçli, yorumlu ve loglanıyor (monitoring/read.py:272, placements.py:49, extraction.py:69,84), ancak aynı niyet için üç farklı yorum ifadesi ve üç farklı log stratejisi (rate-limit/`logger.exception`/belge kaydı) var: tutarsız.
Kanıt: experiments/services.py:452,667,884; farm/models/equipment.py:77; monitoring/read.py:272; farm/placements.py:49-51; knowledge/extraction.py:69,84.
Öneri: `from error`; ortak bir "fail-open" yardımcısı düşün.

### 32-13 - Test dosya adlandırması tutarsız (`tests.py`, `tests_*.py`, `test_*.py`)
Önem: info | Güven: high
Dosyalar: core/tests.py, core/tests_assets.py, core/tests_crud_mount.py, core/tests_schema.py, core/tests_scope.py, core/tests_settings.py, core/tests_templates.py, core/tests_widgets.py, core/tests_workspaces.py, core/test_*.py, farm/tests/, hr/tests/
Açıklama: `core` içinde hem `tests_*.py` hem `test_*.py` hem `tests.py` var; diğer app'ler `tests/` paketi kullanıyor. Django varsayılan keşfi `test*.py` olduğundan çalışır, ama kalıp tutarsız; `core`'un testleri paket altında değil.
Kanıt: `ls core` çıktısı (core/tests.py, core/tests_*.py, core/test_*.py).
Öneri: `core/tests/` paketine taşı, tek ad kalıbı.

### 32-14 - `core/softdelete.py` içinde gettext `_` döngü değişkeniyle gölgelenmiş
Önem: info | Güven: medium
Dosyalar: core/softdelete.py
Açıklama: Satır 71'de `for _, link in pairs` generator ifadesi, modülde `_` (gettext, satır 33) adını kullanıyor. Generator kendi kapsamında olduğundan şu an çalışıyor; ancak benzer ifade fonksiyon gövdesine taşınırsa çeviri fonksiyonu bozulur (ruff F402).
Kanıt: core/softdelete.py:71 (F402), import satır 33.
Öneri: `for _unused, link` ya da `__`.

### 32-15 - `farm/stock/views.py _back` ile `farm/feeding/views.py _back` delegasyon kalıbı tutarsız; `_context` 8 kez
Önem: info | Güven: medium
Dosyalar: farm/stock/views.py, farm/feeding/views.py, çeşitli views
Açıklama: `_context` adı 8 modülde, `_day` 7, `label` 7, `problems` 7, `compute` 6 kez tanımlı. Bunların çoğu modül-yerel olup normal, ama `_context`/`_day` gibi genel adlar grep/okuma maliyeti yaratıyor.
Kanıt: yardımcı adı sayımı (`grep -rnE "^def ..."`): `_context` 8, `_day` 7, `_back` 6, `_refused` 5.
Öneri: yalnız davranışı aynı olanları (bkz. 32-1, 32-2) birleştir.
