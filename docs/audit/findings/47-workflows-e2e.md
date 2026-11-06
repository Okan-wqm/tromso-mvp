# 47 - workflows-e2e: Uçtan uca iş akışları ve modüller arası tutarlılık denetimi

## Özet

Yemleme -> stok (depo), tedavi -> arınma -> hasat uyarısı, planlı hasat -> stok operasyonu -> düzenleyici rapor, deney -> yemleme atamaları gibi ana zincirler kodda büyük ölçüde sağlam kurulmuş: tek yazma yolu (`_commit`), sıralı kilitler (Batch -> Tank; item -> location), `voided` ile tek geri alma yolu, "okumada hesapla, saklama" ilkesi (arınma, depo kitabı) ve rapor parmak izi (`reports.compute.fingerprint`) ile geriye dönük değişikliği yakalama. Aşağıdaki bulgular bu zincirlerin kopuk veya tutarsız kalan uçlarıdır: modüller arası bağların hiç kurulmadığı yerler (messaging, hr, tasks, inventory<->health), servis katmanında olmayıp yalnız formda olan kurallar, planlanan ile gerçekleşenin doğrulanmaması ve yarım yaşam döngüleri (deney kapatma). Kritik veya yüksek önemde bulgu yok; en önemli konu tedavi->hasat arınmasının yalnızca "onaylanabilir uyarı" olmasıdır (owner kararı, belgelenmiş).

Kod ve veri değiştirilmedi; testler çalıştırılmadı (yalnız okuma).

## İncelenen alanlar

- `farm/stock/services.py` (`_commit`, `_handling`, `_fulfil`, `record_harvest`, `void`), `farm/handling/check.py`, `farm/handling/withdrawal.py`, `farm/health/withdrawal.py`, `farm/health/services.py`, `farm/health/notices.py`
- `farm/feeding/services.py`, `farm/feeding/read.py` (`last_fed_at`), `inventory/services.py`, `inventory/read.py`, `inventory/fold.py`, `inventory/models.py`, `inventory/forms.py`
- `reports/services.py`, `reports/due.py`, `reports/apps.py`, `reports/compute/notices.py`
- `tasks/services.py`, `hr/services.py`, `hr/leave.py`, `experiments/services.py`, `experiments/models.py`, `messaging/events.py`, `messaging/services.py`
- `config/views.py` (genel bakış), `monitoring/read.py` içe aktarmaları, modüller arası import haritası, README ilgili bölümleri
- Mevcut bulgu dosyaları (20, 23, 24, 25, 27) tekrar etmemek için başlık düzeyinde tarandı.

## İncelenmeyen alanlar

- Gerçek veritabanı üzerinde çalıştırma, test paketi çalıştırması, eşzamanlı yarış testleri
- Frontend (TypeScript) ve şablonların uçtan uca davranışı; yetki matrisi (`config/access.py`) ayrıntıları
- `reports/compute/*` hesaplarının doğruluğu, `monitoring` kart içerikleri, `knowledge` modülünün iç akışı
- Zaman serisi (TimescaleDB) tarafı ve su kalitesi -> arınma derece-gün hesabının sayısal doğruluğu (yalnız akış okundu)

## Bulgular

### 47-1 - Messaging modülü hiçbir iş akışına bağlı değil; bildirim zinciri yok
- Önem: düşük
- Güven: yüksek
- Dosyalar: `messaging/events.py:14`, `messaging/services.py:234-246`
- Açıklama: `message_posted` sinyalini gönderen kod var ama dinleyen yok; `messaging` başka hiçbir uygulamadan import edilmiyor ve kendisi de `farm/hr/tasks` vb. import etmiyor. Görev atanması, izin kararı, arınma bitişi, düşük stok, geciken rapor gibi olaylar kimseye mesaj/bildirim olarak gitmiyor; hepsi yalnız ilgili sayfa açılınca okunuyor.
- Kanıt: `grep -rn message_posted` yalnızca `messaging/` içinde ve testlerde; `grep -rn "from messaging"` dışarıdan sıfır sonuç. `messaging/events.py` docstring: "Nothing in the MVP listens".
- Öneri: Bilinçli MVP sınırı ise README'de "olay -> bildirim" akışlarının olmadığı açıkça yazılsın; ilk adım olarak görev atama ve izin kararı gibi olaylar için `on_commit` dinleyicisi tasarlansın.

### 47-2 - Tedavi -> hasat arınması yalnızca onaylanabilir uyarı; ikinci kişi/rol ayrımı yok
- Önem: orta
- Güven: yüksek
- Dosyalar: `farm/handling/check.py:50`, `farm/handling/check.py:318-330` (`require_acknowledged`), `farm/stock/services.py:200-210` (`_handling`), `README.md:1796`
- Açıklama: Arınma sürerken hasat, formdaki kutu işaretlenerek kaydedilebiliyor; engel yok ("owner decision"). Onay kaydı (`HandlingAcknowledgement`) ve kritik log tutuluyor, ancak hasat yetkisi olan her kullanıcı kendi başına onaylayabiliyor; "veteriner/yönetici onayı" gibi ikinci kontrol yok. Bilinmeyen sonlu arınma (`until=None`) da yalnız uyarı. Gıdaya giden balık için düzenleyici risk taşıyan akış.
- Kanıt: `_handling` -> `check.require_acknowledged(assessment, seen)`; uyarı varsa kutu parmak izi eşleşmesi yeterli. Başka bir kapı (rol, ikinci onay) kodda yok.
- Öneri: Owner kararı korunacaksa, arınma uyarısını aşmak için ayrı bir izin (örn. `farm.override_withdrawal`) ve/veya bilinmeyen-bitişli arınmada ikinci onay düşünülsün; aşılan hasatlar `check_withdrawal`/rapor ekranında listelensin.

### 47-3 - Depo (inventory) ile tedavi/ilaç arasında bağ yok; `issue(reason=treatment)` serbest kalan kayıt
- Önem: orta
- Güven: yüksek
- Dosyalar: `inventory/models.py:150-170`, `inventory/models.py:246-251`, `inventory/services.py:45-47`, `inventory/services.py:313-317`, `farm/health/services.py` (`record_treatment`)
- Açıklama: `InventoryItem` yalnız yem bağlayabiliyor (`CheckConstraint(feed__isnull=False)`); ilaç (`Medicine`) depoda yok. `IssueReason.TREATMENT` ile yapılan çıkış hiçbir `Treatment` kaydına referans vermiyor, `record_treatment` de depodan düşmüyor. Yani tedavi kaydı ile ilaç stoğu, lot/SKT izlenebilirliği ve arınma zinciri tamamen ayrı; "hangi ilaç lotu hangi tedavide" sorusu cevapsız. `LOT_REQUIRED = {MEDICINES}` ile ilaç lot kuralları ölü kod (23-9 ile ilişkili; burada akış boyutu).
- Kanıt: `chk_inventory_items_one_link` `Q(feed__isnull=False)`; `issue()` imzasında treatment alanı yok; README:1857 "medicine stock" taşınmamış olarak geçiyor.
- Öneri: README'de bu kopukluk "bilinen eksik" olarak işaretlensin; ilaç öğesi eklendiğinde `Treatment` <-> `InventoryLine` bağı (lot) tasarlansın.

### 47-4 - Depo servisi yemin durumunu/silinmişliğini doğrulamıyor; kural yalnız formda
- Önem: düşük
- Güven: orta
- Dosyalar: `inventory/services.py:71-82` (`item_for`), `inventory/services.py:271-285` (`receive`), `inventory/forms.py:208`, `farm/feeding/services.py:57-61`
- Açıklama: Yemleme servisi yemin aktif ve silinmemiş olmasını kendi içinde zorluyor; depo servisi (`receive`, `item_for`, `count` içindeki `found`) bunu yapmıyor, yalnız form `Feed.objects.filter(status=ACTIVE)` sunuyor. API/asistan gibi başka çağıranlar (modül docstring'i "later the API and the assistants call the same ones" diyor) pasif/silinmiş yeme depo öğesi ve teslimat açabilir. Sayımın "bulunan lot"u formda tüm yemleri sunuyor (23-18 ile ilişkili).
- Kanıt: `item_for` yalnız `InventoryItem.objects.filter(feed=feed).first()` / `create`; `_check_static` yem durumuna bakmıyor.
- Öneri: Kuralı `_check_static`/`item_for` içine taşı; form yalnız kolaylık olsun.

### 47-5 - Planlı hasat gerçekleşince tarih/kesimhane/taşıyıcı tutarlılığı denetlenmiyor; iki ayrı bildirim doğabilir
- Önem: orta
- Güven: orta
- Dosyalar: `farm/stock/services.py:213-239` (`_fulfil`), `reports/due.py:320-348` (`_slaughter`), `farm/models/harvest.py:248-300`
- Açıklama: `_fulfil` yalnız silinmiş/iptal/tamamlanmış, işlem türü ve (birim, parti) eşleşmesini kontrol ediyor. Planın `date`, `facility`, `transport`, `vessel` değerleri gerçekleşen hasat (`HarvestRecord`) ile karşılaştırılmıyor. `reports/due._slaughter` ise plan haftasını plan kesimhanesine, gerçek hasat haftasını `record.facility`ye yazıyor; ikisi farklıysa aynı hasat için iki ayrı "planlı kesim" bildirimi borçlanabilir ve plan "done" göründüğü halde plan kesimhanesi için hafta açık kalır.
- Kanıt: `_slaughter` plans döngüsü (`item.facility_id`, `item.date`) ve ayrı `HarvestRecord` döngüsü (`record.facility_id`, `record.operation.date`) `weeks` sözlüğünde farklı anahtarlar üretir; `_fulfil` içinde tarih/tesis karşılaştırması yok.
- Öneri: Gerçekleşen farklıysa kullanıcıya uyarı göster ve planı güncelle/yeniden bağla; ya da `_slaughter`'da planı yerine getirilmiş sayıp yalnız gerçek kayda dayan. Davranış kasıtlıysa belgelensin.

### 47-6 - Deney yaşam döngüsü yarım: RUNNING -> CLOSED geçişi için servis/arayüz yok
- Önem: düşük
- Güven: yüksek
- Dosyalar: `experiments/models.py:50-54`, `experiments/services.py:636-680` (`start`), `docs/experiments.md:15,51-52`
- Açıklama: `TRANSITIONS` RUNNING -> CLOSED'ı tanımlıyor ve DB tetikleyicisi kapalı deneyi donduruyor; ancak koda tek bir `Status.CLOSED` ataması yok (yalnızca `start` durumu değiştiriyor). Deney süresi bitse de "running" kalıyor; tank yerleştirmeleri `until_on` ile kendiliğinden bitse de sonuçlar kilitlenmiyor, `release_unit/replace_unit` hâlâ çağrılabiliyor. Belgede "lifecycle plan'ın işi" olarak yazılı, yani bilinen eksik.
- Kanıt: `grep -rn "Status.CLOSED\|\.status = " experiments` yalnız `services.py:669`.
- Öneri: Kapatma servisi (kilit, log, atamaları sonlandırma) planlansın; o zamana dek arayüz "running" deneyin süresi dolduğunu göstersin.

### 47-7 - İK izin/işten ayrılma bilgisi görev, deney ve yemleme akışlarına hiç yansımıyor
- Önem: düşük
- Güven: orta
- Dosyalar: `hr/leave.py:74-79` (`away_on`), `hr/services.py:91-109` (`leave_company`), `tasks/services.py:117-131`, `tasks/read.py:120-124`
- Açıklama: `hr.leave.away_on` ("başkalarının yalnız izinde olup olmadığını öğrenebileceği yerler için") üretim kodunda hiç çağrılmıyor (yalnız `hr/tests/test_leave.py`). `leave_company` çalışanın hesabını ve açık görev atamalarını değiştirmiyor; görevler izindeki/ayrılmış kişiye atanmış kalıyor, vardiya planı ile görev ataması ayrı dünyalar. Hesap pasifleştirmesi "platform yöneticisinin tercihi" (docstring), bu yüzden ayrılan kişi `readers()`'da kalıyor ve yeni seri görevleri alabiliyor (24-7, 25-11 ile ilişkili).
- Kanıt: `grep -rn away_on` yalnız tanım ve test; `leave_company` yalnız `left_on` ve placement hizalar.
- Öneri: Atama ekranında `away_on` ile "izinde" rozeti; `leave_company` sonrası açık görevler için uyarı listesi.

### 47-8 - Sitesiz üretim bölümündeki birimlerin yemlemesi depo kitabından sessizce düşmüyor
- Önem: orta
- Güven: yüksek
- Dosyalar: `inventory/read.py:59-65` (`_feeding`), `README.md:61,80` (site silinince departman sitesiz kalır)
- Açıklama: Depo, yemlemeyi `unit__production_department__site_id` ile siteye bağlıyor ve `site__isnull=False` filtresi koyuyor. README'ye göre bir site silinince üretim bölümleri ve birimleri sitesiz kalıyor, yemleme kayıtları ise duruyor. Bu kayıtlar ne depodan düşülüyor ne de "karşılanmamış besleme" olarak raporlanıyor; yani tüketim kaybolur ve stok fazla görünür.
- Kanıt: `FeedingRecord.objects.filter(feed_id__in=feed_ids, unit__production_department__site__isnull=False)`.
- Öneri: Sitesiz kayıtları ayrı bir "siteye bağlanmamış besleme" satırı olarak göster (veya site silmeyi, yemlemesi olan birimlerde engelle).

### 47-9 - Yemleme çekişi silo/besleyici bağını kullanmıyor: "silo X'i dolduran besleyici" yapılandırması etkisiz
- Önem: düşük
- Güven: yüksek
- Dosyalar: `inventory/fold.py:198-236` (`_feed`), `inventory/forms.py:44-82`, `farm/feeding/services.py:44-80`
- Açıklama: Depo lokasyonunun `feeder` alanı var (silo -> besleyici), yemleme kaydı da `feeder` taşıyabiliyor; ancak çekiş site genelindeki tüm kovalardan "ilk SKT'si dolan ilk çıkar" sırasıyla yapılıyor, `feeder` hiç kullanılmıyor. Yani yemleme -> stok zincirinde lokasyon düzeyinde doğruluk yok; birden çok silolu sitelerde "kitap" ile gerçek silo içeriği ayrışır. (23-15 ile aynı kök; burada uçtan uca etki: sayım farkları hep varyans olarak çıkar.)
- Kanıt: `_feed` yalnız `self.places[bucket[0]].site == site` filtresi kullanıyor.
- Öneri: Yemlemenin besleyicisi bir silo ile eşleşiyorsa o silodan önce çek; kararı README'de belgele.

### 47-10 - `reports` kaydedilmezse hastalık bildirimi "borç yok" gibi, refah bildirimi "hepsi borç" gibi davranıyor (kapanış yönü tutarsız)
- Önem: bilgi
- Güven: orta
- Dosyalar: `reports/due.py:365-396`, `farm/health/notices.py:44-62`, `reports/apps.py:15-17`
- Açıklama: `notices.told()` sağlayıcı yokken `None` ("kontrol edilmedi") döner. `_diseases` `notices.pending(events) or []` ile bunu "bekleyen yok" sayar; `_unexplained` ise `notices.told(events) or {}` ile "hiçbiri bildirilmemiş" sayar. Sağlayıcı `reports.ready()` içinde kayıtlı olduğundan normalde sorun yok; ama sağlayıcı yokken iki akış zıt yönde sessizce başarısız olur. Arınma sağlayıcısı ise "kontrol edilmedi" notu üretiyor (doğru yaklaşım).
- Kanıt: yukarıdaki iki satır; karşılaştırma için `farm/handling/check.py:_withdrawal` açık not düşer.
- Öneri: İki yerde de `None`'u ayrı ele alıp "kontrol edilmedi" satırı üret.

### 47-11 - Arınma sağlayıcısı kayıt defterinde hata yalıtımı yok; deney çipi kaydı ise "fail open"
- Önem: bilgi
- Güven: orta
- Dosyalar: `farm/handling/withdrawal.py:36-46`, `README.md:2143` (placements kaydı)
- Açıklama: Placement çip sağlayıcıları kendi savepoint'inde, hata olursa sessizce çalışıyor; arınma sağlayıcısı (`blocks_of`) ise hata yalıtımsız: sağlayıcı istisna atarsa hasat sayfası/kaydı komple 500 verir. Güvenlik açısından "fail closed" savunulabilir; ama aynı mimari kalıbın (kayıt defteri) iki farklı hata politikası var ve belgede yalnız biri anlatılmış.
- Kanıt: `blocks_of` doğrudan `provider(units, day)` çağırıyor, try/except yok.
- Öneri: Politikayı bilinçli kararlaştır ve `farm/handling/withdrawal.py` docstring'ine yaz.

### 47-12 - Görevler iş akışı kayıtlarından bağımsız: tamamlamak ilgili kaydı doğrulamıyor, olaydan görev doğmuyor
- Önem: bilgi
- Güven: yüksek
- Dosyalar: `tasks/services.py:117-131`, `tasks/models.py` (`batch`, `unit`, `equipment` bağları)
- Açıklama: `complete` yalnız durum/kullanıcı/not yazıyor; "besle", "tedavi kaydet", "sayım yap" gibi görevler ilgili yemleme/tedavi/sayım kaydıyla eşlenmiyor. Tersine, hiçbir modül görev üretmiyor (`Task(` yalnız `tasks/` içinde): arınma bitişi, SKT yaklaşan lot, geciken rapor, düşük stok görev/uyarı olarak akmıyor.
- Kanıt: `grep -rn "Task(\|Task.objects.create" ` `tasks/` dışında sonuç yok; `complete` içinde başka modüle erişim yok.
- Öneri: Kasıtlı basitlik ise belgelensin; değilse olay -> görev köprüsü (örn. arınma bitişi, SKT) planlansın.

### 47-13 - Ana sayfalarda depo (düşük stok/SKT/kapsama günü) ve arınma altındaki birim özeti yok; modüller arası risk sinyalleri dağınık
- Önem: bilgi
- Güven: orta
- Dosyalar: `config/views.py:34-50`, `monitoring/read.py:56-77`, `inventory/read.py` (`overview`)
- Açıklama: Üretim genel bakışı stok, yemleme, su ve görev kutucuklarını gösteriyor; depo uyarıları (düşük stok, SKT, karşılanmamış besleme, kapsama günü) yalnız Depo sayfasında. `monitoring` `inventory` import etmiyor. Besleme tüketiminin stok kapsama günü ile ilişkisi (yemleme -> stok) bu yüzden operatörün günlük ekranında görünmez; arınma için ise birim satırında rozet var (iyi).
- Kanıt: `config/views.py` yalnız `feeding_tiles`, `overview_tiles`(stock), `water_tiles`, `task_tiles`; `grep inventory monitoring/*.py` sonuç yok.
- Öneri: Depo uyarılarından en az "karşılanmamış besleme" ve "düşük stok" üretim genel bakışına kutucuk olarak eklenebilir.

## Olumlu gözlemler (bulgu değil)

- Kilit sırası modüller arasında tutarlı: stok `Batch -> Tank`, deney başlatma aynı sırayı izliyor, tedavi `Tank` kilitliyor (hasatla serileşiyor), depo `item -> location`; yemleme depoyu kilitlemiyor (kitap okumada hesaplanıyor).
- Filed raporlar kaynak kayıt iptal/değişince `compute.fingerprint` ile yakalanıyor (`reports/due.py:no_longer_match`, `reports/compute/notices.py:65`); iptal edilen hasat/kaçış `LiveOperations` yöneticileriyle due listesinden düşüyor.
- Arınma "saklanmıyor, okumada hesaplanıyor": tedavi iptali/sıcaklık düzeltmesi/geriye dönük transfer anında yansıyor.
