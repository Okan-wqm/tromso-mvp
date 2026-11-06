# 44 - Erişilebilirlik (accessibility) denetimi

## Özet

Depo erişilebilirlik açısından olgun bir temele sahip: skip link, `lang` özniteliği, `:focus-visible` halkası, `prefers-reduced-motion`, `forced-colors` desteği, SVG grafiklerde `role="img"` + başlık/desc, durum için şekil+sözcük (yalnız renk değil), izleme duvarı için ayrı assertive/polite canlı bölgeler ve klavyeyle çalışan kart tasarımcısı var. Buna rağmen şu alanlarda gerçek açıklar var: (1) mobil off-canvas menü kapalıyken klavye/ekran okuyucuya açık ve odak tuzağı yok; (2) form hataları ve zorunlu alanlar alanlarla programatik/görsel olarak ilişkilendirilmemiş; (3) giriş alanı kenarlığı 3:1 kontrastın altında (1.68:1); (4) iç sekmelerde `aria-controls`/`aria-labelledby`/Home-End eksik; (5) izleme duvarının "bağlantı yok/eski veri" uyarısı CSS `content:` ile basılıyor ve canlı bölge değil; (6) bazı ARIA kullanımları geçersiz (`td`'de `aria-selected`, `<a>`'da `aria-pressed`, `tr`'de `aria-current`); (7) yalnızca `title` ile verilen bilgi (roster "!" işareti, vardiya adı).

Not: Django bu ortamda kurulu olmadığı için (`ModuleNotFoundError`) Django'nun widget'lara kendiliğinden eklediği `aria-describedby`/`aria-invalid` davranışı çalıştırılarak doğrulanamadı; ilgili bulgu bu yüzden güven=orta. Tarayıcı/ekran okuyucu ile çalışma zamanı testi yapılmadı; bulgular kod okumasına dayanır. Kontrast oranları depodaki token değerlerinden WCAG formülüyle hesaplandı.

## İncelenen alanlar

- `templates/app_base.html`, `modal_base.html`, `auth_base.html`, `_language_switcher.html`, `registration/_field.html`, `registration/_form.html`, `crud/form.html`, `crud/list.html`, `crud/_pager.html`, `crud/_row.html`
- `frontend/shell.ts`, `nav-boot.ts`, `components.ts` (sekmeler, modal), `poll.ts`, `windows.ts`, `announce.ts`, `roster.ts`, `auth.ts`, `designer.ts` ve `grid/keyboard.ts` (gözden geçirme)
- `static/css/base.css`, `app.css`, `components.css` (seçili bölümler), `monitor.css`, `hr.css`
- `templates/monitoring/*` (izleme duvarı, kart, pencereler), `templates/hr/roster.html`, `templates/tasks/_task_drawer.html`, `templates/farm/_unit_drawer.html`, `production_units.html`, Deffeyes/pH SVG şablonları, `messaging/inbox.html`
- Kontrast oranı hesabı (token renkleri)

## İncelenmeyen alanlar

- Gerçek tarayıcı / NVDA / VoiceOver / TalkBack testi, axe/Lighthouse taraması yapılmadı
- 149 şablonun tamamı satır satır okunmadı; `farm`, `inventory`, `knowledge`, `reports`, `experiments` şablonları yalnızca desen taraması (grep) ile incelendi
- `components.css`'in tamamı ve `messages.css`, `tasks.css`, `auth.css` ayrıntılı incelenmedi
- PDF çıktıları, e-posta şablonu, `water_calculator_report.html` erişilebilirliği
- Çeviri (`locale/`) kalitesi

## Bulgular

### 44-1 - Mobil off-canvas menü kapalıyken odaklanabilir ve ekran okuyucuya açık; odak tuzağı/`inert` yok
- Önem: orta | Güven: yüksek
- Dosyalar: `static/css/app.css:370-385`, `frontend/shell.ts:39-48,91-98`, `templates/app_base.html:21,63`
- Açıklama: 767px altında `.rail` yalnızca `transform: translateX(-100%)` ile ekran dışına itiliyor; `display:none`, `visibility:hidden`, `inert` veya `aria-hidden` yok. Kapalı menünün bağlantıları Tab sırasında görünmez şekilde odak alır, ekran okuyucu da okur. Menü açıkken ise ne odak tuzağı ne `inert` ile arka plan kilidi var; Tab menüden çıkıp arkadaki sayfaya gider. `scrim` tıklanabilir ama menü `role="dialog"`/modal olarak işaretlenmemiş. Menü kapanınca odak yalnızca Esc yolunda `openButton`'a döner; scrim tıklamasıyla kapanışta odak geri verilmez.
- Kanıt: `app.css` `.rail, [data-nav="collapsed"] .rail { ... transform: translateX(-100%); }`; depoda `inert`/`visibility` araması yalnızca `poll.ts`'te `visibilityState` buluyor; `shell.ts:46-47` scrim ve açma tıklamaları odak yönetmiyor.
- Öneri: Mobilde kapalı durumda `inert` (veya `visibility:hidden` geçişli) uygula; açıkken arka plana `inert`, odak tuzağı ve kapanışta odağı `openButton`'a geri ver.

### 44-2 - Form hata mesajları alanlara bağlanmamış; zorunlu alan görsel göstergesi yok
- Önem: orta | Güven: orta
- Dosyalar: `templates/registration/_field.html:155-175`, `templates/crud/form.html:24`, `static/css/base.css:67-69,100-106`
- Açıklama: `{{ field.errors }}` alanın yanına düz `<ul class="errorlist">` olarak basılıyor; hata listesine `id` verilip alanın `aria-describedby` değerine eklenmiyor. Yardım metnine `{{ field.auto_id }}_helptext` id'si verilmiş (Django'nun üreteceği describedby ile eşleşir) fakat hatalar için eşdeğeri yok; hata yalnızca kenarlık rengiyle (`.has-error`) ve listeyle işaretleniyor. Ayrıca 32 şablondaki `novalidate` formlarda ve CSS'te zorunlu alan işareti (yıldız/"zorunlu" metni) yok (`required` araması CSS'te boş). Ekran okuyucu kullanıcı hatayı alana odaklanınca duymayabilir; görme engelsiz kullanıcı da hangi alanın zorunlu olduğunu önceden göremez (WCAG 3.3.1, 3.3.2). Django sürümü kurulu olmadığı için `aria-invalid` davranışı çalıştırılarak doğrulanamadı (`poll.ts:288` yalnızca canlı formda elle `aria-invalid` ekliyor).
- Kanıt: `_field.html:172-173` (`help` id'li, `{{ field.errors }}` id'siz); `grep describedby` yalnızca test/ts dışında hiçbir şablonda yok.
- Öneri: Hata listesine `id="{{ field.auto_id }}_errors"` ver, alan widget'ına `aria-describedby` ile ekle (veya form `__init__`'te widget attrs); zorunlu alanlara görünür işaret ve `aria-required` ekle.

### 44-3 - Giriş alanı kenarlığı kontrastı WCAG 1.4.11 (3:1) altında
- Önem: orta | Güven: yüksek
- Dosyalar: `static/css/base.css:10,47,165`, `static/css/components.css:70,959`, `static/css/components.css` (`.water-date input` ~597)
- Açıklama: Form kontrollerinin tek görsel sınırı olan `border: 1.5px solid var(--sage)` (#C3CBB2) beyaz zeminde 1.68:1, `--mist` zeminde 1.47:1 kontrast veriyor; bileşen sınırı için gereken 3:1 sağlanmıyor. Dil seçici segmentinin kenarlığı da aynı renk. Kontrol hover'da `--muted` (6.13:1) olduğuna göre uygun bir token zaten mevcut.
- Kanıt: Hesaplanan oranlar sage/white 1.68, sage/mist 1.47; `base.css:47`.
- Öneri: Varsayılan kenarlığı en az 3:1 bir tona (örn. `--muted`) çek, hover'ı koyulaştır.

### 44-4 - Giriş alanlarında odak göstergesi yalnızca 2-3px yarı saydam gölge + kenarlık rengi
- Önem: düşük | Güven: orta
- Dosyalar: `static/css/base.css:59-65,151-153`, `static/css/components.css:70,959`
- Açıklama: `.field input:focus` ve `:focus-visible` için `outline:none`; odak, `border-color: var(--stripe)` ve `box-shadow: 0 0 0 3px rgba(184,69,95,.2)` ile gösteriliyor. Gölge %20 opak olduğundan tek başına belirgin değil; kenarlık değişimi de (sage -> stripe) görsel fark yaratsa da forced-colors (Windows Yüksek Karşıtlık) modunda `box-shadow` yok sayılır ve kenarlık rengi sistem rengine zorlanır, odak halkası kaybolabilir. `monitor.css:181` forced-colors desteği yalnızca izleme için var, form alanları için yok.
- Kanıt: `base.css:151-153` global 3px outline'ı alanlar için açıkça kapatıyor.
- Öneri: Alanlarda da `outline` bırak (veya forced-colors için `outline: 2px solid` ekle).

### 44-5 - İç sekmeler (tabs): `aria-controls`/`aria-labelledby` yok, Home/End yok
- Önem: düşük | Güven: yüksek
- Dosyalar: `templates/crud/form.html:13-19,27,49`, `frontend/components.ts:21-49`
- Açıklama: `role="tab"` düğmelerinde `id`/`aria-controls`, `role="tabpanel"` bölümlerinde `id`/`aria-labelledby` yok; ekran okuyucu sekme-panel ilişkisini kuramaz. Klavye yalnızca ArrowLeft/Right işliyor; Home/End yok. Tüm `extra_tabs` şablonları (board_form, task_form, report_form, experiment_form...) aynı yapıyı kopyalıyor.
- Kanıt: `components.ts:43` `event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0`; panel/sekme eşleşmesi yalnızca `data-tab`/`data-panel`.
- Öneri: Sekme ve panellere üretilen `id`, `aria-controls`, `aria-labelledby` ekle; Home/End destekle.

### 44-6 - Modal 403 yanıtında `aria-labelledby` geçersiz referans, kapatma düğmesi yok; hata yüklemesinde geri bildirim yok
- Önem: düşük | Güven: yüksek
- Dosyalar: `frontend/components.ts:333-366`, `templates/app_base.html:107`, `templates/modal_base.html`
- Açıklama: `<dialog aria-labelledby="modal-title">` yalnızca `modal_base.html` içeriği yüklenince geçerli. 403 yolunda `components.ts:350-357` yalnızca `<p class="form-error">` koyuyor: `#modal-title` yok (dialog adsız kalır), `data-modal-close` düğmesi yok (yalnızca Esc/arka plan tıklaması kapatır; dokunmatik kullanıcı için zor). `fetch` ağ hatasında `load()` yakalanmamış reddedilir, kullanıcı hiçbir şey görmez; `void this.load(...)` ile bırakıldığı için sessiz hata. Yükleme sırasında `aria-busy`/duyuru da yok. Başarılı yüklemede odak ilk girdiye gider, başlık/duyuru verilmez (kabul edilebilir).
- Kanıt: `components.ts:304-311` `void this.load(opener.href)`; `:350-357`.
- Öneri: 403 içeriğine başlık + kapat düğmesi ekle; fetch hatasında dialog içinde `role="alert"` mesajı göster.

### 44-7 - İzleme duvarında "bağlantı yok / eski veri" uyarısı yalnızca CSS `::before content:` ile basılıyor
- Önem: yüksek | Güven: orta
- Dosyalar: `static/css/monitor.css:5-21`, `templates/monitoring/monitor.html:37`, `frontend/poll.ts:143-147`, `templates/monitoring/_windows.html:5`
- Açıklama: Poll 2 başarısızlıktan sonra `data-poll-state="stale"`, 401/403/404'te `gone` yazıyor; kullanıcıya görünen metin CSS `content: attr(data-stale-text)` ile üretiliyor. Bu metin canlı bölgede değil, tutarlı biçimde erişilebilirlik ağacına açılmıyor ve değişiklik duyurulmuyor. `announce.ts` yalnızca kartın durumu kötüleştiğinde konuşuyor; bağlantının kopması (kart verisinin eskimesi güvenlik açısından kritik: balık çiftliği izleme duvarı) ekran okuyucu kullanıcıya hiç bildirilmiyor. Pencere gövdesi için de aynı.
- Kanıt: `monitor.css:17-18` `content: attr(data-stale-text)`; `announce.ts` yalnızca `poll:merged` olayını dinliyor, `data-poll-state` değişimini dinlemiyor.
- Öneri: `poll:stale`/`gone` durumunda `#monitor-announce` assertive bölgesine metni yaz veya DOM'da `role="status"` bir eleman yönet.

### 44-8 - Mobil menüdeki `aside aria-label="Main navigation"` ve etiketsiz iç `nav` landmark karmaşası
- Önem: düşük | Güven: yüksek
- Dosyalar: `templates/app_base.html:21,46`
- Açıklama: Ana gezinme etiketi `<aside>` (complementary landmark) üzerinde; asıl `<nav class="rail-nav">` etiketsiz. Ekran okuyucu "Main navigation, complementary" ve ayrıca adsız "navigation" bildirir; sayfada `production_units.html:13`, `task_list.html:13` gibi başka `nav aria-label` var ama ana nav ayırt edilemiyor. Ayrıca çalışma alanı menüsü ve kullanıcı menüsü `aria-haspopup="true"` (menu rolü) ile işaretli ama panel içeriği `role="menu"`/`menuitem` değil, normal bağlantı/düğme; `aria-haspopup="true"` `menu` anlamına gelir ve beklenen ok tuşu davranışı yok (`shell.ts:78-98` yalnızca tıklama ve Esc; açılışta odak panele taşınmıyor).
- Kanıt: `app_base.html:21` ve `:46`; `:27,76`.
- Öneri: `aria-label`'ı `<nav>`'a taşı; `aside`'ı kaldır/ayrı etiketle; menü düğmelerinde `aria-haspopup` kaldır (disclosure deseni) veya tam menu klavye desenini uygula.

### 44-9 - Geçersiz/uygunsuz ARIA: `td`'de `aria-selected`, `<a>`'da `aria-pressed`, `tr`'de `aria-current`
- Önem: düşük | Güven: yüksek
- Dosyalar: `frontend/roster.ts:61`, `templates/farm/production_units.html:32,37,41`, `templates/hr/roster.html` (hücreler), `templates/farm/production_units.html:87`, `templates/tasks/task_list.html:81`
- Açıklama: (a) `roster.ts` seçili `td`'ye `aria-selected` yazıyor; tablo `grid` rolünde değil, `td` rolü `cell` bu özniteliği desteklemez. (b) Filtre "düğmeleri" `<a class="filter-button" aria-pressed=...>`: bağlantı rolünde `aria-pressed` geçersiz, bağlantı seçili durumunu `aria-current` ile bildirmeli. (c) `tr.unit-row` üzerinde `aria-current="true"`; bu rol için anlamı belirsiz. Ekran okuyucu bu durumları yok sayar: seçili hücre/filtre bilgisi işitsel kullanıcıya iletilmez.
- Kanıt: `roster.ts:61` `cell.setAttribute('aria-selected', String(on))`; `production_units.html:32` `<a class="filter-button" ... aria-pressed="...">`.
- Öneri: Roster seçimi için gerçek bir kontrol (ör. gizli onay kutusu) veya `role="grid"`/`gridcell` desenini kullan; filtre bağlantılarında `aria-current="true"`; satır işaretini bir görünür/sr-only metne çevir.

### 44-10 - Roster'da bilgi yalnızca `title` ile veriliyor ("!" uyarıları, vardiya adı)
- Önem: orta | Güven: yüksek
- Dosyalar: `templates/hr/roster.html` (`roster-finding`, `shift-chip title`), `static/css/hr.css:28-29`
- Açıklama: Hücrelerdeki uyarı işareti `<span class="roster-finding" title="{{ cell.finding_text }}">!</span>`: uyarı metni yalnızca tooltip'te; klavye/dokunmatik/çoğu ekran okuyucu bunu okumaz, görünen içerik yalnızca "!" (imleç `cursor:help`). Vardiya çipleri yalnızca kodu (ör. "N") gösterir, ad ve saat `title`'da; bağlantı erişilebilir adı yalnızca kod kalır. Vardiya boyama düğmelerinde de aynı: `title="{{ shift.name }}"` açıklama niteliğinde. Hata/blok durumu (`has-block` kırmızı alt kenar, `has-warning` sarı) `box-shadow` ile; forced-colors'ta kaybolur. Haftalık toplam sütunundaki "!" için de aynı.
- Kanıt: `hr.css:28-29` `.roster-finding {... cursor: help; }`; `roster.html` `title="{% trans 'More than the standard week' %}"`.
- Öneri: Uyarı metnini `sr-only` kardeş metin olarak ekle, `aria-label`/`aria-describedby` kullan; vardiya adını sr-only olarak çipin içine koy; durum için `box-shadow` yanında metin/ikon.

### 44-11 - Hareketli pencerelerde ok tuşları gövde kaydırmasını engelliyor; klavye kısayolları belgelenmemiş
- Önem: düşük | Güven: orta
- Dosyalar: `frontend/windows.ts:185-203`, `templates/monitoring/_windows.html:9-16`
- Açıklama: Pencere `keydown` işleyicisi pencere içinde herhangi bir yerde ok tuşuna `preventDefault` çağırıyor (yalnızca `input,select,textarea` hariç). Gövde (`.monitor-window-body`, `overflow:auto`) kaydırılabilir; bir bağlantı/düğmeye odaklıyken veya gövde odaklıyken ok tuşuyla kaydırma yerine pencere kayıyor. Taşıma (ok) ve yeniden boyutlandırma (Shift+ok) klavye kısayolları ekranda ya da `aria-describedby` ile duyurulmuyor; pencere başlığındaki sürükleme tutamacı yalnızca fareyle. `role="dialog"` ile modal olmayan pencere odak tuzağı yapmıyor (bu kasıtlı), ancak `aria-modal` yok, kabul edilebilir. Poll gövdeyi `innerHTML` ile değiştirirken (`poll.ts:176`) içindeki odak kaybolabilir (yalnızca `merge` yolunda id ile geri yükleniyor).
- Kanıt: `windows.ts:191-193` `if (!arrow || (event.target as Element).closest('input, select, textarea') || PHONE.matches) return; event.preventDefault();`.
- Öneri: Taşıma için yalnızca pencere elemanının kendisi odaklıyken (`event.target === element`) tetikle; kısayolları sr-only metinle belgele.

### 44-12 - Çekmece (drawer) modal değil, Esc ile kapanmıyor, odak yönetilmiyor, arkadaki içerik odaklanabilir
- Önem: düşük | Güven: orta
- Dosyalar: `templates/tasks/_task_drawer.html:6-12`, `templates/farm/_unit_drawer.html:7`, `static/css/components.css:1128-1133`
- Açıklama: `aside.drawer` `position:fixed` ile sayfanın sağını kaplıyor, DOM'da sayfanın sonunda; Tab sırasında önce arkadaki tüm tablo satırları gelir. Esc kapatmıyor (`frontend/` içinde `drawer` ile ilgili kod yok), kapatma yalnızca bağlantı (`close_url`). Açılışta (sayfa yeniden yüklendiği için) odak çekmeceye taşınmıyor, ekran okuyucu içerik değişikliğini fark etmez. Dar ekranda (`min(30rem,100vw)`) çekmece sayfanın tamamını örter ama arka içerik hâlâ odaklanabilir.
- Kanıt: `grep drawer frontend/*.ts` boş; `components.css:1129` `position: fixed ... z-index: 45`.
- Öneri: Açılışta odağı `#drawer-title`'a taşıyan küçük betik; Esc ile `close_url`'e git; mobilde arka planı inert yap.

### 44-13 - Grafik renkleri beyaz zeminde 3:1 altında (pH grafikleri, Deffeyes)
- Önem: düşük | Güven: orta
- Dosyalar: `static/css/components.css:690-704,822-835`
- Açıklama: Seri/çizgi renkleri `#F59E0B` (2.15:1), `#10B981` (2.54:1), `#FF8F73` (2.23:1) beyaz üzerinde WCAG 1.4.11 grafik nesneleri için 3:1'in altında. Lejant ve sayısal metin ("facts") ile desteklendiği ve SVG `role="img"` + `aria-labelledby` ile adlandırıldığı için etki sınırlı; ayrıca `.ph-series-*` renkleri yalnızca renkle ayrışıyor (çoğu seri aynı kalınlık/aynı çizgi stili), renk körü kullanıcı seriler arasında kaybolabilir (izleme kartlarında şekil/desen kullanılırken burada kullanılmamış).
- Kanıt: `components.css:693-698`; hesaplanan oranlar yukarıda.
- Öneri: Daha koyu tonlar kullan ve seri başına farklı `stroke-dasharray`/işaretçi ekle.

### 44-14 - Dil değiştirici düğmelerinde görünen metin erişilebilir adın içinde değil (EN/TR/NB vs. English/Türkçe/Norsk bokmål)
- Önem: düşük | Güven: yüksek
- Dosyalar: `templates/_language_switcher.html:6`, `config/settings.py:153`, `static/css/base.css:170-175`
- Açıklama: Düğmenin görünen etiketi `{{ code|upper }}` ("TR", "NB"), `aria-label` ise dilin adı ("Türkçe", "Norsk bokmål"). "TR" ifadesi "Türkçe" içinde düz metin olarak geçmiyor, "NB" de "Norsk bokmål" içinde yok (WCAG 2.5.3 Label in Name; sesle kontrol "TR'ye tıkla" komutu çalışmaz). Düğme yüksekliği `min-height:2rem` (32px) dokunmatik hedef için 44px önerisinin altında (WCAG 2.5.5 AAA/2.5.8 AA 24px'i geçer, bilgi amaçlı). Seçili dil `aria-current="true"` ile iyi işaretlenmiş.
- Kanıt: `_language_switcher.html:6` `lang="{{ code }}" aria-label="{{ name }}" title="{{ name }}"` ve görünen `{{ code|upper }}`.
- Öneri: Görünen metni dil adının kısaltması olarak tut ve adı "TR Türkçe" gibi görünen metni içerecek biçimde ver; veya görünür metni dil adına çevir.

### 44-15 - Menü daraltma durumunda başlıklar gizleme biçimi ve etiket kısaltmaları
- Önem: bilgi | Güven: orta
- Dosyalar: `static/css/app.css:130-150,207-232,300-312`, `frontend/shell.ts:12-18`
- Açıklama: (a) Daraltılmış rail'de `.rail-section`/`.rail-group` `color: transparent; height:1px; overflow:hidden` ile gizleniyor; metin hâlâ erişilebilirlik ağacında, yani ekran okuyucu bölüm başlıklarını okur (iyi), ancak `[data-nav="collapsed"] .rail-section + .rail-group { display:none }` yalnızca bazı grup başlıklarını tamamen kaldırıyor: ekran okuyucu/klavye kullanıcısı için tutarsız bölüm yapısı. (b) Daraltılmış rail'de bağlantı etiketleri `.8125rem` ve `max-width:100%` + `text-overflow:ellipsis` ile kırpılıyor; tam ad yalnızca `title` ile (dokunmatikte görünmez). (c) Rail durumu `localStorage`'da; `aria-expanded` ve etiket güncelliyor (`shell.ts:12-18`), bu iyi. (d) `.rail-badge` sayısı (okunmamış mesaj) için ekran okuyucu metni yok: badge yalnızca "3" gibi sayı okunur, "okunmamış" bağlamı yok; ayrıca `data-poll` ile güncellendiğinde duyurulmuyor.
- Kanıt: `app.css:223` `.rail-label { overflow:hidden; text-overflow: ellipsis }`; `app_base.html:55` `<span class="rail-badge" ...>{{ entry.badge.text }}</span>`.
- Öneri: Rozete `aria-label`/sr-only bağlam metni ekle; kırpılan etiket için daraltılmış durumda en az `aria-label` sağlam kalsın.

### 44-16 - Flash mesajları `role="status"` (hata dahil), tek seferlik; dinamik hata duyurusu yok
- Önem: düşük | Güven: orta
- Dosyalar: `templates/app_base.html:99-101`, `templates/modal_base.html:13`, `static/css/app.css:458-461`
- Açıklama: Başarı ve hata (`flash-error`) mesajları aynı `role="status"` (polite) kapsayıcıda. Hata için `role="alert"` kullanılmıyor (form `non_field_errors` için doğru kullanılmış). Kapsayıcı sayfa yüklenirken zaten dolu olduğu için çoğu ekran okuyucu içeriği duyurmaz (canlı bölgeler yalnızca sonradan eklenen içeriği duyurur). Modal içinde form POST sonrası içerik `innerHTML` ile değiştirilip odak ilk girdiye taşındığında hata özeti okunmuyor; odak `.has-error input`'a gidiyor ama hata metni alana bağlı değil (bkz. 44-2).
- Kanıt: `app_base.html:99` `<div class="flash-list" role="status">`; `components.ts:363-365`.
- Öneri: Hata mesajlarını `role="alert"` ile ver, odağı hata özetine veya ilk geçersiz alana + describedby ile taşı.

### 44-17 - Başlık seviyesi atlamaları ve tablo başlık/caption eksikliği
- Önem: düşük | Güven: orta
- Dosyalar: `templates/monitoring/_card.html:7`, `templates/app_base.html:73`, `templates/crud/list.html:36,44`, 95 `<table>` / 3 `<caption>`
- Açıklama: Sayfa `h1` (üst çubuk) ardından izleme kartları `h3` kullanıyor; `h2` atlanıyor. Çoğu veri tablosunda `<caption>` yok (95 tablo, 3 caption) ve tablolar bölüm başlığıyla ilişkilendirilmemiş (`aria-labelledby` yok); `<th>` taraması `scope` olmayan `<th>` bulmadı (iyi). Boş durum başlığı `h2` olarak sayfaya giriyor ama sayfada başka `h2` yok.
- Kanıt: `_card.html:7` `<h3 id="card-title-...">`; `grep -rn "<caption" templates` 3 sonuç.
- Öneri: Kart başlığı için `h2` kullan veya sayfaya gizli `h2` ekle; çok tablolu sayfalarda `caption`/`aria-labelledby`.

### 44-18 - Yeni sekmede açılan bağlantılar ve yalnızca simge/kısaltma bağlantı metni
- Önem: bilgi | Güven: yüksek
- Dosyalar: `templates/knowledge/document_list.html:47`, `templates/knowledge/document_detail.html:35`, `templates/farm/calculator/_actions.html:2`, `templates/reports/outside_duties.html:47`
- Açıklama: `target="_blank"` bağlantılar yeni pencerede açıldığını belirtmiyor (WCAG 3.2.5 AAA/G201 önerisi). Doküman listesinde bağlantı metni yalnızca "PDF" (simge + kısaltma), hangi belge olduğu bağlamdan çıkarılıyor (satır bağlamı dışında okunduğunda anlamsız). `rel="noopener"` doğru kullanılmış.
- Kanıt: `document_list.html:47` `<a href=... target="_blank" rel="noopener">...PDF</a>`.
- Öneri: sr-only "(yeni sekmede açılır)" ve belge adını içeren erişilebilir ad.

### 44-19 - Parola göster/gizle düğmesinde hem değişen etiket hem `aria-pressed`
- Önem: bilgi | Güven: yüksek
- Dosyalar: `frontend/auth.ts:11-15`, `templates/registration/_field.html:166`
- Açıklama: Düğme etiketi Show/Hide olarak değişirken aynı anda `aria-pressed` de güncelleniyor; ekran okuyucu "Hide, toggle button, pressed" gibi çelişkili duyurur (etiket değişiyorsa `aria-pressed` kullanılmamalı veya etiket sabit kalmalı). Düğme `aria-controls` ile girdiye bağlı (iyi). Dokunmatik hedef `padding:.375rem .625rem` (~30px yükseklik).
- Kanıt: `auth.ts:13-14`.
- Öneri: Etiketi sabit tut ("Show password") + `aria-pressed`, ya da etiketi değiştir ve `aria-pressed`'i kaldır.

### 44-20 - Canlı mesaj listesi (`aria-live="polite"`) ve duyuru bölgelerinin sınırlamaları
- Önem: bilgi | Güven: düşük
- Dosyalar: `templates/messaging/inbox.html:31`, `frontend/announce.ts:113-122`
- Açıklama: Sohbet listesi `<ol aria-live="polite">` ve poll ile eklenen her mesajı duyurur; `role="log"` bu iş için daha uygun olurdu. İzleme duyurusunda aynı metin art arda atanırsa (`node.textContent = out`) bazı ekran okuyucular aynı içeriği yeniden okumaz (içerik değişmedi). Poll aralığı kısa olduğunda yoğun duyuru riski sınırlayıcıyla (5 sn) azaltılmış (iyi).
- Kanıt: `announce.ts:117` `node.textContent = out;`.
- Öneri: `role="log"`; aynı cümle için boşaltıp yeniden yaz (clear-then-set) deseni.

## Olumlu gözlemler (kayıt için)

- Skip link (`app_base.html:17`, `app.css:22-30`), `main tabindex="-1"`, `html lang`, `prefers-reduced-motion`, global `:focus-visible` 3px halka.
- İzleme durumu şekil + sözcük + kenarlık stiliyle (`monitor.css:123-145`), forced-colors desteği.
- SVG grafikler `role="img"`, başlık/desc, sayısal "facts" metinleri.
- Kart tasarımcısı klavye ile tam kullanılabilir (`grid/keyboard.ts`) ve `aria-pressed`, `aria-invalid`, durum duyurusu var.
