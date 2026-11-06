# 38 - API sözleşmeleri denetimi (URL tasarımı, view sözleşmeleri, HTTP metodları, idempotency, JSON uçları, frontend-backend sözleşmesi)

## Özet
Uygulama ağırlıklı olarak sunucu tarafında render edilen HTML sayfalarından oluşuyor. Gerçek JSON ucu yalnızca `monitoring:cardtemplate_preview`; geri kalan "API" yüzeyi `X-Modal*` ve `X-Poll-Next` başlıklarıyla konuşan HTML parçaları (modal/poll). Tasarımın genel kalitesi yüksek: durum değiştiren uçların çoğu POST ile, `entry_key` ile idempotent kayıt, sürüm (`version`) ile iyimser kilit, `next` doğrulaması var. Bulgular çoğunlukla sözleşme tutarsızlıkları (HTTP durum kodları, HEAD/405, kenar durumda 500), eksik idempotency (mesaj, not) ve frontend'in sunucu sözleşmesini tam kullanmaması üzerine. Kritik/yüksek bulgu yok.

## İncelenen alanlar
config/urls.py ve tüm app urls.py; core/crud.py (Resource/ResourceView/CRUD view'ları); farm (stock, feeding, health, water), inventory, reports, tasks, hr, messaging, knowledge, monitoring, core views; frontend/components.ts, poll.ts, designer.ts; core/test_frontend_contract.py; entry_key kullanımı.

## İncelenmeyen alanlar
experiments view'larının (start/copy/release/replace) tek tek metod davranışı; hr/resources ve farm/resources içindeki özel create_view'lar; şablonların tamamı; testlerin çalıştırılması; çalışan uygulamaya karşı canlı HTTP denemesi (Django ortamda kurulu değil).

## Bulgular

### 38-1 - Çakışan `next` doğrulama kodu 6+ yerde kopyalanmış, davranışları farklı
- Önem: low | Güven: high
- Dosyalar: farm/stock/views.py:257, farm/health/views.py:49, farm/water/views.py:114, inventory/views.py:57, hr/views.py:34, tasks/views.py:30
- Açıklama: "geri dönülecek adres" kuralı her modülde ayrı yazılmış. farm/health/inventory/water yalnızca `GET['next']` okur ve `require_https` vermez; hr yalnızca `POST['next']` okur ve `require_https=request.is_secure()` kullanır; tasks hem POST hem GET okur ama kendi `startswith('/operations/tasks/')` kuralını kullanır.
- Kanıt: bkz. dosya:satırlar; hr/views.py `_return` `require_https` içerir, diğerleri içermez.
- Öneri: tek bir `core.crud.safe_next(request, default)` yardımcısı; https zorunluluğu tek yerde.

### 38-2 - Mesaj gönderme (`messaging:post`) idempotent değil
- Önem: medium | Güven: high
- Dosyalar: messaging/views.py:91, messaging/services.py:232, templates/messaging/inbox.html:37
- Açıklama: Stok, besleme, envanter, tedavi vb. `entry_key` ile aynı form iki kez gönderilince tek kayıt yaratır; mesaj formunda anahtar yok. Çift tıklama/yeniden gönderme/ağ tekrarı aynı mesajı iki kez ekler. `Message` modelinde `entry_key` yok (grep sonucu yalnızca hr, tasks, inventory, farm, experiments modellerinde).
- Kanıt: `post()` doğrudan `services.post_as(...)`; `MessageForm` içinde istemci anahtarı yok.
- Öneri: formda gizli UUID, `Message(conversation, author, client_key)` benzersiz kısıtı.

### 38-3 - Görev notu ekleme (`task_note`) idempotent değil
- Önem: low | Güven: high
- Dosyalar: tasks/views.py:79, tasks/services.py:190, templates/tasks/_task_drawer.html:71
- Açıklama: Notlar "kalıcı, düzenlenmez, silinmez" olduğundan çift gönderim kalıcı yinelenen not üretir. `tick` ise mutlak küme (idempotent) olarak tasarlanmış; `add_note` ile tutarsız.
- Kanıt: `add_note` view -> `services.add_note`, anahtar yok.
- Öneri: `entry_key` benzeri istemci anahtarı.

### 38-4 - `<int>.isdigit()` kontrolü Unicode rakamlarda 500 üretir
- Önem: low | Güven: high
- Dosyalar: messaging/views.py:72, messaging/views.py:113, reports/views.py:153, farm/water/views.py:462
- Açıklama: `str.isdigit()` '²' gibi karakterlerde True döner ama `int('²')` ValueError fırlatır. `?before=²` (conversation), `?after=²` (poll, 5-10 sn'de bir çağrılan uç), `?year=²` (duty_done) işlenmemiş istisna -> HTTP 500. (Python'da doğrulandı: `'²'.isdigit()` True, `int('²')` ValueError.) farm/water/views.py:462 yalnızca kendi servis anahtarını ayrıştırdığı için daha az erişilebilir.
- Kanıt: `int(after) if after.isdigit() else 0`.
- Öneri: `isdecimal()`/`isascii() and isdigit()` ya da try/int/except ValueError.

### 38-5 - CRUD view'ları HEAD isteğine 405 döner; `Allow` başlığı yok
- Önem: low | Güven: high
- Dosyalar: core/crud.py:559-561
- Açıklama: `ResourceView.as_view` `getattr(self, request.method.lower())` ile gönderir; `head` tanımlı olmadığından tüm CRUD liste/form/detay sayfalarında HEAD 405 döner, oysa düz fonksiyon view'ları (monitor, storage vb.) HEAD'i kabul eder. 405 yanıtında `Allow` başlığı da yok (RFC 9110 zorunlu kılar). Ayrıca keyfi metod adı (`CONTEXT`, `URL`, `PAGE`) sınıfın kendi metodlarına eşleşir ve `TypeError` -> 500 verir (`handler(request, *args)`).
- Kanıt: `handler = getattr(self, request.method.lower(), None)`.
- Öneri: izinli metod beyaz listesi (`get/post`, `head=get`), 405'te `Allow` başlığı; Django `View.http_method_names` kullanın.

### 38-6 - Doğrulama hatası durum kodları tutarsız (200 vs 422)
- Önem: low | Güven: high
- Dosyalar: core/crud.py:648-662, farm/stock/views.py:267-271, messaging/views.py:44, reports/views.py:118,172, inventory/views.py
- Açıklama: Özel diyaloglar (stok, envanter, mesajlaşma, raporlar) geçersiz formda 422 döner (`_refused`), Resource tabanlı CRUD formları (CreateView/UpdateView `self.page(form)`) ise 200 döner. tasks `_action` ve messaging `start` da farklı davranır. İstemci (components.ts `load`) durum koduna bakmadığı için çalışıyor ama sözleşme belirsiz; proxy/izleme/test araçları hata oranını yanlış ölçer.
- Kanıt: `return self.page(form)` (200) vs `response.status_code = 422`.
- Öneri: `render_page` sonrası geçersiz form için tek yerde 422.

### 38-7 - `UpdateView`/`RowListView` kilit altında `.get(pk=pk)` DoesNotExist'ı yakalamaz
- Önem: low | Güven: medium
- Dosyalar: core/crud.py:724, core/crud.py:815
- Açıklama: `get_object()` 404 ile korunuyor, sonra transaction içinde `r.visible(request).select_for_update().get(pk=pk)` çağrılıyor. İki istek arasında kayıt soft-delete edilirse (veya görünürlük değişirse) `DoesNotExist` yakalanmaz -> 500. `DeleteView.post` ise `get_object_or_404` kullanır (tutarlı değil).
- Kanıt: satırlar yukarıda.
- Öneri: `get_object_or_404(r.visible(request).select_for_update(of=('self',)), pk=pk)`.

### 38-8 - Yıkıcı/sonlandırıcı eylemlerde ikinci istek idempotent değil: 404 veya hata
- Önem: low | Güven: medium
- Dosyalar: reports/views.py:104-120 (`close`, `_due_row`), reports/views.py:124-130 (`reopen`), reports/views.py:179-185 (`duty_undo`), messaging/views.py:262-272
- Açıklama: `close` çift gönderilince ikinci istekte `_due_row` None döner -> 404 (kullanıcıya "Nothing is owed" yerine sayfa bulunamadı); `reopen`/`duty_undo` ikinci istekte `get_object_or_404` -> 404. Buna karşılık `messaging.delete_message` ve `tasks.tick` bilinçli idempotent. Sözleşme tutarsız.
- Kanıt: `if row is None: raise Http404`.
- Öneri: bilinçli kararla ikinci istekte aynı sonuç sayfasına yönlendirme veya kullanıcı dostu mesaj.

### 38-9 - Durum değiştiren GET'ler (okundu işareti, oturum yenileme)
- Önem: info | Güven: high
- Dosyalar: messaging/views.py:63-80 (`conversation`), messaging/views.py:108-122 (`poll`), monitoring/views.py:50-58
- Açıklama: `GET /messages/<id>/` ve `GET /messages/<id>/new/` `mark_read` ile veritabanına yazar; `GET` monitoring `?wall=1` günde bir oturumu yeniler. Docstring'ler bunu belgeliyor (bilinçli) ancak GET'in güvenli/önbelleklenebilir olması varsayımını ihlal eder; prefetch/link önizleme araçları mesajları okundu işaretler. Poll yanıtı `no-store` olduğundan önbellek riski düşük.
- Kanıt: `services.mark_read(participant, ...)` GET içinde.
- Öneri: belgeleyin; mümkünse okundu işaretini ayrı bir POST/beacon'a taşıyın.

### 38-10 - `X-Modal` ile içerik değişen yanıtlarda `Vary: X-Modal` yok
- Önem: low | Güven: medium
- Dosyalar: core/crud.py:86-93, frontend/components.ts:334
- Açıklama: Aynı URL, `X-Modal: 1` başlığına göre `modal_base.html` veya `app_base.html` ile render ediliyor. Sayfa yanıtlarında `Cache-Control`/`Vary: X-Modal` ayarlanmıyor (yalnızca poll parçaları ve PDF için ayarlı). Tarayıcı geri-ileri önbelleği veya ara önbellek modal parçasını tam sayfa olarak gösterebilir.
- Kanıt: `grep Vary|vary_on` kodda eşleşme yok; `is_modal` yalnızca başlık okur.
- Öneri: `render_page` içinde `patch_vary_headers(response, ('X-Modal',))`.

### 38-11 - `components.ts` modal `load()` ağ/sunucu hatalarında sessiz bozuk davranış
- Önem: low | Güven: high
- Dosyalar: frontend/components.ts:333-362
- Açıklama: `fetch` try/catch dışında (ağ hatasında yakalanmamış promise rejection, diyalog açılmaz); yalnızca 403 özel işlenir; 404/405/500 yanıtlarının gövdesi (boş veya hata sayfası HTML'i) doğrudan `innerHTML` ile diyaloğa basılır. Ayrıca 403 mesajı CSRF hatalarında da "yetkiniz yok" anlamına gelir.
- Kanıt: `this.content.innerHTML = await response.text();`
- Öneri: `!response.ok` (422 hariç) için genel hata görünümü ve try/catch.

### 38-12 - Tasarımcı önizlemesi (`cardtemplate_preview`) hataları istemcide yutulur; hata yanıt biçimi tutarsız
- Önem: low | Güven: high
- Dosyalar: frontend/designer.ts:467-474, monitoring/views.py:186-194, monitoring/views.py:66-72
- Açıklama: Sunucu 413/400 için `{"error": ...}` JSON, 503 için `text/plain` döner; istemci `!response.ok` ise sessizce `return` eder (kullanıcıya hiçbir ileti yok, `error` alanı hiç okunmuyor). Başarılı/başarısız yanıt zarfı: 200 + `{html, problems}`, hatalarda farklı. Tek JSON ucu için sözleşme yazılı bir şemaya bağlı değil.
- Kanıt: `if (!response.ok) { return; }`
- Öneri: tek hata zarfı (`{error, code}`), istemcide durum bildirimi (`status` alanı zaten var).

### 38-13 - Poll istemcisi `Retry-After` başlığını yok sayar
- Önem: info | Güven: high
- Dosyalar: monitoring/views.py:67-72, frontend/poll.ts:196-199
- Açıklama: Sunucu 503'te `Retry-After: 30` gönderir; poll.ts `!response.ok` -> `failed()` (kendi geri çekilmesi) ve başlığı okumaz (`grep Retry-After frontend/poll.ts` boş). Sunucunun beklenen aralığı ile istemcinin geri çekilmesi birbirinden bağımsız.
- Kanıt: dosyalar yukarıda.
- Öneri: `Retry-After` varsa gecikme için kullan veya sunucu başlığını kaldırıp belgeleyin.

### 38-14 - URL adlandırma kuralları tutarsız (fiil yeri, kök yolları, tekil/çoğul)
- Önem: low | Güven: high
- Dosyalar: farm/urls.py:25-47, reports/urls.py:12-20, messaging/urls.py:13, hr/urls.py, core/urls.py, çeşitli resources `url_prefix`
- Açıklama: "void" eylemi bir yerde `.../void/<pk>/` (units, feeding, water, storage) başka yerde `.../<pk>/void/` (treatments, lice, events). Rapor: `reports/close/` (sorgu dizgesiyle kimlik) ve `reports/closed/<pk>/reopen/`. Mesajlaşma: yeni mesajları poll eden uç `<pk>/new/` (`new/` ise yeni konuşma). Referans veri uçları kökte (`sites`, `tanks`, `roles`, `users`) ama işlemler `operations/...`, İK `hr/...`, deneyler `research/experiments`. `hr/` ve `production/team/` aynı sayfaları iki adreste sunar.
- Kanıt: urlpatterns listeleri.
- Öneri: tek kural (`<kaynak>/<pk>/<fiil>/`), poll için `.../poll/`.

### 38-15 - `close` ve `duty_done` diyaloglarının kimliği sorgu dizgesinde taşınıyor, POST'ta da
- Önem: low | Güven: high
- Dosyalar: reports/views.py:93-101, reports/views.py:146-155, templates/reports/duty_done.html:12
- Açıklama: Kaynağın kimliği path yerine `?kind=&site=&period=` ve form `action=request.get_full_path`; URL yolu bir kaynağı tanımlamıyor, böylece kaynak-tabanlı yetkilendirme/log/önbellek için anlamlı bir path yok, ayrıca eksik/hatalı parametreler 404 olur. Kayıt oluşturan POST'lar için `entry_key` yok (close/duty_done), çift gönderim 38-8 yolunu izler.
- Kanıt: `_due_row(request)` `request.GET`'ten okur.
- Öneri: `reports/due/<kind>/<site>/<period>/close/` gibi path parametreleri.

### 38-16 - `document_file` `?download` değerinden bağımsız indirir
- Önem: info | Güven: high
- Dosyalar: knowledge/views.py:33
- Açıklama: `as_attachment='download' in request.GET` — `?download=0` bile indirmeye zorlar. Ayrıca PDF yanıtı `X-Content-Type-Options` yalnız SecurityMiddleware varsayılanına bağlı (dosyada açık belirtilmedi).
- Kanıt: satır 33.
- Öneri: `request.GET.get('download') in ('', '1')` gibi açık kural.

### 38-17 - Rapor dışa aktarımı: ham `X-Api-*` başlıkları ve ek bağımlılık; `api_call` None ise TypeError riski
- Önem: low | Güven: medium
- Dosyalar: reports/views.py:200-215, reports/exports.py:115-139
- Açıklama: JSON export'ta `shaped = exports.api_json(...)` None değilse `call = exports.api_call(report)` çağrılıyor ve `call['method']` doğrudan indeksleniyor; `api_call` uç noktası olmayan türlerde None döndürür. `api_json` ile `api_call` farklı koşullarla (şekil vs. ENDPOINTS) karar verdiğinden, ikisi ayrışırsa 500. Şu an tutarlı olup olmadığı testle kilitlenmemiş (doğrulanmadı).
- Kanıt: `call = exports.api_call(report)`; `call['method']`.
- Öneri: `if call is None: raise Http404` veya tek kaynaktan türetme + test.

### 38-18 - Sözleşme testi yalnızca `data-poll*` kancalarını kapsar
- Önem: info | Güven: high
- Dosyalar: core/test_frontend_contract.py:1-40
- Açıklama: Şablon <-> poll.ts sözleşmesi test edilmiş; ancak `X-Modal`, `X-Modal-Redirect`, `X-Modal-Load`, `X-Poll-Next` başlık adlarının sunucu (core/crud.py:102-109, monitoring/views.py:136, messaging/views.py:121) ve istemci (components.ts:339-344, poll.ts:201) arasında eşleştiğini doğrulayan bir sözleşme testi yok; ad değişikliği sessizce kırar. Designer JSON yanıt şeması da testsiz.
- Kanıt: dosya başlığı yalnızca `data-poll|live|scroll-end|submit-on-enter` regex'i.
- Öneri: başlık sabitlerini tek yerden paylaşan/doğrulayan test.
