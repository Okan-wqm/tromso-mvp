# 36 - Testing (test kapsami, kirilganlik, negatif/yetki testleri, test verisi, flaky)

## Ozet
Repo test acisindan olgun: ~2500 Python `def test_`, 37.8k satir test kodu, TS birim ve tarayici testleri, esik/rol/403 testleri, TransactionTestCase ile yaris testleri. Ana riskler: (1) repoda CI tanimi yok, bu yuzden `CI=1` korumasi ve zorunlu calistirma etkisiz; (2) tarayici, yuk ve TS testleri sessizce skip oluyor; (3) CSRF, middleware, login kaba-kuvvet gibi alanlar dogrudan test edilmiyor; (4) saat dilimi/tarih kaynakli kucuk flaky riskleri; (5) N+1 koruma testleri cok az. Ortamda Django ve PostgreSQL yoktu, testler CALISTIRILMADI; tum bulgular statik okumaya dayanir.

## Incelenen
Tum `*/tests/`, `core/test_*.py`/`tests*.py`, `frontend/**/*.test.ts`, `config/test_runner.py`, `package.json`, `tsconfig.test.json`, README "Tests" bolumu, `.gitignore`, settings (TEST_RUNNER, DATABASES, TIME_ZONE).

## Incelenmeyen
Testlerin gercek calistirilmasi (Django/DB yok), her test dosyasinin satir satir kalitesi, kapsam (coverage) olcumu, locale/template testleri derinligi.

## Bulgular

### 36-1 Repoda CI tanimi yok; `CI=1` korumasi bos
- Onem: medium | Guven: high
- Dosyalar: core/test_catalogs.py:229-238, README.md (Tests bolumu), .github (yok)
- Aciklama: TS birim testi Node yoksa skip, `CI=1` iken fail olacak sekilde tasarlanmis; ancak repoda `.github/workflows` veya baska CI tanimi yok (`ls -a`: .github yok). Testlerin her degisiklikte calistigini garanti eden mekanizma repoda gorunmuyor.
- Kanit: core/test_catalogs.py:230 "under CI (`CI=1`) a missing Node is a failure"; dizinde CI dosyasi yok.
- Oneri: CI tanimi ekleyip `CI=1`, Postgres+timescaledb, `npm ci` ile `manage.py test` ve `npm test` kosulsun.

### 36-2 Tarayici (Playwright) testleri sessizce skip oluyor
- Onem: medium | Guven: high
- Dosyalar: frontend/test/designer.browser.test.ts:105, frontend/test/announce.browser.test.ts:58
- Aciklama: Chrome/Edge yoksa test `skip` ile geciyor; `CI=1` icin fail mekanizmasi yok (TS testindeki gibi degil). Tasarimci ve duyuru (erisilebilirlik/aria-live) davranislari hic calismadan "yesil" gorunebilir.
- Kanit: `{ skip: BROWSERS.length ? false : 'no Chrome or Edge on this machine' }`
- Oneri: CI'da tarayici zorunlu kil; skip sayisini raporla.

### 36-3 Yuk/performans testi varsayilan olarak kapali ve sure-bazli
- Onem: low | Guven: high
- Dosyalar: monitoring/tests/test_load.py:39, :43-45
- Aciklama: `MONITOR_LOAD=1` olmadan calismaz, dolayisiyla 200 kartlik duvar icin sorgu/sure regresyonu rutin kosuda yakalanmaz. Calistiginda `time.perf_counter` ile mutlak sure esigi kullaniyor, yavas makinede flaky olabilir.
- Kanit: `@skipUnless(os.environ.get('MONITOR_LOAD') == '1', ...)`
- Oneri: sorgu sayisi esigini (deterministik) her kosuda, sure esigini ayri etiketli kosuda tut.

### 36-4 N+1 / sorgu sayisi korumasi cok az
- Onem: low | Guven: high
- Dosyalar: monitoring/tests/test_render.py:90, test_read.py:168, test_resolve.py:115, core/tests.py:214
- Aciklama: ~2500 testte `assertNumQueries` yalniz 4 yerde; liste/sayfa goruntuleri (farm, hr, reports) icin sorgu sabitligi testi yok. Veri buyudukce sessiz N+1 regresyonu olabilir.
- Kanit: grep `assertNumQueries` toplam 4 sonuc.
- Oneri: ana liste ve izgara gorunumlerine sorgu butcesi testi ekle.

### 36-5 CSRF korumasi hicbir testte dogrulanmiyor
- Onem: medium | Guven: high
- Dosyalar: config/settings.py:70, tum test_pages.py dosyalari
- Aciklama: Django test `Client` varsayilan olarak CSRF denetimini atlar; reponun testlerinde `enforce_csrf_checks` / `csrf` gecmiyor (grep: 0 dosya). Yazma uclari (POST/void/delete) token olmadan reddedilir mi testlenmiyor; middleware kaldirilsa/muaf edilse testler yesil kalir.
- Kanit: `grep -rli csrf --include=test*.py .` sonuc yok.
- Oneri: temsili yazma uclari icin `Client(enforce_csrf_checks=True)` ile 403 testi; tum POST url'leri icin genel bir tarama testi.

### 36-6 Kimlik dogrulama: yalniz temel login/logout testi, kaba-kuvvet/oturum testleri yok
- Onem: low | Guven: medium
- Dosyalar: core/tests.py:34-46
- Aciklama: `test_home_requires_login` ve `test_login_and_logout` var; parola sifirlama, hatali giris tekrari, pasif kullanici girisi, oturum sabitleme gibi negatif durumlar icin dogrudan test bulamadim (login/password sablonlari ve `config/urls.py` var). Kapsam disi olabilir; kesin olmayan, confidence orta.
- Oneri: pasif kullanici, yanlis parola, password_reset akisi icin negatif testler.

### 36-7 Yeni yazilan her URL icin yetki taramasi sadece bazi uygulamalarda otomatik
- Onem: medium | Guven: medium
- Dosyalar: hr/tests/test_scope.py:144-145, experiments/tests/test_pages.py:403, core/tests_crud_mount.py
- Aciklama: hr, experiments ve core'da URL sayimi/rol matrisi var; farm (1009 test), reports, monitoring, tasks icin "tum URL adlari icin anonim=302, rolsuz=403" tarzi genel bir tarama testi gormedim, yetki testleri elle yazilmis. Yeni eklenen bir view icin yetki testi unutulabilir. (Oranlar: inventory 2/50, knowledge 6/60 yetki-ilgili eslesme; yine de 403 testleri mevcut.)
- Oneri: `get_resolver()` ile tum rotalari dolasip anonim/yetkisiz erisimi dogrulayan tek bir test ve muaf listesi.

### 36-8 Middleware dogrudan test edilmiyor
- Onem: info | Guven: high
- Dosyalar: core/middleware.py:1-15, core/tests_workspaces.py
- Aciklama: `WorkspaceMiddleware` icin ozel test dosyasi/ad eslesmesi yok; yalniz `navigation.workspace_of` ve calisma alani testleri dolayli kapsiyor. Oturum anahtari yazma davranisi (degismediginde yazmama) dogrulanmiyor olabilir.
- Oneri: kucuk bir birim testi.

### 36-9 Rastgele (fuzz) stok testinde tum ValidationError'lar yutuluyor
- Onem: low | Guven: high
- Dosyalar: farm/tests/test_stock.py:451-478
- Aciklama: Tohumlu RNG (20261102) iyi, tekrarlanabilir; ancak `except ValidationError: pass` her reddi sessizce gecer. Hizmetin cok sayida islemi yanlis nedenle reddetmesi (ornegin tarih penceresi) testi anlamsizlastirir, kac islemin kabul edildigi sayilmiyor/dogrulanmiyor.
- Kanit: satir 474 `pass`; son assert yalniz "stok >= 0" ve toplam esitligi.
- Oneri: kabul edilen islem sayisi icin alt sinir assert'i ekle.

### 36-10 Saat dilimi tutarsizligi: `date.today()` ile `timezone.localdate()` karisik
- Onem: low | Guven: medium
- Dosyalar: experiments/tests/test_places.py:500, farm/tests/test_water.py:712, monitoring/tests/test_pages.py:203, config/settings.py:160
- Aciklama: TIME_ZONE='UTC'. test_places.py sistem yerel saatiyle `date.today()` kullaniyor, uygulama UTC `localdate` kullaniyor; makine saat dilimi UTC disindaysa gece yarisi civarinda `starts_on` ve uygulama bugunu farkli gunler olabilir (flaky). Ayrica 24 yerde gercek saat okunuyor, yalniz hr testleri `timezone.now`'u mock'luyor; gece yarisi sinirinda gun degisirse testler kirilabilir.
- Oneri: `timezone.localdate()` kullan veya `now`'i sabitle.

### 36-11 Sabit kodlanmis tarih/kod degerleri (2026) zamanla bayatlayabilir
- Onem: low | Guven: medium
- Dosyalar: experiments/tests/test_places.py:502-503 (`E-2026-00N`), cok sayida `date(20xx,...)` (387 eslesme)
- Aciklama: Gercek saate bagli (`STOCK_BACKDATE_DAYS=31` gibi) kurallar ile sabit takvim tarihleri karisirsa yil/pencere ilerleyince testler kirilir. Bugun 2026-11-06; deney kodu yili ve geriye donuk tarih penceresi sabit tarihlerle etkilesiyorsa risk vardir. Dosya bazinda dogrulanmadi.
- Oneri: sabit tarihli testlerde saati mock'la, kod yilini bugunden turet.

### 36-12 Test dosya adlandirma tutarsizligi (core)
- Onem: info | Guven: high
- Dosyalar: core/test_*.py ve core/tests*.py (ornek core/tests.py, tests_scope.py, test_database.py)
- Aciklama: Ayni pakette `test_x.py` ve `tests_x.py` karisik; diger uygulamalar `tests/` paketi kullaniyor. Varsayilan `test*.py` deseni ikisini de bulur, ama okunabilirlik ve arama zorlasir. `core/tests.py` 510 satirlik toplu dosya.
- Oneri: core icin `core/tests/` paketine tasi.

### 36-13 Test altyapisi: MD5 hasher ve tek DB; paralel kosu icin yonerge sinirli
- Onem: info | Guven: high
- Dosyalar: config/test_runner.py:6-9, config/settings.py:124, README.md
- Aciklama: Testlerde MD5 hasher aciliyor; bu hizlandirir ama parola dogrulama/uyumluluk (hasher yukseltme, `check_password`) davranislarini gercek hasher ile denemez. Ayrica TimescaleDB eklentisi gerektirdigi icin testler yalniz gercek Postgres ile calisir (SQLite yok); `--parallel` kullanimi belgelenmemis, iki kosu icin `DB_TEST_NAME` elle verilmeli.
- Oneri: hasher'a bagli tek bir test, README'ye paralel kosu notu.

### 36-14 Frontend modullerinin cogunun birim testi yok
- Onem: low | Guven: high
- Dosyalar: frontend/auth.ts, components.ts, dom.ts, nav-boot.ts, poll.ts, roster.ts, shell.ts, windows.ts, designer.ts
- Aciklama: ~3150 satir TS'in yalniz announce.ts ve grid/{history,keyboard,layout}.ts icin birim testi var; designer yalniz (skip olabilen) tarayici testinde. `poll.ts` (veri guncelleme/birlestirme) ve `windows.ts` (dialog) gibi durumlu modullerin birim testi yok. Python tarafi `test_frontend_contract.py` yalniz sozlesme/nitelik varligini dogruluyor.
- Oneri: poll/windows/roster icin node:test birim testleri.

### 36-15 Testler calistirilamadi (dogrulama siniri)
- Onem: info | Guven: high
- Dosyalar: requirements.txt, docker-compose.yml
- Aciklama: Denetim ortaminda Django kurulu degil, `pg_isready -p 5433` yanit vermedi; yesil/kirmizi durum, gercek skip sayisi ve sure olculemedi. Kapsam (coverage) araci repoda yapilandirilmamis (coverage/pytest-cov yok).
- Oneri: coverage ayari ekle; ilk CI kosusunda skip sayisini raporla.
