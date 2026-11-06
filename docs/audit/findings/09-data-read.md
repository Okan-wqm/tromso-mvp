# 09 - Veri okuma yolları denetimi (data-read)

## Özet
Okuma tarafı genel olarak bilinçli kurulmuş: HR okumaları `hr/scope.py` üzerinden gün bazlı kapsamla yapılıyor, jenerik liste `Resource.scoped` + sunucu tarafı sayfalama (`page_size=50`) kullanıyor, kaynak sınıflarının çoğu `select_related/prefetch_related` içeriyor, veritabanı görüntüleyici (`/database/`) yalnızca GET kabul ediyor, sütun/sıralama/filtre adlarını gerçek sütunlara karşı doğruluyor ve maskeli sütunları hiç okumuyor. Kritik bir veri sızıntısı veya SQL enjeksiyonu bulunmadı. Bulgular ağırlıkla (1) ölçeklenme/N+1 (envanter sayımları, su geçmişi, raporlar `due.due()`, menü rozetleri, görüntüleyici sayımları), (2) kullanıcı girdisinden 500 üreten ayrıştırma hataları (`parse_date`, `isdigit()+int()`), (3) görüntüleyicideki maskeleme politikasının tutarsızlığı ve okumaların izlenmemesi, (4) sessiz kesmeler (CSV 50.000 satır) etrafında.

## İncelenen alanlar
core/dbview.py, core/database.py, core/dbgrid.py, config/database.py, core/crud.py (ListView, FormView geçmişi, filter_by), core/views.py (etkinlik günlüğü), core/audit.py, core/navigation.py (rail context processor), hr/read.py, hr/scope.py, hr/resources/leave.py, messaging/read.py + views.py + models.py, monitoring/read.py + views.py, tasks/read.py, knowledge/search.py + views.py, reports/views.py + resources.py + due.py, inventory/views.py + read.py, farm/stock/views.py + read.py, farm/feeding/views.py, farm/water/read.py + views.py, farm/resources/* (queryset taraması), experiments/read.py (başlık taraması), config/settings.py (DB ayarları), README "Database viewer" bölümü. Python ortamında Django kurulu olmadığı için testler çalıştırılmadı; Python davranışları (`'²'.isdigit()`/`int`) bağımsız doğrulandı.

## İncelenmeyen / sınırlı incelenen alanlar
Gerçek veri hacmiyle ölçüm (EXPLAIN, sorgu sayısı) yapılmadı; performans bulguları kod okumasına dayanır. farm/health, farm/harvest, farm/handling, farm/feeding/projection, experiments/services, her Resource'un `search` alanlarındaki indeks kapsamı, şablonlarda tek tek alan sızıntısı, frontend TypeScript, migrations'daki indeksler tek tek incelenmedi. SQL enjeksiyonu/yetki konuları 02/04 numaralı uzmanların alanıdır.

## Bulgular

### 09-1 | Orta | Güven: yüksek
**Veritabanı görüntüleyici genel bakışı her tablo için ayrı tam `COUNT(*)` çalıştırır (hypertable dahil)**
- Dosyalar: core/dbview.py:25-30, core/database.py:115-122
- Açıklama: `overview` her tablo için `table.counts()` çağırır; bu, `_base_manager.aggregate(Count('pk'), Count('pk', filter=is_deleted))` ile tablo başına bir tam tarama sorgusudur. Tablo sayısı onlarcadır; `water_measurements` (TimescaleDB hypertable, tüm chunk'lar), `audit_log`, `stock_movements`, `messages` büyüdükçe sayfa doğrusal yavaşlar. Önbellek, zaman aşımı veya yaklaşık sayım (`reltuples`) yok. Tablo sayfasında da (`browse`) bir `counts()` ve ayrıca Paginator `COUNT(*)` var.
- Kanıt: `[{'table': table, **table.counts()} for table in tables]` (dbview.py:28); `self.model._base_manager.aggregate(**counted)` (database.py:121).
- Öneri: Genel bakışta tahmini satır sayısı (pg_class.reltuples) veya kısa süreli önbellek kullan; hypertable için `approximate_row_count`.

### 09-2 | Orta | Güven: orta
**Görüntüleyicinin "her sütunda ara" ve sütun filtreleri indekssiz `ICONTAINS(CAST(... AS text))` üretir; sorgu zaman aşımı yok**
- Dosyalar: core/dbgrid.py:59-72, 163-165, 171-172; config/settings.py:107-122
- Açıklama: Arama terimi, okunabilir her sütun için `Cast(attname, TextField()) ILIKE '%terim%'` koşuluna çevrilip OR'lanır; büyük tablolarda (audit_log JSON `changes`, stock_movements, water_measurements) tam tarama olur ve Paginator'ın `COUNT(*)` sorgusu aynı koşulla yeniden çalışır. `DATABASES` altında `statement_timeout` veya `OPTIONS` yok; tek bir platform yöneticisi isteği veritabanı bağlantısını uzun süre meşgul edebilir (gunicorn worker'ı da).
- Kanıt: `Q(IContains(Cast(field.attname, models.TextField()), term))` (dbgrid.py:72); `rows.filter(reduce(or_, conditions))` (dbgrid.py:165); settings.py:107-122'de zaman aşımı ayarı yok.
- Öneri: Görüntüleyici sorguları için `SET LOCAL statement_timeout` (ör. 5-10 sn) uygula; arama için sütun sayısını/kapsamı sınırla veya büyük tablolarda aramayı kapat.

### 09-3 | Düşük | Güven: yüksek
**CSV dışa aktarma 50.000 satırda sessizce keser; dosyanın içinde kesildiği belli değil**
- Dosyalar: core/dbgrid.py:26, 258-262; core/dbview.py:58-64; templates/core/database/_grid.html:24
- Açıklama: `export()` `queryset()[:EXPORT_LIMIT]` ile keser. Sınır yalnızca düğmenin `title` metninde yazıyor; üretilen dosyada bir uyarı satırı/üst bilgi yok, kullanıcı eksik dışa aktarmayı tam sanabilir ("veriyi denetlemek" amacıyla indirilen dosya için yanıltıcı). Ayrıca akış başladıktan sonra oluşan bir DB hatası HTTP 200 ile yarım dosya bırakır.
- Kanıt: `for values in self.queryset()[:EXPORT_LIMIT].iterator():` (dbgrid.py:261).
- Öneri: Kesildiğinde son satıra/ayrı bir başlığa "kesildi" işareti ekle ya da `X-Export-Truncated` başlığı ve sayfada sayı uyarısı göster.

### 09-4 | Orta | Güven: orta
**Maskeleme politikası tutarsız: kişilerin yazdığı diğer serbest metinler (görev notları, iptal/tamamlama notları, deney gerekçeleri) maskesiz; README "ne yazdıkları kişilerin kendi arasındadır" ilkesine yalnızca `messages.body` uyar**
- Dosyalar: config/database.py:17-24; tasks/models.py:357,361,493; tasks/services.py:188-198; experiments/models.py:93,98,366; reports/models.py:86-87; README.md (Database viewer, "Sensitive data")
- Açıklama: `masked` yalnızca `auth_user.password`, `messages.body`, `shift_assignments.note`, `leave_requests.reason/decision_note`, `attendance_records.note` içerir. `task_notes.body` (4000 karakterlik kişi yazısı), `tasks.completion_note/cancel_reason`, `experiments` notları/`left_reason` ile `reports.contact_email/contact_phone` görüntüleyicide ve CSV'de açık okunur. Üstelik `tasks.services.add_note` not metnini `audit_log.changes` içine düz yazar (tasks/services.py:198) ve `audit_log` tablosu da görüntüleyicide maskesiz. Test yalnızca `password|secret|token|session` adlı sütunları zorunlu kılıyor (core/test_database.py:180); "kişi yazısı" sınıfı için kontrol yok. Politika bilinçli olabilir (görev notu "iş kaydının parçası") ama config'te gerekçesi yazılı değil.
- Kanıt: `masked={'auth_user': ('password',), 'messages': ('body',), 'shift_assignments': ('note',), 'leave_requests': (...), 'attendance_records': ('note',)}` (config/database.py:20-24); `audit.record(user, AuditLog.Action.UPDATE, task, {str(NOTE): [None, body]})` (tasks/services.py:198).
- Öneri: Hangi serbest metin sütunlarının kasıtlı açık olduğunu config'te yorumla belgele; `task_notes.body` ve `audit_log.changes` için karar ver; testle "TextField/uzun CharField adayları" için liste uyarısı ekle.

### 09-5 | Düşük | Güven: yüksek
**Görüntüleyici `audit.restrict` kısıtlarını atlar: `audit_log` tablosu HR kayıt türlerinin geçmişini de gösterir**
- Dosyalar: core/audit.py:25-43, hr/apps.py:14-17, core/dbgrid.py:157, config/database.py:11
- Açıklama: Etkinlik günlüğü sayfası HR geçmişini `hr.all_employee` sahibi olmayanlardan gizler; veritabanı görüntüleyicisi `audit_log`'u `_base_manager.all()` ile ham gösterir. Görüntüleyici yalnızca platform yöneticisine açık olduğundan bu bir yetkisiz erişim değil, ama iki yüzeyin kuralı farklıdır ve README bunu söylemez (platform yöneticisi `hr.all_employee` sahibi sayılsa da `has_perm` superuser için hep True olduğundan etkisiz).
- Kanıt: `rows = self.table.model._base_manager.all()   # soft-deleted rows included: this is the database` (dbgrid.py:157).
- Öneri: Bilinçli kabulü README'ye yaz.

### 09-6 | Bilgi | Güven: yüksek
**Görüntüleyici okumaları denetim izine/erişim günlüğüne yazılmaz**
- Dosyalar: core/dbview.py:25-64
- Açıklama: Tablo gezme ve CSV dışa aktarma (auth_user e-postaları, çalışan adları, rapor iletişim bilgileri vb. dahil 50.000 satıra kadar) hiçbir `audit.record` veya erişim günlüğü yazmaz; "kim hangi tabloyu ne zaman indirdi" sorusu cevapsız. Görüntüleyici "salt okur" olduğu için tutarlı ama veri çıkışı izlenemiyor.
- Kanıt: dbview.py'de `audit` içe aktarımı yok.
- Öneri: En azından dışa aktarmaları ayrı bir önem düzeyiyle (ör. NOTICE) denetim günlüğüne kaydet.

### 09-7 | Düşük | Güven: düşük
**`Grid.queryset` okunabilir sütun listesi boşsa `values_list()` tüm sütunları (maskelenmişler dahil) okur**
- Dosyalar: core/dbgrid.py:131-133, 168; core/dbgrid.py:183-186
- Açıklama: `values_list(*[])` argümansız çağrıldığında Django tüm alanları döndürür. `masked` içine bir tablonun tüm (pk dahil) sütunları yazılırsa maskeli değerler yine veritabanından okunur; hücre eşleştirmesi de (`next(values)`) kayar. Bugünkü yapılandırmada ulaşılamaz (pk hiç maskelenmemiş); yalnızca yapılandırma hatasına karşı savunma eksikliği. Başka dosyada doğrulanmadı.
- Kanıt: `return rows.order_by(*order, 'pk').values_list(*[select(column) for column in self.readable])` (dbgrid.py:168).
- Öneri: `readable` boşsa `rows.none()` döndür veya her zaman pk'yi seç.

### 09-8 | Düşük | Güven: yüksek
**`?page=` değeri `isdecimal()` ile doğrulanıp `int()`'e verilir; çok uzun rakam dizisi (4300+ hane) `ValueError` (500) üretir**
- Dosyalar: core/dbgrid.py:146
- Açıklama: Python'un `int()` rakam sınırı (varsayılan 4300) aşılırsa `ValueError` fırlar ve bu yakalanmaz. Gunicorn'un 4094 baytlık istek satırı sınırı arkasında ulaşılamaz; daha gevşek bir ters vekilde (8 KB) erişilebilir. Etkisi yalnızca oturum açmış platform yöneticisinin kendi isteğidir.
- Kanıt: `max(int(params['page']), 1) if params.get('page', '').isdecimal() else 1`.
- Öneri: `try/except ValueError` veya `len` sınırı.

### 09-9 | Düşük | Güven: orta
**README'nin görüntüleyici bölümü gösterilen uygulama listesini eksik veriyor**
- Dosyalar: README.md (Database viewer, "Tables are not listed one by one"), config/database.py:10-21
- Açıklama: README `farm, inventory, knowledge, messaging, reports, tasks, core, auth` sayıyor; gerçek yapılandırma ayrıca `hr`, `experiments` ve `monitoring` bölümlerini içerir. Dokümantasyon-kod tutarsızlığı (HR kişisel verilerinin görüntüleyicide göründüğünü okuyan biri README'den çıkaramaz).
- Kanıt: config/database.py:10-21 on bölüm; README'de sekiz uygulama.
- Öneri: README'yi güncelle (HR tablolarının ve maskeli HR sütunlarının listesini ekle).

### 09-10 | Orta | Güven: yüksek
**Etkinlik günlüğü sayfası her istekte tüm günlük üzerinde iki `DISTINCT` taraması ve `icontains` araması yapar**
- Dosyalar: core/views.py:28-58, core/models.py:154-196
- Açıklama: Filtre açılır listeleri için `readable.order_by('user_name').values_list('user_name', flat=True).distinct()` ve `...'entity_type'...distinct()` her sayfa yüklemesinde (filtre/sayfa değişiminde de) tüm `audit_log` üzerinde çalışır; günlük salt-eklemeli ve sınırsız büyür. Yalnızca `created_at` ve `(entity_type, entity_id)` indeksleri var; `user_name` indeksi yok. `q` araması `entity_label ILIKE '%q%'` (indeks dışı), sonra Paginator `COUNT(*)`.
- Kanıt: `'users': readable.order_by('user_name').values_list('user_name', flat=True).distinct()` (core/views.py:53-54).
- Öneri: Kullanıcı/tür listelerini önbellekle ya da ayrı küçük tabloya al; `user_name` için indeks; arama için trigram indeks.

### 09-11 | Yüksek | Güven: yüksek
**Envanter "Sayımlar" sekmesi her sayım satırı için tüm envanter defterini yeniden katlar (N+1, sayfa başına 20 tam yeniden hesap)**
- Dosyalar: inventory/views.py:49,219-234; inventory/read.py:69-80, 338-350
- Açıklama: `_counts` sayfadaki her sayım için `read.count_variances(operation)` çağırır. Bu fonksiyon o konumda satırı olan tüm kalemleri çekip `folds(items)` çalıştırır; `folds` her çağrıda `_lines(items)`, `_counts()` (tüm sayımlar), `_places()` ve `_feeding(...)` okur. Sayfa başına 20 sayım = 20 kez tüm defter/sayımların yeniden yüklenmesi ve katlanması; veri büyüdükçe karesel yavaşlama. Oysa hesap tüm sayfa için tek seferde yapılabilir.
- Kanıt: `'variances': read.count_variances(operation)` (views.py:231) döngü içinde; `for fold in folds(items).values():` (read.py:343).
- Öneri: Sayfanın sayımlarını/konumlarını tek seferde katla ve sonuçları operasyon bazında dağıt; ya da varyansı sayım kaydedilirken saklı değere çevir.

### 09-12 | Orta | Güven: yüksek
**Su geçmişi tarih aralığını sınırsız alır: tüm örnekler belleğe çekilip bellekte yargılanır, sayfalama sonradan yapılır**
- Dosyalar: farm/water/views.py:215-246; farm/water/read.py:469-505
- Açıklama: `from`/`to` kullanıcı tarafından serbest verilir (varsayılan 30 gün). `samples_of(...)` aralıkta TimescaleDB hypertable'dan tüm örnekleri (`select_related` ile 3 yollu join) döndürür; `read.history(list(samples))` hepsini listeye çevirir ve her değeri yargılar, `alerts=1` süzmesi de bellekte yapılır, `Paginator` yalnızca sonuç listesine uygulanır (sayfa başına 50 gösterim için tüm aralık hesaplanır). `?from=2000-01-01` bir sitenin tüm tarihçesini tek istekte işler. Üst sınır/tavan yok.
- Kanıt: `rows = read.history(list(samples))` ... `page = Paginator(rows, PAGE_SIZE).get_page(...)` (views.py:224-229).
- Öneri: Aralığı en çok N gün ile sınırla ve/veya sayfalamayı sorgu düzeyinde yap, yargılamayı yalnızca sayfadaki örnekler için çalıştır (uyarı süzmesi için ayrı sayım).

### 09-13 | Orta | Güven: orta
**`?from=`/`?to=` geçerli biçimde ama var olmayan tarihte (`2026-13-45`) `parse_date` `ValueError` fırlatır: 500**
- Dosyalar: farm/water/views.py:214-216
- Açıklama: `django.utils.dateparse.parse_date` biçimi doğru ama geçersiz tarihte `ValueError` fırlatır (yalnızca biçim uymazsa None döner). `_day` bunu yakalamaz. Aynı klasördeki diğer sayfalar (`farm/feeding/views.py:73-77`, `core/views.py:_day`, envanter `_day`) `ValueError`'u yakalıyor; bu kullanım tutarsız. Django bu ortamda kurulu olmadığından çalıştırılarak doğrulanmadı, Django belgelerine/uygulamasına dayanır.
- Kanıt: `return parse_date(request.GET.get(name, '')) or default` (views.py:215).
- Öneri: `try/except ValueError` ile `default` döndür; test ekle.

### 09-14 | Orta | Güven: yüksek
**`reports.due.due()` tüm çiftlik için ağır hesabı her rapor listesi ve her ana sayfa yüklemesinde çalıştırır**
- Dosyalar: reports/resources.py:168-169; reports/views.py:41-52; config/views.py:26; reports/due.py:139-165, 320-360
- Açıklama: Rapor listesinin `filter_list`'i (arama, filtre, sayfa değişimi dahil her GET) `due.due()` ve `due.no_longer_match()` çağırır; bunlar her site için stok varlık zaman çizelgeleri (`Presence.of_units`), tüm `Report`'lar, tüm `HarvestRecord`/`EscapeRecord` (movement prefetch'leriyle) ve sağlık olaylarını sınırsız okur. Aynı hesap şirket genel bakış sayfasında (`overview_upcoming`) `reports.view_report` sahibi her kullanıcı için her ana sayfa yüklemesinde de çalışır. Sonuç önbelleklenmez; `?q=`/`?page=2` isteği de yeniden hesaplar.
- Kanıt: `owed = due.due()` (resources.py:168); `'upcoming': overview_upcoming(request.user)` (config/views.py:26); `for report in Report.objects.filter(corrects__isnull=True):` (due.py:172).
- Öneri: Hesabı istek içi/kısa süreli önbellekle; ana sayfada yalnızca özet sayım hesapla; `_existing` ve harvest/escape okumalarını dönemle sınırla.

### 09-15 | Orta | Güven: orta
**Menü `rail` context processor'ı her sayfa render'ında tüm çalışma alanlarının rozetlerini ve `show_when` kurallarını sorgular**
- Dosyalar: core/navigation.py:165-196; config/navigation.py:173, 186; messaging/read.py:25-37; hr/read.py:539-547; hr/scope.py:187-203
- Açıklama: `rail` her istekte (fragment olmayan her render, modal dahil) kullanıcının görebildiği tüm çalışma alanlarının tüm girdileri için `badge_for(user)` çağırır, yalnızca geçerli panelin değil. Bu: mesaj okunmamış sayımı (`Message` üzerinde `Exists` alt sorgulu `COUNT`, tüm konuşmalar) ve izin bekleyen sayısı (`scope.by_day` + `Exists`) ile `LEADS`/`production_only` (`ProductionDepartment...exists()`, `Employee...exists()`) sorgularını her sayfaya ekler. `monitoring.cards` yorumu "no request goes to the template, so the menu is never worked out for a poll" ile sorunun farkında olunduğunu gösteriyor; normal sayfalar için ise rozetler her seferinde hesaplanıyor. Ayrıca `entries()`/`place()` her çağrıda menüyü doğrusal tarar.
- Kanıt: `'badge': entry.badge_for(user)` (navigation.py:182); `Message.objects.filter(is_deleted=False).filter(Exists(mine)).count()` (messaging/read.py:31).
- Öneri: Rozetleri yalnızca geçerli panelde/yalnızca gösterilirken hesapla ya da kullanıcı başına kısa önbellekle; `entries()` sonucunu sabitle.

### 09-16 | Düşük | Güven: yüksek
**Mesajlaşma ve raporlarda `isdigit()` ile doğrulanan değer `int()`'e verilir; "²" gibi karakterler 500 üretir**
- Dosyalar: messaging/views.py:72,74,113; reports/views.py:153,157,164
- Açıklama: `str.isdigit()` üst simge rakamlar (`'²'`) için True döner, `int('²')` ise `ValueError` fırlatır. Python'da doğrulandı (`'²'.isdigit()` True, `int('²')` ValueError). `GET /messages/<pk>/?before=²`, `...poll?after=²` ve `?duty=...&year=²` yakalanmamış 500 verir; yalnızca oturumlu kullanıcıyı etkiler ve veri sızdırmaz.
- Kanıt: `shown, earlier = read.timeline(participant, int(before) if before.isdigit() else None)` (messaging/views.py:72).
- Öneri: `isdecimal()` + ASCII kontrolü ya da `try: int()`; `core/dbgrid.py:146` gibi `isdecimal` kullanılan yerlerle tutarlı hale getir.

### 09-17 | Düşük | Güven: yüksek
**Konuşma sayfasını GET ile açmak okundu işaretçisini yazar (okuma yolunda yazma)**
- Dosyalar: messaging/views.py:66-77; messaging/services.py:278
- Açıklama: `conversation` bir GET görünümüdür ve `services.mark_read(participant, shown[-1].pk)` çağırır; ön yükleme/prefetch, bağlantı önizleyici veya yeniden yükleme okundu durumunu değiştirir. Yanıt `no-store` ile işaretlenmiş poll fragmanının aksine bu sayfa için önbellek başlığı da yok. Tasarım amaçlı ("Opening it marks what it shows as read") ama GET'in yan etkisi ve rozet sayımıyla (09-15) etkileşir.
- Kanıt: `if reading_latest and shown: services.mark_read(participant, shown[-1].pk)`.
- Öneri: Bilinçli kabul olarak belgele veya işaretçiyi ayrı POST/beacon ile ilerlet.

### 09-18 | Düşük | Güven: orta
**`stock_of` her çağrıda mevcut stoklu partilerin tüm hareket geçmişini katlar (Üretim birimleri sayfası, izleme duvarı)**
- Dosyalar: farm/stock/read.py:327-335, 33-45; farm/stock/views.py:124-134; monitoring/read.py:314-317
- Açıklama: Şu an stokta olan her partinin tüm `StockMovement` satırları (hayat boyu) `ledger()` ile belleğe alınıp katlanır; bu sonuç Üretim birimleri sayfası, izleme kartları (poll 204 kısayolu dışında) ve raporlarda tekrar tekrar hesaplanır. Parti geçmişi büyüdükçe maliyet partilerin yaşıyla orantılı artar; önbellek veya anlık görüntü (snapshot) yok.
- Kanıt: `rows = list(StockMovement.objects.filter(batch_id__in=batch_ids, operation__is_deleted=False).values_list(...))` (read.py:36).
- Öneri: Ölçüm yap; gerekirse partiler için kısa ömürlü önbellek/özet tablo.

### 09-19 | Düşük | Güven: yüksek
**Sayfalaması olmayan listeler ve her istekte yüklenen tam açılır liste verileri**
- Dosyalar: farm/stock/views.py:124-133; monitoring/read.py:208-222 ve monitoring/views.py:112-120; farm/resources/harvest_plan.py:138-156 (`ProductionPlanResource`, `page_size` yok); farm/water/views.py:233-246 (`_owner_groups`); farm/feeding/views.py:84-89 (`'batch': Batch.objects.order_by(...)`)
- Açıklama: Üretim birimleri sayfası tüm birimleri ve stok/yem/su okumalarını Python'da süzer, izleme duvarı tüm eşleşen birimler için kart üretir, `ProductionPlanResource` tüm (parti, birim) satırlarını sayfalamadan listeler, su geçmişi sayfası tüm birim/sistem/ekipmanı seçici için, yem kayıtları sayfası tüm partileri açılır liste için yükler. Küçük çiftlik için kabul edilebilir; çok siteli büyümede sınırsız. `Tank.objects.count()` her izleme poll'unda tekrarlanır (monitoring/views.py:78).
- Kanıt: `units = list(Tank.objects.select_related('production_department__site', 'system'))` (farm/stock/views.py:125).
- Öneri: Ölçek hedefini README'de yaz; seçiciler için arama tabanlı (autocomplete) yükleme.

### 09-20 | Bilgi | Güven: yüksek
**`filter_by` sorgu kümesi seçeneklerinin tüm pk'lerini her istekte çeker**
- Dosyalar: core/crud.py:603-618; reports/resources.py:150-152; farm/resources/*.py (filter_list)
- Açıklama: Filtre değerini doğrulamak için `choices.values_list('pk', flat=True)` tümüyle çalıştırılıp küme yapılır; ardından aynı sorgu kümesi şablonda seçenek listesi için tekrar okunur (iki kez okuma). Küçük tablolar için zararsız; doğrulama `choices.filter(pk=chosen).exists()` ile tek satırlık olabilir.
- Kanıt: `allowed = {str(pk) for pk in choices.values_list('pk', flat=True)}` (crud.py:612).
- Öneri: Gereksiz tekrarı kaldır.

### 09-21 | Bilgi | Güven: orta
**Form sayfasındaki "geçmiş" paneli `audit.readable` süzgecini kullanmaz**
- Dosyalar: core/crud.py:650-654; core/audit.py:38-43; hr/apps.py:11-17
- Açıklama: `FormView.page` kaydın etkinlik geçmişini doğrudan `AuditLog.objects.filter(entity_type=..., entity_id=...)[:20]` ile okur; etkinlik günlüğü sayfası ise HR türlerini `readable()` ile gizler. `hr/apps.py` bunu "kaydın kendi geçmişi kendi sayfasında kalır, ekip kapsamı korur" diye bilinçli yapar; kapsam `get_object` ile uygulanıyor (core/crud.py:592-596) bu yüzden ek bir sızıntı bulunmadı. Yalnızca iki yolun kuralı farklıdır, belgeye değer.
- Kanıt: `history = AuditLog.objects.filter(entity_type=r.entity_type(), entity_id=str(obj.pk))[:20]` (crud.py:652).
- Öneri: Bilinçli kural olduğunu `audit.readable` docstring'ine yaz.

### 09-22 | Bilgi | Güven: yüksek
**İzleme sayfası filtre seçenekleri (site/departman/sistem/tank adları) ilgili okuma izni olmadan bağlama verilir (02-7 ile aynı)**
- Dosyalar: monitoring/views.py:112-120
- Açıklama: Çapraz referans: yetki uzmanının 02-7 bulgusunu okuma yolu açısından doğruladım; ayrıca bu dört sorgu her sayfa yüklemesinde ve izin süzgeci olmadan çalışır.
- Kanıt: `sites=Site.objects.order_by('name'), departments=..., systems=..., all_units=Tank.objects.order_by('code')`.
- Öneri: 02-7'deki öneriyi uygula.

### 09-23 | Bilgi | Güven: yüksek
**Olumlu doğrulamalar (bulgu değil): HR okuma kapsamı, mesaj gizliliği, görüntüleyici girdi doğrulaması**
- Dosyalar: hr/scope.py, hr/read.py, hr/resources/leave.py, messaging/read.py, core/dbgrid.py, core/dbview.py
- Açıklama: Roster/bugün/özet okumaları sabit sayıda sorgu ve `visible_days`/`by_day` ile gün bazlı kapsam uyguluyor; kriz (crew) görünümü yalnızca düz değerlerden kuruluyor (`CrewCell`); izin türü/gerekçesi yalnızca kişi ve yetkilere gösteriliyor (`show_reason`, `type_shown`); silinmiş mesaj gövdesi şablonda gösterilmiyor ve `Message.__str__` metni dışarı vermiyor; mesaj ve görüntüleyici etiketleri (`Grid.labels`) maskeli sütunlara dokunmuyor; sıralama/filtre adları gerçek sütunlara karşı doğrulanıyor, `require_safe` ve `permission_required` her görüntüleyici görünümünde var; CSV hücreleri formül enjeksiyonuna karşı kaçışlı.
- Kanıt: core/dbview.py:14-15; core/dbgrid.py:133-138; hr/read.py:260-300; messaging/models.py:195-198.
- Öneri: Yok.
