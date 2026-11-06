# 20 - İş mantığı: sağlık (biz-health) denetim bulguları

## Özet

Kapsam: tedaviler (`Treatment`), sağlık olayları (`HealthEvent`), deniz biti sayımları (`LiceCount`), ilaç arınma süresi
(`MedicineWithdrawal`, `farm/health/withdrawal.py`), arınma/oruç (purging, `farm/handling/fasting.py`) ve handling
kuralı uyarıları (`farm/handling/check.py`).

Genel kanaat: çekirdek mantık (arınma süresinin okuma anında saklanmadan hesaplanması, gün/derece-gün, güvenlik marjı,
türe göre satır çözümü, bilinmeyen sonun "uyarı" sayılması, lakselusforskriften § 8 limitleri ve Vedlegg 1 nokta 6
ortalaması) kodda tutarlı ve testle kapsanmış. Kritik veya yüksek önem derecesinde bir bulgu yok. Bulgular ağırlıkla
orta/düşük: (a) sağlık sayfasının "site ortalaması"nın süzgeçle yanıltıcı hale gelmesi, (b) ilaç türü ile tedavi nedeni
arasında bağ olmaması nedeniyle haftalık bit raporundan tedavinin düşebilmesi, (c) geriye dönük girilen tedavinin
zaten yapılmış hasatla çakışmasının yakalanmaması, (d) arınma süresinin değişebilen referans verilerden anlık
hesaplanıp anlık görüntüsünün tutulmaması, (e) kilitleme ve 31 günlük pencere kaynaklı küçük tutarsızlıklar.

Not: Testler çalıştırılmadı (ortamda PostgreSQL yanıt vermiyor: `pg_isready` "no response"). Tüm bulgular kod okuma ile
doğrulandı; kod ve veri değiştirilmedi.

## İncelenen alanlar

- `farm/models/health.py` (Medicine, MedicineWithdrawal, Treatment, HealthEvent, LiceCount ve kısıtlar)
- `farm/health/` (`withdrawal.py`, `services.py`, `read.py`, `lice.py`, `diseases.py`, `notices.py`, `views.py`)
- `farm/handling/` (`check.py`, `fasting.py`, `withdrawal.py`) ve `farm/models/handling.py`
- `farm/water/degree_days.py` (derece-gün için sıcaklık kaynağı), `farm/forms/health.py`,
  `farm/resources/medicine.py`, `farm/templatetags/health.py`, `farm/management/commands/check_withdrawal.py`
- `farm/stock/services.py` (harvest/transfer/delivery handling bağlantısı, `voided`), `farm/stock/dates.py` (`check_date`)
- `reports/compute/lice.py`, `reports/due.py` (hastalık/ölüm bildirimleri), `reports/periods.py`
- `farm/migrations/0017` ve `0021` (başlangıç kuralları, arınma verisi göçü), `docs/regulatory-reports.md` ilgili bölümler,
  `config/access.py` (izin alanları)
- Test kapsamı: `farm/tests/test_health.py` test adları gözden geçirildi

## İncelenmeyen alanlar

- Testlerin çalıştırılması (veritabanı yok).
- `farm/harvest/` plan sayfaları, `monitoring/` kartları ve `tasks/`, `messaging/` içindeki sağlık göstergeleri yalnızca
  grep düzeyinde tarandı.
- Şablonlar (`templates/farm/*.html`) yalnızca `lice_list.html` ilgili satırlar kadar.
- Yetkilendirme ayrıntıları ve denetim günlüğü (RowList üzerinden MedicineWithdrawal değişikliklerinin günlüğe nasıl
  yazıldığı) derinlemesine doğrulanmadı.
- Yönetmelik metinlerinin (lakselusforskriften, dyrehelseforskriften) Lovdata ile yeniden doğrulanması yapılmadı; kod
  içindeki yorumlara güvenildi.

## Bulgular

### 20-1 - Deniz biti sayfasında süzgeç "site ortalaması"nı ve limit aşımını bozuyor
- Önem: orta
- Güven: yüksek
- Dosyalar: `farm/health/views.py:257-285`, `farm/health/read.py:422-437`, `templates/farm/lice_list.html:51-56`
- Açıklama: `lice_counts` görünümü, `site/unit/from/to` süzgeçleriyle daraltılmış sayım kümesini doğrudan
  `read.lice_weeks(counts)` fonksiyonuna verir. `LiceWeek.average` bir sitenin ortalamasını "sayımı olan birimlerin
  ortalamalarının ortalaması" olarak hesapladığı için, bir birime (veya tarih aralığına) süzülmüş sayfa tek bir kafesin
  değerini "site ortalaması" ve "Limitin üzerinde" rozeti olarak gösterir. Süzgeç tek kafesi seçtiğinde site
  limitinin aşıldığı gizlenebilir veya olmayan bir aşım gösterilebilir.
- Kanıt: `views.py:285` `weeks = read.lice_weeks(counts)[:LICE_WEEKS]` ve `_filtered_counts` (257-278) `counts`
  üzerinde `unit` ve `date` süzgeci uygular; `read.py:425-434` yalnızca verilen sayımlardan hafta kurar.
- Öneri: Haftalık site ortalamasını süzgeçsiz (yalnızca site) sayım kümesinden hesapla; süzgeç yalnızca alttaki sayım
  listesini daraltsın.

### 20-2 - İlaç türü ile tedavi nedeni bağlı değil: bit ilacıyla girilen tedavi haftalık bit raporundan düşebilir
- Önem: orta
- Güven: yüksek
- Dosyalar: `farm/health/services.py:97-116`, `reports/compute/lice.py:44-49`, `farm/models/health.py:340`
- Açıklama: Haftalık Mattilsynet bit raporu yalnızca `reason=SEA_LICE` olan tedavileri alır. `_check_medicine` ise
  ilacın `kind` (örn. `LICE`) değerini tedavi `reason` ile eşlemez; yalnızca aşı/aşılama ve uygulama yöntemi
  kontrol edilir. Bir bit ilacı `reason=PARASITES` veya `OTHER` ile girilirse tedavi raporda yer almaz, yasal bildirim
  eksik kalır; tersine antibakteriyel ilaç `SEA_LICE` nedeniyle girilirse raporda "etken madde yok" sorunu çıkar.
  Termal/mekanik/tatlı su yöntemlerinde de neden `SEA_LICE` seçilmezse aynı düşme olur.
- Kanıt: `lice.py:46` `Treatment.objects.filter(reason=TreatmentReason.SEA_LICE, ...)`; `services.py:115` yalnızca
  `medicine.is_vaccine != (reason == VACCINATION)` kontrolü var.
- Öneri: `Medicine.kind == LICE` ise nedeni `SEA_LICE` zorunlu kıl (veya en azından uyarı ver); rapor tarafında bit
  ilacı kullanan ama nedeni farklı tedaviler için "rapora girmedi" uyarısı üret.

### 20-3 - Geriye dönük girilen tedavi, zaten yapılmış hasatla çakışmayı yakalamıyor
- Önem: orta
- Güven: orta
- Dosyalar: `farm/health/services.py:182-196`, `farm/health/withdrawal.py:277-304`, `farm/handling/check.py:236-245`
- Açıklama: Arınma denetimi yalnızca hasat kaydı sırasında çalışır (`WITHDRAWAL_KIND = HARVEST`). Tedavi kaydı
  geriye dönük (31 güne kadar) girilebilir ve yalnızca başlangıç gününde balık olması aranır. Aynı partinin tedavi
  gününden sonra ama kayıttan önce hasat edilmiş olması (yani ilaçlı balığın yiyeceğe gitmiş olması) bildirilmez;
  tedavi kaydı sessizce başarılı olur ve gıda güvenliği ihlali hiçbir ekranda işaretlenmez. Stok servisi ters yönü
  (tedaviyi boşta bırakacak stok işlemi) reddediyor, bu yönün karşılığı yok.
- Kanıt: `services.py:192-194` yalnızca `_has_fish(unit, start_date, 'treatment')`; `withdrawal.py:155`
  `holds_on(day)` yalnızca sorulan gün için çalışır; hasat sonrası tarama yok.
- Öneri: Tedavi kaydında, tedavi penceresi ile arınma süresi içinde parti için kayıtlı hasat olup olmadığını denetle ve
  kritik uyarı/onay iste; ya da `check_withdrawal` benzeri bir rapor ekle.

### 20-4 - Arınma süresi değişebilen referans verilerden anlık hesaplanıyor; tedaviye anlık görüntü yok
- Önem: orta
- Güven: orta
- Dosyalar: `farm/models/health.py:202-215`, `farm/health/withdrawal.py:68-85,218-238`, `farm/models/species.py:118-121`,
  `farm/forms/health.py:96-152`
- Açıklama: Tasarım gereği hiçbir şey saklanmıyor (`HLT-02` düzeltmesi); ancak bir tedavi kaydı, o günkü ilaç
  `MedicineWithdrawal` satırı, `safety_margin_pct` veya türün `withdrawal_temperature_c` değerinin kopyasını tutmaz.
  İlacın arınma satırı düzenlenir/silinirse (satır listesi toptan değiştirilir, `MedicineWithdrawal` modelinde güncelleme
  ve soft-delete sütunu yok) devam eden ve geçmiş tüm tedavilerin arınma bitişi geriye dönük değişir; satır silinirse
  süre "bilinmiyor"a döner, marj/gün 0 yapılırsa süre kısalır. Hasat onay kaydı (`HandlingAcknowledgement`) yalnızca
  hasat anında gösterileni saklar; tedavi anındaki kural saklanmaz. Denetimde "o gün hangi arınma kuralı geçerliydi"
  sorusu cevaplanamaz. Değişikliklerin denetim günlüğüne `RowList` üzerinden yazıldığı bu incelemede doğrulanmadı.
- Kanıt: `models/health.py:208-211` ("no update or soft-delete columns"), `withdrawal.py:218-238` kuralı her okumada
  `MedicineWithdrawal.objects` üzerinden çözer.
- Öneri: Tedavi kaydında kullanılan kuralın (gün, derece-gün, marj, tür, varsayılan sıcaklık) özetini saklamayı veya
  kural değişikliklerini versiyonlamayı değerlendir; ilaç arınma satırı değişiklikleri için ayrı yetki ve kritik günlük.

### 20-5 - `change_last_day` ve `void_treatment` birimleri kilitlemiyor; hasatla yarış mümkün
- Önem: düşük
- Güven: düşük
- Dosyalar: `farm/health/services.py:175,218-252`, `farm/stock/services.py:134-150`
- Açıklama: Modül belgesi "tedavi ve hasat birimi kilitleyerek sırayla çalışır" der; `record_treatment` birimleri
  `locked(Tank, ...)` ile kilitler, fakat `change_last_day` yalnızca tedavi satırını `select_for_update`, `void_treatment`
  da yalnızca tedaviyi kilitler. Eşzamanlı bir hasat, kilitli birimlerle uyarı hesaplarken eski (kısa) `end_date`'i
  okuyabilir; son gün uzatılıyorsa uyarı üretilmeden hasat tamamlanabilir.
- Kanıt: `services.py:223` `Treatment.all_objects.select_for_update(of=('self',))`; `locked(Tank` yalnızca 175 ve 260
  satırlarında (tedavi kaydı ve sayım kaydı).
- Öneri: Son gün değişikliğinde ve iptalde de ilgili birimleri (ve partileri) hasatla aynı sırayla kilitle.

### 20-6 - 31 günden eski tedavi iptal edilemiyor; arınma sürüyorken yanlış kayıt silinemez
- Önem: düşük
- Güven: orta
- Dosyalar: `farm/stock/services.py:498-512`, `farm/health/services.py:245-252`, `farm/templatetags/health.py:68-72`,
  `config/settings.py:217`
- Açıklama: `voided` kaydı `entry.date` (tedavide `start_date`) ile `site_earliest` karşılaştırır; 31 günden eski
  tedavi "Operations older than 31 days cannot be voided" ile reddedilir. Derece-gün cinsinden arınma süresi soğuk
  suda haftalarca sürebilir ve son gün planlanan 28 güne kadar ileri olabilir; bu durumda yanlış girilmiş ama hâlâ
  hasadı engelleyen bir tedavi iptal edilemez. `change_last_day` de hem eski hem yeni son gün pencereden eskiyse
  reddeder.
- Kanıt: `services.py:509-512`, `templatetags/health.py:72` `record.date >= earliest(unit)`.
- Öneri: Arınması hâlâ süren tedavilerde pencere kontrolünü bitiş gününe göre yap veya yetkili bir istisna yolu tanımla.

### 20-7 - Canlı balık teslimi (delivery) sırasında arınma uyarısı yok; bilgi müşteriye aktarılmıyor
- Önem: düşük
- Güven: orta
- Dosyalar: `farm/handling/check.py:101-103,201-206`, `farm/stock/services.py:728-739`, `farm/models/handling.py:205-210`,
  `README.md:519-520`
- Açıklama: Arınma uyarısı yalnızca `HARVEST` için çalışır; `DELIVERY` (şirket dışına canlı balık, "smolt satışı" dahil)
  yalnızca oruç denetimi alır. Belgelenmiş bir tasarım kararı, ancak teslim edilen balığın alıcı tarafından
  yiyecek amaçlı kesilebileceği ve arınma süresindeki partinin sistemden çıkıp izlenemez hale geldiği durumda hiçbir
  uyarı/not yok.
- Kanıt: `check.py:103` `WITHDRAWAL_KIND = HandlingKind.HARVEST`; `check.py:202-203` yalnızca bu tür için
  `_withdrawal`.
- Öneri: Teslimde arınma altındaki partiler için en azından bilgilendirici not (uyarı değil) göster ve teslim
  kaydına arınma bitiş tarihini yaz.

### 20-8 - Çok birimli tedavide handling onayı birim bilgisi taşımıyor
- Önem: düşük
- Güven: yüksek
- Dosyalar: `farm/models/handling.py:305-353`, `farm/handling/check.py:395-413`, `farm/health/services.py:204-207`
- Açıklama: Çok birimli bir tedavide her birim için ayrı oruç uyarısı üretilir ve her biri ayrı
  `HandlingAcknowledgement` olarak yazılır; ancak satırda birim (unit) sütunu yoktur. Hangi birimin yetersiz oruç
  uyarısının onaylandığı sonradan ayırt edilemez (yalnızca `rule`, saatler). `uq_handling_acknowledgements_one_fast`
  yalnızca `operation` için tanımlı olduğundan tedavide birden fazla "fasting" satırı mümkündür (bilinçli), ama
  yinelenen veya eksik satır kontrolü yoktur.
- Kanıt: `models/handling.py:314-331` alan listesi (unit yok); `services.py:205-207` her uyarılı değerlendirme için
  `check.acknowledge`.
- Öneri: Onay satırına `unit` FK'si ekle ve tedavi için (treatment, unit, warning) tekilliği tanımla.

### 20-9 - Sağlık olayı kuralları yalnızca formda; servis kapalı veya ileri tarihli olayı kabul ediyor
- Önem: düşük
- Güven: orta
- Dosyalar: `farm/health/services.py:119-126`, `farm/forms/health.py:269-273`, `farm/models/health.py:460-531`
- Açıklama: Tedavi formu yalnızca açık (`closed_on` boş) olayları listeler, ancak `_check_event` kapalı olayı
  reddetmez (yalnızca silinmiş, site ve tarih). Doğrudan servis çağrısı veya eski form ile kapalı olaya tedavi
  bağlanabilir. Ayrıca `_check_event` olay tarihi <= tedavi başlangıcı kuralını yalnızca kayıt anında uygular;
  olay sonradan düzenlenip tarihi ileri alınırsa kural sessizce bozulur. `HealthEvent.units` için modelde "birim
  olayın sitesine ait" kuralı yok, yalnızca formun queryset'i kısıtlar.
- Kanıt: `services.py:124` yalnızca `event.date > day`; `forms/health.py:272` `closed_on__isnull=True`.
- Öneri: Kural tek yerde (servis) toplansın; olay düzenlemesi bağlı tedaviler varken tarihi ileri almayı reddetsin.

### 20-10 - Bit sayımı girişinde asgari örneklem ve makullük kontrolü yok
- Önem: düşük
- Güven: yüksek
- Dosyalar: `farm/health/services.py:256-276`, `farm/models/health.py:578-582,597-602`, `farm/forms/health.py:341`
- Açıklama: Vedlegg 1 gereği kafes başına en az 10 (bahar haftalarında 20) balık sayılmalıdır; bu yalnızca form
  yardım metninde geçer ve `LiceWeek.small_samples`/rapor uyarısında kullanılır. Kayıt anında hiçbir uyarı yoktur;
  `fish_counted` alt sınırı 1'dir. Bit sayıları için üst sınır 1.000.000'dir (1000 balıkta fiziksel olarak makul
  değil) ve bir aşama sayısının örneklem büyüklüğüne oranı doğrulanmaz; bir sıfır fazlası yazım hatası bir siteyi
  limit aşımına sokabilir.
- Kanıt: `models/health.py:578-582` (`MinValueValidator(1)`, `MAX_LICE`), servis içinde minimum örneklem kontrolü yok.
- Öneri: Kayıt anında `lice.minimum_fish(area, week)` altı için uyarı ver; kafes başına ortalama olağandışı yüksekse
  onay iste.

### 20-11 - Bit sayfasında ve tedavi listesinde tüm kayıtlar bellekte işleniyor
- Önem: düşük
- Güven: yüksek
- Dosyalar: `farm/health/read.py:422-437`, `farm/health/views.py:143-150`, `farm/health/views.py:285`
- Açıklama: `lice_weeks` sorgu kümesinin tamamını döngüyle okur, sonra `[:12]` ile keser; yıllar içinde sayım sayısı
  arttıkça her sayfa açılışı O(tüm sayımlar) olur. `show=withdrawal` veya parti süzgeci, tüm aday tedavileri
  belleğe `list(treatments)` ile alıp `Reader` kurar.
- Kanıt: `read.py:425-428` `for count in counts.filter(is_deleted=False)...order_by(...)`; `views.py:143`.
- Öneri: Hafta sayısını veritabanında sınırla (tarih alt sınırı) ve `LICE_WEEKS` kadar haftayı sorgula.

### 20-12 - "N of M units with fish now" etiketi geçmiş haftalara güncel stokla uygulanıyor
- Önem: bilgi
- Güven: yüksek
- Dosyalar: `farm/health/views.py:286-288`, `templates/farm/lice_list.html:56`
- Açıklama: `week.stocked` her hafta için bugünkü stoklu birim sayısıdır. Etiket "units with fish now" dediği için
  yanıltıcı değil, ancak geçmiş bir hafta için "3 of 4" göstermek o haftanın kapsama durumunu yansıtmaz (kapsama
  hesabı yalnızca rapor modülünde `_coverage` ile doğru yapılıyor).
- Kanıt: `views.py:286` `stocked = read.stocked_by_site(_units_with_fish(production=True))` her hafta için aynı.
- Öneri: Geçmiş haftalar için etiketi gizle veya o haftanın stok durumunu kullan.

### 20-13 - Lice limit bölgesi (`lice_area`) isteğe bağlı ve konumla doğrulanmıyor
- Önem: bilgi
- Güven: orta
- Dosyalar: `farm/models/site.py:96,176-177`, `farm/health/lice.py:404-416`, `farm/forms/site.py:60`
- Açıklama: Boş bırakılan bölge, 16-26. haftalar için 0,2 limit ve 14-26. haftalar için 20 balık gibi kasıtlı
  katı bir varsayım uygular (sayfa "Area not set" der). Bölge, sitenin `region`/`latitude` bilgisiyle çapraz
  kontrol edilmez; Tromsø/Troms bir site yanlışlıkla "south" seçilirse 21-26. haftalarda limit 0,5 olarak yanlış
  gevşek hesaplanır. Yönetmelik karşılaştırması: kod `>=` limit değerini aşım sayıyor ("færre enn"), uyumlu.
- Kanıt: `lice.py:394-395` `SPRING_WEEKS`/`LARGE_SAMPLE_WEEKS`, `site.py:96` `blank=True`.
- Öneri: Deniz sitesi için bölgeyi zorunlu veya enlemden öner/doğrula.

### 20-14 - Hastalık bildirimi yalnızca teşhisli olaydan veya 14 gün sonra açıklanamayan ölümden doğuyor
- Önem: bilgi
- Güven: orta
- Dosyalar: `reports/due.py:365-396`, `farm/health/notices.py:48-54`, `farm/models/health.py:434-531`
- Açıklama: Bildirim yükümlülüğü `diagnosis in NOTIFIABLE` (şüpheli veya doğrulanmış) olaylardan çıkar. Teşhis
  alanı boş, ancak belirtileri (`signs`) listelenmiş bir gözlem olayı ("şüphe") hiçbir bildirim satırı üretmez; yalnızca
  `MORTALITY` türünde, teşhissiz, kapatılmamış ve 14 gün geçmiş olay "açıklanamayan ölüm" bildirimi doğurur. Ayrıca
  `site.reports_from` boşsa bildirim sessizce atlanır (`due.py:373-374`, `due.py:392-393`). Hepsi belgelenmiş
  tasarım seçimi; yönetmelik (§ 7: şüphede hemen bildir) ile arasındaki boşluk kullanıcıya açıkça söylenmiyor.
- Kanıt: `due.py:368` `HealthEvent.objects.filter(diagnosis__in=diseases.NOTIFIABLE)`, `due.py:373`
  `event.site.reports_from is None` ise `continue`.
- Öneri: `reports_from` boşken yükümlülüğü "kurulmadı" satırı olarak göster; belirtili ama teşhissiz olay için
  veteriner değerlendirme hatırlatması düşün.

### 20-15 - İlaçlı yem örtüsü (covers) ilacı eşlemiyor
- Önem: bilgi
- Güven: orta
- Dosyalar: `farm/health/withdrawal.py:240-273`, `farm/models/feed.py` (yem modelinde ilaç alanı yok)
- Açıklama: İlaçlı yem beslemesi, aynı birimde ve günde herhangi bir `IN_FEED` tedavisi varsa "örtülmüş" sayılır; yemin
  hangi ilaçla hazırlandığı ve tedavinin ilacı ile aynı olup olmadığı kontrol edilmez. Farklı bir ilaçlı yemle
  beslenen birimde başka bir yem içi tedavi varsa, ilaçlı yemin arınması "bilinmiyor" yerine tedavinin (yanlış ilaç)
  arınmasına bağlanır.
- Kanıt: `withdrawal.py:263-267` `covers()` yalnızca yöntem, tarih ve birim; `grep -n medicin farm/models/feed.py`
  sonuç vermedi.
- Öneri: Yem kaydına ilaç bağlantısı ekle veya örtme kararını kullanıcıya açıkça göster.

### 20-16 - Derece-gün bilinmiyorsa gün cinsinden alt sınır dikkate alınmıyor
- Önem: bilgi
- Güven: yüksek
- Dosyalar: `farm/health/withdrawal.py:225-234`
- Açıklama: Hem gün hem derece-gün verilen kuralda derece-gün sonu hesaplanamazsa (`by_degrees is None`) sonuç
  tamamen "bilinmiyor" olur; kesin olarak bilinen gün tabanlı alt sınır (`by_days`) gösterilmez. Muhafazakâr ve
  güvenli, ancak kullanıcıya "en erken şu tarihten önce olmaz" bilgisi verilemiyor.
- Kanıt: `withdrawal.py:229-230` `if by_degrees is None: until, estimated = None, True`.
- Öneri: Bilinmeyen sonu korurken `by_days`'i ayrı bir "en erken" bilgisi olarak sakla.
