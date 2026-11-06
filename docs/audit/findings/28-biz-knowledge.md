# 28 - biz-knowledge denetimi (Knowledge: makaleler, girdiler, PDF arama, AI atif tasarimi)

## Ozet
`knowledge` uygulamasi (Document/DocumentPage/KnowledgeEntry, extraction, search, citation, review) genel olarak
ozenli: DB check'leri, tek kaynak kurali, review surum kilidi, sorgu tarafi stemming ve XSS kacisi saglam.
Bulgularin agirligi (1) review'un kaynak belgedeki degisiklikleri kapsamamasi, (2) NFKC normalizasyonunun yalnizca
PDF sayfalarina uygulanmasi (CO2/CO₂ aramasi), (3) girdinin sayfa/alinti alanlarinin belgenin gercek metniyle
bagli olmamasi, (4) AI ajan atif tasariminin (Rule, kanit, prompt-injection, dil-bagimli atif) bosluklari.
Kod/veri degistirilmedi; PostgreSQL bu ortamda calismadigi icin testler kosulmadi, bulgular kod okumasina dayanir.

## Incelenen alanlar
knowledge/models (common, document, entry), citation.py, search.py, extraction.py, views.py, forms/, resources/,
admin.py, screens.py, templates/knowledge/*, README "Knowledge" bolumu (satir 2442-2630), core/softdelete.py restore,
config/settings.py (KNOWLEDGE_MAX_FILE_BYTES), locale (et al., n.d.), test dosyalarinin kapsami (test adlari).

## Incelenmeyen alanlar
Calisan DB uzerinde sorgu planlari/gercek arama davranisi, testlerin kosulmasi, frontend TS, core.crud ic
ayrintilari (transaction sarmali), nginx/medya depolama dagitimi, migration SQL'in model ile birebir karsilastirmasi.

## Bulgular

### 28-1 | orta | guven: yuksek
Dosyalar: knowledge/models/document.py:217-243, knowledge/forms/entry.py:173-178, knowledge/views.py:59-84
Aciklama: Girdinin "reviewed" durumu yalnizca girdinin kendi alanlari degisince draft'a doner. Atif yaptigi
Document degisince (PDF'i degistirme, baslik/yazar/yil/DOI duzenleme) girdi "reviewed" kalir; oysa review'un
dayandigi kaynak, sayfa numaralari ve alinti artik gecersiz olabilir. AI ajanlari yalniz reviewed girdilerle
calisacagi icin (README 2556) bu sessiz bir guven bosulugudur.
Kanit: entry.py:175 yalnizca `self.changed_data` (girdi formu) kontrol eder; Document.save sayfalari silip yeniden
yazar (document.py:233-238) ama KnowledgeEntry'ye dokunmaz; testlerde belge degisiminin review'a etkisi yok.
Oneri: Belge dosyasi/metni degisince bagli reviewed girdileri draft'a cevir veya girdide "reviewed_document_version"
tut; en azindan dosya degisiminde uyari goster.

### 28-2 | orta | guven: orta
Dosyalar: knowledge/search.py:92-94, knowledge/extraction.py:50-53, knowledge/models/entry.py:386-390
Aciklama: Sorgu NFKC'e normalize edilir ve docstring "saklanan metinler gibi" der; ama yalnizca PDF sayfa metni
NFKC'lenir. Baslik, ozet, statement, quote, citation elle yazilan metinler normalize edilmez. Yardim metninin
kendisi "CO₂" kullanir (forms/entry.py:128): statement'ta "CO₂" yazilirsa vektorde `co₂`, aramada "CO₂" ve "CO2"
ikisi de `CO2`'ye indirgenir; eslesme olmaz.
Kanit: search.py:94 NFKC; document.py/entry.py'de save/clean icinde normalize yok (yalniz normalise_doi/authors,
document.py:38-49). Dokuman "CO2 ile CO₂ bulunur" iddiasi (extraction.py:16) sadece PDF icin gecerli.
Oneri: Document ve KnowledgeEntry metin alanlarini kaydederken NFKC'le (veya arama vektorunde normalize et); test ekle.

### 28-3 | dusuk | guven: orta
Dosyalar: knowledge/models/common.py:7-11, knowledge/search.py:111-113
Aciklama: Turkce i/I buyuk-kucuk harf: depolama tarafi `simple` yapilandirmasi ve DB locale'inin lower()'ina
baglidir. "BALIK" -> `balik`, depolanan "balık" ile eslesmeyebilir; "İstanbul" benzeri birlesik noktali i de
tutarsiz olabilir. ASCII klavyeyle ("balik") Turkce metin bulunmaz. test_languages.py'de bu yonde test yok.
Kanit: SEARCH_CONFIG='simple'; sorgu 'turkish' stemmer okumasi da ayni DB lower'ina baglidir; testte yalnizca
"balıklarda" benzeri kucuk harf senaryolari var (test_search.py:47).
Oneri: unaccent/Turkce katlama (ı/i, İ/i) icin sorgu ve depo tarafinda ek okuma; DB collation'i ile test et.

### 28-4 | orta | guven: yuksek
Dosyalar: knowledge/models/entry.py:372-374, 444-450; knowledge/models/document.py:267-302
Aciklama: Girdinin `pages`, `section`, `quote` alanlari serbest metindir; DocumentPage ile baglantisi yoktur.
Sayfa numarasi PDF sirasi mi (number) yoksa basili etiket mi (label) belirsizdir; sayfa araligi belge
page_count'unu asabilir; alinti belgenin sayfa metninde var mi dogrulanmaz. Kaynak etiketi hep "p." der, aralikta
("12-13") "pp." olmaz.
Kanit: entry.py:372 `pages` CharField(30) dogrulamasiz; source_label entry.py:447-448 `p. %(page)s`;
DocumentPage.shown_number etiket dondurur (document.py:294-296), girdi ise ham metin. README 2593-2596 alinti
dogrulamasini ajan icin "tasarim" olarak verir, insan girdisi icin yoktur.
Oneri: pages icin bicim dogrulamasi + page_count ust siniri; alinti, belge sayfa metninde (NFKC, bosluk-katlamali)
araniyorsa "dogrulanmis" isareti; PDF-numara/etiket ayrimini girdi arayuzunde netlestir.

### 28-5 | orta | guven: yuksek
Dosyalar: knowledge/views.py:59-84, README.md:2587-2590
Aciklama: Dort goz ilkesi yok: edit izni olan kisi kendi girdisini onaylayabilir; ayrica herhangi bir editor
baskasinin onayini "Back to draft" ile geri alabilir. README bunu acik sahip karari olarak not eder, ama AI
ajanlarinin "yalniz reviewed" garantisi su an tek kisiyle saglanabilir. Ayri bir "review" izni de rol
matrisinde yok.
Kanit: views.py:59 yalniz `change` izni; DB check'i reviewed_by<>created_by icermez (entry.py:425-429).
Oneri: Sahip karari verilene kadar reviewed_by != created_by uygula veya ayri review izni ekle.

### 28-6 | dusuk | guven: yuksek
Dosyalar: knowledge/models/document.py:58-72, README.md:2492-2493
Aciklama: validate_pdf `%PDF-` imzasini dosyanin ilk 1024 baytinin herhangi bir yerinde arar
(`b'%PDF-' in head`); README ve docstring "ilk baytlar %PDF-" der. Basina baska icerik eklenmis polyglot dosya
kabul edilir (pypdf'in toleransi ile). Sunulurken content_type PDF zorlandigi icin risk dusuk.
Kanit: document.py:71.
Oneri: `head.startswith(b'%PDF-')` kullan veya dokumani duzelt.

### 28-7 | orta | guven: orta
Dosyalar: knowledge/extraction.py:56-75, knowledge/models/document.py:222-238, README.md:2506-2508
Aciklama: PDF metin cikarma istek icinde, zaman/bellek/sayfa siniri olmadan calisir. 20 MB'lik hazirlanmis bir
PDF (sikistirma bombasi, yuz binlerce sayfa) worker'i uzun sure mesgul eder veya bellegi tuketir; her sayfa icin
DocumentPage satiri bulk_create edilir. README bunu MVP karari olarak kabul eder, ama sinir yok.
Kanit: extraction.py:65-68 tum sayfalar bellekte listelenir; ust sayfa/zaman limiti yok.
Oneri: Sayfa sayisi ve toplam metin boyutu ust siniri, islem zaman asimi veya arka plan isi.

### 28-8 | dusuk | guven: orta
Dosyalar: knowledge/models/document.py:217-243
Aciklama: Document.save, belge satirini kaydedip sonra sayfalari siler/yazar; kendi transaction'ini acmaz
(transaction.atomic yok, sarmal cagiranin sorumlulugunda). Cagiran atomik degilse (admin disi script, shell)
belge `text_status=extracted` iken sayfalari eksik kalabilir. Ayrica `_stored_file` bos gelirse (file alani
defer edilmisse) eski dosya yetim kalir.
Kanit: document.py:232-241 `super().save` ile `bulk_create` ayri adimlar; from_db 181 yalnizca 'file' yuklenmisse.
Oneri: save icinde `transaction.atomic()` kullan; defer durumunda stored degerini DB'den oku.

### 28-9 | dusuk | guven: orta
Dosyalar: knowledge/citation.py:38-44, 28-30, 57-62
Aciklama: Yazar satirinda virgul "soyad, ad" ayiricisi sayilir; virgul iceren kurum adlari
("Norwegian Veterinary Institute, Oslo") "Norwegian Veterinary Institute, O." olarak kisaltilir ve metin ici atifta
(`family_name`) kurumun sadece ilk parcasi kullanilir. Form yardim metni kurumlar icin virgulsuz yazmayi soylemez.
Kanit: apa_author citation.py:40-44; family_name citation.py:29.
Oneri: Kurum yazari icin acik isaret (ornegin sonda isaret veya ayri alan) veya yardim metni uyarisi.

### 28-10 | orta | guven: yuksek
Dosyalar: knowledge/citation.py:17,66,61, locale/tr/LC_MESSAGES/django.po:538,14419
Aciklama: Ajanin alintilayacagi `plain()` ve `short()` ciktisi istek dilinde gettext ile uretilir: "et al." /
"vd." / "u.å." / "t.y." degisir. Ayni belge farkli kullanicilarda farkli atif metni verir; ajan atiflari ve
denetim kayitlari dil-bagimli olur, dil sabit degildir.
Kanit: citation.py `gettext as _` (satir 17) ve year_of/short_authors icinde kullanim; test_languages.py:67 Turkce
"Olsen vd." beklentisini kasten dogrular.
Oneri: Ajan/log icin dilden bagimsiz (kaynak dil) `plain()` surumu; arayuz icin ceviri ayri.

### 28-11 | dusuk | guven: orta
Dosyalar: knowledge/search.py:39-44, 94, 104-124
Aciklama: Sorgu 12 kelimeden fazlaysa fazlasi sessizce atilir; kullaniciya bilgi verilmez. Ayrica her kelime 3+
harfli ise 4 dilin kok on eki olarak eslesir ("running" -> "run:*" -> "runway"); asiri eslesme ve fazla gurultu
olasi. Faz-arama ("...") yok (README bunu belirtir).
Kanit: search.py:94 `[:MAX_WORDS]`; lexeme search.py:101 on ek.
Oneri: Kesme uyarisi goster; ust dizeyi ranking'te on eke gore dusur.

### 28-12 | dusuk | guven: orta
Dosyalar: knowledge/search.py:157-169, knowledge/resources/entry.py:312-318
Aciklama: Girdi aramasi belgenin baslik/ozet vektorunde de eslesir; kutuphane okuma izni olmayan (yalniz girdi
okuma izni olan) kullanici girdi listesi aramasiyla belgenin metnini dolayli sorgulayabilir (sonuc sadece var/yok
ve siralama ile). Belge sayisi (`entry_count`) da izinsiz gorunebilir.
Kanit: search.py:164-165 `document__search_vector` filtresi izin kontrolu olmadan; entry resource `can_read_library`
yalniz baglanti gosterimini kontrol eder (entry.py:353).
Oneri: Kutuphane okuma izni yoksa belge vektorunu aramaya katma.

### 28-13 | dusuk | guven: orta
Dosyalar: knowledge/models/entry.py:376-378, 468-472
Aciklama: Girdinin dogrulama bosluklari: `observed_on` gelecekte olabilir; expert kaynaginda tarih yoksa
"ne zaman" belirsiz; `citation`/`url` ayni belgeyi kutuphane Document'inden ayirt etmez (ayni DOI'li makale hem
kutuphanede hem "external" olarak cift kaynak olabilir); statement tekrar kontrolu yok (ayni bilgi iki kez
girilebilir).
Kanit: entry.py:378 DateField'de ust sinir yok; clean() yalniz kaynak turunun gerekli alanini kontrol eder.
Oneri: observed_on'a bugunden sonrasini reddet; DOI iceren external kaynak icin kutuphaneyi oner.

### 28-14 | orta | guven: yuksek
Dosyalar: README.md:2543-2553, 2563-2575
Aciklama: Tasarlanan AI akisinda eksikler: (a) PDF/belge metni ajana girdi olarak verilir ama "guvenilmeyen
icerik / prompt injection" modeli ve ajanin tool yetkileri belirtilmemis; (b) ajan "taslak girdi" olarak
onerir ama created_by/ajan kimligi (kim onerdi) ve ajan taslaginin insan taslagindan ayirt edilmesi yok;
(c) kabul edilen Rule, girdi duzenlenip tekrar onaylandiginda yeniden dogrulanmaz: statement degisip Rule
kosullari ayni kalabilir (Rule girdi surumune baglanmiyor).
Kanit: README Rule tablosu `entry` PROTECT ile baglanir ama entry.version saklanmaz; evaluator "reviewed girdilerin
kabul edilen Rule'lari" ile calisir (satir ~2570).
Oneri: Rule'a `entry_version` ekle, girdi degisince Rule'u "inceleme gerekli"ye cevir; belge metnini guvenilmez
veri olarak isaretle; ajan taslaklarina kaynak (agent) alani ekle.

### 28-15 | dusuk | guven: yuksek
Dosyalar: README.md:2499-2503, knowledge/views.py:25-40
Aciklama: Dosya `inline` PDF olarak ayni origin'den sunulur; yuklenen PDF kullanici kontrollu. Cache-Control
dogru, ama `Content-Security-Policy: sandbox` / `X-Content-Type-Options` bu view'de ayri verilmez (nosniff
SecurityMiddleware'e bagli). Dosya silindiginde (soft delete) depolamada kalir (kasitli) ama temizleme/saklama
politikasi yok; sureli silinen belgelerin PDF'leri sonsuza dek MEDIA_ROOT'ta kalir.
Kanit: views.py:37-39 yalniz Cache-Control ayarlanir.
Oneri: response'a `Content-Security-Policy: sandbox` ekle; silinen belge dosyalari icin saklama suresi belirle.

### 28-16 | info | guven: yuksek
Dosyalar: README.md:2559-2562, knowledge/screens.py:21-25, templates/knowledge/entry_form.html
Aciklama: Dokuman/kod tutarsizligi kucuk notlari: README "Review tab of its dialog" der ve form sablonu bunu
saglar (dogru); README'nin ajan bolumunde `knowledge_rules` tablosu "yok" olarak isaretli, ama
`Topic` aciklamasi ve form yardim metni "AI agents will read ..." diye mevcut gibi yazar. Ek olarak
`DocumentPage.screen` ozelligi yalniz sablonda kullanilir; testlerde dogrudan kapsami yok.
Kanit: models/common.py:15-17 docstring; forms/entry.py:131 yardim metni.
Oneri: Kullaniciya gorunen metinde "gelecekte" ifadesi kullan.

### 28-17 | dusuk | guven: orta
Dosyalar: knowledge/tests/*.py (test_entries.py:218-263, test_search.py, test_languages.py)
Aciklama: Eksik test kapsami: belge degisince review'un durumu (28-1), el girisli metinde "CO₂" arama (28-2),
Turkce buyuk harf (28-3), parola korumali/bozuk PDF'in 20MB ust siniri, sayfa araligi dogrulamasi (28-4),
cok sayfali PDF'te `matching_pages` limiti.
Kanit: test_search.py ve test_entries.py test adlari bu senaryolari icermez.
Oneri: Yukaridaki senaryolar icin regresyon testleri ekle.
