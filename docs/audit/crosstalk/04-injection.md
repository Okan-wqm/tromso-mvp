# Enjeksiyon uzmanı (04) - çapraz değerlendirme

## Doğrulananlar
- 03-4 / 04-1: templates/registration/_field.html:20 `help_text|safe`. Kaynak şu an sabit çeviri metinleri (farm/forms/water.py:167); kullanıcı verisi akışı yok, risk gelecekteki değişikliğe bağlı. Doğrulandı (low).
- 03-12: password_reset_email.html:1 `autoescape off` düz metin e-postada; kullanıcı adı HTML'e girmiyor. Doğrulandı (info).
- 03-10 / 04-11: `next` doğrulaması 6+ yerde kopya: hr/views.py:38 (POST, require_https), tasks/views.py:31 (POST veya GET), inventory:60, health:52, stock:261, water:117 (`startswith('/')` farklı sırada), feeding:298. Hepsi url_has_allowed_host_and_scheme kullanıyor; açık yönlendirme yok ama hr dışındakiler require_https vermiyor. Doğrulandı.
- 06-4 / 04-4: %PDF- ilk 1KB içinde herhangi bir yerde aranıyor; içerik inline `application/pdf` ile sunuluyor (knowledge/views.py:37). Doğrulandı.
- 06-2 / 04-5: PDF çıkarımı istek içinde sınırsız; doğrulandı.
- 03-3: assets.py importmap mark_safe+json.dumps; girdi dosya yolu/mtime (sunucu kaynaklı), düşük risk. Doğrulandı.

## Önem derecesi itirazları
- 03-4 low/medium uygun. 06-9/03-14 (CSP sandbox yok) düşük kalmalı: nosniff + Content-Type sabit application/pdf; yine de PDF içinde JS çalıştırma yüzeyi tarayıcıya bağlı.
- 01-2 / 05-1 / 05-2 fail-open SECRET_KEY: enjeksiyon açısından önemli, çünkü imzalı çerez/oturum ve audit HMAC (core/audit.py:98) tahmin edilebilir hale gelir; high doğru.

## Yeni bulgular
- 04-X1 (low): knowledge/views.py:37 `filename=document.file_name` kullanıcı yükleme adından türetiliyor (_file_name, document.py:258). Django FileResponse RFC 6266 kaçışlamasını yapıyor, başlık enjeksiyonu yok; ancak 06-10 ile aynı kökten ad normalleştirme zayıflığı (Unicode kontrol/bidi karakterleri indirilen ad ve arayüzde görünür). Öneri: ad temizliğine bidi/kontrol karakteri filtresi.
- 04-X2 (info): `next` yardımcıları için tek ortak fonksiyon yok (7 kopya); biri güvenlik sertleştirmesi (require_https, `//` kontrolü) eklenince diğerleri geride kalır. 03-10 ile aynı; mimari tarafı ile birlikte ele alınmalı.
- 04-X3 (low): ALLOWED_HOSTS (config/settings.py:30) boş ise DEBUG=1 varsayılanıyla Django her hostu kabul eder; `request.get_host()` allowed_hosts olarak kullanıldığından (hr/views.py:38 vb.) next doğrulaması Host başlığına güvenir. DEBUG kapalıysa ALLOWED_HOSTS boşken başlangıçta hata verir; yani risk 05-2'ye bağlı. Host-header tabanlı parola sıfırlama bağlantısı zehirlemesi de aynı koşulda (e-posta bağlantıları request.get_host() ile üretilir) yalnızca DEBUG/boş host durumunda olası. confidence=medium.

## Komşulara sorular
- authn (01): parola sıfırlama e-postası bağlantısı host'unu hangi kaynaktan alıyor (Host başlığı mı, sabit site domaini mi)? ALLOWED_HOSTS boşken zehirlenme mümkün mü?
- file-upload (06): yükleme dosya adı sanitizasyonu için bidi/kontrol karakterleri test ediliyor mu?
- csrf-xss (03): frontend innerHTML sink'lerinin (03-8) beslendiği sunucu yanıtlarında kullanıcı verisi kaçışlı mı, hangi uç noktalar?
- ci-devops (37): 37-5 assets.py her render'da getmtime çağırıyor; DEBUG dışında finders.find hata yolunda path traversal yok (yalnızca sabit şablon argümanları); önem low yeterli mi?
