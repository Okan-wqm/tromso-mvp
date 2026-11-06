# 19 - İş mantığı: yemleme (protokoller, atamalar, meal board, kayıtlar, FCR hesapları, tutarsızlıklar)

## Özet
Yemleme alanı genel olarak titiz kurulmuş: kayıtlar düzenlenmiyor (iptal + yeniden giriş), yem payı batch'lere okuma anında stok defterinden dağıtılıyor, FCR/SFR/tahmini ağırlık saklanmıyor, protokol bantları ve atamalar için DB seviyesinde exclusion/check kısıtları var, tek yazma yolu (`farm/feeding/services.py`) tank kilidi + `entry_key` ile idempotent. Bulunan sorunlar çoğunlukla kenar durumlar ve kurallar arası tutarsızlıklardır: tek sıcaklık sütunlu tablonun fiilen ürün vermemesi (19-1), "%10 üstü onay" kuralının günlük toplamı değil tek kaydı kontrol etmesi (19-2) ve protokol SFR üst sınırıyla (15) çelişmesi (19-3), gün içinde tamamen ayrılan batch'in yeminin projeksiyonda kaybolması (19-4), geçmiş günlerin oran/tahmin değerlerinin sonradan girilen veriyle değişmesi ve bunun düzenleyici biyokütle raporuna sızması (19-6), geri yüklemede silinmiş yeme bağlı bantlar (19-8). Testler çalıştırılamadı (PostgreSQL bu ortamda yok); tüm bulgular kod okuyarak çıkarıldı.

## İncelenen alanlar
- `farm/models/feeding.py`, `farm/models/feeding_protocol.py`, `farm/models/feed.py` (bağlantılar, kısıtlar, `delete_blockers`)
- `farm/feeding/` altındaki tüm modüller: `fold.py`, `projection.py`, `ration.py`, `read.py`, `temperature.py`, `services.py`, `protocols.py`, `assignments.py`, `views.py`
- `farm/forms/feeding.py`, `farm/forms/feeding_protocol.py`, `farm/resources/feeding_protocol.py`
- Tüketiciler: `farm/harvest/forecast.py`, `reports/compute/biomass.py`, `inventory/read.py`, `farm/health/withdrawal.py` (tıbbi yem), `farm/handling/fasting.py` (açlık), `farm/stock/services.py` (`_validate` yetim yemleme kontrolü), `core/softdelete.py`, `core/admin.py`
- README.md "Operations › Feeding" bölümü ve `docs/aquaculture-platform-bugs.md` FDR/FP satırları ile kod karşılaştırması

## İncelenmeyen / sınırlı incelenen alanlar
- Testler çalıştırılmadı (PostgreSQL/TimescaleDB bağlantısı yok); eşzamanlılık ve exclusion kısıtı davranışları gerçek DB ile denenmedi.
- `farm/stock/fold.py` ve `farm/stock/read.py` (defter katlama) yalnızca `feeding/fold.py` kancaları üzerinden okundu.
- `experiments/` ve `monitoring/` içindeki yemleme tüketicileri yüzeysel tarandı (`experiments/design.py`, `read.py`); ayrıntılı denetim ilgili uzman alanlarına bırakıldı.
- Şablonlar (`templates/farm/feeding_*.html`, `meal_board.html`) ve TypeScript frontend incelenmedi.
- `farm/water/read.py` (`water_sources`, `Series`) sıcaklık kaynağı sıralaması varsayıldı, okunmadı.

## Bulgular

### 19-1 | Orta | Güven: yüksek
**Tek sıcaklık sütunlu besleme tablosu fiilen oran üretmiyor (yalnızca tam eşleşen sıcaklıkta)**
- Dosyalar: farm/feeding/ration.py:74-86, farm/forms/feeding_protocol.py (`parse_temperatures`)
- Açıklama: `parse_temperatures` en az bir sütunu kabul ediyor, ama `sfr_at` tek sütunlu tabloda sıcaklık sütundan farklıysa `None` (OUTSIDE_TABLE) dönüyor. Satır 86'daki "a table of one column" yorumu, tek sütunlu tablonun sabit oran verdiğini ima ediyor; oysa o satıra yalnızca `T == cells[0].temperature_c` iken ulaşılıyor. Sabit SFR'lı basit bir protokol tanımlayan kullanıcı, ölçülen sıcaklık (ör. 12.35) sütunla (12.0) tam eşit olmadıkça her gün "tablo dışı, ration yok" görür; projeksiyonda da üst sınır (cap) uygulanmaz, yem olduğu gibi büyüme sayılır.
- Kanıt: `if not cells or temperature_c < cells[0].temperature_c or temperature_c > cells[-1].temperature_c: return None` (ration.py:76); `for low, high in zip(cells, cells[1:])` tek hücrede boş döner; son satır yalnızca eşitlikte erişilebilir (ration.py:86). Form: "Give at least one temperature column." `farm/tests/test_protocols.py` içinde tek sütun testi yok.
- Öneri: Ya en az iki sütun zorunlu kılın (form + doğrulama mesajı), ya da tek sütunlu tabloyu sabit oran olarak okuyun; yorumu ve testi buna göre düzeltin.

### 19-2 | Orta | Güven: yüksek
**"%10 üstü günlük yem" onayı günlük toplamı değil tek kaydı kontrol ediyor**
- Dosyalar: farm/feeding/services.py:64-72, config/settings.py:221
- Açıklama: Hata mesajı "more than %(limit)s %% a day is unusual" diyor ve kural günlük oran olarak tanımlı; ama oran yalnızca bu kaydın `amount_kg` değeri / defter biyokütlesi olarak hesaplanıyor, o gün aynı ünitenin önceki kayıtları hesaba katılmıyor. Günde 5 kayıt x %4 = %20 hiçbir onay istemeden girilebilir; öte yandan tek seferde girilen %11 onay ister. Kural bu hâliyle asıl hedefi (gram yerine kilo yazma gibi hatalar) kısmen yakalar, ama gün içinde parçalı fazla yemlemeyi yakalamaz.
- Kanıt: `rate = 100 * amount_kg / book.biomass_kg` / `if rate > settings.FEEDING_ACK_PERCENT:` (services.py:64-65); aynı günün kayıtları sorgulanmıyor.
- Öneri: Oranı `bugünün mevcut kayıtları + yeni kayıt` toplamı üzerinden hesaplayın (kilitli ünite içinde), ya da mesajı "tek kayıt" olarak düzeltin.

### 19-3 | Düşük | Güven: yüksek
**Protokol SFR üst sınırı (15 %) ile yemleme onay eşiği (10 %) çelişiyor**
- Dosyalar: farm/models/feeding_protocol.py:44, config/settings.py:221, farm/feeding/services.py:64-72, farm/feeding/views.py (`next_meal`)
- Açıklama: Tablo hücreleri 15 %/gün'e kadar tanımlanabiliyor ("covers first-feeding fry"), ancak herhangi bir kayıt biyokütlenin %10'unu aşarsa kullanıcıdan onay kutusu isteniyor. %10 üstü SFR'li bir bantta (yavru) tüm gün tek öğün (`meals_per_day=1`) olduğunda board'daki "Record meal" önerilen miktarı doğrudan onay uyarısına çarpar; sistem kendi hesapladığı oranı "alışılmadık" diye reddeder. Eşik bant/tür bazlı değil, global.
- Kanıt: `MAX_SFR = 15` (feeding_protocol.py:44) ve `FEEDING_ACK_PERCENT = 10` (settings.py:221); `next_meal()` ration/meals miktarını formu doldurmak için kullanır, `ack` set etmez.
- Öneri: Eşiği protokolün o gün için hesaplanmış oranına (veya bant SFR'sine) göre ayarlayın ya da onay eşiğini en az `MAX_SFR`'a eşitleyin.

### 19-4 | Orta | Güven: orta
**Gün sonunda unit'te olmayan batch'in o günkü yemi tahmini ağırlığa ve hesaplanan rasyona yansımıyor**
- Dosyalar: farm/feeding/projection.py:341-350 (`Projector.day`), farm/feeding/fold.py:210-220 (`_allocate`), farm/feeding/projection.py:191 (`UnitDay.fed_kg`)
- Açıklama: Yem payı gün başındaki batch'lere dağıtılır (`_allocate`, `start`), ama `Projector.day` yalnızca gün SONUNDA ünitede sayısı > 0 olan paylar için döner (`if unit != unit_id or not share.count: continue`). Gün içinde tamamen başka üniteye transfer edilen (veya hasat edilen) batch gün başında yemlenmiş olsa bile bu yem o batch'in `Track`'ine büyüme olarak eklenmez; transfer edilen balıkların `moved` track'i yemden önce kopyalandığı için yem hiç kredilendirilmez. Sonuç: tahmini ağırlık düşük kalır, `UnitDay.fed_kg` (kayıt toplamı) o batch'in payını içerirken `calculated_kg` (yalnızca gün sonu share'leri) içermez; by-day sapma yüzdesi (deviation) şişer.
- Kanıt: `if unit != unit_id or not share.count: continue` (projection.py:341); `fed_kg` tüm üretim kayıtlarını toplar (projection.py:191-193); `_allocate` start-of-day biyokütle ile böler (fold.py:210-220).
- Öneri: Gün başı payı olan ama gün sonu sayısı 0 olan batch için de yemi kredilendirin (veya payı gün sonu mevcut balıklara/kaybolan track'e taşıyın) ve `fed_kg` ile `calculated_kg` aynı batch kümesini kullansın. Davranışı kapsayan bir test ekleyin.

### 19-5 | Düşük | Güven: yüksek
**Sıcaklık yoksa ya da açlık gününde yem sınırsız büyüme olarak kredilendiriyor (üst sınır tam da veri eksik olduğunda devre dışı)**
- Dosyalar: farm/feeding/projection.py:246-248, README.md (Estimated weight bölümü), farm/feeding/ration.py:223-234
- Açıklama: Üst sınır (Q4) yalnızca `basis.has_ration` iken uygulanıyor. Sıcaklık yoksa, tablo dışıysa veya açlık (fasting) günüyse `credit = part` olur ve yem tamamı büyümeye çevrilir. README bunu bilinçli ("its feed is credited as given") yazıyor, ama sonuç, ölçümü en güvenilmez günlerde tahmini ağırlığın en şişkin hesaplanmasıdır; bu tahmin düzenleyici biyokütle raporunda (19-6) ve hasat tahmininde kullanılıyor.
- Kanıt: `credit = part` / `if basis.has_ration:` (projection.py:247-248); açlık dalı `Basis(... missing=FASTING)` `sfr=None` (ration.py:226-228).
- Öneri: Bu günlerde büyümeyi kredilendirmeyin veya band için "son bilinen oran" ile sınırlayın; en azından bu günleri raporda "kör gün" gibi işaretleyip projeksiyonu PROJECTED olarak kullanmayın.

### 19-6 | Orta | Güven: orta
**Geçmiş günlerin oran/tahmin değerleri sonradan girilen veriyle değişiyor; düzenleyici biyokütle raporuna sızıyor**
- Dosyalar: farm/feeding/read.py:108-129 (`policy`), farm/forms/feeding_protocol.py:250-256 (`within_window`), reports/compute/biomass.py:130-155 ve 144-175
- Açıklama: Oranlar ve tahmini ağırlık saklanmıyor, her okumada mevcut atamalar + su örneklerinden yeniden hesaplanıyor. Atama `valid_from` geçmişe STOCK_BACKDATE_DAYS (31) gün kadar girilebiliyor; geçmiş gün sıcaklığı da sonradan girilen/iptal edilen örneklerle değişiyor. README "geçmiş günlerin oranı değişmez" diyor, ama yalnızca tablonun değişmediği doğru; atama ve sıcaklık değişebiliyor. Aylık biyokütle raporunda PROJECTED yöntemi bu hesaba dayanıyor; `scope()` parmak izi atamaları, kayıtları ve yemleri kapsıyor ama sıcaklıkları kapsamıyor (kod yorumu bunu kabul ediyor), yani sonradan girilen bir geçmiş sıcaklık raporun biyokütle rakamını parmak izi değişmeden değiştirebilir.
- Kanıt: `book.at(unit, now if day >= today[unit_id] else end_of(day, unit))` (read.py:123); `within_window` 31 gün geriye izin verir; `scope` docstring: "the temperatures it also reads are the water module's, and a past sample voided later is shown by the page's own comparison, not by this fingerprint" (biomass.py:130-134).
- Öneri: Gönderilmiş rapor için kullanılan projeksiyon girdilerini (günlük sıcaklık, atama) raporla birlikte dondurun veya parmak izine ekleyin; ya da PROJECTED yöntemini onaylı rapora koymadan önce kullanıcıdan açık onay isteyin.

### 19-7 | Düşük | Güven: yüksek
**Başlamış atama satırının son günü formda uzatılabiliyor/silinebiliyor, servis ise "yalnızca kısaltılır" diyor**
- Dosyalar: farm/forms/feeding_protocol.py:374-381, farm/feeding/assignments.py:76-82
- Açıklama: `assignments.end()` başlamış satırın son gününü yalnızca kısaltmaya izin verir ("The row ends on %(day)s already: it is only ever shortened"). `AssignmentForm.clean_valid_until` ise yalnızca "dünden önce" kontrolü yapar; `until` boş bırakılarak (None) veya ileri bir tarihe alınarak başlamış bir satır uzatılabilir. İki yazma yolu aynı kuralı uygulamıyor; deney (experiments) yolu `end()` kullandığından davranış yola göre değişiyor. Uzatma yalnızca gelecek günleri etkiler ama "satır geçmiştir, sona erdirilir" kuralıyla ve denetim izi beklentisiyle tutarsız.
- Kanıt: `if self.started and until != stored and until is not None and until < self.today - timedelta(days=1)` (forms/feeding_protocol.py:376-378) vs `if row.valid_until is not None and last_day > row.valid_until: raise` (assignments.py:79-82).
- Öneri: Formu da `assignments.end()` kuralına bağlayın (uzatmayı reddedin ya da iki yolda da izin verin ve belgeleyin).

### 19-8 | Düşük | Güven: orta
**Silinmiş bir besleme protokolü geri yüklenince, bu arada silinen yeme bağlı bantlar geri geliyor**
- Dosyalar: farm/models/feed.py:230-240, core/softdelete.py:189-205, farm/models/feeding_protocol.py (`ProtocolBand.feed` PROTECT)
- Açıklama: `Feed.delete_blockers` yalnızca `protocol__is_deleted=False` olan protokollerin bantlarını sayıyor. Soft-deleted bir protokolün bandındaki yem silinebilir. `softdelete.restore` ise yalnızca kaydın kendi somut FK'lerini (species) kontrol ediyor; bantlar `AuditedModel` olmadığı için kontrol edilmiyor. Geri yüklenen protokol silinmiş bir yeme bağlı bantlarla "aktif" kalır; `read.tables` `select_related('feed')` ile silinmiş yemi okur ve board/forecast bu yemi önerir; `record_feeding` ise yalnızca aktif yem kabul ettiğinden kayıt reddedilir.
- Kanıt: `self.protocol_bands.filter(protocol__is_deleted=False)` (feed.py:234); `restore` döngüsü yalnızca `record._meta.concrete_fields` üzerinde (softdelete.py:194-198).
- Öneri: Protokol için geri yükleme kontrolü (bantların yemlerinin canlı olması) ekleyin veya yem silmede silinmiş protokol bantlarını da engelleyici sayın.

### 19-9 | Düşük | Güven: orta
**Atama oluşturma ve protokol emeklilik kontrolleri protokol satırını kilitlemiyor; tablo kaydıyla yarışabilir**
- Dosyalar: farm/feeding/assignments.py:31-67, farm/feeding/protocols.py:49-70, farm/models/feeding_protocol.py:128-136
- Açıklama: `save_table` protokolü `select_for_update` ile kilitleyip `is_assigned()` kontrolü yapıyor; ancak atama yazan yol (`rows()` + `save()`) protokol satırını kilitlemiyor, yalnızca `full_clean` içinde durumunu (ACTIVE) okuyor. READ COMMITTED altında `save_table` `is_assigned()=False` görüp bantları silip yeniden yazarken eşzamanlı bir atama commit edebilir; "atanmış tablo sabittir" kuralı (Q3) bozulur. Aynı biçimde `FeedingProtocol.clean` içindeki "bugün veya sonrası için atama var mı" emeklilik kontrolü kilitsiz.
- Kanıt: `protocol = FeedingProtocol.objects.select_for_update().get(pk=protocol.pk)` yalnızca protocols.py:53'te; assignments.py:57-67 `save()` yalnızca `transaction.atomic()` ve satır kaydı yapar.
- Öneri: Atama kaydında da protokolü kilitleyin ve `is_assigned/status` kontrolünü kilit altında tekrarlayın.

### 19-10 | Düşük | Güven: yüksek
**Sitesiz üretim bölümündeki ünitelerin yemlemesi yem stoğu defterine hiç yansımıyor**
- Dosyalar: inventory/read.py:59-67 ve 240-246, farm/models/feeding.py:23-29
- Açıklama: `feeders_for` ve README, sitesi olmayan üretim bölümündeki ünitelerin de yemlenebildiğini söylüyor (yemleyici bölüm düzeyinde aranıyor). `inventory/read._feeding` ise `unit__production_department__site__isnull=False` filtresiyle bu kayıtları siler; böylece bu üniteler için yemleme depo bakiyesinden hiç düşülmez ve "uncovered feeding" de üretilmez. Kullanıcıya hiçbir uyarı gösterilmiyor.
- Kanıt: `FeedingRecord.objects.filter(feed_id__in=feed_ids, unit__production_department__site__isnull=False)` (inventory/read.py:62); `place = ... if site_id else Q(production_department=department)` (feeding.py:25-27).
- Öneri: Sitesiz bölümlerdeki yemlemeyi ya depo defterinde "site yok" kovasına alın ya da en azından sayıp uyarı gösterin.

### 19-11 | Bilgi | Güven: yüksek
**Yemleme toplamları ekrandan ekrana farklı tanımlanıyor (üretim+temizleyici balık, iptal edilenler)**
- Dosyalar: farm/feeding/views.py:116-118 ve 418-433, farm/feeding/views.py:186-188
- Açıklama: Üretim genel bakışındaki "Feed today / last 7 days" kutucukları temizleyici balık yemini de toplar (`target` süzülmez); by-day görünümünde, SFR/FCR'de ve `Week` içinde temizleyici balık ayrı tutulur (D-1). Kayıt listesinde `count` iptal edilenleri de sayar (voided=1 iken) ama `kilos` yalnızca iptal edilmemişleri toplar; "N kayıt, X kg" satırı aynı kümeyi tanımlamaz.
- Kanıt: `FeedingRecord.objects.filter(date__range=...).aggregate(today=Sum(...), week=Sum('amount_kg'))` target süzmeden (views.py:425-426); `records.aggregate(count=Count('pk'), kilos=Sum('amount_kg', filter=Q(is_deleted=False)))` (views.py:116).
- Öneri: Kutucuklarda hedefi (üretim/temizleyici) belirtin ya da ayırın; `count` ve `kilos` için aynı filtreyi kullanın.

### 19-12 | Düşük | Güven: yüksek
**Yemleme kaydı; açlık günü, bant yemi, pellet uygunluğu ve tıbbi yem için yalnızca uyarı veriyor, hiçbirini engellemiyor**
- Dosyalar: farm/feeding/services.py:25-80, farm/feeding/views.py:337-364, farm/forms/feeding.py:81-103
- Açıklama: `record_feeding` servisi aktif yem, balık varlığı ve %10 onayı dışında hiçbir iş kuralı uygulamıyor: planlı hasat/nakil öncesi açlık günü (`fasting_on` yalnızca sayfada bilgi), kaydedilen yemin atanmış protokol bandının yemiyle aynı olması, türe/ağırlığa uygunluk (yalnızca `messages.warning`), ve ilaçlı yem için kapsayıcı tedavi yoksa yalnızca uyarı. Servisi çağıran başka yollar (ör. ileride API/toplu içe aktarma) bu uyarıları hiç görmez; çünkü bunlar view katmanında. Bant yemi ile verilen yem arasındaki fark by-day sapmasında görünmez (yalnızca kg).
- Kanıt: services.py'de `fasting`, `suits`, `Feed.Type.MEDICATED` hiç geçmez; uyarılar views.py:340-350'de; açlık yalnızca bağlam (`'fasting': fasting_on(unit, day)`, views.py:354).
- Öneri: Uyarı üreten kuralları servis katmanına taşıyıp sonuç olarak döndürün (veya audit log'a yazın), böylece her giriş yolu aynı sonucu görür.

### 19-13 | Bilgi | Güven: orta
**`project()` her çağrıda ünitelerin tüm yemleme geçmişini yürüyor (meal board, by-day, kartlar, rapor, tahmin)**
- Dosyalar: farm/feeding/read.py:58-68, 149-160, README.md (Measured at 100 units paragrafı)
- Açıklama: `feedings(unit_ids)` `since` vermeden tüm kayıtları okur; `lineage()` döngüsü de batch→unit zincirini DB'den tekrar tekrar çözer. README bunu ölçülmüş ve bilinçli bir bırakma olarak kaydediyor ("a measured slow screen would first bound the feeding walk"), ama kayıt sayısı büyüdükçe (yıllarca günlük kayıt) meal board, her kart yenilemesi ve yukarıdaki biyokütle raporu doğrusal yavaşlar; sınır/önbellek yok.
- Kanıt: `records = feedings(unit_ids)` (read.py:155) ve `lineage` döngüsü (read.py:77-91).
- Öneri: Yürüyüşü ilk ölçülen noktanın (son tartım/dikim) gününden başlatın veya sonuçları (UnitDay) kısa süreli önbellekleyin.

### 19-14 | Düşük | Güven: orta
**Protokol emeklilik kontrolü şirket saatini, atama kuralları ünite sitesinin saatini kullanıyor**
- Dosyalar: farm/models/feeding_protocol.py:131-136, farm/models/feeding_protocol.py:318-326, farm/feeding/assignments.py:83
- Açıklama: `FeedingProtocol.clean` "bugün" için `zone_of(None)` (şirket saati) kullanıyor; atama satırlarının `started()`/`today()` ve `end()` fonksiyonları ünite sitesinin saat dilimini kullanıyor. Farklı saat dilimlerindeki sitelerde, gece yarısı civarında bir protokol "aktif atama yok" diye emekliye alınabilir ya da tam tersi engellenir.
- Kanıt: `today = timezone.localdate(timezone=zone_of(None))` (feeding_protocol.py:133) vs `local_today(row.unit)` (assignments.py:83).
- Öneri: Emeklilik kontrolünü her atamanın kendi `today()` değeriyle yapın.

### 19-15 | Bilgi | Güven: yüksek
**Biçim/okunabilirlik: `read.py` içinde tek satırda boşluklu `else None`**
- Dosyalar: farm/feeding/read.py:457
- Açıklama: `in_use = current if ... >= stock[unit.pk].since             else None` ifadesinde uzun boşluk dizisi var (satır sonu devamı birleşmiş görünüyor); geçerli Python ama bakım/linter açısından tutarsız.
- Kanıt: read.py:457.
- Öneri: Satırı normal biçimlendirin.
