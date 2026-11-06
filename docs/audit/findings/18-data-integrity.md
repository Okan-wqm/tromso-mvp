# 18 - Veri bütünlüğü denetimi (data-integrity)

## Özet
Defter tabanlı model (farm/stock, inventory) bilinçli ve sıkı kurulmuş: sayım/biyokütle saklanmıyor, `fold` ile türetiliyor; CHECK/Exclusion/trigger kullanımı geniş; `check_stock`, `check_inventory`, `check_reports`, `check_experiments` bütünlük tarayıcıları var. Bulunanlar çoğunlukla "kural yalnızca uygulamada tutuluyor" türü boşluklar, ikinci doğruluk kaynakları (book vs ölçülen kg, Site/System elle girilen kapasite vs Tank türevi), silme/geri yükleme asimetrisi ve birkaç sessiz filtre. Çalışan veritabanı ve Django ortamı yoktu: `makemigrations --check`, `check_*` komutları ve testler çalıştırılamadı; tüm bulgular statik koddan.

## İncelenen alanlar
farm/models/stock.py, farm/stock/{fold,integrity,read,services}.py, farm/models/{tank,site,system,production_department,harvest,feeding,feed,feeding_protocol,water}.py, inventory/{models,fold,integrity,read,services}.py, reports/{models,integrity,exports}.py ve reports/compute/{common,biomass,stock}.py, reports/migrations/0002-0003, core/{models,softdelete}.py ve core/crud.py silme akışı, hr/leave.py + hr/models/leave.py + hr/forms/leave.py, experiments/{models,integrity}.py, tasks/models.py, messaging/{models,migrations/0001}, monitoring/models.py (FK/on_delete), tüm migrasyonlardaki trigger listesi, docs/data-map.md ve docs/aquaculture-platform-bugs.md başlıkları.

## İncelenmeyen / sınırlı incelenen alanlar
Canlı DB, TimescaleDB hypertable davranışı, testlerin çalıştırılması, farm/health ve farm/handling hesapları (withdrawal, fasting), farm/feeding/fold.py ayrıntıları, knowledge/ ve hr/scheduling/attendance, monitoring kart JSON şeması, çoğu migrasyonun gövdesi, locale/ frontend (TypeScript) tarafı. Diğer denetçilerle örtüşen konular (izin kotası kilidi, silme planı yarışı) burada yalnızca çapraz referansla anıldı (10-3, 10-6).

## Bulgular

### 18-1 | Orta | Güven: yüksek - Defter satırlarının değişmezliği ve "stok negatif olmaz" kuralı yalnızca uygulama katmanında
- Dosyalar: farm/models/stock.py:259-260, 311-312; inventory/models.py:340-343; farm/models/feeding.py:83; core/migrations/0003_audit_log_append_only.py; reports/migrations/0002_filed_reports_frozen.py
- Açıklama: Docstring'ler "satırlar asla düzenlenmez, operasyon void edilir" ve "stok hiçbir günde negatif olmaz" diyor; ancak veritabanında `stock_movements`, `stock_operations`, `inventory_lines`, `inventory_operations`, `feeding_records` için UPDATE/DELETE'i engelleyen tetikleyici yok (tetikleyiciler yalnızca audit_log, regulatory_report*, experiment tasarımı, hr, monitoring'de). Zaman çizgisi kuralı (fold) tamamen Python'da; DB, ardışık satırların toplamının negatif olmasını reddedemez. Elle düzenleme/bug, `check_stock` çalıştırılana dek fark edilmez; void ise `is_deleted` soft-delete olduğundan geçmişi DB düzeyinde de değiştirilebilir.
- Kanıt: Migrasyonlarda `CREATE TRIGGER` yalnızca core/0003, experiments/0002, hr/0001+0005, monitoring/0002, reports/0002+0003 dosyalarında; stock/inventory migrasyonlarında yok. Sabit satır sayısı kuralları (`_operation_problems`, farm/stock/integrity.py:28-70) yalnızca tarayıcıda.
- Öneri: En azından stock_movements/inventory_lines için satır UPDATE'ini (operation_id hariç değişmez alanlar) reddeden trigger; `check_stock`/`check_inventory` zamanlanmış çalıştırma veya CI/izleme kancası.

### 18-2 | Orta | Güven: orta - Envanter feeding çekimi, sitesi olmayan departmandaki ünitelerin yemini sessizce yok sayar
- Dosyalar: inventory/read.py:59-66; farm/models/production_department.py:45-47
- Açıklama: `_feeding` yalnızca `unit__production_department__site__isnull=False` olan beslemeleri toplar. `ProductionDepartment.site` null olabilir (site silinince SET_NULL, "orphaned"). Böyle bir departmanın ünitelerindeki besleme kayıtları ne siloya yansır ne de "karşılanmayan besleme" (uncovered) olarak raporlanır; envanter "stokta" göründüğünden fazla yem sayar. Site silme engeli (`Site.delete_blockers`, farm/models/site.py:116-122) yalnızca canlı StockMovement'a bakar, yani sitesiz departmanlar yalnızca stoksuz ünitelerle ulaşılabilir; yine de kod yolu savunmasız ve diğer okuyucular (`site_today`, farm/stock/dates.py:17-19) sitesiz durumu açıkça ele alırken bu filtre ele almıyor.
- Kanıt: `FeedingRecord.objects.filter(feed_id__in=feed_ids, unit__production_department__site__isnull=False)` (inventory/read.py:62).
- Öneri: Sitesiz besleme sayısını ayrı raporla (uyarı) ya da `check_inventory`'ye "sitesi olmayan departmanda besleme" kuralı ekle.

### 18-3 | Orta | Güven: orta - Gerçek (tartılmış) kg ile defter kg'ı iki ayrı doğruluk kaynağı; sapma hiçbir yerde kontrol edilmiyor
- Dosyalar: farm/models/stock.py:341-344, 352-357; farm/stock/read.py:396-401; farm/feeding/fold.py:240; reports/compute/biomass.py:104-112
- Açıklama: Ölü/hasat/teslimat satırı hem defter gramı (fold: ortalama ağırlıkla çıkış) hem `measured_weight_kg` taşır. Raporlar (`Movement.kilos`) ölçülen kg'ı, stok bakiyesi/biyokütle ise defter gramını kullanır; beslemeyi izleyen yürüyüş (feeding fold) "çıkan biyokütle" için ölçülenı kullanır. Aynı hasat için üç tüketici iki farklı kg görebilir. Ölçülen kg ile `count × defter ortalaması` arasında makullük/sapma eşiği veya uyarı yok (yalnızca `measured_weight_kg > 0`). Biyokütle raporunda "harvested.slaughter_weight_kg" ile kapanış `stock.biomass_kg` bu yüzden tutarlı toplanmayabilir.
- Kanıt: `measured = ... if line.measured_weight_kg is None else line.measured_weight_kg * 1000` (feeding/fold.py:240); `Movement.kilos` (stock/read.py:397-401); CHECK `_check('measured', ...)` yalnızca işaret/tür.
- Öneri: Ölçülen/defter oranı için kayıt anında uyarı (örn. ±%25) ve raporda sapmayı gösteren satır; ya da ölçülenı defterin tek gerçeği yapan tasarım kararı belgele.

### 18-4 | Orta | Güven: yüksek - Silme ile geri yükleme asimetrik: kaskadla silinen alt kayıtlar geri gelmiyor
- Dosyalar: core/softdelete.py:111-117, 139-143, 189-205; core/crud.py:764-781
- Açıklama: `execute` kaskad (CASCADE) çocukları soft-delete eder (Site -> StorageLocation, ProductionDepartment -> Tank, System, Experiment alt tabloları ...), ama `restore` yalnızca kaydın kendisini geri getirir ("only the record itself returns"). Bir üretim departmanı silinip geri yüklendiğinde üniteleri silinmiş kalır; ünite kodları arada alınmışsa tek tek geri yüklenemeyebilir. Silinmiş üniteye bağlı DO_NOTHING geçmiş (stok satırları, besleme) görünmez kalır; `_follow_status` "unit is deleted and would hold fish again" ile void'i de engelleyebilir. Ayrıca kaskad çocuklar `select_for_update` ile kilitlenmeden (yalnızca ana nesne kilitli, crud.py:770) bayat nesneyle `save()` edilir (tam satır yazımı, softdelete.py:179-181).
- Kanıt: softdelete.py:191 "Only the record itself returns, not what was deleted with it."; `soft_delete` -> `self.save()` (core/models.py:49-55) tüm alanları yazar.
- Öneri: Silme günlüğünden "birlikte silinenler" setini kaydet ve geri yüklemede önerisi sun; çocuklarda `save(update_fields=[...])` veya kilit.

### 18-5 | Düşük | Güven: yüksek - `check_stock` içindeki "fold sayısı = satır toplamı" kontrolü totolojik
- Dosyalar: farm/stock/integrity.py:115-121
- Açıklama: Aynı canlı satır kümesi hem fold'a hem `Sum('count_delta')`'ya giriyor; fold'un sayısı zaten `count_delta` toplamı. Kontrol fold'da sapma olmadıkça hiçbir şey yakalamaz ve `shares.update(fold(...))` bir batch'in hata vermesi durumunda (`broken`) atlanır. Gerçek riskleri (yetim satır: silinmiş birim/parti, void edilmiş operasyonun satırı) yakalamıyor.
- Kanıt: `share.count != row['fish']` (integrity.py:119); `ledger` filtresi `operation__is_deleted=False` (stock/read.py:33-35) ile aynı.
- Öneri: Bağımsız doğrulama ekle: `Tank` başına `unit_counts` ile `fold` birim toplamı; silinmiş Batch'e/Tank'a bağlı canlı satır; operasyonsuz satır (FK cascade zaten) için.

### 18-6 | Düşük | Güven: orta - Rapor içeriğinde yuvarlama: parti bazında yuvarlanan değerlerin toplamı birim/site toplamıyla uyuşmayabilir
- Dosyalar: reports/compute/biomass.py:76, 113-115; reports/compute/common.py:36-51
- Açıklama: Biyokütle her parti için `text(grams/1000, 1)` ile yarım-yukarı 0,1 kg'a yuvarlanıp ayrı satır olarak dosyalanıyor; birim/site toplamı raporu okuyan taraf tarafından satırlar toplanarak bulunursa gerçek toplamdan sapabilir. Hacim `water_volume_m3 or volume_m3` 3 ondalıktan 1'e yuvarlanıyor (`text(..., 1)`), oysa kapasite/yoğunluk 3 ondalıklı hacimle hesaplanıyor. Kayıp kg'ı `line.kilos` (ölçülen veya defter) karışık kaynaktan.
- Kanıt: `'biomass_kg': text(figure['grams'] / 1000, 1)` ve `'volume_m3': text(unit.water_volume_m3 or unit.volume_m3, 1)`.
- Öneri: Toplamı tam hassasiyetle hesaplayıp tek yuvarlama; hacimde `or` yerine `is not None` (0 hacmi yanlışlıkla sonraki alana düşmesin).

### 18-7 | Düşük | Güven: orta - `water_volume_m3 or volume_m3` iki yerde, `Coalesce(water_depth, depth)` üçüncü yerde: aynı kural üç kez yazılmış
- Dosyalar: farm/stock/read.py:267-269; reports/compute/biomass.py:76; farm/models/tank.py:380-384
- Açıklama: "Etkin hacim" kuralı DB'de `Coalesce(F('water_depth'), F('depth'))` ile (max_biomass), Python'da `or` ile (yoğunluk, rapor) ayrı yazılmış. `or` Decimal('0.000') değerini de "yok" sayar (örn. su derinliği 0 girilirse yoğunluk toplam hacme göre hesaplanır, max_biomass ise 0 hacme göre 0 olur) - iki gösterge birbirini tutmaz. water_depth için alt sınır CHECK'i (>0) var mı doğrulanmadı.
- Kanıt: bkz. dosya:satırlar.
- Öneri: Tek yerde `effective_volume_m3` GeneratedField veya özellik; `is not None` kullan.

### 18-8 | Düşük | Güven: yüksek - Site ve System kapasite alanları elle giriliyor, hiçbir yerde türetilmiş Tank toplamıyla karşılaştırılmıyor; Site alanlarında negatif değer CHECK'i yok
- Dosyalar: farm/models/site.py:100-104, 129-190; farm/models/system.py:58-66, 77-84; farm/models/tank.py:370-384; templates/farm/system_list.html:45-46
- Açıklama: `System.total_volume_m3`/`max_biomass_kg` ve `Site.water_capacity_m3`/`max_biomass_kg` girilen değerler; Tank'ın hacmi/max biyokütlesi ise DB'de türetiliyor. Hiçbir okuyucu bunları karşılaştırmıyor (grep: yalnızca liste şablonu gösteriyor) - çift kaynaklı doğruluk, zamanla çelişir. Üstelik System'de `>= 0` CHECK'i varken Site'ta `area_m2`, `water_capacity_m3`, `max_biomass_kg` için hiçbir sınır (model validator veya CHECK) yok; negatif girilebilir.
- Kanıt: sites constraint listesinde bu alanlar için `chk_*` yok (site.py:129-190); `chk_systems_total_volume` yalnızca System'de.
- Öneri: Alanları kaldır/türet (Tank toplamı) veya "tavan vs kullanım" kontrolü ekle; Site alanlarına `>= 0` CHECK.

### 18-9 | Düşük | Güven: yüksek - İzin günleri okuma anında hesaplanıyor: çalışma günü ayarı/tatil sonradan değişince onaylı izinlerin maliyeti ve bakiyeler geriye dönük değişir
- Dosyalar: hr/leave.py:41-71; hr/forms/leave.py:94-102; hr/models/leave.py (LeaveRequest docstring)
- Açıklama: `leave_days` hiçbir yerde saklanmıyor; `SchedulingSettings.working_weekdays` veya `Holiday` eklenip silinince geçmiş/onaylı taleplerin "kullanılan gün"ü ve kalan hak değişir (örn. cumartesi çalışma günü yapılınca 2025 izinleri de yeniden fiyatlanır). Ayrıca `used()` mevcut taleplerin hepsini yeni talebin `site`'ı ile fiyatlandırıyor (hr/leave.py:56-64, forms/leave.py:92-97): çalışan site değiştirmişse önceki talepler yanlış site tatilleriyle hesaplanır.
- Kanıt: `charged_by_year(request.first_day, request.last_day, site)` içinde `SchedulingSettings.get().working_weekdays` anlık okunuyor (leave.py:43).
- Öneri: Onay anında `charged_days` ve kullanılan takvimin anlık kaydı (snapshot) ya da ayar değişiminde geriye dönük etki uyarısı.

### 18-10 | Düşük | Güven: orta - Rapor `scope` parmak izi: ledger dışı kaynaklar (su örnekleri) ve doğrulama komutu eksik
- Dosyalar: reports/compute/biomass.py:109-125; reports/compute/common.py:96-107; reports/integrity.py:30-48
- Açıklama: Biyokütle projeksiyonu su sıcaklıklarını okuyor ama parmak izi bunları içermiyor (kod yorumu da kabul ediyor). `check_reports` dosyalanmış raporun dayandığı kaynak sonradan void edilmiş mi (örn. kaçış operasyonu void) bakmıyor; yalnızca site eşleşmesi ve hash. Bildirilen kayıt ile mevcut defter ayrışabilir ve tarayıcı bunu raporlamaz.
- Kanıt: biyokütle `scope()` docstring'i "a past sample voided later is shown by the page's own comparison, not by this fingerprint".
- Öneri: `check_reports`'a "dosyalanmış rapor kaynağının parmak izi şimdiki ile aynı mı" bilgi satırı.

### 18-11 | Düşük | Güven: orta - `_number` ondalık metni float'a çeviriyor (JSON API çıktısı)
- Dosyalar: reports/exports.py:31-38
- Açıklama: İçerik "tam karşılaştırma için metin" ondalık olarak donduruluyor (common.text), fakat API JSON'unda `float(text)` ile sayıya çevriliyor; çok büyük değer/çok ondalıkta ikili kesirli sapma ve `int(value)==value` ayrımı (12.0 -> 12) tür tutarsızlığı doğurabilir. Mevcut alan genişlikleri için pratikte güvenli.
- Kanıt: `value = float(text); return int(value) if value == int(value) else value`.
- Öneri: `Decimal` ile JSON'a `Decimal` kodlayıcı veya sabit ondalık sayı.

### 18-12 | Düşük | Güven: yüksek - Duyarlılık uyuşmazlıkları: ağırlık/fiyat birimleri farklı ondalıklarla iki yerde
- Dosyalar: farm/models/stock.py:314-318 (avg_weight_g 4 ondalık), farm/models/feed.py:277-281 ve farm/models/feeding_protocol.py:151-154 (bant sınırları 2 ondalık), farm/models/feed.py:160 (`price_per_kg` 2 ondalık, >= 0.01) ve inventory/models.py:355 (`unit_cost` 4 ondalık)
- Açıklama: Balık ortalama ağırlığı 0,0001 g, besleme bandı sınırları 0,01 g; sınırdaki bir ortalama (örn. 5,0049 g) bandın "altında" kalır, davranış tutarlı ama belgelenmemiş. Aynı yemin fiyatı Feed.`price_per_kg` (kg başına) ve InventoryLine.`unit_cost` (birim başına) olarak iki kaynakta ve farklı duyarlılıkla; maliyet raporları hangisini kullanacağı belirsiz. `feed_suitability` CHECK'leri `max_weight_g` için `>=0.01` yazılmış ama alan null olabilir (NULL CHECK'i geçer): niyet ile kısıt uyumsuz.
- Kanıt: bkz. satırlar; `chk_feed_suitability_max_weight` (feed.py ~305).
- Öneri: Sözleşmeyi belgele; fiyat için tek kaynak; `max_weight_g` null ise açık kısıt.

### 18-13 | Düşük | Güven: orta - Besleme bandı "boşluksuz" kuralı yalnızca kaydetme anında; DB yalnızca çakışmayı engelliyor
- Dosyalar: farm/models/feeding_protocol.py:145-147, 177-185
- Açıklama: Docstring "bantlar boşluksuz buluşur (kaydedilirken kontrol)" ve "asla çakışmaz (veritabanı)" diyor; boşluk kontrolü DB'de yok. Bir boşluktaki ağırlık için ration bulunamazsa besleme/öngörü sessizce boş dönebilir. (Okuma yolunun boşluğu nasıl ele aldığı incelenmedi.)
- Kanıt: `excl_feeding_protocol_bands_overlap` tek DB kuralı; `uq_feeding_protocol_bands_start`.
- Öneri: Okuma yolunda boşluk testi veya bütünlük tarayıcısına kural.

### 18-14 | Bilgi | Güven: yüksek - Batch.input_date ile giriş operasyonu tarihi bilinçli çift kaynak; yalnızca tarayıcı denetliyor
- Dosyalar: farm/models/stock.py:174-176, 211; farm/stock/integrity.py:47-48; farm/stock/services.py:153
- Açıklama: `input_date` "listeler için tek değer" olarak Batch'te tutuluyor, aynı gün giriş operasyonunda da var; servis ikisini yazıyor, `correct_batch` bu alanı değiştirmiyor (BatchDetailsForm yalnızca year_class/provenance). Void edilip yeniden girişte ikisi birlikte yeni olur. Risk: admin (farm/admin.py:35 list_display) veya SQL ile tek taraflı değişiklik; yalnızca `check_stock` yakalar. Bilgi amaçlı.
- Kanıt: integrity.py:47-48 kuralı.
- Öneri: `input_date`'i operasyondan türeyen GeneratedField/annotation yap veya admin'de salt-okunur yap (admin.py'de readonly olduğu doğrulanmadı).

### 18-15 | Bilgi | Güven: orta - Çıkarım tabanlı değerler başka örneklerin varlığına bağlı: NH3/oksijen türevleri geriye dönük değişir
- Dosyalar: farm/water/read.py:300-348
- Açıklama: Örnekte tuzluluk yoksa son 30 günde başka örnekten alınıyor (`salinity_for`); ardından NH3/NH4/oksijen türetimi o tuzluluğa göre. Sonradan tuzluluk örneği eklenir/void edilirse eski örneğin gösterilen NH3'ü ve değerlendirmesi (limit aşımı) değişir. Türetilen değer saklanmadığından kasıtlı; ancak limit aşımı olaylarının geçmişte "değişen" sonuç vermesi denetim izini etkiler.
- Kanıt: `_ammonia`/`_oxygen` ve `_salinity_missing` (read.py:300-337).
- Öneri: Gerekirse olay anındaki sonuç kaydı; en azından belgelemek.

### 18-16 | Bilgi | Güven: orta - Envanter bütünlük tarayıcısı lot yetimlerini ve pasif konum varışlarını denetlemiyor
- Dosyalar: inventory/integrity.py:56-91; inventory/services.py:346-351
- Açıklama: Void edilen operasyonun tüm satırları gitmiş lotu servis soft-delete ediyor; ancak `problems()` "canlı satırı olmayan canlı lot" (el ile silme/bug ile oluşmuş yetim) kuralını içermiyor, pasif (`inactive`) konuma yeni giriş kuralını ve sayım satırlarının `lot.item` ile birimini de doğrulamıyor. `check_stock`'taki kadar kapsamlı değil.
- Kanıt: integrity.py'de `InventoryLot` için yalnızca numara/son kullanma kuralları (74-79).
- Öneri: "canlı lot, canlı satırı yok", "pasif konuma giriş", "sayım satırı kendi konumunda" kuralları.
