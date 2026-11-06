# 22 - İş mantığı: su kimyası, water limits, alarm eşikleri, birimler, monitoring kartları

## Özet
Su alanı genel olarak titiz: parametreler tek listede (`farm/water/parameters.py`) birim/baz/plausibility/tazelik ile tanımlı, durum (status) saklanmıyor ve okuma anında güncel limitlere göre hesaplanıyor, NH₃-N ve O₂ doygunluğu aynı örneğin pH/sıcaklık/tuzluluğundan türetiliyor, birim dönüşüm sabitleri (dKH 17.85, NH₄⁺/1.29, NH₃/1.22, NO₂⁻/3.29, NO₃⁻/4.43, NH₃-N limiti 0.0103) doğru, O₂ çözünürlüğü (10 °C tatlı su 11.29 mg/L) ve NH₃ payı (pH 8, 15 °C, %2.66) bilinen referanslarla uyuşuyor (doğrudan saf Python çalıştırılarak denendi). Bulunan sorunlar: monitoring bar widget'ının açık alt sınırlı limitlerde tamamen "kritik" boyaması (22-1), `Site.altitude` sınırsız olduğundan saçma bir rakımın O₂ doygunluğu hesabını (dolayısıyla su sayfalarını) `ValueError` ile düşürmesi (22-2), negatif günlük sıcaklıkların derece-gün toplamından düşmesi (22-3), limit tanımlanmamışken kartların sessizce "OK" görünmesi ve hiçbir bildirim gönderilmemesi (22-4, 22-5), tür+su tipi limit satırının "any" satırını bütünüyle gölgelemesi (22-6), takvim/hesaplayıcı ile ünite durumu arasındaki farklı uyarı tanımları (22-8, 22-9) ve çeşitli düşük önemli tutarsızlıklar. Testler çalıştırılmadı (PostgreSQL/TimescaleDB bu ortamda yok); tüm bulgular kod okuyarak, bazıları saf-Python hesapla (`farm/water/chemistry.py`, bar mantığı) doğrulandı.

## İncelenen alanlar
- `farm/water/`: `parameters.py`, `evaluate.py`, `read.py`, `chemistry.py`, `services.py`, `calculation.py`, `degree_days.py`, `deffeyes.py` (analyse/judge/why_impossible), `dosing.py` (başlık ve reaktif sabitleri), `views.py` (özet/durum sayaçları)
- `farm/models/water.py` (WaterMeasurement, WaterLimit kısıtları), `farm/models/water_point.py` (nokta türleri), `farm/models/site.py` (altitude), `farm/models/tank.py` (WaterType), `farm/species_catalog.py`
- `farm/forms/water.py` (örnek formu, limit formu, hesaplayıcı formu)
- `farm/feeding/temperature.py`, `farm/health/withdrawal.py` (derece-gün tüketimi), `reports/compute/lice.py` (deniz sıcaklığı)
- `monitoring/`: `models.py`, `cards/builtin.py`, `cards/catalogue.py`, `cards/render.py`, `read.py` (`state_of`, `_key_readings`), `templates/monitoring/widgets/_bar.html`, `_value.html`, `farm/templatetags/water.py`
- README.md ve `docs/aquaculture-platform-bugs.md` (Water chemistry bölümü başlığı) ile kod karşılaştırması

## İncelenmeyen / sınırlı incelenen alanlar
- Testler çalıştırılmadı (PostgreSQL/TimescaleDB yok); DB check kısıtlarının (Round, num_nonnulls) gerçek davranışı denenmedi.
- `farm/water/charts.py`, `deffeyes.py` çizim/geometri kısmı (clip, layers), `dosing.py` recipes/simulate gövdesi ve `farm/water/points.py` ayrıntılı okunmadı; yalnızca sabitleri ve sınıfları kontrol edildi.
- Kimya sabitlerinin (Millero, Dickson katsayıları) literatürle satır satır karşılaştırması yapılmadı; yalnızca O₂ çözünürlüğü ve NH₃ payı sayısal olarak kontrol edildi.
- TypeScript frontend (`frontend/designer.ts`, `poll.ts`) ve çeviri katalogları incelenmedi.
- `docs/aquaculture-platform-bugs.md` içeriğinin tamamı (WQ-xx satırları) kodla tek tek eşlenmedi.
- Rol/yetki (water görme izni) ve veri okuma/yazma güvenliği ilgili başka uzman alanlarına bırakıldı.

## Bulgular

### 22-1 | Orta | Güven: yüksek
**Bar widget'ı: alt sınırları boş limitte çubuk baştan sona "kritik" çiziliyor**
- Dosyalar: monitoring/cards/render.py:149-170, monitoring/tests/test_render.py:145-155, templates/monitoring/widgets/_bar.html
- Açıklama: `bar()` bantları `order` listesiyle üretiyor; listede sınır değeri `None` olan öğe "son bant, çubuğun sonuna kadar" olarak yorumlanıyor (`end = 100.0 if edge is None else at(edge)`). Ancak `None`, yalnızca son öğede değil, `critical_low`/`warning_low` boş olduğunda da ilk öğelerde geliyor. NH₃-N, TAN, nitrit, CO₂ gibi yalnızca üst sınırı olan limitlerde (modelde "Any bound may be left open") ilk öğe `('critical', None)` olup 0-100 arası tek bir kritik bant üretiyor, sonraki bantlar `end > start` koşuluyla atlanıyor. Sonuç: değer tamamen güvenli olsa bile çubuk tümüyle kritik renk/desenle çiziliyor; `aria-label` cümlesi ise doğru limitleri söylüyor (görsel ile metin çelişiyor).
- Kanıt: Aynı mantık Python'da çalıştırıldı: sınırlar `{critical_low: None, warning_low: None, warning_high: 5, critical_high: 10}`, değer 3 için çıktı `[('critical', 0.0, 100.0)]`. Mevcut test yalnızca dört sınırın da dolu olduğu O₂ limitini (`critical_low=6, warning_low=7, warning_high=12, critical_high=14`) deniyor.
- Öneri: Açık alt sınırları atlayın (None ise o bandı üretmeyin, sonraki kenara geçin); yalnızca son banda `100` atayın. Testi tek yönlü limit (yalnızca high ya da yalnızca low) için ekleyin.

### 22-2 | Orta | Güven: yüksek
**`Site.altitude` sınırsız: aşırı rakım `pressure_atm` içinde `ValueError` ile su okumasını düşürüyor; hesaplayıcı ile okuma katmanı farklı aralık kullanıyor**
- Dosyalar: farm/models/site.py:87, farm/forms/site.py (altitude yalnızca TextInput), farm/water/read.py:339-341, farm/water/chemistry.py:365-367, farm/water/calculation.py:36,228-229, farm/forms/water.py:427
- Açıklama: `altitude` DecimalField(max_digits=8, decimal_places=2) olup validator veya DB check yok (tipik yazım hatası: 50000 gibi). Okuma katmanı `_oxygen()` içinde bu değeri doğrudan `chemistry.pressure_atm(float(altitude))`'a veriyor; taban `1 - 2.25577e-5*h` yaklaşık 44 331 m üzerinde negatif olup `math.pow(neg, 5.25588)` `ValueError` fırlatıyor. Oksijeni olan herhangi bir örnek `Context.readings` üzerinden bu yola girdiği için su özet/geçmiş/monitoring okumaları o siteye bağlı tüm ünitelerde patlar. Ayrıca negatif rakım (örn. -500 m) okuma katmanında kabul edilip basınç 1.06 atm hesaplanırken, `offers()` ve hesaplayıcı formu 0-5000 m dışını sessizce yok sayıp deniz seviyesi (1.0 atm) kullanıyor: aynı site için O₂ % ünite sayfasında ve hesaplayıcıda farklı çıkabilir.
- Kanıt: `python3` ile `chemistry.pressure_atm(50000)` -> `ValueError: math domain error`; `pressure_atm(-500)=1.0607`, `pressure_atm(5000)=0.533`. `calculation.py:228`: `0 <= site.altitude <= ALTITUDE_HIGH` (5000). `forms/water.py:427`: `number_field(_('Altitude (m)'), 0, 5000, 0, ...)`.
- Öneri: `Site.altitude` için model validator + DB check (örn. -500..5000 ya da tek sabit) ekleyin; `pressure_atm` girdisini sınırlandırın; okuma, hesaplayıcı ve form aynı sabiti kullansın.

### 22-3 | Düşük | Güven: yüksek
**Negatif günlük sıcaklık derece-gün toplamından düşüyor (projeksiyon ise ≤0'ı reddediyor)**
- Dosyalar: farm/water/degree_days.py:125-133,171, farm/health/withdrawal.py:196-215, farm/water/parameters.py (temperature_c low=-3)
- Açıklama: Sıcaklık plausibility aralığı -3 °C'den başlıyor; ölçülen günlük ortalama negatif olabilir (Tromsø'de kışın buz altı/şok durumları, yazım hatası). `Counted(value, MEASURED)` bu negatif değeri olduğu gibi döndürüyor ve hem `accrue()` hem `degree_days()` `total += counted.value` ile toplamı azaltıyor; yani bekleme (withdrawal) ve açlık (fasting) hedefi o gün için ilerlemek yerine geriliyor. Bu güvenli yönde (daha uzun bekleme) bir hata, ama derece-gün tanımına aykırı ve bekleme/açlık tarihini keyfî uzatıyor. Aynı dosyada projeksiyon ortalaması `mean <= 0` ise "bilinmiyor" sayıyor (withdrawal.py:212): iki yol arasında negatif/sıfır sıcaklık için tutarsız kural var. Ayrıca tatlı suda -3 °C ölçüm fiziksel olarak mümkün değil, yani plausibility alt sınırı kaba.
- Kanıt: `accrual.total += counted.value` (degree_days.py:171), `total += counted.value` (withdrawal.py:207), `if mean is None or mean <= 0: return None, True, ...` (withdrawal.py:212); `_parameter('temperature_c', ..., 1, -3, 40, 24, 'oxygen')`.
- Öneri: Günlük katkıyı `max(value, 0)` ile sınırlandırın (ya da kuralı açıkça belgeleyin) ve hem toplam hem projeksiyon aynı kuralı kullansın; tatlı su ünitelerinde alt sınırı 0 yapmayı düşünün.

### 22-4 | Orta | Güven: yüksek
**Hiç limit tanımlı değilken stoklu ünite kartı sessizce "OK" kalıyor (NO_LIMIT hiçbir uyarı üretmiyor)**
- Dosyalar: monitoring/read.py:400-450, farm/water/evaluate.py:71-76, farm/models/water.py (WaterLimit docstring: "None is seeded"), farm/water/read.py:362-369
- Açıklama: Limitler tohumlanmıyor (WQ-24 kararı) ve her tür/parametre için elle girilmeli. Limit yoksa `assess()` `NO_LIMIT` döndürüyor; `state_of()` yalnızca `point.alerts` (CRITICAL/WARNING) ve key okumaların tazeliğine bakıyor, `NO_LIMIT` için ne `NOTE` ne `BLIND` üretiyor. Taze sıcaklık+O₂ ölçümü olan fakat o türe hiç limit girilmemiş bir ünite, 2 mg/L oksijenle bile yeşil "OK" kartı gösteriyor. Tek ipucu `_value.html` içindeki küçük "No limit" etiketi ve `_bar.html`'deki "no limit set for this value" yazısı (yalnızca ilgili widget varsa).
- Kanıt: `state_of` içinde yalnızca `for reading in point.alerts` döngüsü ve `_key_readings` tazelik kontrolü var; `NO_LIMIT` için dal yok. `evaluate.py:75`: `return Status.NO_LIMIT, []`.
- Öneri: Stoklu ünitede sıcaklık/O₂ için limit bulunamıyorsa kartı "not" (NOTE) ya da "blind" benzeri bir kademeye alın ve nedeni ("limit tanımlı değil") yazın; ayrıca su limiti olmayan stoklu tür/su tipi için bir kurulum denetimi/uyarısı ekleyin.

### 22-5 | Orta | Güven: yüksek
**Alarm eşikleri var ama bildirim yok; yalnızca ekrana bakan kişi görüyor**
- Dosyalar: templates/farm/water.html:58, monitoring/read.py:400-456, tasks/models.py:93 (yalnızca WATER_QUALITY görev kategorisi)
- Açıklama: Su sayfasının yardım metni açıkça "Nobody is alerted: critical values are shown here, not sent" diyor; messaging/tasks tarafında su durumuna bağlı hiçbir bildirim/görev üretimi yok (`grep` ile yalnızca görev kategorisi enum'unda "water" geçiyor). Ek olarak kritik bir değer tazelik süresini (O₂/sıcaklık 24 sa) aşınca `STALE` oluyor ve kart kırmızı yerine "blind" oluyor ("never red"). Yani ölçülen kritik oksijenin 25 saat sonra alarmı fiilen kalkıyor. Bu bilinçli bir MVP kararı olarak belgelenmiş olsa da, "alarm eşiği" kavramının bir alarm mekanizması olmadığı kayıt altına alınmalı.
- Kanıt: water.html:58 metni; `evaluate.py:34`'teki `RANK` sırasında STALE, CRITICAL'ın altında; `read.py:367-368` `reading.status = Status.STALE` ile kritik durumu eziyor.
- Öneri: En azından kritik değerler için bildirim (mesaj/görev) tasarımını backlog'a alın; stale-kritik değeri "blind" yerine "son bilinen kritik, X saat önce" olarak göstermeyi değerlendirin.

### 22-6 | Düşük | Güven: yüksek
**Su tipine özel limit satırı, "any" satırını bütünüyle gölgeliyor (sınır bazında birleştirme yok)**
- Dosyalar: farm/water/evaluate.py:58-64, farm/models/water.py (WaterLimit docstring), farm/forms/water.py (limit formu help_text)
- Açıklama: `applying()` `rows.get((species, parameter, water_type)) or rows.get((species, parameter, ANY))` ile tek satır seçiyor. Kullanıcı "any" satırında dört sınırı, "saltwater" satırında yalnızca `warning_high` girdiyse, tuzlu sudaki ünite için `critical_*` ve düşük sınırlar tamamen kaybolur (yalnızca `warning_high` yargılanır); satırların alan bazlı mirası yok. Form yardımı yalnızca "wins over" diyor, bunu anlatmıyor.
- Kanıt: `return self.rows.get((species_id, parameter, water_type)) or self.rows.get((species_id, parameter, ANY_WATER))`.
- Öneri: Ya sınırları alan bazında birleştirin (spesifik satır yoksa any'den alın), ya da form/yardım metninde satırın tam yerine geçtiğini ve eksik sınırın "yok" sayıldığını açıkça yazın; boş sınırlı spesifik satır için uyarı verin.

### 22-7 | Düşük | Güven: orta
**Bar, birden çok tür/limit satırında yalnızca ilk satırı çiziyor; durum ise en kötü satıra göre**
- Dosyalar: monitoring/cards/render.py:143-170, farm/water/evaluate.py:66-77
- Açıklama: `assess()` aynı ünitedeki her tür için ayrı satır bulup en kötü durumu veriyor ve tüm satırları `reading.limits`'e koyuyor; `bar()` ise `reading.limits[0]`'ı çiziyor. Karma stoklu ünitede (somon + temizleyici balık) durum "kritik" iken bar, ilk satıra göre tamamen yeşil/OK bantlarla ve işaretçi güvenli bölgede çizilebilir; `aria-label` da yalnızca ilk satırın sınırlarını söylüyor.
- Kanıt: `limit = reading.limits[0]` (render.py:149). `found` sırası `exposures` sırasına bağlı (`read.py:286-289`), sıralama deterministik değil (tür kümesi).
- Öneri: Durumu belirleyen (en kötü) satırı çizin ya da en sıkı sınırları birleştirin; en azından `reading.limits` içinden status'ü üreten satırı seçin.

### 22-8 | Düşük | Güven: yüksek
**Hesaplayıcı/Deffeyes NH₃ ve CO₂ için farklı "uyarı" tanımı kullanıyor (pH payı 0.2) ve türün warning sınırını yok sayıyor**
- Dosyalar: farm/water/calculation.py:11-14,230-233, farm/water/deffeyes.py:51,129-137, farm/water/evaluate.py:45-55
- Açıklama: Ünite okuma yolunda NH₃-N ve CO₂ dört sınırla (warning/critical) yargılanırken, hesaplayıcı ve ünitenin Deffeyes grafiği yalnızca `critical_high`'ı limit olarak alıp "uyarı"yı sınırdan 0.2 pH uzaklık (`ALERT_PH`) olarak üretiyor. Aynı ünite için üretim ekranında NH₃ "OK" iken grafikte "warning" (veya tersi) görünebilir. Bu kod yorumunda belgelenmiş bir tasarım kararı, ancak iki ayrı "durum" tanımının kullanıcıya açıklandığına dair UI ipucu yok.
- Kanıt: `_strictest(limits.get(code, []), 'critical_high', min)` (calculation.py:232); `status = ... WARNING if margin <= ALERT_PH` (deffeyes.py:137).
- Öneri: Uyarı metnine "grafikteki uyarı pH payıdır, tür limitindeki warning sınırı değil" notu ekleyin ya da warning_high'ı da hesaba katın.

### 22-9 | Bilgi | Güven: yüksek
**Sınırdaki değerin durumu iki yargılayıcıda farklı: eşitlik `evaluate.judge`'da iç banda, `deffeyes.judge`'da kritik banda**
- Dosyalar: farm/water/evaluate.py:46-55, farm/water/deffeyes.py:137, farm/water/calculation.py:83
- Açıklama: Limit satırı için "sınıra eşit değer iç banttadır" (`<`/`>` katı). `deffeyes.judge` ise `margin <= 0` ile sınıra eşit pH'ı kritik sayıyor ve `margin <= ALERT_PH` ile uyarı sınırını dahil ediyor. Simülatörün pH adımı `judge_bounds` ile (eşitlik iç bant) yargılanırken NH₃/H₂S/CO₂ adımları `deffeyes.judge` ile (eşitlik kritik) yargılanıyor: aynı `JudgedStep` içinde iki kural. Ölçüm hassasiyeti (float) nedeniyle pratikte nadir ama tutarsız.
- Kanıt: `status = Status.CRITICAL if margin <= 0 else Status.WARNING if margin <= ALERT_PH else Status.OK`.
- Öneri: Kararı tek yerde belgeleyin; tercihen `margin < 0` ile `evaluate`'ın "eşitlik iç banttadır" kuralına uyun.

### 22-10 | Düşük | Güven: orta
**Ünite grafiği ve hesaplayıcı, farklı örneklerden/zamanlardan gelen "en son" değerleri tek bir su gibi birleştiriyor**
- Dosyalar: farm/water/read.py:24-27,393-413, farm/water/calculation.py:217-246,297-337
- Açıklama: `latest()` her parametrenin en yeni değerini ayrı ayrı alıyor (tasarım gereği, WQ-04). `chart_of()`/`offers()` sıcaklık, pH, alkalinite, tuzluluk ve TAN'ı bu bağımsız okumalardan birleştirip tek bir Deffeyes noktası olarak çiziyor; tazelik farkı büyük: sıcaklık 24 sa, pH 72 sa, alkalinite 336 sa, tuzluluk 168 sa. Kullanıcıya her girdinin yaşı gösteriliyor ancak çizilen NH₃/CO₂ sınır pH'ı farklı günlerin değerleriyle hesaplanıyor ve grafik "tutarlı bir örnek" gibi görünüyor; girdiler arasındaki maksimum zaman farkı için bir eşik/uyarı yok.
- Kanıt: `values = {name: float(found[name].value) ...}` her ad ayrı `Reading`'ten (calculation.py:310); `parameters.py` `fresh_hours` değerleri 24/72/336/168.
- Öneri: Girdiler arasında örnek zamanı farkı belirli bir eşiği (örn. 24 sa) aşıyorsa grafikte uyarı gösterin.

### 22-11 | Düşük | Güven: orta
**pH aralıkları tutarsız: örnek 2-12, hesaplayıcı girişi/hedef 4-12, pH sınır alanları 0-14, grafik 4-12.5**
- Dosyalar: farm/water/parameters.py (ph low=2, high=12), farm/forms/water.py:413,428,435-438, farm/water/deffeyes.py:47, farm/water/calculation.py:35,297-337
- Açıklama: Bir örnek 2-12 arası pH ile kaydedilebiliyor ve `offers()` bu değeri hesaplayıcıya taşıyor; ancak hesaplayıcı formu pH alanını 4-12 ile sınırlıyor (`_measured('ph', low=4)`), dolayısıyla 4 altı bir pH (asit şoku, tam kritik durum) için hesaplayıcı form hatası veriyor ve aynı pH, `chart_of`'ta kullanıma girerse grafik alanı (4-12.5) dışında kalıyor. pH limit sınırı alanları ise 0-14 kabul ediyor (hesaplayıcıda), WaterLimit modelinde 2-12.
- Kanıt: `ph = _measured('ph', required=True, low=4)`; `PH_RANGE = (4.0, 12.5)`; `_parameter('ph', ..., 2, 2, 12, 72, 'acid', ...)`; `PH_FIELDS` alanları `number_field(..., 0, 14, 2)`.
- Öneri: Aralıkları tek sabitte toplayın; 4 altı pH için hesaplayıcıda "grafik bu pH'ı çizemez" gibi açık mesaj verin.

### 22-12 | Düşük | Güven: orta
**Kart "blind" kuralı yalnızca sıcaklık ve oksijene bakıyor; bayat pH/TAN/NH₃ değeri ne alarm ne uyarı üretiyor**
- Dosyalar: monitoring/read.py:380-393,430-439, farm/water/parameters.py (fresh_hours), farm/water/read.py:359-369
- Açıklama: Tazelik süresi geçen her değer `STALE` olup alarm listesinden (`alerts`) düşüyor. `state_of()` yalnızca sıcaklık ve O₂ eksik/bayat ise kartı "blind" yapıyor; pH (72 sa), TAN/NO₂/TGP/tuzluluk (168 sa) bayatlayınca kart "OK" kalıyor. TAN ve nitrit ölçümü için 7 günlük "taze" süre RAS'ta toksik bir olay için çok uzun, TGP için de (hızlı değişir) 7 gün uzun görünüyor; bunlar sabit koda gömülü ve çiftlik/tür bazlı ayarlanamıyor.
- Kanıt: `_key_readings` yalnızca `parameters.TEMPERATURE` ve oksijen döndürüyor; `_parameter('tan_mg_l', ..., 168, ...)`, `_parameter('tgp_pct', ..., 168, ...)`.
- Öneri: Tazelik sürelerini yapılandırılabilir yapın (veya limitin olduğu her parametre için bayat durumda not üretin); kararı belgeleyin.

### 22-13 | Düşük | Güven: yüksek
**Tuzlu/acı su ünitesinde tuzluluk girilmemişse NH₃-N hiç hesaplanmıyor (en toksik parametre yargılanmıyor)**
- Dosyalar: farm/water/read.py:75-78,291-301,319-328, farm/models/tank.py (WaterType), farm/water/calculation.py:313-320
- Açıklama: `assumed_salinity` yalnızca tüm üniteler tatlı su ise 0 varsayıyor; `saltwater`/`brackish` ünitede son 30 günde tuzluluk ölçümü yoksa NH₃-N ve eksik olan O₂ (mg/L ↔ %) hesaplanmıyor, yalnızca "Needs the salinity" notu çıkıyor (durum NOT_MEASURED). NH₃ limiti olan bir deniz ünitesi, TAN ölçülse bile NH₃ üzerinden hiç alarm üretmiyor ve unit chart reddediliyor. Ayrıca `Tank.water_type` ile ölçülen tuzluluk arasında çapraz kontrol yok (tatlı su ünitesinde 30 ‰ ölçüm sessizce kabul edilir; o zaman tuzluluk ölçümü varsayımın yerine geçer).
- Kanıt: `return Decimal(0) if set(water_types) == {Tank.WaterType.FRESHWATER} else None`; `_ammonia()`: `if salinity is None: return {NH3_N.code: Reading(NH3_N, None, ...)}`.
- Öneri: Su tipine göre tuzluluk için makul bir uyarı/varsayılan (ör. tanım alanı olarak tank/sistem tuzluluğu) veya örnek formunda TAN girilip tuzluluk yoksa uyarı verin; su tipi ile ölçülen tuzluluk aralığı uyuşmazlığı için plausibility uyarısı ekleyin.

### 22-14 | Bilgi | Güven: orta
**O₂ mg/L ile % tutarsızlığı yalnızca not; iki değer ayrı limitlerle bağımsız yargılanıyor**
- Dosyalar: farm/water/read.py:350-356, farm/water/read.py:66
- Açıklama: Girilen mg/L ve % değerleri beklenen oranla %10'dan fazla ayrışırsa yalnızca bir not konuluyor; iki okuma da girildiği gibi bırakılıp ayrı ayrı yargılanıyor. Mg/L limiti "OK" iken % limiti "kritik" olabilir (ya da tersi) ve kart durumu en kötüyü alır. Servis katmanı (`services.record`) de bu tutarsızlığı kayıt anında engellemiyor/uyarmıyor, yalnızca okuma anında not düşüyor.
- Kanıt: `if expected and abs(mg_l - expected) / expected > OXYGEN_TOLERANCE: note = ...; return {code: Reading(... getattr(sample, code), sample, False, note) ...}`.
- Öneri: Form kayıt anında aynı kontrolü uyarı olarak gösterin; tutarsız örneğin durumunu "kontrol et" notuyla birlikte işaretleyin.

### 22-15 | Düşük | Güven: düşük
**Bit raporu deniz sıcaklığı: sitedeki tüm 3 m derinlik noktalarının örnek ortalaması (ünite türü/su tipi filtresi yok)**
- Dosyalar: reports/compute/lice.py:52-73
- Açıklama: `depth_samples()` site genelindeki `kind=DEPTH, depth_m=3` noktalarının tüm örneklerini alıp aritmetik ortalamasını § 6 "deniz sıcaklığı" olarak veriyor. Aynı sitede tatlı su tankı/havuzu da bir 3 m derinlik noktasına sahipse o sıcaklık deniz sıcaklığına karışır; ortalama zaman ağırlıklı değil, günde çok örnek alınan noktalar ağır basar. Güven düşük: sitelerin gerçekte tankları ile kafeslerini karıştırıp karıştırmadığı veri durumuna bağlı.
- Kanıt: `water.samples_of(site=site, ...).filter(point__kind=PointKind.DEPTH, point__depth_m=TEMPERATURE_DEPTH_M)`; `sum(...) / len(found)`.
- Öneri: Yalnızca deniz kafesi/tuzlu su ünitelerinin noktalarını alın ve günlük ortalamaların ortalamasını kullanın.

### 22-16 | Bilgi | Güven: yüksek
**Olumlu doğrulamalar: birim dönüşümleri ve kimya sabitleri tutarlı**
- Dosyalar: farm/water/parameters.py, farm/water/chemistry.py, farm/water/dosing.py, farm/forms/water.py:400-460
- Açıklama: Yardım metinlerindeki dönüşümler doğru: alkalinite dKH × 17.85 (≈17.848), NH₄⁺ / 1.29 (18.04/14.007), NH₃ / 1.22 (17.03/14.007), NO₂⁻ / 3.29, NO₃⁻ / 4.43; `MG_CACO3_PER_MEQ=50.04345`, `H2S_PER_S=34.08088/32.065`, NH₃-N limiti varsayılanı 0.0103 = 0.0125 mg/L NH₃ × 14.007/17.031. Bound check'leri (`Round(F(bound), decimals)`), sıralı sınır kısıtı ve parametre başına duyarlılık tek kaynaktan türetiliyor. Saf Python ile: O₂ çözünürlüğü 10 °C tatlı su 11.288 mg/L, 10 °C %35 tuzluluk 9.024 mg/L; NH₃ payı pH 8, 15 °C tatlı su %2.66, deniz suyu %1.72 (beklenen aralıkta).
- Kanıt: Doğrudan `farm/water/chemistry.py` fonksiyonlarının çalıştırılması (`oxygen_solubility`, `nh3_fraction`, `pressure_atm`).
- Öneri: Yok; yalnızca regresyon testi olarak bu referans değerleri (11.29 mg/L, %2.66) `farm/tests/test_water.py`'ye sabitlemek faydalı olur.
