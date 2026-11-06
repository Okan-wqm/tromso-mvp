# 35 - Performans denetimi

Uzman alani: Performans (N+1, indeksler, agir view'lar, bellek, buyuk tablolar, grid, rapor hesaplari, cache).
Kapsam: /home/user/tromso-mvp (Django 6.1, PostgreSQL + TimescaleDB). Salt-okunur inceleme; kod ve veri degistirilmedi, yalnizca bu dosya yazildi.

## Ozet

Kod tabani toplu okuma (bulk read) konusunda ozenli yazilmis: izleme kartlari her kaynak icin tek toplu cagri yapiyor, anket (poll) uclari degisiklik belirtecine (token) gore 204 donuyor, istemci gorunurluk ve jitter kullaniyor, bilgi kutuphanesi aramasi GIN indeksli. Asil yapisal performans riski su: stok, yemleme ve su analizi "olay defteri (ledger)" olarak saklaniyor ve her okumada TUM gecmis Python'da katlaniyor (fold). Hicbir figur onbellege alinmiyor (CACHES tanimsiz, materyalize tablo yok). Cogu sayfa ve ozellikle 15 sn'de bir yenilenen izleme duvari, veri biriktikce lineer yavaslayacak. Ikinci grup: bazi listeler (hasat, deniz biti (lice) sayimi, su gecmisi, rapor "due" listesi) sayfalamadan once butun gecmisi hesapliyor. Ucuncu grup: veritabani gezgini, aktivite gunlugu ve soft-delete plani gibi yonetim ekranlarinda tam tablo taramalari ve bellekte buyuk kume uretimi.

Toplam 24 bulgu: 4 high, 10 medium, 9 low, 1 info.

## Incelenen alanlar

- core: crud.py (ListView/filter_by), dbgrid.py, dbview.py, database.py, audit.py, views.py (activity_log), softdelete.py, navigation.py (rail context processor), models.py (indeksler), middleware.
- config: settings.py (DB, CONN_MAX_AGE, middleware, cache, static), views.py (ana sayfa/uretim ozeti).
- monitoring: read.py, views.py (kart okuma modeli ve poll).
- farm: stock/read.py, stock/fold.py, stock/services.py, stock/views.py, feeding/read.py, feeding/views.py, feeding/services.py, water/read.py, water/views.py, models/water.py, health/read.py, health/views.py, harvest/read.py, harvest/views.py, forms/harvest.py, forms/feeding_protocol.py, resources/harvest_plan.py, resources/feeding_protocol.py, management/commands/check_withdrawal.py.
- messaging: read.py, views.py (okunmamis rozeti, inbox, poll).
- tasks: read.py, models.py (indeksler).
- hr: read.py (roster haftasi).
- inventory: read.py.
- reports: due.py, resources.py, views.py, services.py.
- knowledge: search.py, extraction.py, models/document.py.
- experiments: read.py (toplu okuma dogrulamasi).
- frontend/poll.ts (poll davranisi), docker-compose.yml, requirements.txt, static/css boyutlari.

## Incelenmeyen / sinirli incelenen alanlar

- Gercek veri hacmi ve EXPLAIN ANALYZE planlari: veritabani calistirilmadi; tum olceklenme degerlendirmeleri kod okumasina dayanir.
- TimescaleDB ayarlari (compression, retention, continuous aggregate): migrations/0014_water.py yalnizca hypertable olusturuyor; baska politika bulunmadi.
- hr/scope.py, hr/services.py, experiments/design.py/services.py, tasks/services.py, farm/stock/integrity.py, reports/compute/* icindeki hesaplarin ayrintili sorgu sayimi.
- Sablon (template) render maliyetleri ve frontend paket boyutu (TypeScript derlenmis cikti repoda yok).
- Uretim dagitimi (gunicorn/ters vekil/CDN): repoda Dockerfile ya da sunucu yapilandirmasi yok.

## Bulgular

### 35-1 - Izleme duvari her yenilemede tum stok defterini ve tum yemleme gecmisini yeniden katliyor
- Onem: high
- Guven: high
- Dosyalar: monitoring/read.py:315-336, monitoring/read.py:103, monitoring/read.py:460-472, farm/stock/read.py:33-48, farm/stock/read.py:327-335, farm/feeding/read.py:58-69, farm/feeding/read.py:77-96, farm/feeding/read.py:149-160, farm/water/read.py:231-252, monitoring/views.py:128-146
- Aciklama: `cards()` her cagrida `stock_read.stock_of(units)` ile, goruntulenen birimlerde stogu olan her batch'in TUM StockMovement gecmisini (`ledger`) cekip Python'da `fold` ediyor. Ardindan `feeding_read.figures(..., ration=True)` -> `project()` -> `lineage()` birimlerin bagli oldugu butun batch/birim agini transitif olarak genisletiyor ve `feedings(unit_ids)` `since` olmadan bu birimlerin TUM FeedingRecord'larini yukluyor. `water_read.latest()` -> `Context` -> `SpeciesBook` -> `Presence.of_units` yine tum stok satirlarini okuyor. Degisiklik belirteci dakika kovasi (TOKEN_BUCKET=60) icerdigi icin hicbir sey degismese bile her ekran en az dakikada bir tam yeniden hesap yaptiriyor; her denetim kaydi yazimi (herhangi bir kayit) tum ekranlari 15 sn icinde tam hesaba zorluyor. Maliyet gecmis boyutuyla (yillar) buyur, kart sayisindan bagimsiz sabit bir taban var.
- Kanit: `stock = stock_read.stock_of(units) if STOCK in sections else {}` (monitoring/read.py:323); `records = feedings(unit_ids)` ve `walk(ledger(batch_ids), records, days, projector=projector)` (farm/feeding/read.py:149-160, `since` yok); `TOKEN_BUCKET = 60` ve `str(int(now.timestamp() // TOKEN_BUCKET))` (monitoring/read.py:103, 470); `MONITOR_POLL_SECONDS = 15` (config/settings.py:239). `lineage` dongusu "until nothing is added" (feeding/read.py:77-96) transfer yoluyla birbirine baglanan tum birimleri iceri aliyor.
- Oneri: Defter katlamasini birim/batch basina "son olcum noktasi" anlik goruntusu (snapshot tablosu veya audit revizyonuna anahtarli onbellek) olarak sakla; `project()` icin tarihi son olcum noktasindan baslat; kart cevabini (kullanici bolumleri + sorgu + revision anahtari) kisa sureli onbellege al ki ayni duvari izleyen birden fazla ekran tek hesaplamayi paylassin.

### 35-2 - Menu rozeti (okunmamis mesaj) her sayfada ve 30 sn'de bir tum Message tablosunu tarayabilir
- Onem: high
- Guven: medium
- Dosyalar: messaging/read.py:23-33, core/navigation.py:69-70, core/navigation.py:163-197, config/settings.py:89-96, messaging/views.py:136-138, messaging/models.py (index message_timeline)
- Aciklama: `unread_total` sorgusu `Message.objects.filter(is_deleted=False).filter(Exists(<Participant correlated>)).count()` seklinde; yani sürücü tablo Message (butun konusmalar, butun kullanicilar). PostgreSQL planinda genelde tum canli mesajlar taranip her biri icin Participant alt sorgusu denenir; kullanicinin kendi konusmalarindan baslayip mesajlara gitmek (Participant -> Message(conversation, id > last_read)) yerine ters yon kullaniliyor. Bu sorgu `core.navigation.rail` baglam islemcisi icinden her tam sayfa render'inda calisiyor (rozet, `rail()` icinde yalnizca aktif panele degil, kullanicinin gorebildigi TUM panellerin tum girdileri icin `entry.badge_for(user)` ile hesaplaniyor) ve ayrica her istemci icin 30 sn'de bir poll ediliyor.
- Kanit: `return Message.objects.filter(is_deleted=False).filter(Exists(mine)).count()` (messaging/read.py:23-28); `'badge': entry.badge_for(user)` (core/navigation.py:182) tum workspace'ler icin dongu icinde; `data-poll-every="30"` (core/test_frontend_contract.py:75 yoluyla shell sablonu). Index yalniz `message_timeline (conversation, id)`.
- Oneri: Sorguyu `Participant.objects.filter(user=user)` uzerinden baslat ve `Message.objects.filter(conversation=..., id__gt=last_read)` toplamini (index `message_timeline` ile) hesapla; ya da Participant'ta `unread_count` sayaci tut. Rozeti yalnizca gorunen panelde hesapla.

### 35-3 - Hasat listesi butun hasat gecmisini ve tum batch defterlerini katlayip sonra sayfaliyor
- Onem: high
- Guven: high
- Dosyalar: farm/harvest/read.py:39-50, farm/harvest/read.py:98-114, farm/harvest/views.py:94-99, farm/harvest/views.py:60-90
- Aciklama: `harvests(lines)` filtreye uyan TUM hasat satirlarini (`list(lines.select_related(...))`) ve bunlarin operasyon, kayit, kayip, plan, onay satirlarini yukluyor; `add_book` ise bu satirlarin tum batch'leri icin `moved_grams` ile defteri bastan katliyor. `Paginator(rows, PAGE_SIZE)` ancak bunlarin hepsi bellekte hazir olduktan sonra uygulaniyor, yani sayfa 1 bile tum gecmisin maliyetini oduyor. Ek olarak filtre secenekleri (`choices`) `movements__in=harvested` alt sorgusu uzerinde `.distinct()` birlesimleri; her filtre icin `values_list('pk')` tam kume cekiliyor.
- Kanit: `rows = read.harvests(lines)` ... `page = Paginator(rows, PAGE_SIZE).get_page(...)` (farm/harvest/views.py:97-99); `moved = moved_grams({line.batch_id for line in lines})` (farm/harvest/read.py:46); `'site': Site.all_objects.filter(production_departments__tanks__movements__in=harvested).distinct()` (views.py:66).
- Oneri: Sayfalamayi sorgu duzeyinde yap (operasyon id sayfasi), sonra yalniz o sayfanin batch'leri icin kitap hesabi yap; toplamlari (Total) ayri bir agregasyon sorgusuyla hesapla.

### 35-4 - Su analizi gecmisi: tarih araligi sinirsiz, tum ornekler degerlendirilip sonra sayfalaniyor
- Onem: medium
- Guven: high
- Dosyalar: farm/water/views.py:218-232, farm/water/read.py:469-505, farm/water/read.py:242-262
- Aciklama: `_history` `from`/`to` sorgu parametrelerini sinirlamadan kabul ediyor (varsayilan 30 gun ama kullanici cok eski bir `from` verebilir). `read.history(list(samples))` butun ornekleri `select_related` ile cekip her biri icin `context.readings` + `judge` calistiriyor; `Paginator(rows, 50)` bundan sonra uygulaniyor. `Context` ayrica ilgili birimlerin tum stok satirlarini (`Presence.of_units`) ve tuzluluk serisini (`since - WINDOW`) yukluyor. Sayfa basina 50 satir gostermek icin tum araligin maliyeti odeniyor. Ek olarak sayfa uzerinde `services.earliest(sample.point)` nokta basina ayri cagriliyor (`setdefault` arguman olarak da degerlendirildigi icin her satirda hesaplaniyor).
- Kanit: `rows = read.history(list(samples))` ... `page = Paginator(rows, PAGE_SIZE).get_page(...)` (farm/water/views.py:228-232); `first = earliest.setdefault(sample.point_id, services.earliest(sample.point))` (views.py:238) - `services.earliest` her satirda degerlendirilir.
- Oneri: Araligi ust sinirla (ornegin 366 gun) ve sayfalamayi `samples_of` sorgusu uzerinde yap, sadece sayfadaki ornekleri `history()`'e ver; "yalniz alarmlar" filtresi icin veritabanında durum sutunu ya da ayri hesap gerekir. `earliest` icin `if point_id not in earliest` kullan.

### 35-5 - Rapor "due" listesi her cagrida tum siteleri/donemleri bastan hesapliyor; ana sayfa dahil her yerde cagriliyor
- Onem: high
- Guven: medium
- Dosyalar: reports/due.py:139-160, reports/due.py:196-233, reports/due.py:399-417, reports/resources.py:158-175, reports/views.py:41-49, reports/views.py:88, reports/views.py:139, reports/services.py:116, config/views.py:23-28
- Aciklama: `due.due()` her site icin tum Tank'lari, tum StockMovement varligini (`Presence.of_units`) ve `reports_from`'dan bugune tum haftalik/aylik donemleri uretip her donem icin tum (birim, batch) zaman cizelgelerini tarıyor (`_periodic_line`: donem x timeline x present_between, O(D x T)). Sonuc hicbir yerde onbellege alinmiyor ve sirasiyla: sirket ana sayfasi (`overview_upcoming`, `report.view` izni olan herkes), rapor listesi, `outside_duties`, `_due_row` (kapatma linki) ve `close_due` (ayrica dogrulama icin tekrar) icinde cagriliyor. Rapor listesi ayrica `no_longer_match()` cagiriyor: son ~1 yilin her kayitli raporu icin `compute.scope(report)` + `fingerprint` hesaplaniyor (rapor basina sorgular), yani rapor sayisiyla dogrusal.
- Kanit: `owed = due.due()` (config/views.py uzerinden reports/views.py:46, resources.py:168); `for period in periods.periods_between(...)` icinde `any(... presence.present_between(unit, batch, ...) for unit, batch in presence.timelines)` (due.py:225-227); `for report in filed: ... compute.fingerprint(compute.scope(report))` (due.py:411-414).
- Oneri: `due()` sonucunu audit revizyonu + gun anahtariyla kisa sureli onbellekle; ana sayfa ozetini ayri/hafif hesapla; `Presence` zaman cizelgesini donem basina degil site basina bir kez indeksle (sorted days + bisect).

### 35-6 - check_withdrawal komutunda stock_of birim sayisi kadar tekrar hesaplaniyor (O(n^2))
- Onem: medium
- Guven: high
- Dosyalar: farm/management/commands/check_withdrawal.py:16
- Aciklama: List comprehension kosulu icinde `read.stock_of(units)` cagriliyor; her birim icin butun birim listesinin stoku (sorgu + tum defter katlamasi) yeniden hesaplaniyor. Birim sayisi n ise n kez tam farm katlamasi.
- Kanit: `stocked = [unit for unit in units if unit.pk in read.stock_of(units)]`
- Oneri: `stock = read.stock_of(units)` bir kez hesaplanip `unit.pk in stock` kullanilmali (degisiklik tek satir).

### 35-7 - Kucuk ihtiyaclar icin tum ciftligin stok defteri katlaniyor (ozet fayanslari, form constructor'lari, birim secici)
- Onem: medium
- Guven: high
- Dosyalar: farm/stock/views.py:549-562, farm/stock/views.py:316-319, farm/forms/harvest.py:169, farm/feeding/views.py:293-297, farm/resources/harvest_plan.py:154-157, config/views.py:31-52
- Aciklama: Uretim ana sayfasinin "Stocked units / Fish / Biomass" fayanslari (`overview_tiles`) tum Tank'lari cekip `stock_of` ile tam defteri katliyor; ayni sayfada ayrica su/yemleme/gorev fayanslari ve `System`/`Tank` icin ayri COUNT sorgulari (sistem durumu ve birim turu basina bir sorgu) var. `ProductionPlanForm.__init__` her olusturuldugunda (GET, POST, hatali POST) `stock_of(list(Tank.objects.all()))` calistiriyor; `_unit_choices` ve `choose_unit` de ayni sekilde. Yalnizca "hangi birimde balik var / ne kadar bos yer" gibi bilgiler icin tam gecmis katlaniyor.
- Kanit: `stock = stock_read.stock_of(list(Tank.objects.all()))` (farm/forms/harvest.py:169); `stock = read.stock_of(units)` (farm/stock/views.py:555); `units_by_kind` ve `systems_by_status` icinde dongu ile `.count()` (config/views.py:43-52).
- Oneri: Mevcut "birim basina anlik stok" bir read-model/materyalize tabloda tutulsun ya da `unit_counts()`/`batches_in_stock()` gibi mevcut ucuz agregasyon fonksiyonlari kullanilsin (yalniz sayi ve biyokutle gerektiren yerlerde); sayimlari tek `values('kind').annotate(Count)` ile al.

### 35-8 - Stok ve yemleme yazma yolu her islemde ilgili tum gecmisi katliyor (kilit altinda)
- Onem: medium
- Guven: medium
- Dosyalar: farm/stock/services.py:285-335, farm/stock/services.py:125, farm/stock/services.py:747, farm/feeding/services.py:54-58, farm/feeding/read.py:163-168
- Aciklama: `_validate` her stok operasyonunda birimlerin hic gordugu tum batch'lerin butun defterini, `since=day` sonrasi yemlemeleri ve saglik kayitlarini yukleyip katliyor; bu `select_for_update` kilitleri alindiktan sonra (islem acikken) yapiliyor, dolayisiyla kilit tutma suresi gecmisle buyur ve es zamanli yazmalari bekletir. Yemleme kaydi `book_on(unit, day)` ile birimin tum soyunu katliyor; hata yolunda `book_on` iki kez cagriliyor (`read.book_on(unit, day).has_fish` satir 58).
- Kanit: `batch_ids = batch_ids | read.batches_ever_in(unit_ids)` / `lines = read.ledger(batch_ids)` (stock/services.py:299-300); `walked = walk(lines, feeding_read.feedings(unit_ids, since=day), ...)` (satir 322-324).
- Oneri: Kilit suresini kisaltmak icin katlama hazirligini kilitten once yap ya da birim basina anlik goruntu tut; `book_on` sonucunu degiskene ata.

### 35-9 - Veritabani gezgini: iki tam COUNT, her sutunda ILIKE taramasi, genel bakista her tablo icin COUNT
- Onem: medium
- Guven: high
- Dosyalar: core/dbgrid.py:156-172, core/dbgrid.py:51-65, core/database.py:115-122, core/dbview.py:25-40, core/dbgrid.py:20-21
- Aciklama: `browse` bir gorunumde `table.counts()` (COUNT(*) + filtreli COUNT) ve `Paginator.count` (ikinci bir COUNT(*) filtreli sorgu) calistiriyor; hypertable (`water_measurements`) ve audit_log gibi buyuk tablolarda bu tam tarama. Arama kutusu her okunabilir sutunu `Cast(..., TextField)` + `ILIKE` ile OR'layip hicbir indeksi kullanamaz; siralama herhangi bir sutuna izinli (indeksiz sirala + `OFFSET`). `overview` her tablo icin ayri bir COUNT calistiriyor (cok sayida tablo). Disa aktarma 50.000 satira kadar (`EXPORT_LIMIT`) `.iterator()` ile akisla gonderiliyor ve bu sirada ayni sorguyla tam tarama yapiliyor. Yalniz platform yoneticisine acik oldugu icin etki sinirli.
- Kanit: `return Paginator(self.queryset(), PAGE_SIZE).get_page(self.page_number)` (dbgrid.py:172); `counts = self.model._base_manager.aggregate(**counted)` (database.py:121); `'tables': [{'table': table, **table.counts()} for table in tables]` (dbview.py:27); `Q(IContains(Cast(field.attname, models.TextField()), term))` (dbgrid.py:65).
- Oneri: Satir sayisi icin `pg_class.reltuples` tahmini kullan (tam sayim yalniz filtreli goruntude); arama yalniz secilen sutun filtresiyle; genel bakista kestirimli sayilar.

### 35-10 - Etkinlik gunlugu: indekssiz filtreler, her sayfada DISTINCT acilirlar, sinirsiz buyuyen tablo
- Onem: medium
- Guven: medium
- Dosyalar: core/views.py:36-71, core/models.py:154-200, core/audit.py:130-141
- Aciklama: `user_name` filtresinin indeksi yok; `q` aramasi `entity_label__icontains` (indeks kullanamaz). Her sayfa yuklemesi `users` ve `types` acilirlari icin tum audit_log uzerinde `DISTINCT` sorgusu calistiriyor (`readable.order_by('user_name').values_list(...).distinct()`), `Paginator` ayrica COUNT(*) yapiyor. Tablo yalniz ekleniyor (tetikleyici UPDATE/DELETE'i yasakliyor), saklama/bolumleme politikasi yok; her kayit degisikligi, JSON `changes` ile satir ekliyor. `revision()` iki indeksli sorgu ile iyi tasarlanmis (created_at indeksli), ancak tum izleme ekranlari tarafindan poll ediliyor.
- Kanit: `'users': readable.order_by('user_name').values_list('user_name', flat=True).distinct()` (core/views.py:66); `entity_type`'a ve `created_at`'e indeks var, `user_name`'e yok (core/models.py:171-196).
- Oneri: Acilir listeleri kucuk bir referans tablosundan/onbellekten besle; `(user_name, created_at)` indeksi ekle; log icin `created_at` bolumleme veya arsivleme stratejisi dusun.

### 35-11 - Soft-delete plani silinecek kaydin tum su orneklerinin pk kumesini bellekte topluyor
- Onem: medium
- Guven: medium
- Dosyalar: core/softdelete.py:105-160, core/softdelete.py:177-190
- Aciklama: `_collect` DO_NOTHING iliskilerde `set(model.objects.filter(link=obj)....values_list('pk'))` ve `_keep` icinde `child.objects.filter(<fk>__in=new).values_list('pk')` ile bir birimin/noktanin TUM iliskili kayitlarinin (ornegin binlerce su olcumu) pk'lerini Python kumesine cekiyor; plan onay sayfasi (GET) icin de calistirildigi icin yalnizca "kac kayit korunacak" sayisi icin tum pk'ler tasiniyor. Cascade'de her cocuk icin ayri sorgu (`_collect` ozyinelemeli, N x iliski). `execute` her kayit icin ayri `soft_delete` + `audit.record_delete` (satir basina INSERT).
- Kanit: `found = child.objects.filter(**{f'{relation.field.name}__in': new}).values_list('pk', flat=True)` / `_keep(child, set(found), plan)` (softdelete.py:155-156); `plan.kept_records` yalniz `len(pks)` olarak kullaniliyor (`kept` property).
- Oneri: Korunan kayitlar icin yalniz `COUNT` kullan (pk kumesi gerektiren yerde sayfalanmis/sinirli); cascade'i iliski basina tek sorgu ile topla.

### 35-12 - PDF metin cikarimi istek icinde ve model.save() icinde (acik islem sirasinda), sayfa sayisi sinirsiz
- Onem: medium
- Guven: high
- Dosyalar: knowledge/models/document.py:215-240, knowledge/extraction.py:56-76, config/settings.py:185, core/crud.py:(CreateView islem blogu)
- Aciklama: Yukleme sirasinda `Document.save()` `extraction.read_pdf(upload.file)` ile 20 MB'a kadar PDF'in tum sayfalarini pypdf ile senkron isliyor (CPU-bound, yuzlerce sayfada saniyeler) ve bu `CreateView`'in `transaction.atomic()` blogu icinde yapiliyor; yani islem boyunca veritabani baglantisi/kilitleri acik. Sayfa sayisi/sure siniri yok. Ayrica yeniden kaydetmede `self.pages.all().delete()` + `bulk_create` ile tum sayfalar yeniden yaziliyor.
- Kanit: `reading = extraction.read_pdf(upload.file)` (document.py:224); `with transaction.atomic(): obj = form.save(commit=False) ... obj.save()` (core/crud.py CreateView.post); `KNOWLEDGE_MAX_FILE_BYTES = 20 * 1024 * 1024`.
- Oneri: Cikarimi islemden once (form temizleme asamasinda) ya da arka plan isinde (kuyruk) yap; sayfa/sure ust siniri koy.

### 35-13 - Bilgi kutuphanesi aramasi: belge basina 4 iliskili alt sorgu ve tum eslesmeler icin Rank hesabi
- Onem: low
- Guven: medium
- Dosyalar: knowledge/search.py:127-145, knowledge/search.py:149-155
- Aciklama: `search_documents` her belge icin `best` sayfa sorgusunu 4 ayri `Subquery` olarak (`page_rank`, `number`, `label`, `Headline(text)`) tekrar calistiriyor; `ORDER BY rank` tum eslesen belgeler icin hesaplanmadan sayfalanamaz. `Headline` tum sayfa metni uzerinde calisiyor. GIN indeksleri dogru kurulmus (olumlu), asil maliyet siralama asamasinda.
- Kanit: `hit_text=Subquery(best.annotate(passage=Headline(F('text'), query.any)).values('passage')[:1])` (search.py:143).
- Oneri: Once indeksli eslestirmeyle kucuk aday kumesi cikar; Headline'i yalniz sayfadaki belgeler icin ikinci bir sorguda hesapla.

### 35-14 - Envanter okumasi tum defteri ve tum yemleme kayitlarini tarıyor; "fed_week" icin N+1
- Onem: medium
- Guven: high
- Dosyalar: inventory/read.py:44-66, inventory/read.py:69-80, inventory/read.py:205-253
- Aciklama: `folds()` her cagrida tum canli InventoryLine'lari (`select_related('operation','lot')`), tum sayimlari ve - yem urunleri icin - tum zamanlardaki FeedingRecord'lari (feed x site x tarih gruplamasi, tarih siniri yok) cekiyor. `overview()` (site, urun) cifti basina ayri bir FeedingRecord agregasyonu calistiriyor (N+1), depo konumu icin `rows` listesini her konumda tekrar tariyor (O(L x R)).
- Kanit: `FeedingRecord.objects.filter(feed_id__in=feed_ids, ...).values('feed_id', 'unit__production_department__site_id', 'date').annotate(kg=Sum('amount_kg'))` (inventory/read.py:62-64); `for (site_id, _item_id), record in per.items(): ... FeedingRecord.objects.filter(...).aggregate(...)` (read.py:239-244); `sum(... for row in rows if row.location.pk == location.pk ...)` (read.py:256).
- Oneri: Yemleme gruplamasini tarih araligina bagla, fed_week'i tek gruplu sorgu ile al; konum bazli toplamlari sozlukte on-hesapla.

### 35-15 - Poll yogun mimari: DB baglantisi her istekte yeniden aciliyor, oturum DB'de, onbellek yok
- Onem: medium
- Guven: medium
- Dosyalar: config/settings.py:110-125, config/settings.py:64-78, messaging/views.py:30, config/settings.py:239, monitoring/views.py:128-146, core/audit.py:130-141, frontend/poll.ts
- Aciklama: `CONN_MAX_AGE` varsayilani 0 (istek basina yeni PostgreSQL baglantisi). Istemci poll sikligi: acik konusma 5 sn, konusma listesi 15 sn, menu rozeti 30 sn, izleme ekrani 15 sn. Her poll istegi: oturum sorgusu (DB oturumlari, `CACHES` tanimsiz), kullanici + izin sorgulari (ilk `has_perm`'de 2 sorgu), `audit.revision()` (2 sorgu), kullaniciya ozgu bolum izinleri. Yani bos 204 yaniti bile yaklasik 5-6 sorgu ve yeni bir baglanti. Baglanti havuzu/pgbouncer yapilandirmasi repoda yok; `CONN_MAX_AGE` yorumu yalnizca runserver uyarisi veriyor. (Olumlu: istemci gorunmeyen sekmede poll etmiyor, jitter ve geri cekilme var - frontend/poll.ts:118,152,187.)
- Kanit: `'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '0'))` (settings.py:121); `CACHES`/`SESSION_ENGINE` ayari yok (settings.py arandi).
- Oneri: Uretimde `DB_CONN_MAX_AGE` veya psycopg pool (`OPTIONS: {'pool': True}`) ac; oturum icin cache/signed-cookie dusun; `revision()` sonucunu process icinde 1-2 sn onbellekle.

### 35-16 - Izleme sayfasi: tum Tank'lar Python'da filtreleniyor, her tam sayfada ve poll'de ekstra COUNT/listeler
- Onem: low
- Guven: high
- Dosyalar: monitoring/read.py:170-196, monitoring/views.py:74-92, monitoring/views.py:113-125
- Aciklama: `units_for` metin aramasini (`q`) veritabaninda degil Python'da (`params.q.lower() in word.lower()`) tum filtrelenmis Tank'lar uzerinde yapiyor, `select_related` ile tum birimleri yukledikten sonra siralama da Python'da. `_grid` her poll yanitinda `Tank.objects.count()` calistiriyor; tam sayfada ayrica `all_units=Tank.objects.order_by('code')` (secici icin tum birimler), `sites`, `departments`, `systems` tam listeleri cekiliyor. Kart sayisi icin sayfalama yok (duvar tum birimleri cizer).
- Kanit: `units = [unit for unit in found if not params.q or any(params.q.lower() in word.lower() ...)]` (read.py:188-189); `farm = Tank.objects.count()` (views.py:79).
- Oneri: Metin aramasini `Q(code__icontains)|Q(name__icontains)` ile sorguya tasi; sayiyi `len` veya onbellek ile ver.

### 35-17 - Gorev "Tamamlanan" gorunumu ifade ile siralaniyor; indeks yalniz (status, due_date)
- Onem: low
- Guven: medium
- Dosyalar: tasks/read.py:70-86, tasks/models.py:406
- Aciklama: Kapali gorevler `Coalesce('completed_at','cancelled_at')` ifadesine gore azalan siralaniyor; bu ifade icin indeks yok (tek indeks `status, due_date`). Kapali gorev sayisi surekli artar; her sayfa isteginde butun kapali kumeler siralanir, `Paginator` ayrica COUNT yapar. Ayrica her satir icin iki iliskili alt sorgu (`lines`, `lines_done`) ve cok sayida `select_related`/`prefetch_related` var (sayfa 50 ile sinirli, kabul edilebilir).
- Kanit: `closed = Coalesce('completed_at', 'cancelled_at')` / `.order_by(closed.desc(), 'title')` (read.py:78-80); `indexes = [models.Index(fields=['status', 'due_date'], name='tasks_status_due_idx')]` (models.py:406).
- Oneri: Kapanis zamanini tek bir `closed_at` sutununa denormalize edip indeksle ya da ifade indeksi ekle.

### 35-18 - Her AuditedModel tablosunda dusuk secicilikli is_deleted B-tree indeksi
- Onem: low
- Guven: medium
- Dosyalar: core/models.py:35
- Aciklama: `is_deleted` `db_index=True` ile tum AuditedModel tablolarinda ayri bir boolean indeks olusturuyor. Cogu satir `False` oldugundan planlayici bu indeksi nadiren secer; yazma maliyeti ve disk kullanimi artar. Canli kayit kisitlari icin kismi indeks (`WHERE NOT is_deleted`) daha uygun olurdu.
- Kanit: `is_deleted = models.BooleanField(_('Deleted'), default=False, db_index=True)`
- Oneri: `db_index` kaldirilip gerekli yerlerde kosullu (partial) indeks kullan; once `pg_stat_user_indexes` ile kullanim dogrulansin.

### 35-19 - Bazi listeler butun gecmisi hesaplayip kesiyor (lice_weeks, records_of_batch)
- Onem: low
- Guven: high
- Dosyalar: farm/health/read.py:121-138, farm/health/views.py:283-286, farm/feeding/read.py:192-199, farm/feeding/views.py:105-117, farm/health/views.py:146-155
- Aciklama: `lice_weeks(counts)` filtreye uyan TUM bit sayimlarini `select_related` ile cekip Python'da haftalara grupluyor, ardindan `[:LICE_WEEKS]` ile kesiyor. Yemleme kayitlarinda batch filtresi `records_of_batch` ile adaylarin hepsini (`list(records.filter(...))`) cekip `split_of` ile defteri katliyor, yalnizca sonra sayfaliyor. Saglik tedavilerinde `UNDER_WITHDRAWAL` veya batch filtresi tum aday tedavileri `treated_batches` ile degerlendiriyor.
- Kanit: `weeks = read.lice_weeks(counts)[:LICE_WEEKS]` (health/views.py:283); `candidates = list(records.filter(unit_id__in=unit_ids, date__gte=batch.input_date))` (feeding/read.py:197).
- Oneri: Haftalik gruplamayi SQL'de (`TruncWeek`/`DISTINCT ON`) yap, tarih alt sinirini sorguya koy; batch filtresini sayfa sonrasi uygula veya sonucu sinirla.

### 35-20 - Sayfalama olmayan buyuyen listeler: Uretim birimleri, yemleme panosu, hasat plani
- Onem: low
- Guven: medium
- Dosyalar: farm/stock/views.py:125-141, farm/feeding/views.py:238-262, farm/resources/harvest_plan.py:154-160, core/crud.py:396
- Aciklama: Bu sayfalar tum birimleri ve her birim icin hesaplanan satirlari tek sayfada uretiyor (sayfalama yok); satir sayisi birim sayisiyla (ciftlik buyudukce) artar ve her satir `stock_of`/`project`/`latest` sonuclarini gerektirir. `ListView` `page_size=None` ise (ic ice listeler) tum kayitlari listeler.
- Kanit: `units = list(Tank.objects.select_related(...))` + `stock = read.stock_of(units)` + `water_views.unit_water(request.user, shown)` (stock/views.py:125-143); `projection = read.project([unit.pk for unit in stocked], ...)` (feeding/views.py:259).
- Oneri: Filtre varsayilanlarini daralt (site/bolum) ve sayfalama ya da sanal kaydirma ekle; ayrintiyi cekmece (drawer) icin tembel yukle.

### 35-21 - Su orneklerinde 30 gunluk pencere icin tum satirlarin id'leri ArrayAgg ile toplaniyor; hypertable'da id ile arama tum chunk'lari tarar
- Onem: low
- Guven: medium
- Dosyalar: farm/water/read.py:377-413, farm/models/water.py:78-90, farm/models/water.py:125-131
- Aciklama: `_newest_ids` her nokta icin 30 gunluk penceredeki TUM satir id'lerini slot basina (12+ parametre) `ArrayAgg(... order_by=...)` ile toplayip ilkini aliyor; manuel ornekleme seyrek oldugu icin simdilik kabul edilebilir, fakat sensor akisi eklenirse nokta basina on binlerce satir id'si 12 kez tasinir. `in_bulk(ids)` hypertable'da yalniz `id` ile aradigi icin (birincil anahtar `(id, measured_at)`) tum chunk'lar taranir; model dokumantasyonu bunu "ciftlik hacminde ucuz" diye kabul ediyor. Hypertable icin sikistirma/saklama politikasi tanimli degil.
- Kanit: `First(ArrayAgg('id', filter=condition, order_by=('-measured_at', '-created_at')))` (read.py:384-386); `samples = WaterMeasurement.objects.select_related(*POINT_RELATED).in_bulk(ids)` (read.py:401); "an update by id alone (a void) looks in every chunk" (models/water.py:88).
- Oneri: `DISTINCT ON (point_id)`/LATERAL ile slot basina en yeni satiri sec ve `(id, measured_at)` ile getir; sensor verisi planlaniyorsa continuous aggregate ve sikistirma ekle.

### 35-22 - Her kaydedilen kayit icin denetim anlik goruntusu M2M ve FK `str()` sorgulari yapiyor
- Onem: low
- Guven: low
- Dosyalar: core/audit.py:62-67, core/audit.py:144-160, core/softdelete.py:177-190, core/dbgrid.py:125-132
- Aciklama: `_display` ManyToMany alanlari icin `getattr(instance, name).all()` ve FK icin `str(related)` cagiriyor; ilgili nesne onceden yuklenmediyse her kayitta ek sorgular (alan basina). Veritabani gezgininde `labels()` `select_related()` (argumansiz) kullaniyor: yalniz null olmayan FK'leri izler, `__str__` null olabilir bir FK kullanan modellerde (ornegin Treatment `self.medicine.name`) satir basina ek sorgu olusabilir. Bu madde kod yolu okumasina dayaniyor, sorgu sayimiyla dogrulanmadi.
- Kanit: `', '.join(sorted(str(item) for item in getattr(instance, field.name).all()))` (audit.py:67); `.select_related()` (dbgrid.py:128); `what = self.medicine.name if self.medicine_id else ...` (farm/models/health.py:404).
- Oneri: Kritik formlar icin `assertNumQueries` testleri ekle (repoda yalniz 4 kullanim var); `select_related`'i acik alan listesiyle ver.

### 35-23 - Statik dosyalar ve sunucu yigini: sikistirma, hashli statik depolama, uretim sunucusu yok; DEBUG varsayilan acik
- Onem: low
- Guven: medium
- Dosyalar: config/settings.py:28, config/settings.py:64-78, config/settings.py:173-174, requirements.txt, static/css/components.css, docker-compose.yml
- Aciklama: Ara katmanda `GZipMiddleware` yok, statik dosyalar icin `ManifestStaticFilesStorage`/WhiteNoise yok (onbellek-surumleme ve sikistirma yok); requirements'ta gunicorn/uvicorn yok (yalniz Django); `DEBUG` varsayilan `'1'` (DEBUG acikken Django her baglantida sorgu gunlugu tutar ve bellek kullanimi artar). `components.css` 61 KB, minify edilmemis. docker-compose yalniz veritabani iceriyor.
- Kanit: `DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'` (settings.py:28); MIDDLEWARE listesi GZip icermiyor; `static/css/components.css` 61042 bayt.
- Oneri: Uretim profilinde GZip + WhiteNoise/CDN ve hashli depolama ac; `DEBUG` varsayilanini kapali yap (ayrica guvenlik uzmanini ilgilendirir).

### 35-24 - Olumlu dogrulamalar: toplu okuma, poll tasarimi ve indeksler (bilgi)
- Onem: info
- Guven: high
- Dosyalar: monitoring/read.py:315-367, experiments/read.py:129-185, hr/read.py:180-262, farm/models/water.py:131, knowledge/models/document.py:172-173, frontend/poll.ts:118-187, messaging/read.py:48-76
- Aciklama: Kayda gecen iyi uygulamalar: (1) izleme kartlari kaynak basina tek toplu sorgu ve opsiyonel kaynaklar icin savepoint + log kisitlamasi kullaniyor; (2) HR haftalik cizelgesi kisi sayisindan bagimsiz sabit sayida sorgu yapiyor; (3) deney okumalari toplu (`stock_of`, `Presence`); (4) `water_meas_point_time_idx` (point, -measured_at) hypertable uzerinde mevcut, bilgi kutuphanesi aramasi GIN indeksli; (5) poll istemcisi sekme gizliyken durup jitter uyguluyor, sunucu 204 ile cevap veriyor; (6) `inbox()` iliskili alt sorgularla tek sorguda okunmamis sayilarini hesapliyor. Bu bolumler bulgu sayilmaz; yukaridaki bulgularin cogu ayni toplu tasarimin 'gecmisi tamamen katlama' temeline baglidir (35-1, 35-3, 35-7, 35-8).
- Kanit: monitoring/read.py:1-37 (modul aciklamasi "ONE bulk call per source"), farm/models/water.py:131 (`water_meas_point_time_idx`), frontend/poll.ts:118 (`document.visibilityState !== 'visible'`).
- Oneri: Yok; mevcut deseni koruyup defter katlamasini onbellege/anlik goruntuye tasimak ana aksiyon (35-1).
