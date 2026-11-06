# 05 - Gizli bilgiler ve yapılandırma denetimi (secrets-config)

## Özet
Repoda git geçmişinde (299 commit, tüm dallar) gerçek bir sır bulunmadı; `.env`, anahtar, dump dosyası izlenmiyor. Ancak yapılandırma "geliştirme varsayılanı güvenli olmayan, üretim için fail-closed olmayan" tasarımda: SECRET_KEY, DEBUG ve DB parolası kodda sabit varsayılanlara düşüyor; hiçbir `SECURE_*`/cookie bayrağı yok; üretim ayarı ayrımı, `.env.example`, Dockerfile, CI ve secret-scanning yok. Bulgular 01-authn ve 02-authz ile kısmen örtüşür; burada yapılandırma ve sır yönetimi açısından ele alındı.

## İncelenen alanlar
config/settings.py, docker-compose.yml, .gitignore, requirements.txt, wsgi/asgi/manage.py, core/audit.py (SECRET_KEY kullanımı), config/database.py (maskeleme), README dağıtım bölümü, git geçmişi (SECRET/PASSWORD/django-insecure aramaları, silinmiş dosya adları), izlenen dosya listesi.

## İncelenmeyen alanlar
Gerçek dağıtım ortamı (nginx/gunicorn, sunucu env'leri), frontend bağımlılıklarının (package-lock) sır/tedarik zinciri incelemesi, entropi tabanlı tam secret-scan aracı çalıştırılmadı.

## Bulgular

### 05-1 | yüksek | güven: yüksek - SECRET_KEY sabit, bilinen varsayılana düşüyor (fail-open)
Dosyalar: config/settings.py:25, core/audit.py:98-99
Açıklama: `DJANGO_SECRET_KEY` yoksa herkesçe bilinen (repoda açık) anahtar kullanılır; hata vermez. Oturum, parola sıfırlama token'ları ve audit "private text" HMAC özetleri tahmin/üretilebilir olur.
Kanıt: `SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-development-only')`; `settings.SECRET_KEY.encode()` HMAC anahtarı olarak core/audit.py:99.
Öneri: DEBUG kapalıyken anahtar yoksa `ImproperlyConfigured` fırlat; varsayılanı yalnızca DEBUG açıkken ver.

### 05-2 | yüksek | güven: yüksek - DEBUG varsayılanı açık (fail-open)
Dosyalar: config/settings.py:28
Açıklama: `DJANGO_DEBUG` verilmezse DEBUG=True. Unutulan bir env üretimde ayrıntılı hata sayfaları, ayar/SQL sızıntısı ve gevşek ALLOWED_HOSTS davranışı demektir.
Kanıt: `DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'`
Öneri: Varsayılanı '0' yap; geliştirici `.env`/komutla açsın.

### 05-3 | orta | güven: yüksek - Veritabanı kimlik bilgileri kodda varsayılan, parola kullanıcı adıyla aynı
Dosyalar: config/settings.py:113-116, docker-compose.yml:8-10
Açıklama: DB adı/kullanıcı/parola `balik` varsayılan; env verilmezse üretimde de bu denenir. Compose, Postgres portunu tüm arayüzlere (0.0.0.0) yayınlar.
Kanıt: `'PASSWORD': os.environ.get('DB_PASSWORD', 'balik')`; `ports: ["${DB_PORT:-5433}:5432"]` (127.0.0.1 bağlaması yok); `POSTGRES_PASSWORD: ${DB_PASSWORD:-balik}`.
Öneri: Compose portunu `127.0.0.1:${DB_PORT:-5433}:5432` yap; DEBUG kapalıyken DB_PASSWORD zorunlu olsun.

### 05-4 | orta | güven: yüksek - Cookie/HTTPS sertleştirme ayarları hiç yok
Dosyalar: config/settings.py (yokluk; ilgili ayarlar yok)
Açıklama: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_AGE`, `SECURE_CONTENT_TYPE_NOSNIFF` vb. tanımlı değil; HTTPS arkasında bile çerezler Secure işaretsiz gider. `grep` tüm .py dosyalarında yalnızca `LANGUAGE_COOKIE_SAMESITE` buldu (settings.py:158).
Kanıt: `grep -rnE 'SESSION_COOKIE|CSRF_|SECURE_|HSTS'` boş (testler ve migrations hariç).
Öneri: DEBUG kapalıyken etkinleşen bir üretim bloğu ekle; `manage.py check --deploy` CI'da çalışsın.

### 05-5 | orta | güven: yüksek - Üretim/geliştirme ayrımı ve dağıtım artefaktları yok
Dosyalar: config/settings.py, docker-compose.yml, README.md:2975-2993
Açıklama: Tek settings dosyası; `.env.example`, Dockerfile, CI iş akışı, gunicorn/nginx örneği repoda yok (izlenen dosyalar arasında `.github`, Dockerfile, `.env.example` yok). README yalnızca env adlarını yazıyor (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` README'de sistematik bir "üretim kontrol listesi" olarak yer almıyor). Not: `.env` .gitignore'da ama uygulama `.env` okumuyor (python-dotenv yok), dolayısıyla .gitignore girdisi yanıltıcı olabilir.
Kanıt: `git ls-files | grep -iE 'github|Dockerfile|\.env'` boş; requirements.txt'te dotenv yok.
Öneri: `.env.example`, üretim kontrol listesi ve `check --deploy` adımı ekle; .env'in nasıl yüklendiğini belgele.

### 05-6 | orta | güven: yüksek - E-posta üretim için yapılandırılmamış (konsol arka ucu), parola sıfırlama sızıntısı riski
Dosyalar: config/settings.py:191-195, README.md:3253
Açıklama: Tek posta ayarı konsol backend'i; üretimde sıfırlama bağlantıları sunucu loguna düşer (log okuyan herkes hesap ele geçirebilir) ve kullanıcı e-posta almaz. SMTP kimlik bilgileri için env tabanlı yol yok.
Kanıt: `'BACKEND': 'django.core.mail.backends.console.EmailBackend'`. `MAILERS` ayarı yeni Django 6.1 biçimi; eski `EMAIL_*` kullanılmıyor.
Öneri: Backend ve SMTP bilgilerini env'den oku; üretimde konsol backend'ini reddet.

### 05-7 | orta | güven: orta - ALLOWED_HOSTS boş varsayılan; DEBUG kapalıyken tüm istekler reddedilir, belgesi yok
Dosyalar: config/settings.py:30
Açıklama: Boşsa DEBUG açıkken yalnız localhost kabul edilir; kapalıyken her istek 400 alır. Güvenli yönde ama hata mesajı sezgisel değil ve README'de DJANGO_ALLOWED_HOSTS biçimi (virgüllü liste, boşluk kırpılmıyor) yok. `split(',')` sonrası `strip()` yapılmadığından `a.com, b.com` yazımında ikinci host eşleşmez.
Kanıt: `[h for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h]`
Öneri: `h.strip()` ekle, belgele.

### 05-8 | orta | güven: yüksek - Gizli bilgi alanı (SECRET_KEY) çoklu amaçlı kullanılıyor; rotasyon yolu yok
Dosyalar: config/settings.py:25, core/audit.py:98
Açıklama: `SECRET_KEY_FALLBACKS` tanımlı değil; anahtar değişince tüm oturumlar düşer ve audit HMAC özetleri eski kayıtlarla karşılaştırılamaz hale gelir. Audit özeti için ayrı bir anahtar yok.
Kanıt: settings.py'de `SECRET_KEY_FALLBACKS` yok; audit.py:99 doğrudan SECRET_KEY kullanır.
Öneri: Audit için ayrı anahtar ve `SECRET_KEY_FALLBACKS` ile rotasyon planı.

### 05-9 | düşük | güven: yüksek - Compose: parolasız-yan etkili ve sürüme/kaynağa kısıt yok, restart: unless-stopped geliştirme DB'si için
Dosyalar: docker-compose.yml:5-15
Açıklama: Görüntü sürümü sabitlenmiş (iyi) ama digest yok; kaynak limiti, healthcheck, ağ izolasyonu yok. Başlık "Local development" diyor; üretim DB'si olarak kullanılırsa varsayılan parola geçerli kalır.
Kanıt: docker-compose.yml:1-15 (healthcheck/deploy anahtarı yok).
Öneri: Healthcheck ekle; dosyanın yalnızca geliştirme için olduğunu README'de vurgula.

### 05-10 | düşük | güven: yüksek - MEDIA_ROOT varsayılanı checkout içinde
Dosyalar: config/settings.py:180, .gitignore (/media/)
Açıklama: Yüklenen PDF'ler varsayılan olarak `BASE_DIR/media`'ya yazılır; git'e girmez (iyi, /media/ ignore) ve MEDIA_URL rotası yok (iyi). Üretimde env verilmezse veri kod dizininde kalır, dağıtımda silinebilir. README uyarıyor ama ayarda zorlama yok.
Kanıt: `MEDIA_ROOT = Path(os.environ.get('DJANGO_MEDIA_ROOT', BASE_DIR / 'media'))`
Öneri: Üretimde DJANGO_MEDIA_ROOT'u zorunlu kıl.

### 05-11 | düşük | güven: orta - DEBUG varsayılanı açık olduğundan DEBUG'a bağlı komutlar varsayılan çalışır
Dosyalar: README.md:2827, config/settings.py:28
Açıklama: `seed_hr_demo` "yalnızca DEBUG açıkken" korumasına dayanıyor; DEBUG varsayılanı açık olduğundan (05-2) bu koruma yapılandırma hatasında devre dışı kalır ve demo verisi üretimde oluşabilir. (Komutun kendi kodu doğrulanmadı.)
Kanıt: README.md:2827.
Öneri: 05-2'nin düzeltilmesiyle kapanır.

### 05-12 | düşük | güven: orta - Parola doğrulayıcı minimum uzunluğu varsayılan (8), parola politikası yapılandırılmamış
Dosyalar: config/settings.py:132-145
Açıklama: `MinimumLengthValidator` seçeneksiz; farm/HR verisi için daha uzun alt sınır düşünülebilir. Parola hasher'ı özelleştirilmemiş (Django varsayılanı PBKDF2, kabul edilebilir).
Kanıt: settings.py:137-138.
Öneri: `OPTIONS: {'min_length': 12}`.

### 05-13 | bilgi | güven: yüksek - Git geçmişinde gerçek sır bulunmadı
Dosyalar: git geçmişi (299 commit)
Açıklama: `git log --all -S'SECRET'/'django-insecure'` yalnızca aynı geliştirme varsayılanını gösterdi; silinmiş dosyalar arasında .env/pem/key/sql/dump yok; izlenen `.sql/.pem/.key/.sqlite3/.csv` dosyası yok. Gerçek DB parolası veya üretim anahtarı sızmamış görünüyor (tam entropi taraması yapılmadı).
Kanıt: `git log --all --diff-filter=D --name-only` filtresi boş; `git ls-files | grep -iE '\.(sql|dump|pem|key|sqlite3|csv)$'` boş.
Öneri: CI'ya gitleaks/trufflehog ekle.

### 05-14 | bilgi | güven: yüksek - İyi uygulamalar
Dosyalar: config/database.py:20-28, .gitignore, requirements.txt
Açıklama: `auth_user.password` ve mesaj gövdeleri DB görüntüleyicide maskeli; `.env`, `/media/`, `db.sqlite3` ignore'da; bağımlılıklar sabit sürümlü (`==`), pypdf için güvenlik gerekçesi yorumlanmış; telemetri kapalı (`timescaledb.telemetry_level=off`); `LoginRequiredMiddleware` global.
Kanıt: ilgili satırlar yukarıda.
Öneri: Korunmalı.

### 05-15 | bilgi | güven: yüksek - Bağımlılık kilidi hash'siz; `requirements.txt` sürümleri sabit ama `--require-hashes` yok
Dosyalar: requirements.txt
Açıklama: Tedarik zinciri sertleştirmesi (hash doğrulama, pip-audit) yok; sürümler kilitli olduğundan risk düşük.
Kanıt: requirements.txt satırları `paket==sürüm`.
Öneri: pip-compile --generate-hashes ve pip-audit CI adımı.
