# 33 - Hata Yönetimi Denetimi

## Özet
Hata yönetimi denetimi: 15 bulgu. En önemlileri: üretim LOGGING yapılandırmasının yokluğu (DEBUG=False iken 500'ler kaydedilmez), DEBUG varsayılanının açık olması, özel 400/403/404/500 sayfalarının olmaması, monitoring.read.cards içindeki kayıtsız geniş except, knowledge PDF hata metninin ham olarak kullanıcıya gösterilmesi, designer.ts/poll.ts içinde sessiz sunucu hataları ve IntegrityError'ların kısıt ayrımı yapılmadan tek mesaja çevrilmesi. Olumlu: core.crud.constraint_error, hr/messaging'deki constraint_name kontrolü, monitoring _optional için throttle'lı logger.exception ve 503 + stale mekanizması iyi tasarlanmış.

## İncelenen alanlar
- config/settings.py (LOGGING/DEBUG/handler'lar)
- templates/ hata şablonları
- monitoring/read.py, views.py
- farm/placements.py
- knowledge/extraction.py, models/document.py
- hr/views.py, services.py
- reports/views.py
- IntegrityError yakalayıcıları (core, hr, messaging, experiments, farm)
- frontend/poll.ts, designer.ts, windows.ts, nav-boot.ts
- scripts/ ve boş 'pass' blokları

## İncelenmeyen alanlar
- Testlerin hata yolu kapsamı ayrıntılı incelenmedi
- Çalışma zamanında gerçek 500/404 cevapları denenmedi (salt-okunur kural)
- tasks, inventory, experiments view'ları tek tek taranmadı
- Şablonlarda form hata gösterimi ve erişilebilirlik ayrıntısı

## Bulgular

### 33-1 - Üretim için LOGGING yapılandırması yok; DEBUG=False iken yakalanmayan 500 hataları hiçbir yere yazılmaz
- Önem: high
- Güven: medium
- Dosyalar: config/settings.py
- Açıklama: config/settings.py içinde LOGGING, ADMINS, EMAIL_* veya SERVER_EMAIL tanımı yok. Django'nun varsayılan günlükleme ayarında console handler'ı yalnızca DEBUG=True iken, mail_admins ise DEBUG=False iken çalışır ve ADMINS boşsa hiçbir şey göndermez. Sonuç: DEBUG kapalı bir dağıtımda view içindeki yakalanmayan istisnalar ve 5xx cevapları kalıcı olarak kaydedilmez (yalnızca WSGI sunucusunun kendi çıktısı kalır). Uygulamada logger kullanan yalnızca 3 modül var (monitoring/read.py:60, monitoring/cards/resolve.py:24, farm/placements.py:18); core, hr, knowledge, reports, messaging, tasks, inventory, experiments altında hiç logger yok.
- Kanıt: grep: LOGGING|ADMINS|EMAIL -> config/settings.py'de eşleşme yok; 'logger\.|logging\.' yalnızca monitoring/read.py, monitoring/cards/resolve.py, farm/placements.py.
- Öneri: settings.py'ye açık bir LOGGING sözlüğü ekleyin (console/stderr handler, django.request ve uygulama logger'ları INFO/ERROR, yapılandırılabilir seviye); gerekirse ADMINS/Sentry benzeri bir 5xx bildirim yolu tanımlayın.

### 33-2 - DEBUG varsayılanı açık (fail-open): ortam değişkeni unutulursa hata sayfaları ayrıntı sızdırır
- Önem: medium
- Güven: high
- Dosyalar: config/settings.py
- Açıklama: DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1' ifadesi, değişken tanımlı değilse DEBUG'ı açar. SECRET_KEY için de bilinen 'django-insecure-...' yedeği var ve ALLOWED_HOSTS boş liste (DEBUG kapalıyken tüm istekler 400 olur, DEBUG açıkken localhost'a izin verilir). Hata yönetimi açısından: yanlış yapılandırılmış bir dağıtım kullanıcıya Django'nun teknik hata sayfasını (ayarlar, SQL, yerel değişkenler) gösterir. Başka uzmanlıkların da (secrets-config) kapsayabileceği konu; burada hata sayfası sızıntısı yönünden kaydedildi.
- Kanıt: config/settings.py:25 (SECRET_KEY yedeği), :28 (DEBUG varsayılanı '1'), :30 (ALLOWED_HOSTS).
- Öneri: Varsayılanı '0' yapın veya DJANGO_DEBUG verilmediğinde ve SECRET_KEY yedeği kullanıldığında başlangıçta hata verin; geliştirme için .env/docker-compose'da açıkça '1' verin.

### 33-3 - Özel 400/403/404/500 şablonları ve handler'ları yok; hata sayfaları markasız ve çevrilmemiş
- Önem: medium
- Güven: high
- Dosyalar: templates/, config/urls.py, core/crud.py
- Açıklama: templates/ altında 400.html/403.html/404.html/500.html yok; config/urls.py'de handler400/403/404/500 tanımı yok; CSRF_FAILURE_VIEW da yok. Uygulama sürekli PermissionDenied (core/crud.py:557, hr/views.py, @permission_required(raise_exception=True)) ve Http404 (kapsam dışı kayıtlar için bilinçli 404) kullanıyor; kullanıcı bu durumlarda Django'nun düz İngilizce ('Forbidden', 'Not Found', 'Server Error (500)') sayfasını görür: menü yok, dil seçimi yok (uygulama EN/NB/TR çok dilli), geri dönüş bağlantısı yok. frontend/poll.ts GONE=401/403/404 durumlarına özel davranıyor ama sayfa tarafında karşılığı yok.
- Kanıt: find . -name '404.html' -o -name '500.html' -o -name '403.html' (node_modules hariç) -> sonuç yok; grep handler404|handler500|csrf_failure -> yok.
- Öneri: templates/ kökünde 400/403/404/500.html (app/auth base'ten türeyen, çevrilmiş, ana sayfaya link veren) ekleyin; 500.html bağlam işlemcisi olmadan statik güvenli olmalı; CSRF_FAILURE_VIEW tanımlayın; locale katalogları ekleyin.

### 33-4 - monitoring.read.cards: zorunlu kaynak hatası her türlü istisnayı yutup günlüğe yazmadan Unavailable'a çevirir
- Önem: high
- Güven: high
- Dosyalar: monitoring/read.py, monitoring/views.py
- Açıklama: cards() içindeki geniş 'except Exception as error: raise Unavailable(str(error)) from error' (monitoring/read.py:335-336) için hiçbir logger çağrısı yok. View'lar Unavailable'ı yakalayıp 503 döndürüyor (monitoring/views.py:110, 142, 204) ve istisna oradan başka bir yerde kaydedilmiyor. Böylece kaynak okuma hatası (SQL hatası, TypeError/AttributeError gibi programlama hatası, kod regresyonu) izlenemez; yalnız duvar ekranı 'stale' görünür. Opsiyonel kaynaklar (_optional, satır 272-277) ise logger.exception ile kaydediliyor: iki yol arasında tutarsızlık var, ve kritik olanı kayıtsız. Geniş catch ayrıca gerçek hataları 'geçici kullanılamıyor' gibi maskeliyor (Retry-After: 30).
- Kanıt: monitoring/read.py:335-336; monitoring/views.py:66-71, 110, 142, 204; kıyas: monitoring/read.py:277 logger.exception.
- Öneri: Unavailable'a çevirmeden önce logger.exception (aynı 60 sn throttle ile) çağırın; yalnızca DatabaseError/beklenen okuma hatalarını yakalayın, programlama hatalarını yükseltin.

### 33-5 - Monitor sayfası 503 durumunda düz metin dönüyor (HTML sayfa değil)
- Önem: low
- Güven: high
- Dosyalar: monitoring/views.py
- Açıklama: _unavailable() hem poll parçası hem tam sayfa (monitor, satır 108-111) için content_type='text/plain' cevap veriyor. Poll için uygun ama tam sayfa isteğinde kullanıcı menüsüz, stilsiz, çevrilmiş tek satır metin görür ve yeniden denemek için sayfa yenilemesi gerekir. Docstring 'a page says so' diyor; gerçekte sayfa şablonu kullanılmıyor.
- Kanıt: monitoring/views.py:66-71 ve :108-111.
- Öneri: Tam sayfa isteğinde render_page ile 503 durumlu bir hata şablonu (yenile bağlantısı ile) döndürün; poll yolunda düz metin kalabilir.

### 33-6 - Kaynak hatası log throttle'ı süreç-yereli global sözlük; sayaç/metrik yok, başarısızlık sıklığı görünmez
- Önem: low
- Güven: medium
- Dosyalar: monitoring/read.py
- Açıklama: FAILED_AT (monitoring/read.py:86) modül düzeyi dict; çok süreçli (gunicorn worker) dağıtımda her worker ayrı throttle tutar ve dakikada en fazla bir kayıt yazılır. Hata sürerken yalnızca ilk istisna kaydedilir, kaç kartın/ne kadar süre etkilendiği hiçbir yerde sayılmaz. Ek olarak kart tarafı yalnızca 'no data' gösterir; kullanıcı kaynağın bozuk olduğunu operatöre bildirmek için ipucu görmüyor olabilir (failed seti kartlara geçiyor; kapsam doğrulanmadı).
- Kanıt: monitoring/read.py:86-87, 270-278.
- Öneri: Throttle'ı koruyun ama sayaç/son hata zamanı metriği veya sağlık ucu (health endpoint) ekleyin.

### 33-7 - farm.placements.of: bozuk sağlayıcı her istekte günlüğe istisna basar (throttle yok), üstelik TypeError dahil her şeyi yutar
- Önem: low
- Güven: medium
- Dosyalar: farm/placements.py
- Açıklama: 'except Exception' (farm/placements.py:49) 'fail open' olarak her istekte logger.exception çağırıyor; monitoring/read.py'deki gibi dakikada-bir sınırlaması yok. Kalıcı bir sağlayıcı hatası her sayfa/poll isteğinde tam stack trace yazar (log seli). Ayrıca sağlayıcının dönüş tipi doğrulaması için fırlatılan TypeError (satır 46-47) aynı genel yakalayıcıya düşüyor, yani sözleşme ihlali sessizce 'chip yok'a dönüşüyor; testler dışında fark edilmez.
- Kanıt: farm/placements.py:41-52.
- Öneri: Throttle ekleyin (monitoring/read.py ile ortak yardımcı); sözleşme ihlalini ayrı seviyede (error) ve ayrı mesajla kaydedin.

### 33-8 - knowledge: PDF okuma hatasının ham istisna metni veritabanına yazılıp kullanıcıya gösteriliyor; hata kaydı yok
- Önem: medium
- Güven: medium
- Dosyalar: knowledge/extraction.py, knowledge/models/document.py
- Açıklama: read_pdf geniş 'except Exception' ile f'{type(error).__name__}: {error}'[:500] biçimindeki ham metni text_error alanına yazıyor (knowledge/extraction.py:69-70). Document.text_status mesajı bunu gettext('The text could not be read: %(reason)s') içinde olduğu gibi kullanıcıya gösteriyor (knowledge/models/document.py:254). Sonuçlar: (a) Python sınıf adları ve kütüphane (pypdf) iç mesajları son kullanıcıya sızıyor, çevrilmiyor; (b) hiçbir logger çağrısı yok, bozuk dosya/kütüphane regresyonu operatöre görünmez; (c) 'The PDF is protected by a password.' (satır 62) sabit İngilizce, çeviri sarmalı yok ve veritabanında İngilizce saklanıyor (diğer alanlar için 'English at rest' kuralı var ama burada kullanıcıya olduğu gibi gidiyor). Doğrulanmadı: şablonda başka yerde farklı biçimde kullanılıyor olabilir.
- Kanıt: knowledge/extraction.py:62, 69-70; knowledge/models/document.py:227, 254.
- Öneri: Kullanıcıya sabit, çevrilebilir bir kod/mesaj gösterin; ham metni logger.warning ile kaydedin; _labels içindeki sessiz except (satır 84) için de en azından debug log ekleyin.

### 33-9 - Designer önizlemesi: sunucu hataları sessizce yok sayılıyor, ağ hatası yakalanmayan Promise reddine dönüşüyor
- Önem: medium
- Güven: high
- Dosyalar: frontend/designer.ts, monitoring/views.py
- Açıklama: refresh() içinde '!response.ok' durumunda hiçbir şey yapılmadan return ediliyor (frontend/designer.ts:~457-459): 400/403/413/503 cevaplarında kullanıcıya mesaj yok, önizleme eski haliyle kalıyor ve sunucunun {error:'too large'/'bad request'} gövdesi (monitoring/views.py:188,193) hiç okunmuyor. catch bloğu yalnızca AbortError'ı yutuyor, diğer her hata (çevrimdışı TypeError, response.json() parse hatası) 'throw error' ile yeniden fırlatılıyor; çağıran 'void this.refresh()' olduğundan bu yakalanmayan unhandledrejection olur ve arayüzde durum göstergesi güncellenmez. Oturum süresi dolarsa (redirected/401) de geri bildirim yok.
- Kanıt: frontend/designer.ts:~445-485 (refresh); frontend/designer.ts:~391 'void this.refresh()'; monitoring/views.py:186-193.
- Öneri: Hata durumunda this.status/problems alanına çevrilmiş bir 'önizleme alınamadı' mesajı yazın; ağ hatalarını yakalayın; response.redirected/401/403 için poll.ts'deki gibi oturum uyarısı verin.

### 33-10 - poll.ts form 'live' yenilemesi: sunucu hatası ve ağ hatası tamamen sessiz
- Önem: low
- Güven: high
- Dosyalar: frontend/poll.ts
- Açıklama: live() içinde '!response.ok' ise 'return' (frontend/poll.ts:~311-316 'a passing server error: the next change asks again') ve catch bloğu boş (satır ~324-326); yalnızca aria-busy kaldırılıyor. Kullanıcı filtre/arama sonucunun yenilenmediğini fark edemez ve ekran okuyucuya da bildirim yok. poll() tarafında ise 'stale' durumu var; iki mekanizma arasında tutarsızlık.
- Kanıt: frontend/poll.ts:~311-330 (live), kıyas ~193-210 (failed()/state('stale')).
- Öneri: Hata durumunda forma 'sonuçlar güncel olmayabilir' uyarısı (aria-live) ekleyin; ya da sayfayı ?query ile yeniden yükleyin.

### 33-11 - IntegrityError yakalayıcıları kısıt adını ayırt etmeden tek bir 'başkası aynı anda yaptı' mesajı veriyor
- Önem: medium
- Güven: medium
- Dosyalar: hr/views.py, experiments/services.py, farm/resources/feeding_protocol.py, messaging/services.py, farm/feeding/assignments.py
- Açıklama: Bazı yerler doğru yapıyor: hr/services.py:355 ve messaging/services.py:142 kısıt adını (constraint_name) kontrol edip diğerlerini yeniden fırlatıyor, core/crud.py constraint_error ile yalnız bilinen kısıtları eşliyor. Ancak şu yerler her IntegrityError'ı tek bir yarış mesajına çeviriyor ve kaydetmiyor: hr/views.py:86-88 ('Someone planned one of these days at the same time'), experiments/services.py:451, 666, 883 ('A tank was booked to another experiment meanwhile'), farm/resources/feeding_protocol.py:150 ve farm/feeding/assignments.py çağıran view ('Another protocol was assigned...'). NOT NULL/FK/CHECK ihlalleri gibi gerçek hatalar da bu mesajla maskelenir ve günlüğe düşmez. messaging/services.py:112 ise IntegrityError sonrası doğrudan Conversation.all_objects.get(direct_key=key) çağırıyor: ihlal başka bir sebepten ise DoesNotExist (yakalanmamış 500) oluşur.
- Kanıt: hr/views.py:78-88; experiments/services.py:451,666,883; farm/resources/feeding_protocol.py:150; messaging/services.py:105-114.
- Öneri: Ortak bir yardımcıyla constraint_name'e göre ayıklayın, tanınmayanı yeniden fırlatın veya en azından logger.exception ile kaydedin; messaging'de get() sonucunu da koruyun.

### 33-12 - Hata mesajlarının dili/çevirisi tutarsız: bazı JSON/Http yanıtları sabit İngilizce
- Önem: low
- Güven: high
- Dosyalar: monitoring/views.py, hr/views.py, knowledge/views.py
- Açıklama: JsonResponse({'error': 'too large'}) ve ({'error': 'bad request'}) (monitoring/views.py:188,193) çevrilmemiş ve ham; HttpResponseBadRequest() gövdesiz (hr/views.py:63,73; knowledge/views.py:62) olduğundan kullanıcı Django'nun boş 400 sayfasını görür (özel 400 şablonu da yok, bkz. 33-3). Oysa uygulamanın geri kalanı messages.error ve gettext kullanıyor.
- Kanıt: monitoring/views.py:188,193; hr/views.py:63,73; knowledge/views.py:62.
- Öneri: Form tabanlı view'larda 400 yerine messages.error + yönlendirme; JSON hata kodlarını sabit anahtar yapıp istemcide çevirin.

### 33-13 - hr.views.plan: anlamsız 'except PermissionDenied: raise' ve 'cells' ayrıştırma hatasında nedensiz boş 400
- Önem: info
- Güven: high
- Dosyalar: hr/views.py
- Açıklama: 'except PermissionDenied: raise' (hr/views.py:80-81) davranışı değiştirmez, ölü koddur (yalnızca ValidationError/IntegrityError'dan önce sıralama niyeti olabilir). Biçimi bozuk 'cells' veya bilinmeyen vardiya için HttpResponseBadRequest() cevabında neden yok; gerçek kullanıcı formlarında bu durum yalnızca sahte istekte oluşur, bu nedenle etkisi düşük.
- Kanıt: hr/views.py:60-74, 78-88.
- Öneri: Gereksiz except'i kaldırın; 400 yanıtlarına kısa neden ekleyin.

### 33-14 - Frontend'de fetch yanıtları için merkezi hata/oturum-bitti kullanıcı bildirimi yok; yalnızca localStorage hataları yorumla yutuluyor (kabul edilebilir)
- Önem: info
- Güven: medium
- Dosyalar: frontend/poll.ts, frontend/windows.ts, frontend/nav-boot.ts, frontend/designer.ts
- Açıklama: Boş catch blokları: windows.ts:61,77 ve nav-boot.ts:10,13 yalnızca localStorage erişimi için ve yorumlu (kabul edilebilir). windows.ts:228 'request.catch(() => undefined)' reddedilen bir isteği yorumla yutuyor. Asıl ağ çağrıları (poll.ts, designer.ts) için ortak bir hata raporlama/telemetri noktası yok; tarayıcı tarafı hatalar için window.onerror/unhandledrejection dinleyicisi veya sunucuya raporlama bulunmuyor (grep ile console.error/onerror eşleşmesi yok).
- Kanıt: grep: 'console\.(error|log)|onerror|unhandledrejection' frontend/*.ts (test/ hariç) -> eşleşme yok; frontend/windows.ts:61,77,228; frontend/nav-boot.ts:10,13.
- Öneri: Küçük bir ortak 'reportError' yardımcısı (kullanıcıya durum + isteğe bağlı sunucu log ucu) düşünün.

### 33-15 - Silme/geri alma view'larında (reports.reopen, duty_undo) ValidationError yakalanmıyor; kardeş view'lar yakalıyor
- Önem: low
- Güven: low
- Dosyalar: reports/views.py, reports/services.py
- Açıklama: reports/views.py:123-131 reopen ve :178-182 duty_undo, services.reopen/undo_duty_done çağrısını try/except olmadan yapıyor; aynı dosyadaki diğer POST view'ları (satır 63-67, 107-110, 162-165, 192-194) ValidationError'ı mesaja çeviriyor. services.reopen ve undo_duty_done içinde 'raise' bulunmadığı için şu an tetiklenmiyor (grep ile doğrulandı), fakat servis ileride bir kural eklerse 500 olur; tutarsız desen.
- Kanıt: reports/views.py:123-131, 178-182 vs 55-70, 94-120, 147-175, 187-195.
- Öneri: Aynı deseni (try/except ValidationError -> messages.error) uygulayın veya servislerin hata fırlatmadığını testle sabitleyin.
