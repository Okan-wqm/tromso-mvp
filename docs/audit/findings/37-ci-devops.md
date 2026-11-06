# 37 - CI/DevOps (Build/Deploy, gözlemlenebilirlik) Denetimi

## Özet
Repoda üretim dağıtımına dair hiçbir yapı taşı yok: CI/CD pipeline (.github, vb.), Dockerfile, uygulama servisi, gunicorn/WSGI sunucusu bağımlılığı, statik dosya servisi (STATIC_ROOT/whitenoise), healthcheck, yapılandırılmış LOGGING, hata izleme, .env.example, Makefile/pre-commit/lint yapılandırması bulunmuyor. docker-compose.yml yalnızca yerel veritabanı içindir (imaj sürümü sabitlenmiş, ancak healthcheck ve yedek yok). Dağıtım adımları (npm build, compile_catalogs, migrate) yalnızca Windows odaklı README "Local setup" bölümünde; cron gerektiren komutlar (generate_tasks, check_*) zamanlanmış hâlde değil. Güvenlik odaklı üretim ayarları 05-secrets-config.md'de ayrıca ele alınmıştır; burada yalnızca build/deploy/gözlemlenebilirlik yönü yer alır.

## İncelenen alanlar
- docker-compose.yml, .gitignore, requirements.txt, package.json, package-lock.json, tsconfig*.json, scripts/mark-esm.mjs
- config/settings.py, wsgi.py, asgi.py, urls.py, views.py, test_runner.py
- core/templatetags/assets.py, core/migrations/0001_timescaledb.py, management komutları (generate_tasks, compile_catalogs, check_*)
- README.md "Local setup", "Email", "Languages", "Browser code" bölümleri; THIRD_PARTY.md
- git ls-files (CI/lint/Makefile/pre-commit/pyproject yokluğu), .git/hooks (boş)

## İncelenmeyen alanlar
- Çalışan uygulama/Docker üzerinde canlı test (yıkıcı çalıştırma yasak, docker yok)
- Testlerin tam çalıştırılması ve süresi; frontend testleri (node_modules kurulu değil)
- Tüm templates/ ve frontend/ içeriği; yalnızca build/asset yolu bakıldı
- Yedekleme/geri yükleme ayrıntısı: 12-backup-restore.md; sır/ayar: 05-secrets-config.md

## Bulgular

### 37-1 - CI/CD pipeline yok
- Önem: high | Güven: high
- Dosyalar: (yok: .github/, .gitlab-ci.yml vb.), THIRD_PARTY.md:7
- Açıklama: Repoda hiçbir CI tanımı yok; oysa THIRD_PARTY.md "Used to build and test ... on a developer's machine or in CI" diyerek CI'ı varsayıyor. Büyük bir test paketi (monitoring/tests, farm/tests, TS testleri, axe/playwright tarayıcı testi), `check_*` bütünlük komutları, `tsc --noEmit`, `makemigrations --check` hiçbir otomatik kapıda çalışmıyor.
- Kanıt: `ls .github` -> "No such file"; `git ls-files` içinde workflow/CI dosyası yok; `.git/hooks` boş.
- Öneri: Python testleri (TimescaleDB servisiyle), `manage.py check --deploy`, `makemigrations --check`, `npm run check && npm test`, compile_catalogs ve audit/lint adımlarını içeren bir pipeline ekleyin.

### 37-2 - Dockerfile / uygulama konteyneri ve üretim compose'u yok
- Önem: high | Güven: high
- Dosyalar: docker-compose.yml:1-20
- Açıklama: compose dosyası yalnızca "Local development database" (db servisi). Uygulama imajı, reverse proxy, migrate/collectstatic adımı, üretim topolojisi tanımsız. Dağıtım tekrarlanabilir değil.
- Kanıt: docker-compose.yml:1-2 "Local development database: PostgreSQL 17 ..."; tek servis `db`; `ls Dockerfile*` bulunamadı.
- Öneri: Çok aşamalı Dockerfile (node build -> python runtime), üretim compose/manifest ve migrate/init adımı.

### 37-3 - Üretim uygulama sunucusu (gunicorn) bağımlılıklarda yok
- Önem: medium | Güven: high
- Dosyalar: requirements.txt:1-14, README.md:2991
- Açıklama: README ve settings gunicorn'u uzun ömürlü worker için öneriyor, ancak requirements.txt'te gunicorn/uvicorn yok; tek belgelenmiş çalıştırma `manage.py runserver`. Başlatma komutu, worker sayısı, timeout (PDF çıkarma, monitoring) rehberi yok.
- Kanıt: requirements.txt'te gunicorn geçmiyor; config/settings.py:118-121 yorumu "gunicorn" der; README.md:2987 `runserver 8047`.
- Öneri: Üretim sunucusunu bağımlılık olarak ekleyip komut/ayarını belgeleyin (ayrı requirements-prod).

### 37-4 - Statik dosya üretim hattı yok (STATIC_ROOT, collectstatic, servis)
- Önem: high | Güven: high
- Dosyalar: config/settings.py:173-174, config/urls.py:57-75, .gitignore:6-9
- Açıklama: STATIC_ROOT tanımlı değil, `collectstatic` çalışmaz; whitenoise/CDN/nginx yapılandırması yok; urls.py'de static route yok. DEBUG=0 iken Django statik dosyaları sunmaz, tüm CSS/JS (ve import map) 404 olur. .gitignore `staticfiles/` içeriyor ama ayarda karşılığı yok. STORAGES ile hashed/manifest depolama da yok.
- Kanıt: settings.py:173-174 yalnızca STATIC_URL ve STATICFILES_DIRS; `grep -rn "STATIC_ROOT\|whitenoise\|collectstatic"` kodda eşleşme yok.
- Öneri: STATIC_ROOT + collectstatic adımı ve whitenoise veya proxy ile servis; Dockerfile'da build sırası.

### 37-5 - core/templatetags/assets.py: dosya sistemi mtime'ına dayalı sürümleme üretimde kırılgan ve maliyetli
- Önem: medium | Güven: medium
- Dosyalar: core/templatetags/assets.py:19-41
- Açıklama: `versioned()` her `{% asset %}` çağrısında `finders.find` ile diske bakar, `module_map()` her render'da tüm finder'ları gezip `static/js/*.js` listeler; önbellek yok. Ayrıca `?v=mtime` yalnızca kaynak STATICFILES_DIRS'ten okunur: collectstatic/konteyner kopyalamada mtime değişir (her dağıtımda cache geçersizlenir, replikalar arası farklı v değerleri olabilir). Derlenmemiş static/js (npm build unutulursa) sessizce `static(path)` döner, 404 olur, hata vermez.
- Kanıt: assets.py:25-28 `finders.find(path)`; assets.py:35-40 döngü, lru_cache/CACHES yok (settings.py'de CACHES yok).
- Öneri: İçerik hash'li ManifestStaticFilesStorage veya süreç düzeyi önbellek; eksik derleme çıktısını build/check'te başarısız kılın.

### 37-6 - Healthcheck / liveness-readiness uç noktası ve compose healthcheck yok
- Önem: medium | Güven: high
- Dosyalar: config/urls.py:57-75, docker-compose.yml:6-17
- Açıklama: Yük dengeleyici/orkestratör için `/healthz` benzeri login gerektirmeyen DB-kontrol uç noktası yok (LoginRequiredMiddleware tüm sayfaları kilitler, settings.py:76). db servisinde `healthcheck:` yok, bu yüzden bağımlı servisler hazır olmayı bekleyemez (`pg_isready`).
- Kanıt: urls.py'de health route yok; `grep -rn health` yalnızca `CONN_HEALTH_CHECKS` ve water "fresh" kavramlarını verir; compose db tanımında healthcheck yok.
- Öneri: `@login_not_required` hafif /healthz (SELECT 1) ve compose healthcheck ekleyin.

### 37-7 - Yapılandırılmış LOGGING ayarı yok; gözlemlenebilirlik (metrik, hata izleme) yok
- Önem: medium | Güven: high
- Dosyalar: config/settings.py (LOGGING yok), monitoring/read.py:277, monitoring/cards/resolve.py:112, farm/placements.py:50
- Açıklama: settings.py'de LOGGING, ADMINS, hata izleme (Sentry vb.), metrik, istek kimliği yok. Kod `logger.exception/error` çağırıyor (ör. monitoring kaynakları, yer sağlayıcı hataları, kart şablonu doğrulaması) ancak Django varsayılanıyla DEBUG=False iken bu kayıtlar yalnızca console'a (WARNING+) gider, merkezi toplama/uyarı yok; "no data" ile sessizce yutulan hatalar kimseye bildirilmez.
- Kanıt: `grep -n "LOGGING" config/settings.py` boş; monitoring/read.py:277 `logger.exception(... widgets say "no data")`.
- Öneri: Üretim LOGGING (JSON, stdout), hata izleme ve ADMINS/e-posta veya uyarı entegrasyonu.

### 37-8 - Zamanlanmış işler (generate_tasks, check_*) için scheduler/dağıtım tanımı yok
- Önem: medium | Güven: high
- Dosyalar: tasks/management/commands/generate_tasks.py:5-12, README.md:1923, farm/management/commands/check_stock.py
- Açıklama: `generate_tasks` "for a cron job" diye tasarlanmış, ancak cron/CronJob/systemd timer tanımı yok. `check_stock/check_inventory/check_reports/check_hr/check_experiments/check_withdrawal` bütünlük kontrolleri de hiçbir yerde periyodik çalıştırılmıyor ve çıktıları uyarıya bağlı değil. Görev üretimi yalnızca sayfa okumasında yan etki olarak yapılıyor (README:1923), sayfa açılmazsa üretilmez.
- Kanıt: generate_tasks.py help metni; repoda cron/timer dosyası yok.
- Öneri: Zamanlama tanımları ve başarısızlıkta uyarı (non-zero exit kodlarını doğrulayın).

### 37-9 - Üretim/geliştirme yapılandırma ayrımı yok, .env.example yok; kurulum yalnızca Windows yolları
- Önem: medium | Güven: high
- Dosyalar: config/settings.py:25-30, README.md:2979-2988, .gitignore:5
- Açıklama: Tek settings.py; DEBUG varsayılanı '1', ALLOWED_HOSTS boş, SECRET_KEY sabit yedek (DJANGO_SECRET_KEY eksikse sessizce yerel anahtar). `.env` ignore ediliyor ama okuyan kod yok ve `.env.example` yok; ortam değişkenleri yalnızca README paragrafında dağınık (DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS, DJANGO_MEDIA_ROOT, DB_*, DB_CONN_MAX_AGE). Kurulum komutları `C:\Python312\python.exe` ve `.venv\Scripts\` ile yalnızca Windows; Linux/CI karşılığı yok. (Güvenlik boyutu: 05-secrets-config.md.)
- Kanıt: settings.py:25,28,30; README.md:2982-2987.
- Öneri: Ortam değişkeni referans tablosu/.env.example, prod ayarlarında zorunlu env doğrulaması, platformdan bağımsız kurulum.

### 37-10 - Veritabanı: compose'ta yedek, healthcheck ve kaynak/ağ sertleştirmesi yok; varsayılan parola
- Önem: medium | Güven: high
- Dosyalar: docker-compose.yml:6-17
- Açıklama: `restart: unless-stopped` ile kalıcı çalışabilecek bir DB; parola `balik` varsayılanı ve port ana makineye tüm arayüzlerde açılıyor (`"${DB_PORT:-5433}:5432"`, 127.0.0.1 bağlı değil). Yedek/pg_dump, WAL arşivi, kaynak limitleri, loglama sürücüsü tanımsız. Port bağlama 0.0.0.0 olduğundan, varsayılan parola ile sunucuda çalıştırılırsa dışarıdan erişilebilir olur.
- Kanıt: docker-compose.yml:8-10, 15.
- Öneri: `127.0.0.1:` ile bağlayın, parolayı zorunlu env yapın, yedek işi ekleyin (bkz. 12-backup-restore.md).

### 37-11 - TimescaleDB imaj sürümü sabit, ama yükseltme ve extension uyumu süreci belgelenmemiş
- Önem: low | Güven: medium
- Dosyalar: docker-compose.yml:4, core/migrations/0001_timescaledb.py:7-12
- Açıklama: İmaj `timescaledb:2.17.2-pg17` olarak pinlenmiş (iyi), fakat digest yok ve mevcut volume'de imaj yükseltildiğinde `ALTER EXTENSION timescaledb UPDATE` gerekir; migration yalnızca `CREATE EXTENSION IF NOT EXISTS` yapar, reverse noop. CI/test ortamı için aynı imaj kullanımı güvence altında değil. Ayrıca `hr/migrations/0002_people.py:21` btree_gist extension'ı yaratır: yönetilen DB'de superuser/izin gerektirir, belgelenmemiş.
- Kanıt: 0001_timescaledb.py:9-12; hr/migrations/0002_people.py:21.
- Öneri: Yükseltme prosedürü ve gerekli extension/izinleri dağıtım belgesine yazın.

### 37-12 - Bağımlılık yönetimi: Python için lock/hash ve güvenlik taraması yok
- Önem: medium | Güven: high
- Dosyalar: requirements.txt, package-lock.json, package.json:43-48
- Açıklama: requirements.txt tam sürüm sabitli (iyi) ancak hash'siz, geçişli bağımlılıklar kilitli değil (Babel->..., vb.), pip-audit/Dependabot/Renovate yok. npm tarafında lock var (lockfileVersion 3) ama yalnızca devDependencies; `npm audit`/ci zorunlu kılınmamış (README `npm install` der, `npm ci` değil). Python/Node sürümü sabitlenmemiş (.python-version, engines, .nvmrc yok); Django 6.1 / Python sürüm gereksinimi hiçbir yerde belirtilmemiş.
- Kanıt: package.json'da "engines" yok; `git ls-files` içinde .python-version/.nvmrc yok; README.md:2980 `npm install`.
- Öneri: `pip-compile --generate-hashes`, `npm ci`, sürüm dosyaları ve otomatik bağımlılık güncelleme/tarama.

### 37-13 - Derleme çıktıları (static/js, .mo) commit edilmiyor ve otomatik üretilmiyor; eksiklik sessiz
- Önem: medium | Güven: high
- Dosyalar: .gitignore:8-13, core/catalogs.py:55-57, README.md:2980-2985
- Açıklama: `static/js/` ve `*.mo` git dışı; elle `npm run build` ve `compile_catalogs` çalıştırılmadan uygulama JS'siz (404) ve çevirisiz (İngilizce'ye düşer) çalışır. Bunları zorlayan bir makefile/entrypoint/check yok. `.mo` güncelliği `is_fresh`-benzeri kontrolü (catalogs.py:55) üretim başlangıcında kullanılmıyor (sadece `core/catalogs.py` içinde, uygulama dışı bir çağrı bulunmadı). Dağıtım sırası (npm build -> compile_catalogs -> migrate -> collectstatic) hiçbir yerde tek komut olarak yok.
- Kanıt: .gitignore:8-13; `grep` ile catalogs fonksiyonlarının yalnızca management komutlarında ve testlerde kullanımı.
- Öneri: Tek build betiği/Dockerfile aşaması; `manage.py check` içine eksik .mo/static/js doğrulaması.

### 37-14 - tsconfig.test.json derleme çıktısı ve test script'i taşınabilirlik/izolasyon sorunları
- Önem: low | Güven: medium
- Dosyalar: package.json:41, scripts/mark-esm.mjs, tsconfig.test.json
- Açıklama: `npm test` tek satırda `&&` zinciri ve tırnaklı glob kullanıyor (Node 22 gerekli; engines yok). `playwright-core` tarayıcı indirmez, makinedeki Chrome/Edge'e bağımlı (THIRD_PARTY.md:12): CI'da tarayıcı yoksa test davranışı belirsiz (atlanır mı başarısız mı, doğrulanmadı). `scripts/` dizininde başka betik yok: DB hazırlığı, seed, yedek vb. için betik eksik.
- Kanıt: package.json:41; THIRD_PARTY.md:12; node_modules kurulu olmadığı için çalıştırılmadı.
- Öneri: Node sürümü sabitleme ve tarayıcı yoksa net hata/atlama politikası.

### 37-15 - Kod kalitesi/stil araçları yapılandırılmamış (ruff cache var, config yok)
- Önem: low | Güven: high
- Dosyalar: .ruff_cache/ (git dışı), (pyproject.toml / ruff.toml yok)
- Açıklama: Çalışma dizininde `.ruff_cache` var, yani ruff yerelde çalıştırılmış, fakat ruff/flake8/mypy yapılandırması, pre-commit, .editorconfig yok; kurallar repoda tanımlı değil, CI'da uygulanamaz. `.ruff_cache` .gitignore'da listelenmiyor (yalnızca .gitignore sözlüğünde yok; `git status`/izlenme durumu doğrulanmadı).
- Kanıt: `ls -a` -> .ruff_cache; `git ls-files | grep -i "ruff\|pyproject\|pre-commit\|editorconfig"` boş; .gitignore:1-19 .ruff_cache içermez.
- Öneri: pyproject.toml ile lint yapılandırması, .ruff_cache'i .gitignore'a ekleyin.

### 37-16 - E-posta üretimde konsol backend'inde: şifre sıfırlama/davet postaları gönderilmez
- Önem: medium | Güven: high
- Dosyalar: config/settings.py:191-195, README.md:3253-3256
- Açıklama: MAILERS yalnızca console backend. Üretim dağıtımında SMTP/sağlayıcı ayarı env ile yapılamıyor (kod düzenlemek gerekir); şifre sıfırlama ve HR davet e-postaları sunucu stdout'una yazılır (bağlantı token'ları loga sızar).
- Kanıt: settings.py:191-195; README.md:3253-3256 "Email uses the console backend for now".
- Öneri: E-posta yapılandırmasını ortam değişkenlerinden okuyun; üretimde console backend'i reddedin.

### 37-17 - Çalışma zamanı ölçeklenme önkoşulları: önbellek, oturum, medya depolaması tek-düğüm varsayımlı
- Önem: low | Güven: medium
- Dosyalar: config/settings.py:35-62, 180, 110-126
- Açıklama: CACHES tanımsız (varsayılan LocMemCache, süreç başına), medya yerel dosya sistemine (`MEDIA_ROOT`) yazılır ve dosya yalnızca view ile servis edilir; çok replika/konteyner dağıtımında paylaşımlı volume ya da nesne depolama gerekir, belgelenmemiş. İstek gövde sınırı (nginx 25m) yalnızca yorum/README'de; DATA_UPLOAD_MAX_MEMORY_SIZE vb. ayarı yok. `SECURE_PROXY_SSL_HEADER` yok: TLS sonlandıran proxy arkasında Django isteği http sanır (kapsam: güvenlik bulguları 05'te).
- Kanıt: `grep -n "CACHES\|SECURE_PROXY\|DATA_UPLOAD" config/settings.py` boş; settings.py:180, 182-185.
- Öneri: Dağıtım topolojisi belgesi; paylaşımlı medya depolama ve proxy başlığı yapılandırması.

### 37-18 - Dağıtım/operasyon dokümantasyonu eksik (runbook, sürümleme, geri alma)
- Önem: info | Güven: high
- Dosyalar: README.md (2977-2995 "Local setup"), docs/
- Açıklama: README ~3300 satır ve 320 KB, ancak "Deploy/Production/Operations" bölümü yok; docs/ altında dağıtım, rollback, migration sırası, sürüm etiketleme, ortam matrisi belgesi yok (yalnızca özellik ve i18n belgeleri). Git deposunda sürüm etiketi/CHANGELOG izi doğrulanmadı.
- Kanıt: `ls docs` -> aquaculture-platform-bugs.md, data-map.*, experiments.md, hr-launch-checklist.md, i18n.md, regulatory-reports.md; README'de "gunicorn" yalnızca DB_CONN_MAX_AGE açıklamasında geçer.
- Öneri: docs/deploy.md: topoloji, build sırası, migrate stratejisi (sıfır kesinti), geri alma, yedek/geri yükleme, izleme.
