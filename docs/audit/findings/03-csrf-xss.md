# 03 - CSRF / XSS / şablon kaçışı / DOM sink / CSP denetimi

## Özet
Uygulama katmanında CSRF ve XSS kontrolleri sağlam: `CsrfViewMiddleware` açık, `csrf_exempt` hiç yok, incelenen tüm POST formları `{% csrf_token %}` taşıyor, fetch tabanlı tek POST (`designer.ts`) `X-CSRFToken` gönderiyor. Şablonlarda otomatik kaçış korunmuş; `mark_safe`/`|safe` kullanımları az ve çoğu doğru kaçışlanmış. Asıl eksik savunma-derinliği: hiç CSP yok, cookie/HSTS sertleştirme ayarları yok, frontend birçok yerde `innerHTML` ile sunucu HTML'ini sanitize etmeden basıyor. Doğrulanmış istismar edilebilir XSS/CSRF açığı bulunmadı. `manage.py check --deploy` çalıştırılamadı (ortamda Django kurulu değil).

## İncelenen alanlar
config/settings.py (MIDDLEWARE, cookie/SECURE_* ayarları), config/urls.py, tüm templates/ (csrf_token, |safe, autoescape, inline script/style, href), core/templatetags/assets.py, knowledge/citation.py, knowledge/search.py, farm/forms/water.py, frontend/*.ts (innerHTML/insertAdjacentHTML/location.assign/fetch), monitoring/views.py (preview) ve cards/render.py, `next` yönlendirme yardımcıları (hr, tasks, inventory, farm/*), CSV dışa aktarımları (reports/exports.py, core/dbview.py), knowledge/views.py (PDF sunumu), README/docs'ta güvenlik notları.

## İncelenmeyen alanlar
Çalışma zamanı HTTP başlıkları (uygulama çalıştırılmadı, `check --deploy` koşulamadı), Django admin'in kendi şablonları, derlenmiş static/js çıktısı, reverse proxy/TLS dağıtım yapılandırması (repoda yok), her şablonun satır satır taranması (örnekleme + grep ile yapıldı), THIRD_PARTY.md'deki üçüncü parti JS'in içeriği.

## Bulgular

### 03-1 | orta | güven: yüksek - Content-Security-Policy tanımlı değil
Dosyalar: config/settings.py:64-78
Açıklama: MIDDLEWARE listesinde CSP middleware'i ve ayarlarda `SECURE_CSP`/`SECURE_CSP_REPORT_ONLY` yok. Bir kaçış hatası olduğunda ikinci savunma hattı yok. Kod tabanı katı CSP'ye elverişli: şablonlarda satır içi çalıştırılan betik yok (yalnızca `json_script` veri blokları ve tek `importmap`), `on*=` olay işleyicisi yok; yalnızca 3 `style="..."` özniteliği ve `_card.html`'de `style="{{ view.style }}"` var.
Kanıt: `grep -rn "CSP\|CONTENT_SECURITY" --include=*.py` yalnızca monitoring dışı alakasız eşleşme verdi; MIDDLEWARE'de `django.middleware.csp` yok. `core/templatetags/assets.py:41` importmap'i satır içi `<script>` olarak basıyor (nonce gerektirir).
Öneri: Django'nun yerleşik CSP desteğiyle önce Report-Only başlat (`default-src 'self'; script-src 'self' nonce; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`); importmap için nonce kullan; `style-src-attr` için karar ver.

### 03-2 | orta | güven: yüksek - Cookie ve taşıma güvenliği ayarları yok (CSRF/oturum cookie'si Secure değil, HSTS yok, CSRF_TRUSTED_ORIGINS yok)
Dosyalar: config/settings.py
Açıklama: `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_SECURE`, `LANGUAGE_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS` tanımlı değil. TLS arkasında bir proxy ile yayınlanırsa Django `request.is_secure()` false görür; HTTPS'te Origin/Referer kontrolü (CSRF) proxy'de reddedilebilir ve cookie'ler HTTP üzerinden de gidebilir. Yalnızca `LANGUAGE_COOKIE_SAMESITE='Lax'` (satır ~151) tanımlı. Konu 01-3 ile örtüşür; burada CSRF yönüyle kaydedildi.
Kanıt: settings.py'de `grep -n "SECURE_\|CSRF_\|SESSION_COOKIE"` yalnızca LANGUAGE_COOKIE_* satırlarını bulur. README'de dağıtım/HTTPS bölümü yok (yalnızca runserver anlatımı).
Öneri: Ortam bayrağına bağlı üretim profili ekle (Secure cookie'ler, HSTS, proxy header, trusted origins) ve CI'da `check --deploy`.

### 03-3 | düşük | güven: yüksek - Importmap `mark_safe` ile ve `</script>`'e karşı kaçışsız `json.dumps` ile üretiliyor
Dosyalar: core/templatetags/assets.py:41
Açıklama: `mark_safe('<script type="importmap">' + json.dumps(...) + '</script>')`. `json.dumps` `<`, `>`, `&` karakterlerini kaçışlamaz; girdiler `static/js/*.js` dosya adları ve mtime sürümü olduğundan bugün geliştirici kontrolünde, fakat desen güvenli değil (dosya adında `</script>` bulunması betik bloğunu kırar).
Kanıt: `imports = {static(path): versioned(path) ...}` -> `json.dumps({'imports': imports})`.
Öneri: `django.utils.html.json_script` benzeri kaçış (`<`) uygula; CSP nonce eklerken aynı yerde düzelt.

### 03-4 | düşük | güven: orta - `registration/_field.html` form `help_text`'ini `|safe` ile basıyor (örtük güven sözleşmesi)
Dosyalar: templates/registration/_field.html:20, farm/forms/water.py:175-181
Açıklama: Şablon her alanın `help_text`'ini kaçışsız yazar; bu, Django parola doğrulayıcılarının HTML listesi için gerekli. Bugünkü kullanıcılar (parola formları) güvenli; ancak `farm/forms/water.py` aynı yardımı `format_html_join` ile elle kaçışlıyor ve yorumu "shown as HTML (registration/_field.html)" diyor, yani sözleşme yalnızca yorumla tutuluyor. Şablon başka bir forma yeniden kullanılır ve `help_text` kullanıcı verisi içerirse (ör. tür adı) saklı XSS oluşur. Diğer şablonlar (`experiment_start.html:27`, `_handling_panel.html:15`) `help_text`'i kaçışlı basıyor: tutarsızlık.
Kanıt: `{{ field.help_text|safe }}`; water.py: `help_text = format_html_join(' ', '{}', ...)` (zaten SafeString, yani `|safe` orada gereksiz).
Öneri: `|safe` yerine yalnızca `SafeString` olanları basan kaçışlı çıktı (`{{ field.help_text }}` zaten SafeString'i korur); `|safe` kaldırılabilir.

### 03-5 | düşük | güven: orta - Harici URL alanları yalnızca form doğrulayıcısıyla `http/https`e kısıtlı, şablonda doğrudan `href`
Dosyalar: knowledge/models/document.py:106, knowledge/models/entry.py:75, templates/knowledge/document_detail.html:26, templates/knowledge/entry_detail.html:24, knowledge/citation.py:112-114, farm/models/supplier.py:145
Açıklama: `url` alanlarında `URLValidator(schemes=['http','https'])` var, ama bu yalnızca `full_clean`/ModelForm yolunda çalışır; DB `CheckConstraint` yok. Form dışı bir yazma yolu (içe aktarma, shell, ileride AI ajanları, seed) `javascript:` şeması kaydedebilir ve `<a href="{{ object.url }}">` ile `citation.reference()` bunu tıklanabilir basar (Django `javascript:` URL'ini kaçışlamaz, yalnızca HTML-escape eder). `farm/models/supplier.py:145` `website` alanı varsayılan URLValidator kullanır (http/https/ftp/ftps; `javascript:` reddedilir). Bugün form dışı yol kanıtlanmadı.
Kanıt: `href="{{ object.url }}"`; citation.py: `<a href="{escape(url)}" ...>`.
Öneri: DB düzeyinde şema kısıtı veya şablonda `url|urlize` yerine şema kontrolü yapan bir filtre; en azından `rel="noopener noreferrer"` zaten var (iyi).

### 03-6 | düşük | güven: orta - DOI bağlantısı iki yerde farklı üretiliyor (`urlencode` var/yok)
Dosyalar: knowledge/citation.py:97-99,112-114, templates/knowledge/document_detail.html:25
Açıklama: Şablon `https://doi.org/{{ object.doi|urlencode:'/' }}` kullanır; `citation.link()` ise `f'{DOI_LINK}{document.doi}'` yazar, `escape` ile HTML'e güvenli ama URL olarak kodlanmaz. `#`, `?` veya boşluk içeren DOI iki yerde farklı hedefe gider. Güvenlik etkisi yok (HTML kaçışı doğru), tutarlılık sorunu.
Kanıt: yukarıdaki satırlar.
Öneri: Tek yardımcıdan üret (`citation.link` URL kodlamalı).

### 03-7 | info | güven: yüksek - `highlight()` `mark_safe` doğru kaçışlıyor; güvenlik bir invariant'a dayanıyor
Dosyalar: knowledge/search.py:43-44,170-176, knowledge/extraction.py:17,51
Açıklama: `escape(passage)` sonra `\x02`/`\x03` işaretleri `<mark>` ile değiştiriliyor; yani en kötü durumda sahte `<mark>` oluşur, betik değil. Yorum "kontrol karakterleri depolanan metinde yoktur" diyor; bu PDF çıkarımı için doğru (kontrol karakterleri siliniyor), kullanıcının elle yazdığı entry alanları için doğrulanmadı ama etkisi yalnızca görsel.
Kanıt: `mark_safe(escape(passage).replace(START, '<mark>').replace(STOP, '</mark>'))`; test `knowledge/tests/test_search.py:97`.
Öneri: Eylem gerekmez; sadece not.

### 03-8 | düşük | güven: yüksek - Frontend `innerHTML`/`insertAdjacentHTML` sink'leri sunucu HTML'ini sanitize etmeden basıyor
Dosyalar: frontend/poll.ts:72,169,173,176,319; frontend/components.ts:111,359; frontend/designer.ts:477
Açıklama: Poll, modal ve tasarım önizlemesi sunucu fragmanlarını doğrudan DOM'a yazıyor. Fragmanlar aynı kökenden, Django şablonlarıyla (autoescape) üretiliyor ve `credentials: 'same-origin'` ile çekiliyor; `<script>` `innerHTML` ile çalışmaz, ama `<img onerror>` gibi içerik çalışır. Güvenlik tamamen sunucu tarafı kaçışına bağlı; DOMPurify/Trusted Types yok. `components.ts:111` ise `template.innerHTML.replace(/__prefix__/g, ...)` ile şablon klonluyor (sunucu şablonu, güvenli). CSP olmaması (03-1) bu sink'lerin etkisini büyütür.
Kanıt: `this.content.innerHTML = await response.text();` (components.ts:359), `this.preview.innerHTML = answer.html;` (designer.ts:477), `element.innerHTML = html.trim();` (poll.ts:173/176).
Öneri: CSP + Trusted Types (report-only) ile sink'leri tek yardımcıya topla; fragman uç noktalarının yalnızca şablonla ürettiğini testle sabitle.

### 03-9 | düşük | güven: orta - `X-Modal-Redirect` / `X-Modal-Load` başlık değerleri istemcide şema/köken doğrulaması olmadan kullanılıyor
Dosyalar: frontend/components.ts:339-347, core/crud.py:98-107
Açıklama: İstemci `window.location.assign(redirectTo)` ve `this.load(next)` çağırıyor; değer yalnızca sunucu başlığından geliyor (`core/crud.py:done(request, url, ...)`). Çağıranlar `reverse()`/`_return()` ile üretiyor (hr `_return` `url_has_allowed_host_and_scheme` kullanıyor). Tüm `done()` çağıranlarının kullanıcı girdisi geçirmediği tam doğrulanmadı.
Kanıt: `response.headers.get('X-Modal-Redirect')` -> `window.location.assign(redirectTo)`.
Öneri: İstemcide `new URL(value, location.href).origin === location.origin` kontrolü ekle.

### 03-10 | info | güven: yüksek - `next` yönlendirmeleri tutarlı biçimde doğrulanıyor ama beş farklı uygulamayla
Dosyalar: hr/views.py:37-41, tasks/views.py:28-34, inventory/views.py:59-62, farm/health/views.py:51-53, farm/stock/views.py:260-262, farm/water/views.py:116-120, farm/feeding/views.py:298-299
Açıklama: Açık yönlendirme bulunmadı; hepsi `url_has_allowed_host_and_scheme` veya yol öneki kontrolü yapıyor (tasks yalnızca önek + `//` ve `\` reddi). `feeding/views.py:298` `next`'i doğrulamadan sorguya taşıyor, ancak gideceği yerde `stock_views._back` doğruluyor. `hr` varyantı `require_https` verirken diğerleri vermiyor. Dağınıklık, yeni kodda doğrulamanın unutulma riski.
Kanıt: ilgili satırlar.
Öneri: Tek paylaşılan `safe_next(request, default)` yardımcısı.

### 03-11 | info | güven: yüksek - CSRF kapsaması doğrulandı; testler CSRF'yi hiç zorlamıyor
Dosyalar: config/settings.py:70, templates/**, frontend/designer.ts:69-70,467-470, templates/_language_switcher.html:3, templates/app_base.html:90
Açıklama: `csrf_exempt` repoda yok; çıkış (`logout`, POST + token), dil değiştirme (`login_not_required` ama CSRF'li), giriş formu, modal ve tasarımcı önizlemesi token taşıyor. Durum değiştiren GET görünümü aranmadı ayrıntılı (bu alan başka uzmana ait) ama incelenen `@require_POST`'lar yerinde. Test istemcisi varsayılan olarak CSRF'yi atladığı için (`enforce_csrf_checks` hiç kullanılmamış) bir şablonda `{% csrf_token %}` unutulursa testler yakalamaz.
Kanıt: `grep -rn csrf_exempt` boş; `grep -rn enforce_csrf_checks --include=*.py` boş.
Öneri: Şablonlardaki `method="post"` formlarının token içerdiğini tarayan tek bir test ekle.

### 03-12 | info | güven: orta - Parola sıfırlama e-postasında `{% autoescape off %}`
Dosyalar: templates/registration/password_reset_email.html:1-7
Açıklama: Düz metin e-posta için uygun; `user.get_username` kaçışsız yazılır. Yalnızca düz metin gönderildiği sürece sorun yok; bir HTML alternatifi eklenirse kullanıcı adı XSS/enjeksiyon olur. Bu e-posta `request.get_host()` tabanlı alan adı kullanır (`ALLOWED_HOSTS` boşken DEBUG=0'da tüm istekler reddedilir; DEBUG=1'de yalnızca yerel hostlar).
Kanıt: ilgili satırlar; `settings.py:30`.
Öneri: Not olarak bırak; HTML e-posta eklenirse autoescape'i aç.

### 03-13 | info | güven: yüksek - İyi uygulamalar (kayıt)
Dosyalar: core/dbgrid.py:35-38, reports/exports.py:196, knowledge/views.py:37-39, knowledge/tests/test_documents.py:245, monitoring/cards/validate.py:152, templates/monitoring/_card.html:23
Açıklama: CSV dışa aktarımları `formula_safe` ile formül enjeksiyonuna karşı korunuyor (reports ve DB görüntüleyicisi `Grid.export`); PDF `content_type='application/pdf'` ve nosniff ile sunuluyor (dosya adı sunucu üretimi, `%PDF-` doğrulaması); kart yerleşimindeki `style="--x:..."` değerleri doğrulayıcıda `int` zorunlu (`_is_int`), CSS enjeksiyonu yok; `target=_blank` kullanımı yok, harici bağlantılar `rel="noopener noreferrer"`; `json_script` ile veri aktarımı güvenli.
Kanıt: belirtilen satırlar.
Öneri: Yok.

### 03-14 | düşük | güven: düşük - Kullanıcı yüklü PDF aynı kökenden satır içi (inline) sunuluyor, `Content-Security-Policy: sandbox` yok
Dosyalar: knowledge/views.py:27-40, knowledge/models/document.py:58-72
Açıklama: Yalnızca `%PDF-` başlığı doğrulanıyor; dosya `?download` yoksa satır içi `application/pdf` olarak uygulama kökeninden dönüyor. Tarayıcılar PDF'i kendi sandbox'ında gösterdiği için pratikte risk düşük; derinlemesine savunma olarak yanıta `Content-Security-Policy: sandbox` ve `default-src 'none'` eklenebilir. Tarayıcıya bağlı davranış olduğundan güven düşük.
Kanıt: `FileResponse(stream, as_attachment='download' in request.GET, ..., content_type='application/pdf')`; yalnızca `Cache-Control` ekleniyor.
Öneri: Dosya yanıtına kısıtlayıcı CSP başlığı ekle.
