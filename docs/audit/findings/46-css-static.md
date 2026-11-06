# 46 - CSS ve statik dosyalar denetimi

Uzman alani: css-static (tutarsizlik, olu stil, responsive, ikonlar, cache busting). Kapsam: `static/css/*.css` (8 dosya, 2506 satir), `static/favicon.svg`, `templates/icons/*.svg`, `core/templatetags/assets.py`, `templates/app_base.html`, `auth_base.html`, `modal_base.html`, CSS ile etkilesen `frontend/*.ts` ve `config/settings.py` statik ayarlari. Kod ve veri degistirilmedi; yalnizca okuma yapildi.

## Ozet

- 25 bulgu: 0 kritik, 0 yuksek, 8 orta, 12 dusuk, 5 bilgi.
- En somut hatalar: (1) `a:hover` kurali `<a class="button">` birincil/tehlike dugmelerinin hover rengini koyu metne cevirip kontrasti 2.1:1 / 1.5:1'e dusuruyor (26 yerde); (2) `[hidden]` ozniteligi `display` veren siniflarca eziliyor, JS'siz "gizli" Print dugmeleri ve `roster-paint` formu gorunuyor; (3) yazdirma stili yalniz `hr.css` icinde, regulatory rapor sayfasi yan menu ve ust cubukla yazdiriliyor; (4) `THIRD_PARTY.md` "tarayiciya hicbir sey gonderilmiyor" diyor ama Google Fonts CDN'den yukleniyor; (5) uretim icin statik dosya sunumu (STATIC_ROOT/depolama) tanimli degil.
- Ikonlar: 59 SVG'nin tamami kullaniliyor, kullanilan hicbir ikon eksik degil (`core/test_menu_icons.py` bunu test ediyor). Ikon sisteminde bulgu yalnizca lisans atfi.
- Cache busting (`?v=mtime`) mantik olarak calisiyor ve test edilmis (`core/tests_assets.py`), fakat her istekte dosya sistemi taramasi yapiyor.

## Incelenen alanlar

- Tum CSS dosyalari satir satir okundu: `base.css`, `app.css`, `components.css`, `auth.css`, `hr.css`, `tasks.css`, `messages.css`, `monitor.css`.
- Sablon <-> CSS sinif eslesmesi iki yonlu betikle tarandi (CSS'te tanimli ama sablonda gecmeyen; sablonda gecen ama CSS'te olmayan; sayfa-ozel CSS'in yuklenmedigi sablonlar).
- Dinamik sinif uretimi (`badge-{{ status }}`, `tone-N`, `wq-*`, `depth-N`) model enum'lariyla karsilastirildi.
- CSS degiskenleri (tanimli/kullanilan), z-index olcegi, `!important`, `100vh`, breakpoint listesi, `[hidden]` etkilesimi, `@media print`, `forced-colors`, `prefers-reduced-motion`.
- Kontrast hesaplari (WCAG) paletin ana renkleri icin.
- `core/templatetags/assets.py`, `app_base.html`, `auth_base.html`, `modal_base.html`, `water_calculator_report.html` head/script yapisi, `config/settings.py` statik ayarlari, `.gitignore`, `THIRD_PARTY.md`, README statik/derleme bolumleri.
- `frontend/nav-boot.ts`, `shell.ts`, `windows.ts`, `designer.ts` icindeki CSS ile etkilesen satirlar (z-index, inline style, matchMedia).

## Incelenmeyen alanlar

- Tarayicida gorsel/render dogrulamasi (ekran goruntusu, gercek cihaz) yapilmadi; responsive ve kontrast bulgulari kod ve hesaba dayanir.
- TypeScript davranisi (`frontend/`) yalnizca CSS ile ilgili kisimlariyla okundu; JS mantik denetimi baska uzmanin alani.
- Sunucu tarafi SVG uretimi (`farm/water/charts.py`) yalnizca boyut sabitleri icin okundu.
- `static/js/` repoda yok (derlenmedi); derlenmis cikti denetlenemedi.
- Uretim web sunucusu/CDN yapilandirmasi repoda bulunmadigindan Cache-Control basliklari denetlenemedi.

## Bulgular

### 46-1 - `a:hover` kurali `<a class="button">` hover rengini bozuyor (kontrast 2.1:1)
- Onem: orta
- Guven: yuksek
- Dosyalar: `static/css/base.css:143-144`, `static/css/base.css:110-129`, `static/css/components.css:30-31`
- Aciklama: `a:hover { color: var(--speck) }` ozgullugu (0,1,1); `.button { color: var(--white) }` ozgullugu (0,1,0). `.button:hover` yalniz `background` degistirdigi icin, `<a class="button ...">` uzerine gelinince metin koyu (`#232920`) olur. `.button-ghost`, `.menu-item`, `.rail-link` icin bu elle yamanmis (`color: var(--speck)` hover'da), birincil ve tehlike dugmeleri icin yamanmamis.
- Kanit: `<a class="button` ile baslayan, ghost olmayan 26 sablon kullanimi (ornegin `templates/tasks/task_list.html:27`, `templates/hr/today.html:16`, `templates/registration/password_reset_done.html:7`). Hesap: `#232920` uzerinde `#9A3650` = 2.14:1; `.button-danger:hover` `#7E1D24` uzerinde = 1.48:1.
- Oneri: `.button:hover { color: var(--white) }` ekle (ve `.button-ghost` icin ayri kalsin) veya `a:not(.button):hover` kullan.

### 46-2 - `hidden` oznitelgi `display` veren siniflarca eziliyor (JS'siz progressive enhancement bozuk)
- Onem: orta
- Guven: yuksek
- Dosyalar: `static/css/components.css:5-19`, `static/css/hr.css:46`, `templates/hr/roster.html:12,16`, `templates/hr/overview.html:14`, `templates/hr/orgchart.html:9`, `templates/reports/report_print.html:19`, `templates/farm/water_calculator_report.html:23`
- Aciklama: Sablonlar `data-print hidden` ve `data-roster-paint hidden` ile "JS yoksa gizli" niyetini yaziyor (`frontend/components.ts:13`, `frontend/roster.ts:5` yorumlari). Ancak `.button-inline`/`.button-ghost` `display:inline-flex`, `.roster-paint` `display:flex` veriyor; yazar CSS'i tarayicinin `[hidden]{display:none}` kuralini ezer. Global `[hidden]` kurali yok; yalniz `.tabs`, `.tab-panel`, `.link-row`, `.menu-panel` icin tek tek var (`components.css:186,222,294`, `app.css:309`).
- Kanit: `grep "\[hidden\]" static/css/*.css` yalniz bu 4 sonuc. `roster.html:16` `<form class="roster-paint" ... hidden>` JS'siz gorunur ve calismaz.
- Oneri: `base.css`'e `[hidden] { display: none !important; }` ekle; tek tek `[hidden]` kurallari kaldirilabilir.

### 46-3 - Yazdirma stili yalniz `hr.css` icinde; regulatory rapor sayfasi menu ve ust cubukla yazdiriliyor
- Onem: orta
- Guven: orta
- Dosyalar: `static/css/hr.css:41-45`, `static/css/components.css:1296-1298`, `templates/reports/report_print.html:1-19`, `core/crud.py:92`
- Aciklama: `.rail, .topbar, .scrim` gizleme yalniz `hr.css` `@media print` blogunda; `hr.css` sadece HR sayfalarinda yukleniyor. `report_print.html` `app_base.html`'i genisletiyor, bir "Print" dugmesi var, ama `components.css` print blogu yalniz `.regulatory-print .form-actions` gizliyor; sticky `.rail` (100vh) ve `.topbar` ciktida kalir. Yazdirma stili ayrica sayfa-ozel dosyaya gomulu oldugundan tutarsiz.
- Kanit: `grep "@media print"` -> `components.css:803,1296`, `hr.css:41`; `report_print.html` yalniz `base.css/app.css/components.css` (app_base) yukler.
- Oneri: Kabuk gizleme kuralini `app.css` icine tasi (tum sayfalar icin), `hr.css`'te yalniz HR'a ozgu olanlar kalsin.

### 46-4 - Google Fonts harici CDN'den yukleniyor; `THIRD_PARTY.md` ile celisiyor
- Onem: orta
- Guven: yuksek
- Dosyalar: `templates/app_base.html:8-10`, `templates/auth_base.html:7-9`, `THIRD_PARTY.md:3`, `static/css/base.css:15`
- Aciklama: `THIRD_PARTY.md` "Nothing from a package registry is shipped to the browser" diyor; fakat her sayfa `fonts.googleapis.com` ve `fonts.gstatic.com`'a baglaniyor (Bricolage Grotesque). Sonuclari: kullanici IP'si ucuncu tarafa gider (AB/Norvec veri koruma acisindan beyan gerektirir), cevrimdisi/kapali aginda font yuklenmez (system-ui yedegi kullanilir), render-engelleyici harici stil, ucuncu taraf listesinde font (OFL) lisansi yok. `water_calculator_report.html` fontu hic yuklemiyor (tutarsiz).
- Kanit: yukaridaki `<link>` satirlari; `THIRD_PARTY.md` fontu anmiyor.
- Oneri: Fontu `static/fonts/` altinda barindir (woff2 + `@font-face`), `THIRD_PARTY.md`'ye ekle; ya da en azindan belgele.

### 46-5 - Uretim icin statik dosya sunumu tanimli degil
- Onem: orta
- Guven: orta
- Dosyalar: `config/settings.py:173-174`, `config/settings.py:28`, `README.md:2980,3013`, `.gitignore`
- Aciklama: `STATIC_URL` ve `STATICFILES_DIRS` var; `STATIC_ROOT`, `STORAGES['staticfiles']`, whitenoise veya benzeri yok; README `collectstatic`/statik sunum/Cache-Control'e hic deginmiyor (`grep collectstatic` bos). `static/js/` (derlenmis TS) commit edilmiyor ve repoda CI is akisi yok (`.github` yok): `npm run build` unutulursa `module_map` bos import map uretir ve sayfalar sessizce JS'siz kalir. `DEBUG` varsayilani `'1'`.
- Kanit: `grep -n "STATIC_ROOT\|whitenoise\|collectstatic" config README.md docs` bos; `ls .github` yok.
- Oneri: Dagitim notu ekle (build + collectstatic + sunucu/CDN Cache-Control: `?v=` ile uzun omur), derleme eksikse bir sistem kontrolu/uyari ver.

### 46-6 - `.links` sinifi iki dosyada farkli amacla tanimli (marj sizintisi)
- Onem: dusuk
- Guven: yuksek
- Dosyalar: `static/css/base.css:136-139`, `static/css/components.css:290`, `templates/core/widgets/link_list.html:2`, `templates/registration/login.html:13`
- Aciklama: `base.css` `.links { margin:1.5rem 0 0; font-size:.9375rem }` giris sayfasi baglantilari icin; `components.css` ayni isimle `LinkList` widget'ini (`display:grid; gap`) tanimliyor. Widget `margin-top:1.5rem` ve kucuk font devralir (istenmeyen bosluk). `auth_base` components.css yuklemedigi icin giris sayfasinda catisma yok, uygulama kabugunda var.
- Oneri: Biri yeniden adlandirilsin (`.auth-links`).

### 46-7 - `.card-grid` iki farkli yerlestirme icin kullaniliyor
- Onem: dusuk
- Guven: yuksek
- Dosyalar: `static/css/components.css:73-80`, `static/css/monitor.css:152` (`.card-grid { --row; grid-template-columns: repeat(12...) }`), `templates/farm/site_list.html:6`, `templates/monitoring/_card.html:22`
- Aciklama: Ayni sinif adi hem site kartlari (auto-fill) hem izleme kartinin 12 sutunlu widget izgarasi. Calisma, `monitor.css`'in `components.css`'ten sonra yuklenmesine ve her ozelligin yeniden yazilmasina bagli (kirilgan). `components.css`'teki `list-style/padding/margin` monitor `div`'ine de uygulanir.
- Oneri: Izleme tarafini `.monitor-widgets` gibi ayri adlandir.

### 46-8 - Hareketli pencereler: CSS `z-index:40` JS tarafindan 11+ ile eziliyor (ust cubugun ve cekmecenin altinda kalir)
- Onem: dusuk
- Guven: orta
- Dosyalar: `static/css/monitor.css:39`, `frontend/windows.ts:55,106-108,173`, `static/css/app.css:228`, `static/css/components.css:1129`
- Aciklama: `.monitor-window { z-index: 40 }` ama `windows.ts` `let top = 10` ile baslayip her `raise()`'te inline `z-index = 11, 12, ...` atiyor (acilista `raise` cagriliyor, satir 173). Inline deger CSS'i ezer; sonuc sticky `.topbar` (30) ve `.drawer` (45) altinda kalan pencereler. CSS'teki 40 olu deger. Z-index olcegi (1,2,3,30,40,45,50,60,100) token degil, dosyalara dagilmis ve yorumla elle senkron.
- Oneri: JS'te `top`'u CSS tabanindan (ornegin `getComputedStyle`) baslat veya `--z-window` token'i kullan.

### 46-9 - Dinamik rozet siniflari (`badge-leave-*`, `badge-state-*`) icin CSS yok; flash varyantlari eksik
- Onem: dusuk
- Guven: yuksek
- Dosyalar: `templates/hr/leave_list.html:31`, `templates/hr/_board.html:21`, `templates/app_base.html:100`, `templates/modal_base.html:14`, `static/css/app.css:448` (`.flash-error` tek varyant)
- Aciklama: Izin durumu (`pending/approved/rejected/cancelled`) ve bugunku pano durumu (`upcoming/present/late/not_in/absent/on_leave/done`) rozetleri icin hic kural yok; bunlar renksiz `.badge` olarak cikar. CSS'in kendi ilkesi "yalniz sorunlar renk alir" (`components.css:138`) ile celisir: `rejected`, `late`, `absent` ayirt edilemez. Benzer sekilde mesaj turleri (43 `success`, 8 `warning`, 1 `info` kullanimi) icin `.flash-success/-warning/-info` yok; uyari mesaji basarili mesajla ayni gorunur, yalniz `.flash-error` farkli.
- Kanit: `grep "badge-leave\|badge-state\|flash-warning" static/css` bos.
- Oneri: `.badge-leave-rejected`, `.badge-state-late/absent`, `.flash-warning` vb. ekle.

### 46-10 - Sayfa-ozel CSS yuklenmeyen sablon: `experiment_detail.html` `plain-list` kullaniyor
- Onem: dusuk
- Guven: yuksek
- Dosyalar: `templates/experiments/experiment_detail.html:31`, `static/css/hr.css:15`
- Aciklama: `.plain-list` yalniz `hr.css`'te tanimli, ama deneyler sayfasi `hr.css` yuklemiyor; liste isaretli/bosluksuz stil almaz. Genel yardimci sinif ozel dosyaya konmus.
- Oneri: `.plain-list`'i `components.css`'e tasi.

### 46-11 - Form alani kenari (sage) kontrasti 1.68:1
- Onem: dusuk
- Guven: orta
- Dosyalar: `static/css/base.css:46-50`, `static/css/components.css:64,495,1095,1192,1222`
- Aciklama: Girdi/select/textarea kenarligi `1.5px solid var(--sage)` (`#C3CBB2`) beyaz zemin uzerinde 1.68:1; WCAG 1.4.11 kullanici arayuzu bilesenleri icin 3:1 ister. Alan sinirlari odak disinda zor secilir (hover `--muted` ile 5.4:1'e cikiyor, ama normal hal degil).
- Oneri: Kenarlik rengini en az 3:1 yap (ornegin `#8A9479`).

### 46-12 - Opaklikla azaltilmis metinler dusuk kontrastli
- Onem: dusuk
- Guven: orta
- Dosyalar: `static/css/components.css:958` (placeholder `opacity:.55`), `:870` (`.faint`), `:980-990` (`.null`, 11px), `:993` (`.bool-false`)
- Aciklama: Hesaplanan kontrastlar (beyaz zemin): `.grid-filter` placeholder 2.37:1, `.bool-false` 2.59:1, `.null` rozeti 3.56:1 (11px), `.faint` 3.88:1. Metin icin 4.5:1 gerekir (placeholder ve ikincil metin dahil).
- Oneri: `opacity` yerine yeterli kontrastli bir token kullan.

### 46-13 - Renk token'lari eksik: ayni degerler yuzlerce kez sabit yaziliyor; tanimsiz degisken ve yanlis fallback
- Onem: dusuk
- Guven: yuksek
- Dosyalar: `static/css/components.css` (121 hex), `static/css/hr.css:37,48,49`, `static/css/base.css:5-17`
- Aciklama: `#7A5410` 19, `#F7E6E6` 13, `#ECECEA` 11, `#FBF0D9` 10 kez sabit; amber/kirmizi tint token'i yok. `hr.css:37` `var(--paper, #fff)` ve `:48-49` `var(--stripe-dark, #2B5F43)` tanimsiz/eski degiskenler: `--paper` hicbir yerde tanimli degil, `--stripe-dark` tanimli (`#9A3650`) oldugu icin yesil `#2B5F43` fallback'i hic calismaz ama paletle de ilgisiz (eski temadan kalma). Grafik renkleri (`#2563EB`, `#EF4444` vb.) Tailwind paletinden ayri ikinci bir palet; yorumlar "source's tokens" diyor.
- Oneri: `--warn-bg/--warn-fg/--error-bg` token'lari tanimla; olu fallback'leri temizle.

### 46-14 - `form-grid-*` kurallari site formunun alan kimliklerine bagli ve baska formlara sizar
- Onem: dusuk
- Guven: orta
- Dosyalar: `static/css/components.css:228-247`, `:384-388`, `templates/crud/form.html:32`, `farm/forms/tank.py:90`
- Aciklama: Genel `components.css` icinde `#id_timezone`, `#id_street`, `#id_site_manager`, `#id_city`, `#id_latitude` vb. site alanlarina ozel `:has()` secicileri var. Sinif adi `form-grid-{{ tab.key }}` oldugundan, ayni anahtara (`location`) sahip tank formunun sekmesi de 6 sutunlu `.form-grid-location` duzenini alir (tesadufen calisir). Mobilde `grid-column: 1 / -1 !important` kullaniliyor (tek `!important` bu nedenle).
- Oneri: Site'a ozgu kurallari `site_form` kapsamina al veya veri-oznitelik ile ifade et.

### 46-15 - SVG grafik metin boyutlari dar ekranda/3 sutunda 8px altina iner
- Onem: dusuk
- Guven: dusuk
- Dosyalar: `static/css/components.css:682-686`, `:823-824`, `farm/water/charts.py:166`
- Aciklama: pH grafikleri `viewBox 0 0 400 260` ve `width:100%`; tick metinleri `10px`, eksen `11px`, etiket `10px` viewBox birimi. Telefonda (~290px) olcek ~0.72, `>=1400px`'te 3 sutunda ~280px sutun olcek ~0.7: etkin yazi 7px civari. Tarayicida dogrulanmadi.
- Oneri: Dar ekranda grafik minimum genislik + yatay kaydirma veya font-size'i olcege gore buyut.

### 46-16 - Breakpoint'ler tutarsiz (px/rem karisik, 8 farkli esik) ve JS ile esitlenmemis
- Onem: bilgi
- Guven: yuksek
- Dosyalar: `static/css/app.css:370`, `static/css/auth.css:107` (`48rem`), `static/css/monitor.css:77` (639), `:236` (799), `static/css/messages.css:104` (899), `static/css/components.css:667,671,725` (720/900/1400), `frontend/shell.ts:6`, `frontend/windows.ts:29`, `frontend/nav-boot.ts:5` (1100)
- Aciklama: Kabuk `max-width:767px`, auth `max-width:48rem` (=768px, dahil): tam 768px'te auth mobil, kabuk masaustu duzeninde. JS `matchMedia` degerleri CSS ile elle esitlenmis (yorum/ortak kaynak yok); rail otomatik daraltma esigi 1100 yalniz JS'te.
- Oneri: Ortak breakpoint tablosu/yorum; auth'u `767px`e esitle.

### 46-17 - `100vh` kullanimi mobil adres cubugunda tasma yapar
- Onem: dusuk
- Guven: orta
- Dosyalar: `static/css/app.css:61,71`, `components.css:456,465,486-487,901`, `messages.css:8`, `auth.css:7`, `monitor.css:45,85`
- Aciklama: `dvh/svh` hic kullanilmiyor. Sticky `.rail` (`height:100vh`), tam ekran `.modal` (mobil `height:100vh`), sohbet yuksekligi ve izleme alt sayfasi (`70vh`) mobil tarayicilarda dinamik arac cubugu yuzunden alt kismi (modal eylem dugmeleri, rail alt metni) gorunur alanin disinda kalabilir.
- Oneri: `100dvh` (yedek `100vh` ile).

### 46-18 - Tek parca `components.css` (1298 satir) her sayfada; bolme stratejisi tutarsiz
- Onem: bilgi
- Guven: yuksek
- Dosyalar: `static/css/components.css:606-856` (hesap makinesi/grafik), `:868-1036` (veritabani gorunumu), `templates/app_base.html:13-15`
- Aciklama: HR, gorev, mesaj, izleme kendi dosyasinda `extra_head` ile yukleniyor ama su/hesap makinesi, veritabani gorunumu, rapor ve depo kurallari tum sayfalara giden `components.css`'te. Her sayfa 3 render-engelleyici CSS + 1 harici font; minify/birlestirme yok.
- Oneri: Yukleme stratejisini tek kurala bagla (modul basina dosya) ve uretim derlemesinde birlestir.

### 46-19 - `?v=mtime` surumleme: her istekte dosya sistemi taramasi ve dagitima bagli degisken surum
- Onem: dusuk
- Guven: yuksek
- Dosyalar: `core/templatetags/assets.py:21-26`, `:36-44`
- Aciklama: `versioned()` her `{% asset %}` cagrisinda `finders.find()` ve `os.path.getmtime` yapar (sayfa basina ~8-10 kez); `module_map` her render'da tum finder'lari `list()` ile dolasir ve tum `js/*.js` dosyalarini sayar. Onbellek yok. Ayrica surum dosya mtime'ina bagli: git checkout/imaj olusturma mtime'i degistirir (icerik ayni olsa bile tum istemci onbellegi gecersizlesir) ve coklu sunucuda farkli checkout zamanlari farkli `?v=` uretir.
- Oneri: Surumu icerik hash'i veya surumden uret; `lru_cache`/DEBUG disi onbellek; veya `ManifestStaticFilesStorage`.

### 46-20 - Favicon yalniz metin tabanli SVG; PNG/ico/apple-touch yok; `/favicon.ico` 404
- Onem: dusuk
- Guven: orta
- Dosyalar: `static/favicon.svg`, `templates/app_base.html:11`, `templates/auth_base.html:10`
- Aciklama: SVG `font-family="system-ui"` ile "S" harfi cizen `<text>`; yazi tipi platforma gore degisir ve harf yol olarak cizilmemis. `.ico`/PNG/`apple-touch-icon`/`theme-color` yok; tarayici `/favicon.ico` istedigi icin 404 gunlugu olusur (repo icinde bu yola rota yok).
- Oneri: Harfi `<path>`'e cevir, ek ikon boyutlari ekle.

### 46-21 - Ikon seti (Lucide) icin lisans atfi yok
- Onem: dusuk
- Guven: orta
- Dosyalar: `templates/icons/*.svg`, `README.md:3388`, `THIRD_PARTY.md:1-14`
- Aciklama: README ikonlarin "Lucide icons" oldugunu soyluyor; `THIRD_PARTY.md` yalniz gelistirme araclarini listeliyor ve tarayiciya gonderilen bir sey olmadigini iddia ediyor. Lucide ISC lisansli; telif/lisans metni dagitilmiyor. (Ikonlarin Lucide oldugu README'ye dayanir, dosya basliklarinda dogrulanmadi.)
- Oneri: `THIRD_PARTY.md`'ye Lucide (ISC) ve font girdisi ekle.

### 46-22 - Olu/yinelenen kurallar ve bayat yorumlar
- Onem: bilgi
- Guven: yuksek
- Dosyalar: `static/css/components.css:178` (yorum `site-form.js` - dosya yok), `:538` ve `:884-891` (`.data-table tbody th` iki kez), `:589` ve `:1196` (`.is-voided td` iki kez), `static/css/app.css:405-407` (`.rail` reduced-motion, `base.css:155-157` global kuralla yinelenen), `static/css/monitor.css:1-2` ("no colour of its own" ama sabit `rgba` golge var), `static/css/components.css:1293` (`.number`) vs `:544` (`.num`)
- Aciklama: Gercek anlamda olu sinif tespit edilen yok (96 aday sinifin tamami dinamik uretilen `badge-*`, `deffeyes-*`, `ph-*`, `tone-N`, `depth-N`, `audit-*` onekleri veya form-grid anahtarlari; `form-grid-basic/-contact` `site.py` anahtarlariyla eslesiyor). Ancak yukaridaki yinelemeler ve tutarsiz adlandirma (`num`/`number`) mevcut. README dosya tablosu (`README.md:3387-3392`) `hr.css`, `tasks.css`, `messages.css`, `monitor.css`'i listelemiyor.
- Oneri: Yinelenenleri birlestir, yorumu duzelt, README tablosunu tamamla.

### 46-23 - `button-danger-text` hover'da koyu renge doner
- Onem: dusuk
- Guven: orta
- Dosyalar: `static/css/tasks.css:32`, `static/css/components.css:27`
- Aciklama: `.button-ghost:hover { color: var(--speck) }` (0,2,0) `.button-danger-text { color: var(--error) }` (0,1,0) kuralini hover'da ezer; tehlike metni ustune gelince kirmizi rengini kaybeder. Ayrica tanim yalniz `tasks.css`'te (genel bir dugme varyanti sayfa-ozel dosyada).
- Oneri: `.button-ghost.button-danger-text:hover` tanimla, `components.css`'e tasi.

### 46-24 - Sekme cubugu `overflow-x:auto` ile alt gosterge cizgisi kesilebilir
- Onem: dusuk
- Guven: dusuk
- Dosyalar: `static/css/components.css:179-185`, `:201-208`
- Aciklama: `.tabs { overflow-x:auto }` hesaplanan `overflow-y`'yi de `auto` yapar; secili sekmenin `::after`'i `bottom:-1px` tasar, bu da bazi tarayicilarda 1px dikey kaydirma cubugu/kesme uretebilir. Tarayicida dogrulanmadi.
- Oneri: `overflow-y: hidden` veya `padding-bottom:1px`.

### 46-25 - Dar/genis ekran yerlesimi: icerik sola yasli, ust baslik kesiliyor, satir ici stiller
- Onem: bilgi
- Guven: dusuk
- Dosyalar: `static/css/app.css:349-353` (`.content { max-width:1520px }`, `margin:auto` yok), `static/css/app.css:251-260` (`.topbar h1` nowrap+ellipsis), `templates/farm/production_units.html:112`, `templates/farm/_unit_capacity.html:4`, `monitoring/cards/render.py:40`
- Aciklama: Cok genis ekranda (>1520px + menu) icerik ortalanmaz. Telefonda `h1` tek satir ve ellipsis; uzun (TR/NB) basliklar kesilir, tam metne ulasmak icin `title` yok. Kapasite cubugu ve izleme widget yerlesimi inline `style=` kullaniyor; ileride siki CSP (`style-src`) konursa kirilir (su an CSP yok).
- Oneri: Gerekirse `margin-inline:auto`; baslikta 2 satira izin ver; inline stilleri CSS ozel ozellikleri/siniflariyla degistir.
