# 23 - biz-inventory: Depo (Storage), yem/ilaç stoğu, tedarikçiler, miktar/birim, negatif stok

Denetçi: iş mantığı / inventory uzmanı. Yöntem: salt-okunur kod incelemesi (Postgres bu ortamda çalışmadığı için testler çalıştırılmadı).

## Özet

`inventory` uygulaması (ledger + fold + tek yazma yolu `services._commit`) mimari olarak temiz: miktar hiçbir yerde saklanmıyor, her operasyon satırlarla kaydediliyor, negatif fiziksel stok yazma yolunda tüm zaman çizelgesi için reddediliyor, void geri alma kontrol ediliyor. Bulgular ağırlıklı olarak (a) tedarikçi durumu ve iade tedarikçisi gibi iş kuralı boşlukları, (b) sayımın "listede olmayanı sıfırla" davranışının yarış/kaçak yarattığı noktalar, (c) kitap (feeding-tahmini) ile fiziksel stok ayrımından doğan düzeltme boşlukları, (d) her sayfa yüklemesinde tüm geçmişin fold edilmesi nedeniyle ölçeklenme, (e) ilaç/birim (`units`) yollarının henüz ölü olması ve README ile kod arasındaki küçük tutarsızlıklardır. Kritik/yüksek önemde bulgu yok.

## İncelenen alanlar

inventory/models.py, services.py, fold.py, read.py, forms.py, views.py, integrity.py, resources.py, admin.py, screens.py, urls.py, management/commands/check_inventory.py, testlerin içeriği (başlıklar), farm/stock/services.py (`voided`, `locked`), farm/stock/dates.py, farm/models/supplier.py, README Storage bölümü.

## İncelenmeyen alanlar

Testlerin fiilen çalıştırılması (DB yok), migration SQL'inin satır satır doğrulanması, şablonlar (templates/inventory), frontend TS, `farm` FeedingRecord yazma yolu (feeding uzmanının alanı), yetki matrisinin (config/access.py) derin analizi, i18n çevirileri.

## Bulgular

### 23-1 - Engelli/askıdaki tedarikçiden teslimat ve iade kabul ediliyor
- Önem: medium, Güven: high
- Dosyalar: inventory/services.py:187-195, inventory/forms.py:144-154, farm/models/supplier.py:44-49
- Açıklama: `Supplier.status` ACTIVE/INACTIVE/SUSPENDED/BLOCKED. Yazma yolu yalnızca `supplier.is_deleted` ve `supplies` kategorisini kontrol ediyor; durum kontrolü yok. Form sadece etikete durum ekliyor.
- Kanıt: `_check_static` içinde `if supplier.is_deleted` dışında status bakılmıyor; `suppliers()` `Supplier.objects.filter(supplies__overlap=STOCKED)` (durum filtresi yok); `SupplierChoice.label_from_instance` yalnızca `· <status>` ekliyor.
- Öneri: BLOCKED (en az) tedarikçiden yeni teslimatı reddet; INACTIVE/SUSPENDED için uyarı ya da ayarlanabilir kural. İade için kural daha gevşek olabilir.

### 23-2 - İade (return), lotu getiren tedarikçiye bağlı değil
- Önem: medium, Güven: high
- Dosyalar: inventory/services.py:305-308, inventory/forms.py:296-311, inventory/views.py:338-342
- Açıklama: İade herhangi bir "feed tedarik eden" tedarikçiye yapılabiliyor; lotu o tedarikçi teslim etmiş mi kontrol edilmiyor. Dialog yalnızca ilk teslimatın tedarikçisini `initial` olarak öneriyor. İade edilen miktarın teslim edilenle sınırlanması da yok (yalnız fiziksel stok sınırı).
- Kanıt: `return_to_supplier` -> `_departure(..., supplier=supplier)`; `_check_static` sadece kategori kontrolü; integrity.py:308-311 de yalnız kategori kontrol ediyor.
- Öneri: İade tedarikçisini lotun canlı teslimat tedarikçileriyle sınırla (veya uyar); integrity'e kural ekle.

### 23-3 - Sayım, formdaki liste dışında kalan lotları sessizce 0 yapıyor (yarış / eski form)
- Önem: medium, Güven: medium
- Dosyalar: inventory/fold.py:156-167, inventory/services.py:321-329, inventory/views.py:349-388
- Açıklama: Sayım "tüm lokasyon" semantiğinde: listelenmeyen her kova 0'lanıyor. Form, sayım ekranı açıldığındaki kitap ile doldurulur; ekran açıkken (veya geriye dönük günde) aynı lokasyona yapılan başka bir teslimat/transfer sayım satırlarında olmadığı için kayıt anında 0'a düşer. Sunucu, formun gördüğü kitap ile kayıt anındaki kitabı karşılaştırmıyor; uyarı/ret yok. Değişiklik, aynı gün/gün-sonu sayımı ile fark (variance) olarak görünür ama yeniden hesaplanabilir veri kaybı yerine fiziksel stokta gerçek bir sıfırlama yaratır (void ile geri alınabilir).
- Kanıt: `found.get(bucket, ZERO)` ile listede olmayan kova ZERO; `services.count` satırları yalnız POST'tan; `_items_at(location)` kilitleri formdan sonra alınan kitapla ilişkisiz.
- Öneri: Forma kitap-hash/son hareket zamanı koyup uyuşmazlıkta reddet veya "listede olmayan N kova 0 olacak" onayı iste.

### 23-4 - Sayım pasif lokasyona yeni stok sokabiliyor ("pasif lokasyon yeni stok almaz" kuralını deliyor)
- Önem: low, Güven: high
- Dosyalar: inventory/services.py:48,183-186, inventory/forms.py:342, inventory/models.py (LocationStatus)
- Açıklama: `ARRIVING = (IN, TRANSFER_IN)`; COUNT satırı kontrol dışı. `CountForm` lokasyon seçiminde pasif olanları da sunuyor, "bulunan lot" ile pasif lokasyona stok girilebilir ve kitap artar. Belgelenen kural (README: "An inactive location takes no new stock") yalnızca teslimat/transferi kapsıyor.
- Kanıt: `_check_static` sadece `entry.kind in ARRIVING` iken status kontrolü yapıyor.
- Öneri: Pasif lokasyonda sayım sonucu artış (counted > book / found) için ret veya açık uyarı; ya da kuralı belgede "sayım hariç" olarak yaz.

### 23-5 - Kitap (feeding tahmini) 0 gösterirken fiziksel stok var: issue/write-off/iade/transfer diyaloğu o lotu hiç sunmuyor
- Önem: medium, Güven: medium
- Dosyalar: inventory/views.py:318, inventory/forms.py:231-247, inventory/read.py:127-148, inventory/fold.py:222-229
- Açıklama: Departure diyaloğundaki kova listesi `read.buckets()` (kitap = fiziksel - feeding'in çektiği) ve `quantity > 0` ile sınırlı. Yem tüketimi tahmini (hangi lota denk geldiği bilinmiyor) süresi geçmiş/yanlış lotu "tüketilmiş" gösterirse, fiziksel olarak rafta duran bu lot için imha (write-off, expired) kaydı girilemez; tek çıkış sayım + "bulunan lot". Servis fiziksel kontrol yaptığı için asıl tutarsızlık UI seçim katmanında. Ayrıca departure miktarı fiziksel stoğa kadar kabul edilirken ekranda kitap miktarı gösteriliyor (büyük kayıt kabul edilebilir).
- Kanıt: `buckets = [row for row in read.buckets() if row.quantity > 0]`; servis `physical()` ile doğruluyor (services.py:198-205).
- Öneri: Fiziksel > 0 olan kovaları da listele (kitap farkını göstererek) ya da bu durumda sayım yoluna açık yönlendirme yaz.

### 23-6 - Her sayfa/diyalog yüklemesi tüm lotların tüm geçmişini fold ediyor (ölçeklenme)
- Önem: medium, Güven: high
- Dosyalar: inventory/read.py:69-80, 127-148, 205-260, 338-350, inventory/views.py:221-232, 318, inventory/resources.py:80-83, inventory/fold.py:199-200,219-229
- Açıklama: `folds()` her çağrıda tüm canlı satırlar, tüm sayımlar, tüm yer/FeedingRecord geçmişini yükleyip her (site, gün) için kova sıralaması ve `_drawn_in` toplamlarıyla çözüyor (kabaca gün x kova x çekiş). Sınır yok (`site_earliest` penceresi sadece UI'da). Çağrı noktaları: overview, Stock sekmesi, her departure diyaloğu (GET ve POST), lokasyon listesi (`filter_list`), Counts sekmesi sayfa başına 20 kez `count_variances` -> 20 ayrı fold, `holds_stock` (silme engeli), `book_at`. `_counts()` ayrıca tüm sayım operasyonlarını her item için yeniden okuyor (item başına değil global liste ama her fold'a geçiyor). Overview'da ayrıca site-item başına FeedingRecord sorgusu ve lokasyon başına tüm `rows` taraması (O(L x R)).
- Kanıt: yukarıdaki satırlar; `count_variances` her sayım için `folds(items)` çağırıyor.
- Öneri: Fold sonucunu istek içinde paylaş/önbelleğe al; sayım sekmesinde tek fold; uzun vadede dönemsel kapanış (snapshot) ya da pencere.

### 23-7 - `costs()`: karışık para birimli teslimatlarda diğer para birimleri değer hesabından sessizce düşüyor; kısmi maliyetli lot tamamına yayılıyor
- Önem: low, Güven: high
- Dosyalar: inventory/read.py:111-124, 144, 225-227
- Açıklama: Lot için en son teslimatın para birimi seçiliyor, farklı para birimli teslimatlar `same` filtresiyle atılıyor; maliyet bilgisi olmayan teslimatlar (unit_cost NULL) ortalamaya girmiyor, ama ortalama maliyet lotun tüm kalan miktarına uygulanıyor. Ağırlıklı ortalama, tüketilen/çıkan miktarı hesaba katmıyor (FIFO/lot izleme yok), dolayısıyla "değer" yalnızca bir yaklaşım. Hiçbir uyarı yok.
- Kanıt: `same = [... if money == currency]`; `Bucket.value = quantity * cost[0]`.
- Öneri: Karışık para birimi veya kısmi maliyette değeri "eksik" işaretle; belgede yaklaşımı belirt.

### 23-8 - Birim modeli (`Unit.UNITS`) ve kapasite birimi pratikte ölü; "units" kapasiteli lokasyon asla uyarmaz
- Önem: low, Güven: high
- Dosyalar: inventory/models.py:53-58,163-165,182, inventory/read.py:254-258, inventory/resources.py:83
- Açıklama: Item birimi DB check ile feed -> kg, ve tek item tipi feed. Dolayısıyla `capacity_unit='units'` seçilen lokasyonda `row.item.unit == location.capacity_unit` hiçbir kovada doğru olmaz; "over capacity" asla tetiklenmez, form ise bu seçeneği sunuyor. `capacity = 0` kabul ediliyor (`MinValueValidator(0)`): 0 kapasiteli lokasyon stok girer girmez "over".
- Kanıt: `chk_inventory_items_feed_kg`; `over` döngüsü yalnız eşleşen birimleri topluyor.
- Öneri: Ilaç modülü gelene kadar `units` kapasitesini formda gizle/uyar; kapasite > 0 yap.

### 23-9 - İlaç stoğu (kapsam: yem/ilaç) uygulanmamış; `LOT_REQUIRED` ve integrity ilaç kuralları test edilemez ölü kod
- Önem: info, Güven: high
- Dosyalar: inventory/models.py:132-141,150, inventory/services.py:45-47,94-97, inventory/integrity.py:344-346, inventory/forms.py:29
- Açıklama: `InventoryItem` tek bağ `feed`; DB check `feed IS NOT NULL`; `SupplyCategory.MEDICINES` için lot numarası/SKT zorunluluğu kodu var ama hiçbir yol buna ulaşamıyor. README bunu planlı olarak belirtiyor (health modülü). `Medicine` eklendiğinde `chk_inventory_items_one_link` (şu an `feed__isnull=False`), `category` GeneratedField, `ReorderLevel.ordering = item__feed__name`, `InventoryItem.ordering`, `read.overview` (`record.item.feed_id`), `read._feeding`, integrity `item.feed_id is None` kontrolü ve `label()` (`item.product.code`) birlikte güncellenmeli; birden çok yer feed'e sabit bağlı.
- Öneri: Medicine geçişi için kontrol listesi/test ekle; o zamana dek ölü kodu işaretle.

### 23-10 - Pozitif/negatif işaret ve süre doğrulamaları: geçmiş SKT'li lot teslimatı ve SKT < teslimat tarihi kontrol edilmiyor
- Önem: low, Güven: high
- Dosyalar: inventory/services.py:94-119, inventory/forms.py:191-218, 359-366
- Açıklama: Teslimat/sayım "bulunan lot" için `expiry_date` herhangi bir tarih olabilir (örn. teslimat tarihinden önce biten, zaten süresi geçmiş lot). Fold bunu "expired lot" olarak sona sıralar ve overview'da raporlar, ama giriş anında uyarı yok. Bilinen lot yeniden teslim edilirken SKT verilmezse mevcut SKT sessizce kullanılır (reddedilmez).
- Kanıt: `_resolve` yalnız `lot.expiry_date != wanted.expiry` ve `wanted.expiry is not None` iken kıyaslıyor.
- Öneri: SKT < işlem günü için uyarı/ret (write-off istisnası ayrı).

### 23-11 - Lot numarası eşlemesi Python `.upper()` ile, kısıt Postgres `Upper()` ile: bazı karakterlerde eşleşme/IntegrityError riski
- Önem: low, Güven: low
- Dosyalar: inventory/services.py:106, inventory/models.py:214-218
- Açıklama: `_resolve` DB `Upper('number')` ile Python `number.upper()` sonucunu karşılaştırıyor. `ß` gibi karakterlerde Python 'SS', Postgres (locale'e bağlı) 'ß' verebilir; bilinen lot bulunamayıp yeni lot oluşturulmaya çalışılırsa `uq_inventory_lots_number_live` (Upper) çakışması IntegrityError olarak 500 dönebilir. Gerçek lot numaralarında düşük olasılık.
- Öneri: Karşılaştırmayı tamamen DB tarafında (`Upper(Value(number))`) yap veya IntegrityError'ı yakala.

### 23-12 - `item_days`: aynı site içindeki transferler "geldi" ve "çıktı" olarak şişiriyor
- Önem: low, Güven: high
- Dosyalar: inventory/read.py:287-293
- Açıklama: Site lokasyonlarındaki `transfer_in` ve `transfer_out` satırları arrived/left sütunlarına yazılıyor; aynı site içi transferde net 0 olsa da gün satırında hem giriş hem çıkış görünür. Kapanış (`closing`) doğru ama arrived - left - fed != closing farkı kullanıcıyı yanıltabilir. Sitelerarası transfer doğru yansır.
- Kanıt: `if line.kind in ('in', 'transfer_in')` / `('out','transfer_out')` ayrım yok.
- Öneri: Site içi transfer çiftlerini netle veya ayrı "moved" sütunu kullan.

### 23-13 - Overview: stoğu hiç olmayan yem için "karşılanmamış besleme" görünmüyor; düşük stok yalnız lokasyon bazlı
- Önem: low, Güven: medium
- Dosyalar: inventory/read.py:69-80, 205-260
- Açıklama: `folds()` yalnız var olan `InventoryItem` kayıtları üzerinde döner; item, ilk teslimat/reorder level ile yaratılıyor (`item_for`). Hiç teslimatı girilmemiş bir yem için FeedingRecord varsa uncovered besleme hiç hesaplanmaz/gösterilmez (veri sessizce kapsam dışı). Düşük stok kıyası da lokasyon bazlı (aynı sitedeki diğer lokasyondaki stok sayılmaz) ve süresi geçmiş stok "mevcut" sayılıyor (Q-S4 kararı olabilir).
- Kanıt: `_feeding([item.feed_id for item in items if item.feed_id])`; low döngüsü `held[(location.pk, item.pk)]`.
- Öneri: Beslemesi olan ama item'ı olmayan yemleri overview'da "stok kaydı yok" olarak listele; belgede kararı yaz.

### 23-14 - `check_inventory` bütünlük denetimi kapsam boşlukları ve hiçbir yerde zamanlanmamış
- Önem: low, Güven: medium
- Dosyalar: inventory/integrity.py:295-363, inventory/management/commands/check_inventory.py
- Açıklama: Kontrol edilmeyenler: canlı satırı olan ama soft-deleted lot, aynı sayımda bir lotun iki kez geçmesi (DB unique kısmen), pasif lokasyona gelen arrival (tarihsel), lot SKT tutarlılığı, sayım satırının item/lot lokasyon ilişkisi, teslimat tedarikçisinin durumu. Ayrıca `operation.supplier` None ise (DB kısıtı engeller ama elle düzenleme senaryosu) `AttributeError` ile tüm denetim çöker. README yalnız testlerde çalıştığını söylüyor; cron/CI/deploy'da çağrı bulunamadı (grep: yalnız README ve tests/helpers.py).
- Kanıt: integrity.py:303 `operation.supplier.supplies`; repo genelinde `check_inventory` yalnız yönetim komutu ve test yardımcılarında geçiyor.
- Öneri: Eksik kuralları ekle, None-guard koy, periyodik çalıştır.

### 23-15 - Besleme çekişi lokasyon/silo-besleyici bağını kullanmıyor (site genelinde havuz)
- Önem: info, Güven: high
- Dosyalar: inventory/fold.py:237-252, inventory/models.py:60-70 (feeder docstring)
- Açıklama: Silonun `feeder` alanı yalnız bilgi; besleme tüm site kovalarından SKT'ye göre çekiliyor. Bir silo besleyicisinin yemi, başka depodaki daha erken SKT'li lottan düşülür; lokasyon bazlı kitap ve gerçek akış sapar, sayım varyansı üretir. Modül docstring'i bunu "later phase" olarak belirtiyor.
- Öneri: Beklenen sapmayı belgele; feeder'lı siloda öncelik ekle.

### 23-16 - Yeniden oluşan lot/item ve yem silme: item bir kez oluşunca yem sonsuza dek silinemez
- Önem: info, Güven: medium
- Dosyalar: inventory/models.py:133-134,150-152, inventory/screens.py:105
- Açıklama: `InventoryItem.feed` PROTECT ve item silinemez/düzenlenemez ("an item stays"). Hiç hareketi kalmamış (tüm teslimatlar void) bir yem için bile item kaldığından yem soft-delete edilemez (canlı item PROTECT engeli). `Feed.delete_blockers` (farm/models/feed.py:230-240) envanteri anmıyor; engel genel PROTECT mesajı üzerinden geliyor.
- Öneri: Hareketsiz item'ları temizleyen/gizleyen bir yol veya Feed engelinde açıklayıcı mesaj.

### 23-17 - Departure/Dialog tarihi varsayılanı site saati yerine şirket saati olabilir
- Önem: info, Güven: low
- Dosyalar: inventory/forms.py:138-141, inventory/views.py:335, inventory/services.py:176-181
- Açıklama: `Dialog.__init__` `site_today(site)` kullanıyor; `site` yalnız preset kova varsa veriliyor, aksi halde `site_today(None)` (şirket saat dilimi). Kayıt ise lokasyonun sitesi saatiyle doğrulanıyor; saat dilimleri farklı sitelerde varsayılan tarih "gelecekte" kabul edilip reddedilebilir.
- Öneri: Kaynak seçildiğinde tarih varsayılanını o sitenin gününe çek.

### 23-18 - Silinen yem / pasif yem durumları: giriş ekranı yalnız ACTIVE yem sunuyor ama sayımın "bulunan lot"u tüm yemleri sunuyor
- Önem: info, Güven: high
- Dosyalar: inventory/forms.py:208, 370
- Açıklama: `ReceiptLineForm` yalnız `Feed.Status.ACTIVE`, `FoundLotForm` ise `Feed.objects.order_by('name')` (pasif yemler dahil). Tutarsız; pasif yemin stoğu sayımla sisteme girebilir.
- Öneri: Bilinçli ise belgele, değilse hizala.
