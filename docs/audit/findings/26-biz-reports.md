# 26 - Raporlar (biz-reports) denetimi

## Özet
`reports/` uygulaması (compute modülleri, due listesi, filing/snapshot, export) genel olarak titiz kurulmuş: tek giriş noktası (`reports/compute/__init__.py`), dondurulan içerik + SHA-256 + kaynak parmak izi, DB kısıtları (`reports/models.py:121-190`), Europe/Oslo takvimi ve ISO hafta sınırları doğru. Ciddi bir hesap hatası (kritik/yüksek) bulunmadı. Bulgular ağırlıkla: (1) planlı kesim son tarihinin dört ayrı yerde dört farklı kuralla hesaplanması, (2) rapor listesinin her istekte tüm due listesini ve tüm filed raporların parmak izini yeniden hesaplaması (performans), (3) parmak izi/`no_longer_match` kapsamının eksik veya varsayıma bağlı olması, (4) export katmanındaki küçük sağlamlık/tutarlılık sorunları, (5) bildirim (notice) hesaplarında doğrulanmayan varsayımlar. Testler çalıştırılamadı (ortamda Django kurulu değil).

## İncelenen alanlar
reports/compute/*.py (common, __init__, biomass, stock, lice, smolt, cleaner, slaughter, notices), reports/services.py, reports/due.py, reports/periods.py, reports/kinds.py, reports/exports.py, reports/views.py, reports/resources.py, reports/models.py, reports/forms.py, reports/duties.py, reports/integrity.py, reports/health.py, reports/screens.py, reports/urls.py, reports/admin.py, farm/stock/read.py ve farm/stock/fold.py (okunan kısımlar), farm/handling/fasting.py (fast_of), templates/reports/*.html (deadline kullanımı), docs/audit/findings/02-authz.md (çakışma kontrolü).

## İncelenmeyen / sınırlı incelenen alanlar
Testler (reports/tests/*) çalıştırılmadı (Django kurulu değil: `ImportError`). farm/health/read.py (lice_weeks), farm/feeding/read.py (project/fed), farm/water/read.py ve farm/stock/read.py `Presence` içi doğrulanmadı; şablonların tamamı, frontend TypeScript, docs/regulatory-reports.md'nin resmî alan eşleştirmeleri (Mattilsynet/Fiskeridirektoratet şeması) dış kaynakla karşılaştırılmadı. Yetki/kapsam konusu 02-authz uzmanına bırakıldı (26-18'de yalnızca çapraz referans).

## Bulgular

### 26-1 | Orta | Güven: yüksek
**Planlı kesim son tarihi dört yerde dört farklı kuralla hesaplanıyor (due satırı, liste, detay, filing)**
- Dosyalar: reports/due.py:189-192, reports/services.py:83-84, reports/compute/slaughter.py:131-137, reports/compute/__init__.py:58-63, reports/resources.py:194, farm/handling/fasting.py:282-283, templates/reports/report_list.html:113
- Açıklama: Due satırı son tarihi `slaughter.deadline(...)` (oruç günü varsa daha erken) ve sonra `max(deadline, agreed)` ("sonradan kararlaştırılan kesim") ile hesaplar. Filing anında `services.submit` `compute.deadline(current)` kullanır: `agreed` yok, dolayısıyla due listesinde "gecikmiş değil" görünen bir rapor `filed_late=True` ile kaydedilebilir. Rapor listesi şablonu `report.deadline` (yalnız Perşembe kuralı, oruç ve agreed yok) gösterir; detay sayfası `compute.deadline` (oruç var) gösterir. Ayrıca `fast_of` plan kalemi `is_open` değilse (kesim yapıldı/iptal) `None` döner; kesim gerçekleştikten sonra oruç kısıtı kalkar ve son tarih Perşembe kuralına geri döner, yani aynı rapor için son tarih zamanla değişir.
- Kanıt: due.py:191-192 `deadline = max(deadline, agreed)`; services.py:83 `current.deadline_on = compute.deadline(current)`; fasting.py:282 `if not item.is_open: return None`; report_list.html:113 `report.deadline`.
- Öneri: Tek bir `deadline_for(report)` fonksiyonu (agreed dahil, yapılmış kalemlerin oruç gününü de koruyarak) due, liste, detay ve filing'de kullanılsın; filed raporlarda yalnız `deadline_on` gösterilsin.

### 26-2 | Orta | Güven: yüksek
**Rapor listesi her istekte tüm due listesini ve filed raporların kaynak parmak izini yeniden hesaplıyor**
- Dosyalar: reports/resources.py:168-169, reports/due.py:399-417, reports/compute/common.py:93-100, reports/views.py:48, 88, 138
- Açıklama: `filter_list` her çağrıda `due.due()` ve `due.no_longer_match()` çalıştırır (sayfalama `?page=2` dahil). `no_longer_match`, son ~1 yıldaki her filed raporun `scope`'unu sorgular; `fingerprint` her sorgunun tüm satırlarını belleğe çekip `sorted(..., key=str)` ile hash'ler (stok işlemleri, tüm geçmiş besleme kayıtları `date__lte=period.end` ile). `due()` her site için Presence, tüm HarvestRecord/EscapeRecord/HandlingPlanItem'ları (zaman sınırı yok) tarar. `overview_upcoming`, `_due_row` (kapatma bağlantısı), `outside_duties` ve `close_due` da `due.due()`'yu ayrı ayrı çağırır. Veri büyüdükçe liste ve şirket genel görünümü doğrusal+ yavaşlar.
- Kanıt: resources.py:169 `rows, changed, lines = owed.rows, due.no_longer_match(), []`; common.py:96-98 `for row in sorted(rows.values_list(*names), key=str)`.
- Öneri: Parmak izini DB tarafında toplulaştır (count + max(version)/hash agregasyonu) veya filing'de/yazmada önbellekle; `no_longer_match` sonucunu kısa süreli önbelleğe al ve yalnız ilgili sekmede çalıştır; due taramalarını `reports_from` sonrası ile sınırla.

### 26-3 | Orta | Güven: orta
**`no_longer_match` eski dönemleri "değişemez" varsayarak atlıyor; ana veri değişiklikleri ve stok-dışı kayıtlar kaçar**
- Dosyalar: reports/due.py:402-415, config/settings.py:217, reports/compute/lice.py:100-110, reports/compute/stock.py:62-77
- Açıklama: Dönemi `STOCK_BACKDATE_DAYS` (31 gün) penceresinden eski filed raporlar hiç okunmaz ve `period_start` ~1 yıldan eski raporlar listeden tamamen düşer. Ancak parmak izine giren satırlar yalnız stok işlemleri değil; `sites` (organisation_number, lokalitetsnummer), `species` (official_code), `batches` (year_class), `units`, `medicines` gibi ana veriler de var (`scope_rows`, `lice.scope`) ve bunlar geriye dönük pencereye bağlı değil. Yani türün resmî kodu veya site numarası düzeltilirse, eski filed raporlar "kayıtlar artık eşleşmiyor" uyarısı vermez. Kimlik değişikliği (`IDENTITY_LEAVES`) tespiti yalnızca raporun detay sayfasında (`differences`) çalışır, listede değil.
- Kanıt: due.py:413 `if report.is_superseded or report.period and report.period.end < recent: continue`.
- Öneri: Pencere optimizasyonunu yalnız stok/ledger kaynakları için uygula; ana veri tablolarını (site, species, medicine, batch) pencereye bakmadan karşılaştır, ya da ana veri değişince ilgili raporları işaretle.

### 26-4 | Orta | Güven: orta
**Parmak izi kapsamı raporun okuduğu bazı satırları içermiyor**
- Dosyalar: reports/compute/lice.py:100-110 (scope) ile lice.py:176-179, 209-227; reports/compute/biomass.py:117-130
- Açıklama: Lice hesabı `_coverage` içinde haftadan önceki son sayımları (`LiceCount ... date__lt=period.start`) ve `_all_to_be_slaughtered` içinde `HandlingPlanItem` kayıtlarını okur; `lice.scope` yalnızca hafta içi sayımları, hafta işlemlerini, ilaçları ve su örneklerini içerir. Önceki bir sayımın iptali/değişmesi ya da bir kesim planının değişmesi sayım "gerekli" kararını (`problems`) değiştirir ama filed raporun "eşleşmiyor" durumu tetiklenmez. Biomass için sıcaklıkların kapsam dışı olduğu kod yorumunda kabul edilmiş (biomass.py:116-119).
- Kanıt: lice.py:177 `LiceCount.objects.filter(unit__in=held, date__lt=period.start)`; lice.scope listesinde bu sorgu yok.
- Öneri: `lice.scope`a önceki sayımlar ve ilgili `HandlingPlanItem`'lar eklensin; biomass için sıcaklık kaynağı (water) eklensin veya sınırlama belgelensin.

### 26-5 | Düşük | Güven: yüksek
**Hazır olmayan (problems dolu) taslak da API-JSON/CSV olarak dışa aktarılabiliyor; dosyada uyarı yok**
- Dosyalar: reports/views.py:202-226, reports/exports.py:384-428
- Açıklama: `export`, `compute.compute(report)` içeriğinin `problems` değerine bakmaz. Eksik organisation_number/lokalitetsnummer/species code ile üretilen JSON'da bu alanlar `null` ya da `''` olarak çıkar; taslak olduğunu yalnızca dosya adı eki `-not-filed` ve sayfa gösterir. Dosyanın kendi içinde (API gövdesi) bir "hazır değil" işareti yok; `X-Content-SHA256` başlığı da taslak içeriğin hash'idir.
- Kanıt: views.py:206 `content, filed = _content(report)`; views.py:212 `shaped = exports.api_json(report, content)` (problems kontrolü yok).
- Öneri: `problems` doluyken JSON dışa aktarmayı reddet (veya açık onay iste); CSV'ye "NOT READY" satırı ekle.

### 26-6 | Düşük | Güven: orta
**`authority_id` doğrulanmadan URL yoluna ve HTTP başlığına yazılıyor**
- Dosyalar: reports/forms.py:~186-190 (SubmitForm.authority_id), reports/exports.py:373-376, reports/views.py:222-225
- Açıklama: `authority_id` serbest metin (`CharField`, 100) olarak alınır; düzeltme için `PUT {path}/{authority_id}` yolu ve `X-Api-Path` başlığı bundan üretilir. `/`, `?`, `..` veya satır sonu içeren bir değer yanlış yol üretir; satır sonu Django'nun başlık doğrulamasında `BadHeaderError` (500) verir (taslak düzeltmenin export'unda).
- Kanıt: exports.py:374 `path=f'{path}/{original.authority_id}'`; views.py:223 `response['X-Api-Path'] = call['path']`.
- Öneri: `authority_id` için regex/uzunluk doğrulaması (UUID veya alfanümerik) ve yol için `urllib.parse.quote`.

### 26-7 | Düşük | Güven: yüksek
**API'si olmayan türlerin CSV'sinde iletişim bilgisi iki kez yazılıyor**
- Dosyalar: reports/exports.py:442-450, reports/compute/__init__.py:56-62
- Açıklama: `compute.compute` içeriğe `contact` ekler; `rows()` API-dışı türlerde `{'kontaktperson': contact(report), **content}` üretir. Sonuçta CSV'de hem `kontaktperson` hem `contact` bölümü bulunur (aynı ad/e-posta/telefon). Yazdırma sayfası da aynı `rows`'u kullanır.
- Kanıt: exports.py:446 `source = shaped if shaped is not None else {'kontaktperson': contact(report), **content}`.
- Öneri: `content['contact']` varken `kontaktperson` ekleme (veya tersine) ve tek anahtar kullan.

### 26-8 | Düşük | Güven: orta
**Düzeltme (correction) raporu her zaman orijinalin son tarihine göre "geç" işaretleniyor**
- Dosyalar: reports/services.py:83-84, reports/models.py:223-227 (deadline), reports/services.py:177-199
- Açıklama: Düzeltme, orijinalle aynı `period_start` taşır; `current.deadline_on = compute.deadline(current)` aynı dönem kuralını verir. Düzeltme doğası gereği orijinalden sonra gönderildiğinden `filed_late` neredeyse her zaman `True` olur ve "Filed N days after its deadline" rozeti çıkar. Bu bir gecikme ihlali değil; istatistik/rozet yanıltıcı.
- Kanıt: services.py:84 `current.filed_late = (periods.oslo_today(submitted_at) > current.deadline_on) if current.deadline_on else False` (corrects kontrolü yok).
- Öneri: Düzeltmelerde `deadline_on/filed_late`'ı `None` bırak ya da orijinalin değerini taşı.

### 26-9 | Düşük | Güven: orta
**Biomass: sayım düzeltmesiyle artan stok "kayıp" satırı olarak negatif adetle yazılıyor; ölüm ve itlaf aynı nedende**
- Dosyalar: reports/compute/biomass.py:34-48, 98-101
- Açıklama: `ADJUSTMENT` hatları (artış dahil) `losses` listesine `fish = -line.count` ile girer; pozitif düzeltme (recount up) negatif "kayıp" ve negatif kg üretir (`-(line.kilos or ZERO)`). Ayrıca `MORTALITY` ve `CULL` aynı `dead` nedenine eşlenir; neden adları "unverified" (D-15) olduğu için sınıflama doğruluğu bilinmiyor. Cleaner raporu aynı durumu uyarı ve ayrı alanla ele alıyor (cleaner.py:107-119), biomass'ta bu koruma yok.
- Kanıt: biomass.py:99-100 `row['losses'].append({... 'fish': -line.count, 'kg': text(line.kilos if line.count < 0 else -(line.kilos or ZERO), 1)})`.
- Öneri: Artan düzeltmeleri ayrı alana/uyarıya taşı; negatif kayıp üretme.

### 26-10 | Düşük | Güven: orta
**Lice: iki haftaya yayılan tedavi her iki haftanın raporunda tam miktarla yer alıyor**
- Dosyalar: reports/compute/lice.py:34-39, 241-276
- Açıklama: `week_treatments` haftayla kesişen tedavileri alır; hafta sınırını aşan tedavi her iki haftanın raporunda aynı `amount_value` ile çıkar. Docstring "in both" diyerek bunu kabul ediyor ama Mattilsynet toplamlarında miktar iki kez sayılabilir; hangi haftaya ait olacağı doğrulanmamış.
- Kanıt: lice.py:36 `start_date__lte=period.end, end_date__gte=period.start`; `_kind` miktarı bölüştürmez.
- Öneri: Miktarın hangi haftaya yazılacağını yetkiliyle doğrula (R-sorusu) ve ya başlangıç haftasına bağla ya da uyarı ekle.

### 26-11 | Düşük | Güven: düşük
**Planlı kesim: planı olmayan kesimde kilo yoksa yanlış mesaj; planı olmayan günler API'de `null`**
- Dosyalar: reports/compute/slaughter.py:77-85, 53-60, reports/exports.py:425
- Açıklama: Plansız kesimin `planned_kg` değeri tartım (`measured_weight_kg`) olup `None` olabilir; mesaj "The planned harvest ... has no planned kilos" olarak plansız kesimi planlıymış gibi anlatır. Ayrıca `species` içinde planı olmayan gün `None` bırakılır ve JSON'da `mandagKg: null` gider; API'nin 0/atlanan alan beklentisi doğrulanmamış (docs'ta yok).
- Kanıt: slaughter.py:85 `species.setdefault(code or '', {day: None for day in WEEKDAYS})[weekday] = whole(kilos)`.
- Öneri: Mesajı `item.planned` ayrımına göre düzelt; API şemasında nullable olup olmadığını doğrula.

### 26-12 | Düşük | Güven: düşük
**Kaçak bildirimi `_escape` ve `Report.clean` tek-hat varsayımına dayanıyor**
- Dosyalar: reports/compute/notices.py:61-72, reports/models.py:251-253
- Açıklama: `operation.movements...get()` birden fazla hat olursa `MultipleObjectsReturned` verir (model docstring'i "her birim için ayrı kayıt" diyor, bu yüzden bugün tek hat bekleniyor); `fish` 0 ise `abs(moved.grams) / fish` sıfıra bölme olur. `Report.clean` `movements...first().unit` için `None` kontrolü yapmaz (hatsız operasyon `AttributeError`). Mevcut kısıtlar bunu engelliyor olabilir; sertleştirilmemiş.
- Kanıt: notices.py:62 `line = operation.movements.select_related('unit', 'batch__species').get()`; models.py:253 `.first().unit`.
- Öneri: Savunmacı kontrol ekle (hata mesajı ile problem olarak raporla).

### 26-13 | Düşük | Güven: orta
**`site_in_use` / `site_emptied` bildirimleri "ilk balık / son balık" koşulunu doğrulamıyor**
- Dosyalar: reports/compute/notices.py:87-110
- Açıklama: `site_in_use` yalnızca o gün siteye INPUT/TRANSFER_IN girişi olduğunu ve `site_emptied` yalnızca günün sonunda stok kalmadığını kontrol eder. Site o gün öncesinde zaten kullanımdaysa (başka tank doluysa) giriş yine "kullanıma alındı" bildirimi olarak hazır görünür; `site_emptied` için o gün balık çıkışı olduğu doğrulanmaz (zaten boş bir sitede herhangi bir tarih seçilebilir). Hiçbiri due listesinde üretilmez, kişi başlatır; bu yüzden yanlış bildirime karşı tek koruma kullanıcıdır.
- Kanıt: notices.py:106 `elif read.stock_on(units, day): problems.append(...)` (yalnızca bu koşul); site_in_use'ta önceki stok kontrolü yok.
- Öneri: `site_in_use` için `stock_on(units, day - 1) == {}` ve `site_emptied` için o gün çıkış hattı varlığını problem olarak kontrol et.

### 26-14 | Düşük | Güven: orta
**Filing sırasında içerik ve parmak izi ayrı okumalarla alınıyor (tutarsız anlık görüntü olabilir)**
- Dosyalar: reports/services.py:61-82
- Açıklama: `compute.compute(current)` içeriği üretir, kısa süre sonra `compute.fingerprint(result.scope)` aynı sorguları yeniden çalıştırır; ikisi arasında yazılan bir kayıt (READ COMMITTED) içerikte yok, parmak izinde var olabilir. Sonuç: filed rapor doğumundan itibaren "kayıtlar değişti" olarak işaretlenir (yanlış pozitif) ya da tersi. Rapor satırı kilitli ama ledger/besleme satırları kilitli değil.
- Kanıt: services.py:51 `select_for_update()` yalnızca `Report`; services.py:82 `compute.fingerprint(result.scope)`.
- Öneri: Parmak izini içerikle aynı transaction'da `REPEATABLE READ` altında üret veya iki okuma arasında hash karşılaştırması yap.

### 26-15 | Düşük | Güven: orta
**`due._periodic_line` her dönem için tüm (birim, parti) zaman çizelgelerini tarıyor**
- Dosyalar: reports/due.py:222-235
- Açıklama: Her tür için `reports_from`'dan bugüne her dönemde `any(... presence.present_between ...)` tüm `presence.timelines` üzerinde döner: dönem sayısı × zaman çizelgesi sayısı × tür sayısı × site. Haftalık lice raporunda yıllar içinde yüzlerce dönem; bu çarpım 26-2'deki liste yavaşlığına katkıda bulunur.
- Kanıt: due.py:226-227 `if not any(_category(batches[batch])[fish] and presence.present_between(...) for unit, batch in presence.timelines)`; `_category` her çağrıda yeni sözlük kurar.
- Öneri: Kategori başına bir kez aralık birleşimi hesapla ve dönemleri o aralıklarla kesiştir.

### 26-16 | Düşük | Güven: orta
**Yıllık görevler (`duties`) `reports_from`'u yok sayıyor; "salmonid" tanımı iki yerde farklı**
- Dosyalar: reports/duties.py:140-153, reports/due.py:209-210, reports/services.py:151-153
- Açıklama: `lines_of` her uygun site için 2026'dan bugüne tüm yılların 1 Ekim görevlerini üretir; sitenin `reports_from` tarihi, ya da o yıl balık tutup tutmadığı dikkate alınmaz (yeni bir site için sonradan geçmiş yıllar "gecikmiş" görünür). `salmonids` due'da `presence` (zaman çizelgesi) ile, `record_duty_done`'da `Batch.objects ... movements__unit__...` (silinmiş partiler hariç, farklı sorgu) ile hesaplanıyor; bir görev satırı listelenir ama kaydedilemez ya da tersi olabilir.
- Kanıt: duties.py:149 `for year in range(FIRST_YEAR, today.year + 1)`; services.py:151 `Batch.objects.filter(movements__unit__production_department__site=site)`.
- Öneri: Yılları `max(FIRST_YEAR, site.reports_from.year)`'dan başlat ve salmonid kararını tek fonksiyonda topla.

### 26-17 | Bilgi | Güven: orta
**Export format sürümü ayrımı yok; `FORMAT_VERSION` değişirse eski dondurulmuş içerik `api_json`'da KeyError verebilir**
- Dosyalar: reports/exports.py:384-428, reports/compute/common.py:20, reports/views.py:31-35
- Açıklama: Filed rapor export'u `snapshot.content`'ı güncel `api_json` ile okur (alan adları doğrudan indekslenir: `content['treatments']`, `counts['adult_females']`, `unit['culled']` vb.). `format_version` bugün 1; `LEGACY_FORMAT=0` yalnızca bildirimlerde. Gelecekte içerik şekli değişirse eski filed raporların yeniden dışa aktarımı kırılır ya da farklı çıktı verir.
- Kanıt: exports.py:301-306 `content['treatments']`, `content['counts']`; views.py:34 `return report.snapshot.content, True` (sürüm kontrolü yok).
- Öneri: `format_version` ile dispatch (sürüm başına `api_json`) veya dondurulmuş içerik için migrasyon testi.

### 26-18 | Bilgi | Güven: yüksek
**Rapor okuma izni (`reports.view_report`) tüm sitelerin canlı hesaplanan verisini açar (02-6 ile çakışır)**
- Dosyalar: reports/views.py:31-35, 202-226, reports/resources.py:122-124
- Açıklama: Export/print/detay yalnızca model izni ister; `queryset()` site kapsamı uygulamaz ve taslak içerik stok/yem/ilaç/lice kayıtlarından anlık üretilir. Authz uzmanı bunu 02-6 olarak kaydetmiş; burada yalnızca raporlar tarafında kanıtlandı: `ReportResource.queryset()` tüm `Report.objects`'ı döner.
- Kanıt: resources.py:123 `Report.objects.select_related(...)` (filtre yok).
- Öneri: 02-6 önerisiyle birlikte ele alın.

### 26-19 | Bilgi | Güven: orta
**Bildirimler (escape/disease/welfare) hiçbir zaman "gecikmiş" sayılmıyor; genel görünümdeki gecikme sayacına girmiyor**
- Dosyalar: reports/due.py:179-193, reports/views.py:49-51
- Açıklama: Olay bildirimlerinin `deadline`'ı `None` (kural "at once"); `_row` `overdue = deadline is not None and ...` ile her zaman `False` verir. Haftalardır bekleyen bir kaçış/hastalık bildirimi `overview_upcoming` içindeki `overdue` sayısına katılmaz, yalnızca "at once" olarak listelenir.
- Kanıt: due.py:193 `DueRow(kind, place, period, deadline, deadline is not None and today > deadline, report, event)`.
- Öneri: Olay tarihinden itibaren geçen gün sayısını gösteren bir "bekleyen bildirim" göstergesi ekle.

### 26-20 | Bilgi | Güven: düşük
**`reports_from` dönem ortasında ise ilk (kısmi) dönemin tamamı borçlu sayılıyor**
- Dosyalar: reports/due.py:225, reports/periods.py:122-128
- Açıklama: `periods_between(grain, site.reports_from, ...)` `reports_from`'u içeren dönemin tamamını üretir; dönemin ilk günleri başka yerde raporlanmış olsa bile o dönem için tam rapor beklenir ve hesaplanır (tamamı raporlanır). Docstring "periods before were filed elsewhere" diyor; kısmi dönem için davranış belirtilmemiş.
- Kanıt: periods.py:124 `found, period = [], Period.of(grain, first)`.
- Öneri: Davranışı belgele veya `reports_from`'u dönem başına hizalamayı zorunlu kıl.
