# 17 - Zaman serisi (TimescaleDB / izleme verisi) denetimi

## Özet
Depoda tek bir hypertable vardır: `water_measurements` (`farm/migrations/0014_water.py:96-103`, 90 günlük chunk, `measured_at` boyutu). Sensörden otomatik veri alımı (ingest), retention, compression veya continuous aggregate yoktur; veri yalnızca elle girilen numunelerdir (`farm/water/services.py`). `monitoring/` uygulaması zaman serisi tablosu içermez, `farm/water/read.py` üzerinden okur. Zaman dilimi yönetimi genel olarak tutarlıdır (UTC saklama, site saat dilimi `zone_of`). Kritik bulgu yok; ağırlıklı olarak ölçeklenme, DST ve belgelenmemiş boşluk bulguları var. Testler çalıştırılmadı (veritabanı konteyneri gerekir); yalnızca kod okundu.

## İncelenen alanlar
- farm/migrations/0014_water.py, 0019_water_points.py; farm/models/water.py; farm/water/services.py, read.py, degree_days.py, evaluate.py; farm/forms/water.py; farm/stock/dates.py; farm/feeding/temperature.py, read.py; docker-compose.yml; config/settings.py (DB, TIME_ZONE, USE_TZ); README hypertable bölümü; monitoring/read.py (kullanım).

## İncelenmeyen alanlar
- Canlı veritabanı üzerinde chunk/indeks planları (EXPLAIN), testlerin çalıştırılması, üretim dağıtım yapılandırması (repoda yok), farm/health/withdrawal.py ve handling/fasting.py iç ayrıntıları.

## Bulgular

### 17-1 | info | güven: high
Dosyalar: farm/feeding/temperature.py:3-4, farm/water/services.py, README.md:1062-1068
Sensör/otomatik ingest yolu yok. Açıklama: Tek yazıcı elle giriş formudur (`record`, `record_round`); `temperature.py` docstring'i "Sensors will be one more source" der ama hiçbir ingest, API ucu, toplu yükleme veya `source` değeri sensör için tanımlı değildir. Kanıt: `Source` seçenekleri meter/kit/lab (farm/models/water.py:24 civarı, README:1055). Öneri: Sensör verisi planlanıyorsa ayrı bir geniş-şekilli ham tablo/hypertable, cihaz kimliği, idempotent toplu yazma ve kalibrasyon/kalite bayrağı tasarımı ADR olarak yazılmalı.

### 17-2 | low | güven: high
Dosyalar: farm/migrations/0014_water.py:91-103, README.md:1068
Retention, compression ve continuous aggregate yok. Açıklama: README "compression is left for later" der; retention politikası ve CAGG hiç yok. Mevcut hacimde sorun değil, ancak sensör gelirse tablo sınırsız büyür. Kanıt: migration'da yalnızca `create_hypertable`. Öneri: Hacim eşiği ve gelecekteki politika (compress_after, retention) belgelenmeli.

### 17-3 | low | güven: medium
Dosyalar: farm/water/read.py:~300 (`latest`, `samples = WaterMeasurement.objects.select_related(...).in_bulk(ids)`)
`latest()` numuneleri yalnızca `id` ile getirir; zaman filtresi yok. Hypertable'da PK `(id, measured_at)` olduğundan chunk exclusion çalışmaz, her chunk'ta indeks araması yapılır. Kanıt: `_newest_ids` zaten `measured_at__gte=since` ile 30 günlük pencere bulur ama `in_bulk(ids)` bu bilgiyi kullanmaz; model docstring'i (farm/models/water.py:88) bunu "cheap at a farm's volume" diye kabul eder. Her izleme kartı/pano isteğinde çalışır. Öneri: `.filter(measured_at__gte=since)` eklenmeli (in_bulk yerine filter + dict).

### 17-4 | low | güven: high
Dosyalar: farm/models/water.py:84-90, farm/migrations/0014_water.py:92-102
Hypertable'da `id` tek başına DB düzeyinde benzersiz değildir. Açıklama: PK `(id, measured_at)` ile Timescale yalnızca (id, measured_at) çiftini garanti eder; Django state'i `id`'yi PK sanır (`get(pk=)`, void). UUID4 çakışması pratikte imkansız, ama DB garantisi yok; ayrıca `void` ve `in_bulk` id ile tüm chunk'lara bakar. Öneri: Kabul edilen risk olarak belgelenmiş (docstring); id'ye güvenen kodlarda (audit log object_id) ek `measured_at` taşımak değerlendirilebilir.

### 17-5 | low | güven: medium
Dosyalar: farm/water/services.py:~133-139 (`record`), 169-175 (`record_round`), farm/models/water.py:126
İdempotensi anahtarı `(entry_key, measured_at)`. Açıklama: Aynı form token'ıyla gönderilen ama `measured_at` değeri düzenlenmiş istek tekrar kaydedilir (benzersiz kısıt ve `done` sorgusu zamanı da içerir). "Aynı form iki kez gönderilirse bir kez kaydedilir" iddiası (README:1056) saat alanı değişmediği sürece doğrudur. Kanıt: `filter(entry_key=token, measured_at=measured_at)`. Öneri: Kısıtı zorunlu kılan Timescale sınırı belgelenmeli; uygulama düzeyinde yalnızca `entry_key` ile arama yapılıp zaman farkı ayrıca uyarılabilir (tüm chunk taraması maliyeti ile).

### 17-6 | low | güven: medium
Dosyalar: farm/forms/water.py:209, 308
DST belirsiz/olmayan yerel saatler doğrulanmıyor. Açıklama: `timezone.make_aware(moment, zone_of(...))` ZoneInfo ile hata vermez; ilkbahar geçişinde olmayan saat (örn. 02:30) sessizce bir saat kaydırılır, sonbaharda belirsiz saat `fold=0` (ilk oluşum) alınır. Numune zamanı dakika duyarlıklı serilerde 1 saat hatalı saklanabilir. Öneri: `zone.utcoffset` / `fold` ile gap/overlap tespiti ve kullanıcıya sorma veya doğrulama hatası.

### 17-7 | low | güven: medium
Dosyalar: farm/water/degree_days.py:50-62, 67-70
Günlük sıcaklık ortalaması örneklerin zaman ağırlıksız aritmetik ortalamasıdır. Açıklama: Bir gün içinde sabah turunda çok, gün boyu az numune varsa ortalama sapar; derece-gün (ilaç arınma/ açlık) hesapları buna dayanır. Kanıt: `sum(found)/len(found)`. Docstring bunu "daily mean of the live samples" diye tanımlar, yani tasarım kararı; yine de sıcaklık doğruluğu açısından kayda geçirilir. Öneri: Karar belgelensin; sensör gelirse zaman ağırlıklı ortalama/ saatlik aggregate kullanılsın.

### 17-8 | low | güven: medium
Dosyalar: farm/water/read.py:~250-252 (`Context.__init__`), farm/water/read.py `Series.__init__`
`Context` tuzluluk serisini `since - WINDOW`'dan şimdiye kadar sınırsız çeker. Açıklama: `history()` eski bir dönem için çağrılınca `Series(..., since - WINDOW)` `until` olmadan o günden bugüne tüm tuzluluk satırlarını belleğe alır; `latest()` ise her istekte 60 günlük pencere okur. Kanıt: `until=None` varsayılanı; `history` -> `Context(points, min(sample.measured_at))`. Öneri: `until` olarak `max(sample.measured_at)` geçilmeli.

### 17-9 | low | güven: medium
Dosyalar: farm/water/degree_days.py:50-62, farm/water/read.py (`Series`)
Seri okumaları tüm satırları Python listelerine yükler (aggregate DB'de yapılmıyor). Açıklama: `Temperatures` bir partinin tüm geçmişi (örn. 800 gün) için ham numuneleri okuyup günlük ortalamayı Python'da hesaplar; `time_bucket`/GROUP BY yok. Mevcut elle veri hacminde kabul edilebilir, sensör hacminde değil. Öneri: Günlük ortalamayı SQL'de (`date_trunc` / `time_bucket` site zone'una göre) hesaplayın.

### 17-10 | info | güven: high
Dosyalar: docker-compose.yml:5, README.md:4, config/settings.py:110-123
TimescaleDB yalnızca geliştirme compose'unda tanımlı. Açıklama: Sürüm 2.17.2-pg17 sabit; üretim DB'si için repoda yapılandırma/uyumluluk (managed PG'de timescaledb eklentisi olmayabilir; `CREATE EXTENSION` migration'ı `core/migrations/0001_timescaledb.py` başarısız olur) belgelenmemiş. Öneri: Üretim gereksinimi ve sürüm uyumluluğu (by_range API >= 2.13) belgelensin.

### 17-11 | info | güven: high
Dosyalar: core/migrations/0001_timescaledb.py:11-12, farm/migrations/0014_water.py:102
Geri alma (reverse) davranışı: `RunSQL` ters adımları noop; `0014` geri alınırsa tablo ve chunk'lar düşer (CreateModel tersi) — veri kaybı. Eklenti kaldırılmaz. Kayıt amaçlı (dokümante edilmiş, 0014:94-95).

### 17-12 | info | güven: high
Dosyalar: config/settings.py:160,167, farm/models/site.py:185-188, farm/stock/dates.py
Saat dilimi mimarisi tutarlı: DB `timestamptz`, `TIME_ZONE='UTC'`, `USE_TZ=True`; günler site saat diliminde (`zone_of`, `start_of`/`end_of` ZoneInfo ile). `farm/feeding/read.py:115` UTC gece yarısı kullanır ama -1 gün + 7 günlük geri bakış payı ile kapsanır; hata bulunmadı. Pozitif doğrulama kaydı.

### 17-13 | low | güven: low
Dosyalar: farm/water/services.py:~120 (`_check_time`)
Gelecek zaman kontrolü tolerans içermez (`measured_at > timezone.now()`): cihaz/tarayıcı saat farkı olan elle girişte veya ileride sensör saatinde reddedilir. Mevcut formda saat dakikaya yuvarlandığı için sorun çıkmaz. Öneri: Sensör ingest'i için ayrı tolerans.
