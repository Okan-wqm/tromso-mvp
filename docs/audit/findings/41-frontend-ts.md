# 41 - frontend-ts denetimi (frontend/ TypeScript + grid)

## Özet

Kapsam: `frontend/*.ts`, `frontend/grid/*.ts`, `frontend/test/*`, `package.json`, `tsconfig*.json`, `scripts/mark-esm.mjs` ve bunları yükleyen şablonlar. Kod genel olarak disiplinli: `strict`, `noUnused*`, `noImplicitReturns` açık; `grid/` kütüphanesi saf fonksiyon, değişmez veri ve sunucu ile paylaşılan test vektörleriyle (`monitoring/tests/layout_vectors.json`) korunuyor. Ağırlıklı sorunlar kart tasarımcısında (`designer.ts`): kısmen kontrolsüz tip dönüşümleri, bozuk veride kullanıcı metninin sessizce ezilmesi, "kaldırıldı" duyurusunda `undefined`, çalışmayan Ctrl+Shift+Z ve hata yönetimi boşlukları. `components.ts` içindeki Modal, `FormData(form)` kullandığı için gönderen düğmenin `name/value` değerini kaybediyor (`experiments` formundaki `action=randomise` / `_draft` ile ilişkili). `poll.ts` ve `announce.ts` erişilebilirlik ve dayanıklılık açısından küçük boşluklar içeriyor. Derleme/test altyapısında repo içinde CI tanımı yok.

Not: bu ortamda `node_modules` yok; `npm test` ve `tsc` ÇALIŞTIRILAMADI. Tüm bulgular statik okumaya dayanır.

## İncelenen alanlar
- `frontend/designer.ts`, `grid/layout.ts`, `grid/history.ts`, `grid/keyboard.ts`, `grid/types.ts`
- `frontend/poll.ts`, `announce.ts`, `windows.ts`, `components.ts`, `shell.ts`, `roster.ts`, `auth.ts`, `dom.ts`, `nav-boot.ts`, `globals.d.ts`
- Test dosyalarının yapısı (`*.test.ts`, `test/random.ts`, `test/designer.browser.test.ts` başlıkları), `package.json`, `tsconfig.json`, `tsconfig.test.json`
- İlgili şablonlar (`templates/app_base.html`, `templates/hr/roster.html`, `templates/monitoring/monitor.html`, `templates/experiments/_places.html`), `static/css/monitor.css` (poll-state, touch-action)

## İncelenmeyen alanlar
- Testlerin gerçek çalıştırılması ve `tsc` çıktısı (bağımlılık kurulu değil)
- Sunucu tarafı HTML'in kaçışlanması (XSS; başka uzmanın alanı), `monitoring/cards/validate.py` ile tam eşdeğerlik
- Tarayıcı içi davranış (gerçek ekran okuyucu, dokunmatik), CSS'in tamamı
- `static/js` derleme çıktısı, `{% asset %}` / import map mekanizması

## Bulgular

### 41-1 - `catalogueOf(...)` null dönebiliyor, `designer.ts` `as Catalogue` ile bastırıyor
- Önem: medium | Güven: high
- Dosyalar: `frontend/designer.ts:96`, `frontend/grid/layout.ts:32-49`
- Açıklama: `catalogueOf` geçersiz katalogda `null` döner (tür: `Catalogue | null`). Tasarımcı sonucu `as Catalogue` ile zorla dönüştürüyor; `jsonScript<T>` da JSON'u hiçbir doğrulama yapmadan `T` yapıyor (`designer.ts:49-51`, `'null'` JSON'u dahi `CatalogueData` sayılır).
- Kanıt: `this.cat = catalogueOf(this.data) as Catalogue;` -> sonraki `this.cat.columns` (satır 146) `TypeError` ile tasarımcıyı tamamen çökertir; hata mesajı kullanıcıya gösterilmez. Kütüphanenin "garbage in is a typed answer, never a throw" sözü burada bozuluyor.
- Öneri: `null` ise açık bir hata durumu göster (`data-designer-broken`) ve sınıfı kurma; `as` dönüşümünü kaldır; `jsonScript` sonucunu çalışma anında doğrula.

### 41-2 - Ctrl+Shift+Z ile yinele hiç çalışmıyor; Ctrl+Z tasarımcı içindeki metin alanlarının yerel geri almasını engelliyor
- Önem: medium | Güven: high
- Dosyalar: `frontend/designer.ts:365-370`
- Açıklama: Koşul `event.key === 'z' || event.key === 'y'`. Shift basılıyken `event.key` `'Z'` (büyük harf) olur, dolayısıyla Ctrl+Shift+Z/Cmd+Shift+Z koşula hiç girmez; `event.key === 'z' && !event.shiftKey` içindeki shift dalı ölü koddur. Ayrıca dinleyici `root` üzerinde olduğundan, ızgara düzeni `textarea`'sı ve denetçi `input`'larında yazarken Ctrl+Z `preventDefault` ile tarayıcının kendi geri alma işlemi yerine tasarım geçmişini geri alır.
- Kanıt: `if ((event.ctrlKey || event.metaKey) && (event.key === 'z' || event.key === 'y')) { event.preventDefault(); this.step(event.key === 'z' && !event.shiftKey ? undo : redo); }`. Tarayıcı testi yalnızca ok tuşu ve düğme geri almasını sınıyor (`frontend/test/designer.browser.test.ts:117-123`).
- Öneri: `event.key.toLowerCase()` kullan; hedef `input/textarea/select` ise dokunma; Ctrl+Shift+Z ve Ctrl+Y için test ekle.

### 41-3 - Kaldırma duyurusu "undefined" etiketiyle okunuyor
- Önem: medium | Güven: high
- Dosyalar: `frontend/designer.ts:339-349`, `frontend/grid/layout.ts:266-276`, `frontend/grid/types.ts:377-384`
- Açıklama: Silinen widget artık `history.present` içinde yoktur; `announce` `?? change` ile `Change` nesnesine düşer, `as Item` ile türü susturur. `Change` içinde `type` alanı yok, `labelOf` -> `spec?.label ?? item.type` -> `undefined`; `fill` `String(undefined)` yazar.
- Kanıt: `const item = this.history.present.find((each) => each.id === change.id) ?? change;` ... `label: this.labelOf(item as Item)`. Test şablonu `data-announce-removed="{label} removed"` kullanıyor (`designer.browser.test.ts:50`) ama silme duyurusunu sınayan bir test yok. (Çalıştırılarak doğrulanmadı; mantıksal çıkarım.)
- Öneri: `announce` için silinen öğeyi `before` düzeninden bul (ya da `Change`'e `type/bind` ekle); `as Item` dönüşümünü kaldır; "removed" için test yaz.

### 41-4 - Bozuk kayıtlı yerleşim, ilk düzenlemede sessizce ezilir; `designerBroken` bayrağı hiç temizlenmez / metin değişikliğinde sessiz kalır
- Önem: medium | Güven: high
- Dosyalar: `frontend/designer.ts:105-114`, `:280-288`, `:371-381`
- Açıklama: Başlangıç ayrıştırması başarısızsa `parsed = []` olur ve yorum "metin gerçek kalır" der. Ancak kullanıcı bir widget eklediği/geri aldığı anda `record()` `textarea.value`'yu boş/yeni düzenle üzerine yazar (satır 284); bozuk özgün metin kaybolur. `record()` `designerBroken` bayrağını temizlemez (yalnızca textarea `change` dalı siler). `textarea` `change` olayında `parse` `ok:false` dönerse (örn. şema/id hatası) hiçbir şey yapılmaz ve bayrak da set edilmez; yalnızca JSON istisnası `'shape'` yazar (bayrak sadece 'shape'e sıfırlanır, gerçek hata kodu kaybolur). "Başa dön" (`[data-designer-revert]`) da `this.initial` = `[]` olduğundan bozuk metni geri getirmez.
- Kanıt: `designer.ts:109-111`, `:284`, `:371-381` (`if (parsed.ok) {...}` else dalı yok).
- Öneri: bozuk durumda tasarımcı düzenlemelerini devre dışı bırak ya da önce özgün metni sakla; `ok:false` için `designerBroken = result.error` set et; `record()` sonrası bayrağı yönet.

### 41-5 - Önizleme isteğinde hata yönetimi: yanıt hataları sessiz, ağ hataları işlenmemiş promise reddine dönüşüyor
- Önem: medium | Güven: high
- Dosyalar: `frontend/designer.ts:452-487`
- Açıklama: `!response.ok` durumunda (403 CSRF, 400, 500) sessizce dönülür; önizleme ve sorun listesi eski haliyle kalır, kullanıcı bilgilendirilmez. `AbortError` dışındaki her hata `throw error` ile yeniden fırlatılır ve çağıran `void this.refresh()` (satır 454) bunu yakalamaz -> `unhandledrejection`. `answer.problems` için çalışma anı doğrulaması yok (`as` dönüşümü).
- Kanıt: `if (!response.ok) { return; }` ... `if (!(error instanceof DOMException && error.name === 'AbortError')) { throw error; }`. `csrfToken` form yoksa `''` döner (satır 69-72) ve bu da sessiz 403'e yol açar.
- Öneri: hata durumunda `status`/`problems` alanında çevrilmiş bir uyarı göster; `refresh` çağrısına `.catch` ekle; yanıt şeklini doğrula.

### 41-6 - `aria-invalid` boş değerle ekleniyor (`toggleAttribute`)
- Önem: low | Güven: medium
- Dosyalar: `frontend/designer.ts:515-518`, `static/css/monitor.css:231`
- Açıklama: `node.toggleAttribute('aria-invalid', bad)` özniteliği `aria-invalid=""` olarak yazar; ARIA'da boş değer "false" gibi ele alınır, yardımcı teknolojiye hata bildirilmez. CSS `[aria-invalid]` ile eşleştiği için görsel olarak çalışır, ama ekran okuyucu için etkisiz. Ayrıca öğe `button` olduğu için rolü `aria-invalid` desteklemeyebilir.
- Kanıt: satır 517-518. Sorunlar listesi ayrıca `role="status"` ile duyuruluyor (test şablonu satır 56), bu kısmen telafi eder.
- Öneri: `setAttribute('aria-invalid','true')` / `removeAttribute`; hata ilişkisini `aria-describedby` ile kur.

### 41-7 - Denetçi her değişiklikte yeniden kuruluyor: klavye odağı kayboluyor
- Önem: low | Güven: medium
- Dosyalar: `frontend/designer.ts:143-178`, `:205-257`, `:220`
- Açıklama: `render()` her çağrıda `renderInspector()` ile denetçi DOM'unu `replaceChildren` ile tümüyle değiştirir; odak yalnızca tuval içindeyse geri verilir (satır 171-173). Sayı alanında değeri yazıp Tab'a basan kullanıcıda `change` olayı tetiklenir, ardından odaklanan sonraki alan yok edilir ve odak `body`'ye düşer. Sürükleme sırasında da her `pointermove` `renderOrder` + `renderInspector` yeniden kurar (performans).
- Kanıt: `onMove` -> `this.render()` (satır 430-433) tüm denetçiyi her hareket olayında yeniden oluşturur.
- Öneri: denetçiyi yalnızca seçim/öğe değeri değiştiğinde yeniden kur, ya da odaklı alanın `data-field` anahtarına göre odağı geri ver; sürükleme sırasında yalnız tuvali güncelle.

### 41-8 - Sürükleme iptalinde `pointercancel` dinleyicisi sızıyor
- Önem: low | Güven: high
- Dosyalar: `frontend/designer.ts:434-448`
- Açıklama: `onUp` üç dinleyiciyi kaldırır; `onCancel` yalnızca `pointermove` ve `pointerup`'ı kaldırır, kendisini (`pointercancel`) kaldırmaz. Her iptal edilen jestte düğümde bir bayat `onCancel` kalır; sonraki bir `pointercancel` hepsini çağırır ve `shown`'u sıfırlayıp `render` eder. Zararı küçük ama birikimli. `lostpointercapture` de ele alınmıyor.
- Kanıt: satır 440-445.
- Öneri: `{ once: true }` ya da ortak bir `cleanup()` kullan.

### 41-9 - Seçicilere kimlik değerleri `CSS.escape` olmadan enjekte ediliyor
- Önem: info | Güven: medium
- Dosyalar: `frontend/designer.ts:159`, `:277`, `:296`, `:304`
- Açıklama: `querySelector(`.designer-item[data-id="${item.id}"]`)` ve `#designer-${id}`. Bugün `parse` kimlikleri `ID = /^[a-z][a-z0-9_-]{0,15}$/` ile sınırlıyor (layout.ts:13) ve güvenli; ama `problem.widget` (sunucudan, `showProblems` satır 501-504) için aynı garanti yok. `components.ts` aynı yerde `CSS.escape` kullanıyor -> tutarsızlık.
- Öneri: tek bir yardımcı ile `CSS.escape`.

### 41-10 - Modal, `FormData(form)` kullandığı için gönderen düğmenin `name/value` değeri ve `formaction` kaybolur
- Önem: medium | Güven: medium
- Dosyalar: `frontend/components.ts:317-322`, `templates/experiments/_places.html:30,50`, `templates/experiments/_design.html:42`, `experiments/resources.py:247`
- Açıklama: Submit dinleyicisi `new FormData(form)` ile POST yapar; `event.submitter` FormData'ya eklenmez. Şablonlarda `name="action" value="randomise|save"` ve `name="_draft"` düğmeleri var; sunucu `request.POST.get('action') == RANDOMISE` ile karar veriyor. Modal içinde açılan formda "Randomise" ile "Save places" ayırt edilemez. Ayrıca `form.action` ve `form.method` okunuyor; `formaction/formmethod` ve `<form method="dialog">` ele alınmıyor. Formun `action` adında bir alanı varsa `form.action` bir elemana dönüşür (DOM clobbering).
- Kanıt: `void this.load(form.action, { method: 'POST', body: new FormData(form) });`. Hangi formların fiilen modalda açıldığı (data-modal bağlantısı) kodda tam doğrulanmadı.
- Öneri: `new FormData(form, event.submitter)` (modern tarayıcılar destekler); `getAttribute('action')` kullan.

### 41-11 - `Modal.load` ağ hatasını yakalamıyor, istekler yarışabilir
- Önem: medium | Güven: high
- Dosyalar: `frontend/components.ts:333-366`, `:304-310`, `:321`, `:204`
- Açıklama: `fetch` etrafında try/catch yok; çağrılar `void this.load(...)` olduğundan ağ kesintisinde işlenmemiş reddedilme olur, diyalog açılmaz/değişmez, kullanıcıya geri bildirim yok. 5xx yanıtları da düz `innerHTML` olarak diyaloğa basılır (yalnızca 403 özel işleniyor). Eşzamanlılık denetimi yok: art arda tıklamada iki yanıt sırası belirsiz yarışır; `AbortController` yok. `X-Modal-Load` zinciri sınırsız özyinelemelidir.
- Kanıt: `const response = await fetch(url, {...options, credentials: 'same-origin', headers: { 'X-Modal': '1' }});` (headers `options.headers`'ı ezer). Giriş yönlendirmesi `pathname.startsWith('/accounts/login')` ile sabit kodlu.
- Öneri: try/catch + çevrilmiş hata metni (`label()`), `AbortController`, özyineleme sınırı, `response.ok` kontrolü.

### 41-12 - `init()` zincirinde tek `required` hatası kalan tüm başlatmaları durduruyor
- Önem: low | Güven: high
- Dosyalar: `frontend/components.ts:125-131`, `:283-294`, `:361`
- Açıklama: `initRequires` `required(...)` ile eksik hedefte `throw` eder. `init()` tüm alt başlatıcıları sırayla çağırdığı için sonraki `initAutosubmit`, `initDependents`, `initRefresh`, `initLinkLists`, `initOmitEmpty`, `initPrint` çalışmaz. Modal içinde `init(this.content)` istisna fırlatırsa `showModal()` hiç çağrılmaz (satır 361-362) ve kullanıcı sessizce takılır. "Eksik öğe şablon hatasıdır, yüksek sesle başarısız ol" kararı bilinçli ama etkisi tüm sayfa davranışına yayılıyor.
- Öneri: her başlatıcıyı try/catch ile yalıtıp `console.error` yap; modal için `showModal` önce çağrılsın.

### 41-13 - `data-uppercase`: desteklenmeyen girdi türlerinde `setSelectionRange` istisna fırlatır
- Önem: low | Güven: low
- Dosyalar: `frontend/components.ts:73-81`
- Açıklama: `type=email/number` gibi girdilerde `setSelectionRange` `InvalidStateError` fırlatır. Ayrıca IME bileşimi (`isComposing`) sırasında değer yeniden yazılır. Şablonlarda hangi türlerde kullanıldığı doğrulanmadı.
- Öneri: `try/catch` ve `isComposing` kontrolü.

### 41-14 - Yoklama: her yönlendirme "gone" sayılıyor
- Önem: low | Güven: medium
- Dosyalar: `frontend/poll.ts:193-196`, `:313`
- Açıklama: `response.redirected` doğrudan "kapsam dışı/oturum bitti" kabul edilir; yorumda "giriş sayfasına yönlendirme" deniyor ama hedef denetlenmiyor. Eğik çizgi ekleme (APPEND_SLASH), http->https veya dil önekine yönlendirme gibi zararsız yönlendirmeler yoklamayı kalıcı durdurur ve pencereyi kapatır (`windows.ts:178`). `components.ts:335` giriş yolunu kontrol ediyor; iki yer tutarsız.
- Öneri: yönlendirme hedefinin `pathname`'ini giriş yoluyla karşılaştır (ortak yardımcı).

### 41-15 - Sekme görünür olunca tüm izlenen öğeler aynı anda istek atıyor
- Önem: low | Güven: medium
- Dosyalar: `frontend/poll.ts:117-123`, `:187`
- Açıklama: Başlık "ekranlar hizalanmasın" diye rastgele sapma uyguluyor, fakat `shown()` her izlenen öğenin `refresh()`'ini hemen çağırır; gizli sekmede zamanlayıcı zinciri de kasıtlı kopar (satır 187, `schedule` çağrılmadan dönüş). Sonuç: görünür olduğunda eşzamanlı istek patlaması (grid, pencereler, mesaj listesi) ve duvar ekranı sekmesi arka plandayken hiç güncellenmez.
- Öneri: `shown()` içinde küçük rastgele gecikme; duvar ekranı için görünürlük politikasını belgele.

### 41-16 - `data-autosubmit` iki dosyada farklı yorumlanıyor
- Önem: low | Güven: high
- Dosyalar: `frontend/poll.ts:345`, `frontend/components.ts:135-137`
- Açıklama: `poll.ts` `live` formunda `[data-autosubmit]` taşıyan HER öğeyi "formu kendisi gönderir" diye atlar; `components.ts` yalnızca `select[data-autosubmit]` ile bunu gerçekleştirir. Bir onay kutusu/metin alanında `data-autosubmit` kullanılırsa ne canlı yenileme ne gönderim olur.
- Öneri: seçiciyi tek yerde tanımla (`select[data-autosubmit]`).

### 41-17 - Duvarda "stale/gone" ve kritik kart bildirimi: yalnızca CSS, canlı bölge yok
- Önem: medium | Güven: medium
- Dosyalar: `frontend/poll.ts:143-147`, `static/css/monitor.css:4-8`, `frontend/announce.ts:11-13,289-304`
- Açıklama: Sunucuya ulaşılamadığında (`stale`) ve erişim kaybında (`gone`) uyarı `::before` sözde öğesiyle yazdırılıyor; bu içerik canlı bölge değildir, ekran okuyucuya duyurulmaz ve veri eskirken kullanıcı bunu bilemez. `announce.ts` ise yalnızca "kötüleşen" kartlar için konuşur; ilk yüklemede kritik olan, yeni eklenen (`inserted`) ya da tüm içeriği yeniden yazan yedek yolda (poll.ts:173, `poll:merged` olayı yok) kritik kartlar sessizdir. Kod yorumu bunu bilinçli tasarım olarak belirtiyor, ama çiftlik izleme (su kalitesi alarmı) bağlamında risklidir.
- Öneri: `stale/gone` için `role="status"` canlı bölgesinde çevrilmiş metin; eklenen kritik kartlar için de duyuru düşün.

### 41-18 - Duyuru: aynı metin tekrar okunmaz; bekleyen zamanlayıcılar birikir
- Önem: low | Güven: medium
- Dosyalar: `frontend/announce.ts:279-288`
- Açıklama: `node.textContent = out` aynı metin art arda atandığında DOM değişmediğinden ekran okuyucular tekrar okumaz (aynı kart iyileşip yeniden kritikleşirse aynı cümle). Ayrıca pencere dolmadan birden çok `speak` çağrısı, her biri bekleyen metin varken yeni `setTimeout` kurar (en fazla bir süre sonra boşalır ama gereksiz zamanlayıcılar).
- Öneri: metne görünmez bir ayırıcı ekle ya da önce boşalt; tek zamanlayıcı tut.

### 41-19 - `localStorage` içeriği doğrulanmadan `Places` türüne dönüştürülüyor
- Önem: low | Güven: high
- Dosyalar: `frontend/windows.ts:57-64`, `:95-102`
- Açıklama: `parsed as Places` yalnızca "nesne mi" kontrol eder; değerler `Box` olmayabilir. `box.w * window.innerWidth` `NaN` üretir, `Math.max(MIN_WIDTH, NaN)` `NaN` döndürür ve `style.width = 'NaNpx'` yok sayılır; pencere boyutsuz kalır. Eski/başka sürüm verisinde olası.
- Öneri: sayı alanlarını `Number.isFinite` ile doğrula.

### 41-20 - `load()` içindeki yorum ile davranış çelişiyor
- Önem: info | Güven: high
- Dosyalar: `frontend/windows.ts:125-129`
- Açıklama: Yorum "bring it forward, close this one" der; kod yalnızca öteki pencereyi öne alır, mevcut pencereyi kapatmaz ve bağlantı tıklamasını yutar (kullanıcı hiçbir değişiklik görmez).
- Öneri: yorumu düzelt ya da davranışı yorumla hizala.

### 41-21 - `create()` yarım kurulabilir: sonradan `required` hatası yoklamayı ve öksüz öğeyi bırakır
- Önem: low | Güven: medium
- Dosyalar: `frontend/windows.ts:158-207`
- Açıklama: Sıra: `host.append(element)`, `watch(body)`, `opened.set`, sonra `required('[data-window-handle]')` ve `[data-window-close]`. Şablonda bu öğelerden biri yoksa istisna fırlar; DOM'da pencere, çalışan yoklama ve `opened` kaydı kalır, ama kapanma/sürükleme bağlanmamıştır. Ayrıca `template.content.firstElementChild as HTMLElement` null için denetlenmiyor (satır 159).
- Öneri: tüm `required` çağrılarını öğeyi DOM'a eklemeden önce yap.

### 41-22 - Vardiya planı: `aria-selected` rolsüz `td` üzerinde; boş gönderimde sessiz iptal
- Önem: low | Güven: medium
- Dosyalar: `frontend/roster.ts:368-373`, `:396-401`, `templates/hr/roster.html:45`
- Açıklama: `<table data-roster>` için `role="grid"` yok (grep ile bulunamadı); `aria-selected` yalnızca `gridcell/option/row/tab` gibi rollerde geçerlidir, düz `td`'de axe/ARIA ihlali olur. Form gönderiminde seçim yoksa `preventDefault` ile sessizce hiçbir şey olmaz, kullanıcıya mesaj yok.
- Öneri: seçili durumu `aria-pressed`/`aria-selected` ile geçerli bir role bağla ya da `role="grid"` ekle; boş gönderimde çevrilmiş uyarı göster.

### 41-23 - Derleme/test/CI: repo içinde CI tanımı yok, testler Node yoksa atlanıyor, lint yok
- Önem: medium | Güven: medium
- Dosyalar: `package.json`, `tsconfig.json`, `tsconfig.test.json`, `README.md:3403-3406`
- Açıklama: Repo kökünde `.github/` ve başka bir CI tanımı yok (`ls -a`). README, Node yokken testin atlandığını, `CI=1` iken başarısız olduğunu söylüyor; yani yerel/Django test çalıştırmasında TypeScript doğrulaması sessizce atlanabilir. `npm run check` ve `npm test` ayrı; ESLint/Prettier yok, `engines` alanı yok (Node sürümü belirsiz; `node --test` glob'u Node 21+ gerektirir). `tsconfig.json` `moduleResolution` belirtmiyor (`module: ES2022` ile varsayılan eski "classic" çözümleme; testte `bundler` kullanılıyor) -> iki yapılandırma farklı çözümleme kullanıyor. `.build/test` içindeki `package.json` `mark-esm.mjs` ile yazılıyor; Windows'ta `node --test ".build/test/**/*.test.js"` glob'u kabuğa bağlı. `npm test` önizleme/`static/js` çıktısını üretmiyor. (Bu ortamda `npm test` çalıştırılamadı.)
- Öneri: CI iş akışı (`npm ci && npm run check && npm test`), `engines`, `moduleResolution: "bundler"` veya `"node16"`, eslint-typescript.

### 41-24 - `NavState.saved()` türü gevşek; `shell.ts` `window.suderraNav` varlığını varsayıyor
- Önem: info | Güven: high
- Dosyalar: `frontend/globals.d.ts:3-5`, `frontend/nav-boot.ts:53`, `frontend/shell.ts:73,89`
- Açıklama: `saved(): string | null` oysa yalnızca `'open' | 'collapsed'` anlamlı; `localStorage` ham string döner. `nav-boot.js` yüklenmezse (klasik betik, başka şablon) `nav` `undefined` olur ve `nav.save` `TypeError` fırlatır; tip bildirimi her zaman var der.
- Öneri: `saved(): 'open' | 'collapsed' | null` olacak şekilde doğrula; `window.suderraNav?` koruması.

### 41-25 - Mobil ray ve açılır menülerde odak yönetimi eksik
- Önem: low | Güven: medium
- Dosyalar: `frontend/shell.ts:107-166`
- Açıklama: Telefon rayı açıldığında odak içeri alınıyor, ama içerik `inert`/`aria-hidden` yapılmıyor, odak tuzağı yok (Tab arka plana kaçar). Açılır menüler Tab ile dışarı çıkıldığında kapanmıyor (yalnızca tıklama ve Esc).
- Öneri: `inert` ya da `focusout` ile kapatma.

### 41-26 - `merge`: yinelenen anahtarlı parça davranışı tanımsız
- Önem: low | Güven: low
- Dosyalar: `frontend/poll.ts:79-100`
- Açıklama: Gelen parçada aynı anahtar iki kez geçerse `current.get(id)` aynı `old` öğesini iki kez döndürür; ikinci `replaceWith` bağlantısı kopuk öğede etkisizdir ve `done.replaced` yinelenen girdi alabilir (duyuru yinelenir). Ayrıca `old.outerHTML === node.outerHTML` karşılaştırması DOM'u JS ile değiştirilmiş öğede (sınıf, aria) her yoklamada "farklı" bulup yeniden kurar (odak/durum kaybı).
- Öneri: yinelenen anahtarda `null` dön (tam değiştirme).

### 41-27 - `live()` formu: sınırlı hata geri bildirimi ve URL kurma varsayımları
- Önem: low | Güven: medium
- Dosyalar: `frontend/poll.ts:296-332`
- Açıklama: `!response.ok` (5xx) durumunda sessiz dönülür; `aria-busy` kalkar ama kullanıcı sonucun eskidiğini bilmez. `fetch(`${url}?${query}`)` `data-live` adresi zaten `?` içeriyorsa bozuk URL üretir. `history.replaceState` `#hash`'i atar. `queryOf` dosya alanlarını atlar. Formda `name="action"` alanı varsa `form.action` bir öğeye dönüşür.
- Öneri: `new URL` ile sorgu birleştir; hata durumunda `aria-live` bildirimi.

### 41-28 - Tasarımcı ile `types.ts` arasında yinelenen `Problem` tipi ve sabit kodlanmış sınırlar
- Önem: info | Güven: high
- Dosyalar: `frontend/designer.ts:39-44`, `frontend/grid/types.ts:361-365`, `frontend/designer.ts:214-216`
- Açıklama: İki farklı `Problem` arayüzü (sunucu sorunu vs. geometri sorunu) aynı ad altında; karışıklığa açık. Denetçide `y` için `999` ve `h` için `99` sabitleri sunucunun gerçek sınırlarından türetilmemiş (sunucu doğrulayıcısıyla eşleştiği doğrulanmadı). `grid/layout.ts`'deki `check` tasarımcıda kullanılmıyor (yalnızca testler), sunucu sorunlarına güveniliyor. `clamp` içinde `min_w > min(max_w, columns)` ise `within` alt sınırın altına düşer (satır 152).
- Öneri: sunucu tipi `ServerProblem` olarak adlandırılsın; sınırlar katalogdan gelsin.

### 41-29 - HTML parçaları `innerHTML` ile ekleniyor; CSP tanımı yok
- Önem: info | Güven: medium
- Dosyalar: `frontend/poll.ts:169,173,176`, `frontend/components.ts:359`, `frontend/designer.ts:477`, `frontend/windows.ts` (poll üzerinden)
- Açıklama: Tüm dinamik güncellemeler sunucunun HTML'ini doğrudan DOM'a yazar (tasarım gereği, sunucu şablonları kaçışlıyor varsayımıyla). `config` ve `core` içinde `Content-Security-Policy` ayarı bulunamadı (grep boş), dolayısıyla sunucuda kaçışlanmamış tek bir kullanıcı verisi (mesaj, bilgi bankası) doğrudan betik çalıştırır. Sunucu tarafı XSS denetimi bu uzmanlık alanı dışında; burada yalnızca istemci tarafı savunma derinliği eksiği kaydedilir.
- Öneri: CSP (nonce'lu) ve mümkünse `Sanitizer`/`setHTML` değerlendirmesi.
