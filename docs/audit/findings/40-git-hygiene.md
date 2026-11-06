# 40 - Git Hygiene Denetimi

## Özet
Repo: 299 commit, 53 merge, tek yazar (Okan-wqm), 2026-11-02..11-05 arası. Tek branch `main` (= `origin/main`, 0f5bc72), HEAD detached. Takip edilen artefakt/sır yok; .gitignore temel kalıpları kapsıyor. Ana sorunlar: commit mesajı biçimi (gövdesiz, 1969 karaktere varan konu satırları, tutarsız zaman damgası öneki), `wip/*` branch'lerinin referanssız kalıp sadece merge mesajlarında yaşaması, CI/lisans/.env.example/pre-commit eksikliği, imzasız commitler.

## İncelenen alanlar
git log/graph, branch/ref listesi, merge commitleri, commit mesajı uzunluk ve biçimi, silinen dosyalar, .gitignore/.gitattributes, takip edilen dosya boyutları/türleri, dosya modları, repo kökü dosyaları, docker-compose, settings'teki varsayılan sırlar.

## İncelenmeyen alanlar
Uzak (GitHub) tarafındaki branch protection / PR geçmişi, tarihsel dosya içeriklerinde sır taraması (yalnızca dosya adı ve silinen dosya listesi bakıldı), uygulama kodu.

## Bulgular

### 40-1 - wip/* branch'leri yerel/uzakta yok; geçmiş yalnızca merge mesajlarında
- Önem: medium, Güven: high
- Dosyalar: .git (refs)
- Açıklama: `git for-each-ref` yalnızca `refs/heads/main` ve `refs/remotes/origin/main` gösteriyor. Geçmişte wip/prodteam, wip/cards, wip/hr, wip/experiments, wip/monitoring, wip/reports-gaps, wip/reports-tabs adlı branch'ler kullanılmış; hiçbiri ref olarak kalmamış. HEAD de "detached at refs/heads/main".
- Kanıt: `git branch -a` -> `* (HEAD detached at refs/heads/main)`, `main`, `remotes/origin/main`; fd49eed "Merge branch 'main' into wip/prodteam".
- Öneri: Dal adları artık geri bulunamıyor; büyük özellik dalları (card templates, prodteam) için tag veya merge commit mesajında dal/PR numarası standardı kullan. HEAD'i `git switch main` ile attach et.

### 40-2 - "main'i wip dalına merge et" deseni: main'e ters yönde merge'ler ve tekrarlı merge gürültüsü
- Önem: low, Güven: high
- Dosyalar: .git
- Açıklama: 53 merge commit'in büyük kısmı `Merge main (...) into wip/X` biçiminde; yani main sürekli dallara çekilmiş, sonra dal main'e fast-forward olmuş (first-parent geçmişi 107 commit, toplam 299). Merge conflict çözümleri (katalog .po yeniden üretimi, data map yeniden üretimi) tekrar tekrar elle yapılmış.
- Kanıt: 0f5bc72'nin ebeveyni fd49eed `Merge branch 'main' into wip/prodteam`; 502075a, a4d5729, 6980141, afca8e6, 42e894f, 5508e92 aynı desen. `git log --first-parent --oneline | wc -l` = 107.
- Öneri: Üretilen dosyalar (data-map, .po) için merge driver veya "regenerate" adımı belgelenmeli; mümkünse rebase/squash ile geçmişi sadeleştir.

### 40-3 - Aşırı uzun commit konu satırları, gövde neredeyse hiç yok
- Önem: medium, Güven: high
- Dosyalar: .git (commit mesajları), örn. adcda97
- Açıklama: Medyan konu uzunluğu 281, max 1969 karakter; 96 commit'in konusu 400+ karakter. Tüm açıklama konu satırına yazılmış; `%b` (gövde) toplam 71 satır. `git log --oneline`, GitHub arayüzü ve araçlar bu mesajlarda kesiliyor/okunmaz oluyor.
- Kanıt: `git log --format=%s | awk length` -> median 281, max 1969; adcda97 konusu yaklaşık 900 karakter.
- Öneri: 50-72 karakterlik özet + boş satır + gövde biçimi; commit-msg hook veya CI kontrolü.

### 40-4 - Konu satırına gömülü elle yazılmış zaman damgası, tutarsız ve author date ile uyuşmuyor
- Önem: low, Güven: high
- Dosyalar: .git
- Açıklama: 252 commit konusu `[2026-11-05 16:00 +0100]` önekiyle başlıyor, diğerleri başlamıyor (örn. 0f5bc72, 156cfd9, 0fd548f yok). "Test:" commit'lerinde önek `Test: [ts]` sırasıyla, diğerlerinde `[ts] ...` biçiminde. Gömülü zaman ile git author date 1-2 dakika farklı: bd1e53b (00:59 vs 01:00), 000321d (21:43 vs 21:45), 563ebb7 (14:25 vs 14:24). Ayrıca öneksiz son commit'ler (11-05 18:27 sonrası) biçim değiştiğini gösteriyor. Git zaten tarih tutuyor; önek mesajı uzatıyor ve güvenilir değil.
- Kanıt: awk karşılaştırması: `bd1e53b 2026-11-04 00:59 2026-11-04 01:00`, `000321d ... 21:43 21:45`.
- Öneri: Öneki kaldır; zaman gerekiyorsa git'in kendi tarihine güven.

### 40-5 - Test-önce / uygulama commit çiftleri ayrı commit'ler: ara commit'ler kırık test durumunda
- Önem: low, Güven: medium
- Dosyalar: .git (örn. 625e165, 49f22a6, 0484a84, 55cf25b)
- Açıklama: "Test: ... written down first. Seen failing: ..." desenli commit'ler bilerek kırık testle commitlenmiş (28 "Test" öneki ile başlayan commit, ayrıca "Test: [ts]" varyantları). Bu geçmiş `git bisect` için güvenilmez; her commit yeşil değil. Commit 4204a63 "Seen failing: the trigger refuses every insert" gibi.
- Kanıt: 625e165 "Seen failing on the step-5 code: the partials are missing"; 49f22a6 "Seen failing against a stub resolver: 18 failures, 11 errors".
- Öneri: Test+kod aynı commit'te olsun veya kırık commit'ler `bisect skip` için etiketlensin.

### 40-6 - Commit'ler imzasız, tek yazar, noreply e-posta
- Önem: info, Güven: high
- Dosyalar: .git
- Açıklama: Tüm 299 commit tek kimlikten; `%G?` = N (imzasız). Review/ikinci göz izi yok (denetim izi açısından zayıf).
- Kanıt: `git log --format='%an <%ae>' | sort | uniq -c` -> 299 Okan-wqm; `%G?` N.
- Öneri: Üretim öncesi imzalı commit/branch protection değerlendirilsin.

### 40-7 - CI yapılandırması, LICENSE, .env.example, pre-commit, CONTRIBUTING yok
- Önem: medium, Güven: high
- Dosyalar: repo kökü
- Açıklama: Kökte `.github/`, LICENSE, `.env.example`, `.pre-commit-config.yaml`, `.editorconfig`, CHANGELOG yok. 2000+ test ve ruff kullanılıyor (.ruff_cache var) ama otomatik çalıştıran CI izi yok; ayrıca ruff/mypy yapılandırması takip edilmiyor. THIRD_PARTY.md lisansları anıyor ama proje lisansı belirsiz.
- Kanıt: `ls -a | grep -iE 'env|github|license|editorconfig|pre-commit|CONTRIBUTING|CHANGELOG'` boş döndü; `git ls-files | grep -E '(^|/)\.[^/]+$'` yalnızca .gitattributes, .gitignore, farm/tests/deffeyes_reference/.gitignore.
- Öneri: Minimal CI (test, ruff, tsc --noEmit, makemigrations --check), LICENSE ve .env.example ekle.

### 40-8 - .gitignore kapsamı dar
- Önem: low, Güven: high
- Dosyalar: .gitignore
- Açıklama: Yalnızca .venv/, __pycache__/, *.pyc, db.sqlite3, .env, staticfiles/, static/js/, node_modules/, *.mo, /media/, .build/ var. Eksik: `.env.*`, `.idea/`, `.vscode/`, `*.log`, `.pytest_cache/`, `.coverage`, `htmlcov/`, `.mypy_cache/`, `*.sqlite3`, `*.dump`/`*.sql`, `.DS_Store`, `*.swp`. `.ruff_cache` ruff'ın kendi içindeki .gitignore ile korunuyor, repo kuralı değil. `.env` ignore'u var ama `.env.local` vb. değil.
- Kanıt: .gitignore tam içeriği (satır 1-17); `git status` .ruff_cache göstermiyor ama `git check-ignore -v .ruff_cache` çıktısız.
- Öneri: Standart Python/Node/editör kalıplarını ekle, `.env.*` ve `!.env.example`.

### 40-9 - Repoya girmiş artefakt/sır yok (olumlu doğrulama)
- Önem: info, Güven: medium
- Dosyalar: -
- Açıklama: Takip edilen dosyalar arasında .sqlite/.db/.log/.pyc/.env/.pem/zip yok; en büyük dosyalar docs/data-map.json (852 KB), farm/tests/deffeyes_reference/reference.json (436 KB), .po dosyaları, README.md (316 KB). Pack boyutu 4.61 MiB, garbage 0. Silinen yalnızca iki şablon (_card_health.html, _card_water.html; adcda97) görüldü. Tarihsel içerikte sır taraması yapılmadı.
- Kanıt: `git ls-files | grep -Ei '\.(sqlite3?|db|log|pyc|zip|...)$|node_modules|...'` boş; `git count-objects -vH`.
- Öneri: Yine de gitleaks/trufflehog ile tüm geçmiş taraması CI'a eklensin.

### 40-10 - Varsayılan zayıf kimlik bilgileri/SECRET_KEY kodda ve compose'da
- Önem: low, Güven: high
- Dosyalar: config/settings.py:24-25, config/settings.py:115, docker-compose.yml:10
- Açıklama: `SECRET_KEY` için `django-insecure-local-development-only` ve DB parolası `balik` varsayılanları commit'te. Yorum "yalnızca yerel" diyor ama üretimde env eksikse sessizce zayıf anahtarla açılır (DEBUG kontrolü bu denetimde incelenmedi).
- Kanıt: settings.py:25 `os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-development-only')`; satır 115 `'PASSWORD': os.environ.get('DB_PASSWORD', 'balik')`.
- Öneri: DEBUG=False iken varsayılanı reddet (ImproperlyConfigured); güvenlik uzmanlarıyla koordine et.

### 40-11 - README.md tek dosyada 316 KB; her özellik commit'i onu değiştiriyor
- Önem: low, Güven: high
- Dosyalar: README.md
- Açıklama: Commit mesajları sürekli "README says ..." diyor; README dev bir spesifikasyon/karar günlüğüne dönüşmüş, merge çakışmalarının ana kaynağı (merge mesajlarında "both sides kept in the README"). Git diff/blame için verimsiz.
- Kanıt: `ls -la` -> README.md 320208 bayt; 502075a "both sides kept in the menu, the access areas, the menu tests and the README".
- Öneri: README'yi docs/ altına bölümlere ayır.

### 40-12 - Üretilen dosyalar takipte (data-map, .po) ve her merge'de yeniden üretiliyor
- Önem: low, Güven: high
- Dosyalar: docs/data-map.json, docs/data-map.md, locale/*/LC_MESSAGES/django.po
- Açıklama: data-map.json (852 KB) ve data-map.md koddan üretiliyor ("the data map regenerated" en az onlarca commit); .po dosyaları da "rebuilt from the merged code". Bunlar merge çakışması ve büyük diff üretir. core/test_datamap.py'nin bunu zorladığı commit 9ad5c26'da belirtiliyor, yani tutarlılık testle korunuyor; ama tek kaynak ve yeniden üretim komutu merge sürecinde elle uygulanıyor.
- Kanıt: 502075a, a4d5729, 6980141 mesajları; 9ad5c26 "Data map enforced: core/test_datamap.py fails for a t...".
- Öneri: Yeniden üretim komutunu Makefile/pre-commit adımı yap.

### 40-13 - docs/aquaculture-platform-bugs.md başka bir reponun dahili notlarını içeriyor
- Önem: low, Güven: medium
- Dosyalar: docs/aquaculture-platform-bugs.md:1-9
- Açıklama: Dosya başka bir kod tabanının (`aquaculture_platform`, branch `snowball-test`, commit `352aa2a8`) hata listesi; ✔ işaretsiz girdiler "doğrulanmamış". Bu repoda kaynak/hijyen açısından yabancı içerik ve içindeki iç yol/commit referansları dışarı sızmış olabilir.
- Kanıt: dosyanın ilk satırları ("Source read: `aquaculture_platform`, branch `snowball-test`").
- Öneri: Mülkiyet/gizlilik açısından uygunluğunu doğrula; ayrı repoya taşımayı değerlendir.

### 40-14 - farm/tests/deffeyes_reference/.gitignore ve dosya modları
- Önem: info, Güven: medium
- Dosyalar: farm/tests/deffeyes_reference/.gitignore
- Açıklama: Alt dizinde `out/`, `src/*`, `!src/index.ts`, `!src/shared-contracts.ts` kuralları var; bu, referans üretim için Node kaynağı barındıran bir alt proje izlenimi veriyor ama repo kökünde belgelenmemiş (not: içeriği ayrıca incelenmedi). Hiçbir dosyada 100755 modu yok (scripts/mark-esm.mjs dahil), `.gitattributes` `* text=auto eol=lf` ile tutarlı.
- Kanıt: `cat farm/tests/deffeyes_reference/.gitignore`; `git ls-files -s | grep -c '^100755'` = 0.
- Öneri: Alt dizin için kısa README ekle.

### 40-15 - Çalışma ağacında takipsiz docs/audit/ ve temiz-olmayan durum
- Önem: info, Güven: high
- Dosyalar: docs/audit/
- Açıklama: `git status --short` yalnızca `?? docs/audit/` gösteriyor (denetim çıktıları); başka kirlilik yok.
- Kanıt: `git status --short`.
- Öneri: Denetim çıktıları commitlenecekse ayrı bir commit ile, değilse .gitignore'a.
