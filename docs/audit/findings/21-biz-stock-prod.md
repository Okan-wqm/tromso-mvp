# 21 - İş mantığı: stok ve üretim (biz-stock-prod)

Kapsam: production units (Tank), stok defteri (StockOperation/StockMovement), mortalite, cull, transfer/grading,
harvest, harvest plan, production plans, slaughter (planlı kesim raporu), escape/delivery.
Yöntem: yalnızca kod okuma (DB ayakta olmadığı için testler çalıştırılmadı).

## Özet

Stok çekirdeği (tek yazma yolu `_commit`, tarih sıralı `fold`, DB CHECK kısıtları, void ile geri alma, kilit sırası,
idempotency token) tutarlı ve iyi tasarlanmış; kritik/yüksek bir bütünlük açığı bulunmadı. Bulgular ağırlıkla
(a) iş kuralı boşlukları (mevcut stok devri, sayım düzeltme operasyonunun olmaması), (b) harvest/slaughter
raporlarındaki tutarsızlıklar (hafta kayması, round/gutted etiketi), (c) uyarı-ama-engelleme-yok kararları
(ilaç withdrawal), (d) metrik tanımları (survival/mortality), (e) servis katmanında savunma eksikleri ve ölçeklenme
notları üzerinde toplanıyor. Toplam 14 bulgu: 0 kritik, 0 yüksek, 6 orta, 6 düşük, 2 bilgi.

## İncelenen alanlar

- farm/models/stock.py, farm/models/harvest.py, farm/models/tank.py (durum makinesi, has_stock, kapasite)
- farm/stock/{services,fold,read,integrity,dates,views}.py, farm/forms/stock.py, farm/forms/harvest.py
- farm/harvest/{read,forecast,views}.py, farm/resources/harvest_plan.py
- farm/handling/{check,fasting,withdrawal}.py, farm/placements.py, farm/apps.py
- reports/compute/{slaughter,biomass,stock}.py (stok/harvest'ten beslenen kısımlar), reports/due.py (no_longer_match)
- config/access.py (stok/harvest izin alanları), config/settings.py (STOCK_BACKDATE_DAYS)
- docs/aquaculture-platform-bugs.md (STK bölümü), docs/regulatory-reports.md (ilgili satırlar)

## İncelenmeyen / sınırlı incelenen alanlar

- Testlerin çalıştırılması (PostgreSQL yanıt vermiyordu); eşzamanlılık davranışı yalnızca kod okumayla değerlendirildi.
- farm/feeding (biz-feeding alanı), farm/health, farm/water iç mantığı; yalnızca stok ile arayüzleri okundu.
- Frontend TypeScript, şablonlar (templates/farm/*), çeviri katalogları.
- Migration dosyaları ve DB'deki gerçek kısıtlar (modeldeki Meta.constraints esas alındı).
- reports/compute/{smolt,cleaner,lice}.py ve rapor gönderim akışı.

## Bulgular

### 21-1 - Eldeki (31 günden eski) balık stoğu sisteme doğru tarihle girilemiyor
- Önem: orta | Güven: orta
- Dosyalar: farm/stock/dates.py:61-73, farm/stock/services.py:249 (check_date), config/settings.py:215-217, farm/management/commands/
- Açıklama: Her operasyon (stocking dahil) `STOCK_BACKDATE_DAYS = 31` günden geriye tarihlenemiyor; bir `input` yeni Batch yarattığı için
  `Batch.input_date` de aynı pencereye hapsoluyor. Repoda toplu içe aktarma/açılış bakiyesi komutu yok (yalnızca check_stock ve
  check_withdrawal). Sisteme geçişte mevcut balık, gerçekte 31 günden eski olsa bile yakın bir tarihle girilmek zorunda.
- Kanıt: dates.py:66-73 `if day < site_earliest(site): raise ValidationError(...)`; settings.py:217 `STOCK_BACKDATE_DAYS = 31`; commands/ altında yalnızca
  check_stock.py ve check_withdrawal.py.
- Etki: yanlış stocking tarihi, "days stocked", survival, year_class/rapor dönemi ve beslenme/projeksiyon başlangıcı bozulur; Batch kodu
  (B-YYYY-) yanlış yıla düşer.
- Öneri: açılış bakiyesi için ayrı, loglanan ve yetkisi sınırlı bir "devir/import" operasyonu veya yönetim komutu tanımlayın; pencereyi
  yalnızca günlük operasyonlara uygulayın.

### 21-2 - İlaç withdrawal altındaki balığın harvest'i yalnızca uyarı ile geçiliyor, ayrı yetki yok
- Önem: orta | Güven: yüksek
- Dosyalar: farm/handling/check.py:26-29, farm/stock/services.py:35-41, farm/forms/stock.py:92-100, config/access.py:35
- Açıklama: Withdrawal ve açlık (fasting) uyarıları "owner decision: warn, never block" ile engellemiyor; `add_stockoperation` izni olan herkes
  kutuyu işaretleyerek harvest kaydedebiliyor. Harvest için ayrı bir izin/ikinci onay yok; mortalite kaydı ile aynı yetki (`farm.StockOperation`
  add). Onay satırı saklanıyor ve audit kaydı critical işaretleniyor (hafifletici).
- Kanıt: check.py:26 "Nothing is blocked (owner decision)"; access.py:35 `Area(_('Production units'), 'farm.StockOperation', actions=('view','add','delete'))`;
  forms/stock.py:97 "Fish under a medicine withdrawal must not go to food. Going on is stored ...".
- Etki: gıda güvenliği/düzenleyici risk; yanlışlıkla veya baskıyla yasaklı dönemde kesim kaydı oluşabilir (kayıt gerçekle birlikte
  slaughter raporlarını da besler).
- Öneri: withdrawal aşımı için ayrı bir izin (ör. `override_withdrawal`) veya ikinci kişi onayı; en azından uyarıyı veteriner/yönetici rolüne bağlayın.

### 21-3 - Planlı kesim (slaughter) raporu, planın haftasından/tesisinden farklı gerçekleşen harvest'i çift veya "plansız" sayıyor
- Önem: orta | Güven: yüksek
- Dosyalar: reports/compute/slaughter.py:37-63
- Açıklama: `items_of` yalnızca `date` değeri haftada olan plan kalemlerini alır; `unplanned_of` ise `planned` kümesini yalnızca o haftanın kalemlerinden
  kurar. Bir plan kalemi W haftasına tarihli iken harvest W+1'de gerçekleşirse (kalem `operation` ile bağlı), W raporunda plan kalemi, W+1 raporunda aynı
  operasyon "planlanmamış" olarak (ağırlıklı kg ile ve "late" uyarısıyla) yeniden listelenir. Aynı durum plan tesisi X, gerçek tesis Y olduğunda da olur.
- Kanıt: slaughter.py:48 `planned = {item.operation_id for item in items if item.operation_id}`; :50-52 harvest operasyonları `.exclude(pk__in=planned)`.
- Etki: aynı balık iki raporda (planlı + plansız) kg olarak görünür; gerçek harvest kg'ı ile plan kg'ı birbirine karışır.
- Öneri: `unplanned_of` için plan kalemlerinin tarihten bağımsız `operation_id` kümesini (tüm tesis/hafta) dışlayın; kayma durumunda uyarı üretin.

### 21-4 - Biyokütle raporu "gutted" seçilebiliyor ama sistem yalnızca round (canlı) ağırlık tutuyor
- Önem: orta | Güven: yüksek
- Dosyalar: reports/compute/biomass.py:88-89, reports/models.py:21-25, farm/forms/stock.py:544-548, docs/regulatory-reports.md (OUR-18)
- Açıklama: HarvestForm `measured_weight_kg` "live weight ... before bleeding and gutting" olarak girilir. Rapor `harvest_condition` için
  'gutted' seçildiğinde aynı round kg değerleri "slaughter_weight_kg" olarak 'gutted' etiketiyle yazılır; dönüştürme/uyarı yok.
- Kanıt: biomass.py:88-89 `'slaughter_weight_kg': text(line.kilos, 1), 'condition': condition or None`; models.py:24 `GUTTED = 'gutted'`.
- Etki: yanlış etiketli düzenleyici bildirim (gutted ağırlık round'dan ~%10-20 düşük olmalı).
- Öneri: 'gutted' seçimini, kesim sonucu (SlaughterResult) modellenene kadar engelleyin veya açık bir uyarı/dönüşüm katsayısı ekleyin.

### 21-5 - Sayım düzeltme (count correction) operasyonu yok; ilgili neden değerleri ve rapor eşlemesi ölü kod
- Önem: orta | Güven: yüksek
- Dosyalar: farm/models/stock.py (AdjustmentReason), farm/stock/integrity.py:154-158, farm/stock/services.py:713-725, reports/compute/biomass.py:28-33,
  docs/regulatory-reports.md:321,873
- Açıklama: Sayım düzeltmesi yalnızca `record_escape` (neden `escape`) ve harvest'in "unaccounted loss" satırı ile yazılıyor. `COUNT_CORRECTION` ve
  `OTHER` nedenleri için hiçbir giriş yolu yok; ayrıca integrity.py bir ADJUSTMENT operasyonunu escape kaydı yoksa "problem" sayıyor. Buna rağmen rapor
  belgesi/kodu "count corrections -> Tellefeil" eşlemesini ve "upward correction" durumunu tarif ediyor. Hatalı sayım (31 günden eski) void penceresi
  nedeniyle düzeltilemiyor; tek çıkış harvest sonunda "unaccounted loss".
- Kanıt: services.py:713-725 yalnızca `AdjustmentReason.ESCAPE`; integrity.py:155-156 "a count adjustment on its own is an escape"; biomass.py:98 `-(line.kilos or ZERO)` ve :28-33 eşleme.
- Etki: stok sayısı gerçeğinden sapınca (sayım hatası, sayım) düzeltme yolu yok; rapordaki "Tellefeil" kategorisi hiç dolmaz.
- Öneri: izin verilen bir sayım düzeltme operasyonu (neden, onay, log) ekleyin veya ölü nedenleri/eşlemeyi koddan ve dokümandan kaldırın.

### 21-6 - Void sırasında kapasite (max biyokütle) yeniden kontrol edilmiyor ve onay istenmiyor
- Önem: düşük | Güven: yüksek
- Dosyalar: farm/stock/services.py:742-760 (özellikle :753), :294-340
- Açıklama: `void` `_validate(set(batches), set(units), operation.date)` çağırır; `new_op_id`/`arriving` verilmediği için `grams_after` boş kalır ve
  `_over_capacity` `[]` döner; zaten dönen değer lambda tarafından yok sayılır. Bir çıkış (mortality/harvest/transfer_out) void edilince balık birime geri
  döner ve birim max biyokütleyi aşabilir, onay kaydı oluşmaz. Tür karışımı ise sonraki girişlerde yeniden doğrulanıyor (bu kısım güvenli).
- Kanıt: services.py:753 `check=lambda: _validate(...)`; :340 `return _over_capacity(grams_after, new_op_id)`; :343-345 `if not grams_after: return []`.
- Etki: kapasite aşımı sessizce oluşur; kapasite kuralı (owner decision Q4) yalnızca yeni varış için işler.
- Öneri: void'de geri dönen balık için aşımı uyarı/onay ile ele alın veya bunun bilinçli olduğunu belgeleyin.

### 21-7 - Survival/mortality yalnızca "birim içi kalış" bazında; transfer sonrası batch yaşam boyu mortalitesi ve transfer çıkışı yansımıyor
- Önem: orta | Güven: orta
- Dosyalar: farm/stock/fold.py:80-85,135-143,171-174, farm/stock/read.py:213-215,308-313
- Açıklama: `Share.fish_in` yalnızca varışlarla (input, transfer_in, up-adjustment) artar; transfer_out/harvest `fish_in`'i düşürmez. Kısmi transferden sonra
  kaynak birimde `mortality = deaths / fish_in` payda olarak ayrılan balığı da içerir (risk altındaki gerçek stok daha az). Hedef birimde ise
  `fish_in` yalnızca gelenler; kaynakta transferden önceki ölümler batch'in yaşam boyu oranına yansımaz. Birim boşalıp yeniden dolunca sayaçlar sıfırlanır.
  Bu, owner decision Q2'nin kapsamı içindedir ama "survival" etiketiyle yaşam boyu üretim performansı gibi okunabilir.
- Kanıt: fold.py:174 `share.fish_in += k` (yalnızca arrival dalı); :171 sıfırlama; read.py:309 `HUNDRED * (1 - Decimal(self.deaths) / self.fish_in)`.
- Etki: bölünmüş/transfer edilmiş batch'ler için mortalite/survival yanıltıcı; karşılaştırmalı performans raporlaması hatalı olabilir.
- Öneri: batch bazında (birimlerden bağımsız) kümülatif survival ekleyin ve birim metriğini "bu kalıştaki" olarak etiketleyin; payda için ortalama/başlangıç
  stoğu tanımını netleştirin.

### 21-8 - Harvest/tartım/ölü balık ağırlıkları için makullük (plausibility) kontrolü yok
- Önem: düşük | Güven: orta
- Dosyalar: farm/forms/stock.py:198-202,255-258,544-548, farm/harvest/read.py:31-36
- Açıklama: Harvest `measured_weight_kg` kitap ağırlığıyla veya makul adet başı ağırlıkla karşılaştırılmaz (yalnızca > 0). Fark yalnızca listede
  gösterilir. Benzer şekilde tartım ortalaması önceki ağırlığa/tahmine göre sınırlandırılmaz; sadece `_estimate` fark gösterir (kaydı engellemez).
  Besleme tarafında "gram yerine kilo" hatası için bir kontrol (FEEDING_ACK_PERCENT) varken stok tarafında yok.
- Kanıt: forms/stock.py:544-546 `min_value=Decimal('0.001')` dışında sınır yok; harvest/read.py:31-36 fark yalnızca hesaplanır.
- Etki: yazım hatası (örn. 10 g yerine 10 kg) kitap biyokütlesini ve sonraki yem/projeksiyonu bozar; harvest kg'ı raporlara gider.
- Öneri: kitaba göre belirli bir sapma eşiğinde (ör. +-30%) onay isteyin (ack mekanizması zaten var).

### 21-9 - Boşaltan grading, kaynak biyokütlesini ölçülen toplama sıfırlıyor; kitap ile ölçülen arasındaki fark deftere yazılmıyor
- Önem: bilgi | Güven: orta
- Dosyalar: farm/stock/fold.py:98-111, farm/stock/services.py:650-674
- Açıklama: GRADING operasyonunda ayrılan balık `k * weight` ile çıkar, son balık için bile (`weight is not None and op.kind == GRADING` dalı `k == share.count`
  dalından önce). Kaynakta kalan balık yoksa kitap gramı sıfırlanır ve çıkan biyokütle yalnızca ölçülen toplamdır; kitap ile ölçülen arasındaki fark
  (kayıp/artış) hiçbir satırda izlenmez (harvest'teki "book vs scale" farkı gibi gösterilmez).
- Kanıt: fold.py:98-99 `if weight is not None and line.op.kind == OperationKind.GRADING: out = k * weight`; :111 `share.grams = share.grams - out if share.count else ZERO`.
- Etki: biyokütle devamlılığı kırılır; fark raporlanmaz. Tasarım gereği ("grading is a weighing") olduğu için bilgi düzeyinde.
- Öneri: grading'de kitap-ölçülen farkını harvest'teki gibi gösterin.

### 21-10 - Servis katmanında girdi doğrulaması tutarsız; yalnızca formlar koruyor
- Önem: düşük | Güven: yüksek
- Dosyalar: farm/stock/services.py:581-587,596-604,607-621,634-647,677-704,707-710,726-739
- Açıklama: Modül başlığı servisi "tek yazma yolu" ilan eder, ancak sayı/ağırlık doğrulaması yalnızca `record_escape`/`record_delivery` içinde (`_positive`)
  yapılır. `record_mortality(count=0)` `count_delta=0` üretir ve `chk_stock_movements_sign` ihlaliyle IntegrityError (500) olur; `record_weighing(sample_count=0)`
  Decimal bölme hatası verir; `record_harvest(count<=0)`, `record_transfer`/`record_grading`/`record_input` için de aynı. Şu an yalnızca formlar çağırıyor (başka
  çağıran yok), dolayısıyla etki dolaylı.
- Kanıt: services.py:586 `Entry(unit, batch, MovementKind.MORTALITY, -count, ...)` doğrulamasız; :615 `sample_weight_kg * 1000 / sample_count`; :707-710 yalnızca escape/delivery için `_positive`.
- Etki: yeni bir çağıran (API, import, experiments) doğrulamayı atlarsa kullanıcı dostu hata yerine 500.
- Öneri: servis girişinde ortak `count >= 1`, `weight > 0` doğrulaması (ValidationError).

### 21-11 - Plan kalemi (HandlingPlanItem) ile gerçekleşen operasyon arasında planlanan adet/hedef birim doğrulanmıyor
- Önem: düşük | Güven: yüksek
- Dosyalar: farm/stock/services.py:213-239, farm/models/harvest.py:335-359
- Açıklama: `_fulfil` yalnızca tür, kaynak birim/batch, iptal/silinme ve "zaten yapıldı" durumlarını kontrol eder. Transport planında `destination_unit` gerçek
  transferin hedefleriyle karşılaştırılmaz; planlanan adet/kg ile gerçek arasında eşik yok; plan kalemi `clean()` `planned_count`'ı birimdeki balıkla sınırlamaz.
  Plan "done" olduğunda tarihi veya miktarı ne olursa olsun kapanır; DB'de "done iken iptal edilemez" kuralı yalnızca `clean()`'de (CHECK yok).
- Kanıt: services.py:230-231 yalnızca `(item.unit_id, item.batch_id) != (source.unit.pk, source.batch.pk)`; harvest.py:346-347 iptal+done kontrolü yalnızca model clean.
- Etki: planlanan ile gerçek sapma sessizce "Done" olarak görünür; planlı kesim raporu plan kg'ını kullanır (bkz. 21-3).
- Öneri: plan sapmasını (adet/kg/hedef) uyarı olarak gösterin ve `_add_actuals` çıktısını raporda karşılaştırın.

### 21-12 - Escape kaydı: recaptured doğrulanmıyor, geri yakalanan balık stoğa dönmüyor ve kayıt güncellenemiyor
- Önem: düşük | Güven: yüksek
- Dosyalar: farm/forms/stock.py:602-603, farm/models/stock.py (EscapeRecord), farm/stock/services.py:713-725
- Açıklama: `recaptured` yalnızca `min_value=0`; `count`'tan büyük olabilir. Kayıt "never edited"; sonradan geri yakalanan balık için güncelleme yok, ancak void + yeniden kayıt
  (31 gün penceresi içinde). Geri yakalanan balığı stoğa geri alacak operasyon yok (ör. sayım artışı `chk escape_removes` ve 21-5 nedeniyle mümkün değil).
- Kanıt: forms/stock.py:602 `recaptured = forms.IntegerField(..., min_value=0, required=False)`; models/stock.py EscapeRecord "never edited".
- Etki: Fiskeridirektoratet bildirimi için recaptured bilgisi eskir; stok gerçekten ayrılmış sayılır.
- Öneri: `recaptured <= count` doğrulaması ve ayrı bir güncelleme/geri alım operasyonu.

### 21-13 - Kapasite metni ve seçim etiketi tutarsız; max biyokütle boşsa kontrol sessizce atlanıyor
- Önem: bilgi | Güven: düşük
- Dosyalar: farm/forms/stock.py:53-57, farm/stock/views.py:322-329, farm/stock/services.py:350
- Açıklama: Onay kutusu "Stock above the max density" der, kontrol ise biyokütle (kg) üzerinden yapılır (`max_biomass_kg`). `unit.max_biomass_kg is not None` koşulu
  nedeniyle null ise aşım kontrolü atlanır; seçim listesi ise `unit.max_biomass_kg or 0` ile "0 kg max/free" yazar. `depth` zorunlu olduğundan null olasılığı
  düşük (şekil/ölçü eksikliğinde oluşabilir); doğrulanmadı.
- Kanıt: views.py:325 `number(unit.max_biomass_kg or 0)`; services.py:350 `if unit.max_biomass_kg is not None and kilos > unit.max_biomass_kg`.
- Etki: kullanıcıya yanıltıcı metin; olası sessiz kapasite atlaması.
- Öneri: etiketi "max biomass" olarak hizalayın ve max boşken açıkça uyarı verin.

### 21-14 - Stok okumaları her istekte tüm geçmiş defteri katlıyor (ölçeklenme riski)
- Önem: düşük | Güven: orta
- Dosyalar: farm/stock/read.py:33-48,59-62,327-335, farm/stock/services.py:294-340, farm/harvest/read.py:98-114, farm/harvest/views.py:96-120, farm/resources/harvest_plan.py:99-135
- Açıklama: `stock_of`, `share_on`, `_validate`, `moved_grams` ve harvest listesi, ilgili batch'lerin tüm satırlarını (`ledger`) belleğe alıp baştan katlar;
  her yazma ayrıca besleme yürüyüşünü ve sağlık kayıtlarını yeniden kurar. Harvest listesi sayfalamadan önce tüm filtrelenmiş satırlar için `moved_grams` çalıştırır.
  Plan listesi satır başına `check.in_force`/`check.earliest` (N+1) çağırır.
- Kanıt: read.py:33-48 `ledger` tüm satırlar; harvest/views.py:96-97 `rows = read.harvests(lines)` sonra `Paginator(rows, ...)`.
- Etki: yıllar süren veri ve çok birimle yavaşlama; her stok yazımı uzar (kilit süresi artar).
- Öneri: kapanan batch'ler için kontrol noktası/önbellek, harvest listesinde sayfa bazlı hesap ve plan satırlarında toplu sorgu.
