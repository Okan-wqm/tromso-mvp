# 07 - Bağımlılık ve tedarik zinciri denetimi (deps-supply)

## Özet
Bağımlılık seti küçük ve doğrudan bağımlılıklar tam sürüme sabitlenmiş (`==`; npm tarafında aralıksız sürümler + `package-lock.json`, integrity hash'li). Frontend yalnızca dev bağımlılıkları içeriyor, tarayıcıya üçüncü taraf kod gönderilmiyor. Zayıf yönler: Python tarafında kilit dosyası/hash yok ve geçişli bağımlılıklar kısmen sabitlenmemiş; Python/Node sürüm kısıtı bildirilmemiş; CI, otomatik güvenlik taraması (Dependabot/pip-audit/npm audit) ve Dockerfile yok; THIRD_PARTY.md Python paketlerinin lisanslarını (özellikle LGPL psycopg) içermiyor; projenin kendi LICENSE dosyası yok; Docker imajı etiketle (digest'siz) ve eski bir TimescaleDB sürümüne sabit. Bu ortamda Django kurulu olmadığından pip-audit/CVE taraması çalıştırılamadı; CVE iddiası yazılmadı.

## İncelenen alanlar
requirements.txt, package.json, package-lock.json, THIRD_PARTY.md, docker-compose.yml, .gitignore, README (kurulum/dağıtım bölümleri), Python import'ları ile requirements karşılaştırması, `.github`/Dockerfile/LICENSE varlığı.

## İncelenmeyen alanlar
CVE veritabanı sorgusu (ağ/araç yok, sürümler tek tek doğrulanmadı), geçişli bağımlılıkların gerçek lisans metinleri, imaj içi paket taraması, static/ ve templates/ içindeki gömülü üçüncü taraf varlıklar (yazı tipi, ikon) ayrıntılı lisans incelemesi, gerçek dağıtım ortamı.

## Bulgular

### 07-1 | orta | güven: yüksek - Python bağımlılıkları için kilit dosyası ve hash yok; geçişli bağımlılıklar sabitlenmemiş
Dosyalar: requirements.txt:1-13
Açıklama: Liste elle tutulan, düz `==` sabitlemeli bir dosya. `cryptography` (cffi -> pycparser) ve `pypdf` gibi paketlerin geçişli bağımlılıkları listede yok, dolayısıyla temiz kurulumda sürümleri zamana göre değişir. `--require-hashes`/pip-compile çıktısı yok; yeniden üretilebilir ve doğrulanabilir kurulum sağlanmıyor.
Kanıt: `cryptography==50.0.2` (satır 4) var, `cffi`/`pycparser` yok; hiçbir satırda `--hash=` yok; repoda requirements.in/constraints/pyproject yok.
Öneri: pip-tools veya uv ile hash'li tam kilit dosyası üret; kurulumda `--require-hashes` kullan.

### 07-2 | orta | güven: yüksek - Python ve Node sürümü hiçbir yerde bildirilmiyor
Dosyalar: requirements.txt, package.json:14-29, README.md:2982
Açıklama: Django 6.1 / paket sürümleri belirli bir Python sürümü gerektirir ancak `python_requires`, `.python-version`, Dockerfile veya README'de açık sürüm şartı yok (README yalnızca Windows yolu olarak `C:\Python312\python.exe` örneği veriyor). package.json'da `engines` ve `.nvmrc` yok; `@types/node` 22.x kullanılırken Node sürümü belirsiz (testler `node --test` ve ESM'e dayanıyor).
Kanıt: `git ls-files` çıktısında .python-version, .nvmrc, Dockerfile, pyproject.toml yok; package.json'da `engines` alanı yok; README.md:2982 yalnızca `C:\Python312\python.exe`.
Öneri: Python alt sınırını ve Node sürümünü (`engines`, `.nvmrc`) belgele ve CI'da zorla.

### 07-3 | orta | güven: yüksek - Otomatik güvenlik açığı taraması ve güncelleme mekanizması yok (CI, Dependabot, pip-audit, npm audit)
Dosyalar: (yok) .github/ dizini mevcut değil, requirements.txt, package.json
Açıklama: Sabitlenmiş sürümler zamanla CVE alır; bunları izleyen ya da PR açan bir mekanizma yok. requirements.txt yorumu (satır 8-9) pypdf'in "her yamada" hostile PDF sorunlarını kapattığını söylüyor, ancak güncel tutmayı sağlayan süreç tanımlı değil. README `CI=1` ortamından söz ediyor (README.md:3405) fakat repoda CI tanımı yok.
Kanıt: `ls .github` -> "No such file or directory"; repoda dependabot/renovate yapılandırması yok.
Öneri: Dependabot/Renovate ekle, CI'da `pip-audit` ve `npm audit --omit=dev` çalıştır.

### 07-4 | orta | güven: yüksek - pypdf güvenilmeyen kullanıcı PDF'ini okuyor; bu paket yüksek riskli yüzey ve güncellik süreci yok
Dosyalar: requirements.txt:8-10, knowledge/extraction.py:24
Açıklama: pypdf yüklenen PDF'leri ayrıştırıyor (DoS/bellek tüketimi geçmişi olan bir sınıf). Sürüm güncel görünüyor (6.21.4) ancak güncelleme izleme olmadan bu sabitleme zamanla eskir (bkz. 07-3). `cryptography` yalnızca AES şifreli PDF için isteniyor; sürüm hem pypdf hem Django ile ilgisiz şekilde sabitlenmiş, uyumluluk testi tek bir test dosyasına dayanıyor.
Kanıt: `from pypdf import PdfReader` (knowledge/extraction.py:24); `pypdf==6.21.4` (requirements.txt:10).
Öneri: pypdf'i öncelikli izlenen paket olarak işaretle; ayrıştırmayı kaynak sınırlı alt süreçte çalıştırmayı değerlendir (ayrı alan: injection/dos uzmanı).

### 07-5 | orta | güven: yüksek - THIRD_PARTY.md Python paketlerinin lisanslarını listelemiyor; psycopg LGPL
Dosyalar: THIRD_PARTY.md:1-5, THIRD_PARTY.md:7-16, requirements.txt:5-7
Açıklama: Belge sunucunun çalıştırdığı Python paketlerini "requirements.txt'te" diye havale ediyor, lisans tablosu yalnızca dev npm araçlarını kapsıyor. Oysa dağıtılan/çalışan asıl bağımlılıklar (Django BSD-3, psycopg ve psycopg-binary LGPL-3.0 - binary paketi libpq/OpenSSL de taşır, cryptography Apache-2.0/BSD, pypdf BSD-3, Babel BSD-3) lisans bildirimi gerektirir. LGPL'in yeniden bağlama/değiştirme koşulları belgelenmemiş.
Kanıt: THIRD_PARTY.md:1-5 yalnızca "The Python packages the server runs are in requirements.txt" der; tabloda yalnızca typescript, @types/node, playwright-core, axe-core var.
Öneri: Python paketleri için lisans tablosu ekle (ve geçişli bağımlılıklar), LGPL notunu yaz; lisans listesini araçla üret.

### 07-6 | düşük | güven: yüksek - Projenin kendi lisansı yok; package.json'da license alanı yok
Dosyalar: package.json:14-29, (yok) LICENSE
Açıklama: Repoda LICENSE/COPYING dosyası yok; package.json `private: true` ama `license` alanı yok. Dışarıya dağıtım/müşteriye teslim durumunda hak belirsizliği olur.
Kanıt: `git ls-files` listesinde LICENSE yok; package.json'da "license" anahtarı yok.
Öneri: Kasıtlı olarak tescilli ise `"license": "UNLICENSED"` ve LICENSE/telif notu ekle.

### 07-7 | düşük | güven: yüksek - THIRD_PARTY.md geçişli npm bağımlılığını (undici-types) ve axe-core MPL-2.0 koşulunu belirtmiyor
Dosyalar: THIRD_PARTY.md:7-16, package-lock.json:21-25, package-lock.json:51-55
Açıklama: package-lock'ta `undici-types@6.20.0` (`@types/node` bağımlılığı) var ama tabloda yok. axe-core MPL-2.0 dosya düzeyinde copyleft'tir; yalnızca dev kullanımı olduğu doğru, ancak "asla gömülmez" güvencesi bir CI kontrolüyle doğrulanmıyor.
Kanıt: package-lock.json: `"node_modules/undici-types": {"version": "6.20.0"...}`; THIRD_PARTY.md tablosunda 4 paket.
Öneri: Geçişli paketleri tabloya ekle veya "geçişli bağımlılıklar için package-lock'a bakın" notu yaz.

### 07-8 | orta | güven: orta - Docker imajı yalnızca etiketle sabit (digest yok) ve eski bir TimescaleDB sürümü
Dosyalar: docker-compose.yml:4
Açıklama: `timescale/timescaledb:2.17.2-pg17` değişebilir bir etikettir; imaj içeriği digest ile sabitlenmemiş. 2.17.x serisi güncel TimescaleDB sürümlerinin gerisinde (2024 sonu çıkışlı; bugünün tarihine göre yama/güvenlik düzeltmelerini almıyor olabilir; sürüm geçmişi ağ olmadığından doğrulanmadı). README PostgreSQL 17 + TimescaleDB 2.17 olarak belgeliyor, bu yüzden güncelleme hem compose hem README'yi etkiler.
Kanıt: `image: timescale/timescaledb:2.17.2-pg17`; README.md:4 "PostgreSQL 17 with TimescaleDB 2.17".
Öneri: Güncel yama sürümüne geç, `@sha256:` digest ile sabitle, güncelleme politikasını belgele.

### 07-9 | orta | güven: yüksek - Compose'ta varsayılan zayıf DB parolası ve tüm arayüzlere açık port (tedarik/dağıtım yüzeyi)
Dosyalar: docker-compose.yml:7-9, docker-compose.yml:13
Açıklama: `POSTGRES_PASSWORD` varsayılanı `balik`; port `0.0.0.0` üzerinden yayınlanıyor. Yalnızca "yerel geliştirme" notlu olsa da dosya olduğu gibi sunucuda çalıştırılırsa açık bir DB olur. (05-3 ile örtüşür; burada imaj/compose yönünden kayda geçti.)
Kanıt: `POSTGRES_PASSWORD: ${DB_PASSWORD:-balik}`; `ports: ["${DB_PORT:-5433}:5432"]`.
Öneri: `127.0.0.1:${DB_PORT:-5433}:5432`; parolayı zorunlu yap veya compose'u dev-only olarak adlandır.

### 07-10 | düşük | güven: yüksek - Uygulama için Dockerfile/üretim imajı yok; üretim bağımlılık yolu tanımsız
Dosyalar: docker-compose.yml:1-2, README.md:2982-2987
Açıklama: Yalnızca DB için compose var; uygulama imajı, gunicorn/WSGI sunucusu veya statik dosya sunumu bağımlılığı requirements.txt'te yok (wsgi sunucusu listede yok). Üretim dağıtımının hangi paketlerle çalışacağı belirsiz; `runserver` yönergesi tek yol.
Kanıt: requirements.txt'te gunicorn/uvicorn/whitenoise yok; Dockerfile yok.
Öneri: Üretim bağımlılık ve imaj stratejisini tanımla (ayrı requirements-prod, multi-stage Dockerfile, root olmayan kullanıcı).

### 07-11 | düşük | güven: yüksek - Geliştirme/üretim bağımlılıkları ayrılmamış
Dosyalar: requirements.txt:1-13
Açıklama: Tek dosya var; `Babel` yalnızca çeviri katalog komutunda (core/catalogs.py:15-18) kullanılıyor ve `cryptography` yalnızca PDF AES için; çalışma zamanı vs geliştirme ayrımı yok. Üretim imajına gereksiz paketler girer.
Kanıt: `from babel.messages...` core/catalogs.py:15-18; requirements.txt tek dosya.
Öneri: requirements-dev ayrımı (Babel'in çalışma zamanı mı yoksa derleme aracı mı olduğuna karar ver).

### 07-12 | düşük | güven: orta - Sabitlenen dev araçları eski sürümler (playwright-core 1.49.1, typescript 5.6.3, @types/node 22.10.2, axe-core 4.10.2)
Dosyalar: package.json:24-28, package-lock.json
Açıklama: Sürümler tam sabit, iyi; fakat hepsi 2024 sonu sürümleri, bugün (2026-11) birkaç majör sürüm geride olabilir (ağ doğrulaması yapılmadı). playwright-core eski, tarayıcı sürümleriyle uyumsuzluk riski taşır (Chrome/Edge makinenin kendisinden kullanılıyor). Yalnızca dev olduğu için çalışma zamanı riski düşük.
Kanıt: `"playwright-core": "1.49.1"`, `"typescript": "5.6.3"`.
Öneri: Düzenli güncelleme (bkz. 07-3).

### 07-13 | info | güven: yüksek - npm lock dosyası sağlam: integrity hash'li, yalnızca resmi registry, dev işaretli
Dosyalar: package-lock.json:1-65
Açıklama: lockfileVersion 3, tüm paketler `registry.npmjs.org`, `integrity` sha512 var, hepsi `dev: true`; tarayıcıya çalışma zamanı npm paketi gitmiyor (THIRD_PARTY.md:1-3 ile tutarlı). package.json'daki aralıksız sürümler lock ile eşleşiyor. `postinstall` betiği yok.
Kanıt: `"integrity": "sha512-..."` her pakette; package.json `scripts` içinde yalnızca build/watch/check/test.
Öneri: Kurulumda `npm ci` kullanılmasını README'de belirt.

### 07-14 | düşük | güven: orta - README kurulumunda `npm ci` yerine kurulum talimatı/sürüm sıkılığı belirtilmemiş; `pip install` yönergesi doğrulanamadı
Dosyalar: README.md:2982-2987, README.md:3403-3405
Açıklama: Python kurulum adımları gösterilirken `pip install -r requirements.txt` ve `npm install` satırlarının kesin biçimi (kilitli kurulum) açık değil; README `npm install` ifadesi kullanıyor (satır 3403) bu da lock'u güncelleyebilir. `npm ci` daha güvenli.
Kanıt: README.md:3403 "when Node and `npm install` are there".
Öneri: `npm ci` ve `pip install --require-hashes -r ...` belgelensin.

### 07-15 | info | güven: yüksek - Doğrudan import edilen paketler requirements ile tutarlı; kullanılmayan doğrudan bağımlılık yok
Dosyalar: requirements.txt, core/catalogs.py:15-18, knowledge/extraction.py:24
Açıklama: babel, pypdf, psycopg import ediliyor; asgiref/sqlparse/tzdata/typing_extensions Django ve pypdf'in dolaylı gereksinimi olup elle sabitlenmiş (tutarlı ama bkz. 07-1: kısmi kilit). `psycopg` ve `psycopg-binary` birlikte sabit; binary paket üretim için psycopg belgelerince önerilmeyen bir tercih olabilir (sistem libpq yerine gömülü libpq; güvenlik yamaları paketle gelir).
Kanıt: requirements.txt:6-7; `grep` ile yalnızca bu import'lar bulundu, requests/celery/pandas vb. yok.
Öneri: `psycopg-binary` tercihini (gömülü libpq/OpenSSL güncelleme sorumluluğu) belgele.

### 07-16 | info | güven: orta - Denetim ortamındaki kurulu sürümler requirements ile uyuşmuyor
Dosyalar: requirements.txt:4, requirements.txt:10
Açıklama: Çalıştırma ortamında `cryptography 50.0.1` ve `pypdf 6.17.0` kurulu, requirements `50.0.2` ve `6.21.4` ister; Django hiç kurulu değil. Bu repo sorunu değil ama ortamın requirements'tan kurulmadığını gösterir, bu yüzden CVE/test taraması bu ortamda yapılamadı.
Kanıt: `pip list` çıktısı.
Öneri: Yok (bilgi); denetimlerde ortam requirements'tan kurulmalı.
