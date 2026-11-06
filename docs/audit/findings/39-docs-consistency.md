# 39 - docs-consistency: README/docs ile kod tutarsizliklari

## Ozet
README.md (3408 satir) ve docs/ (aquaculture-platform-bugs, data-map, experiments, hr-launch-checklist, i18n, regulatory-reports) kodla karsilastirildi. Dokumantasyon genel olarak cok ayrintili ve buyuk olcude dogru (komut adlari, ayarlar, dosya yollari, demo kullanicilari, 296/110 px, 100 satir/sayfa, 50.000 satir export siniri dogrulandi). Asil sorunlar: sonradan eklenen uygulamalar (hr, monitoring, experiments) icin guncellenmemis ozet bolumleri (Layout tablosu, Database viewer app listesi, Pages tablosu, maskelenen sutunlar, Roles alan listesi), regulatory-reports.md'nin eskimis "Phase 1" girisi, satir numarali atiflarin kaymasi ve belgelenmemis ortam degiskenleri. Django kurulu olmadigi icin `manage.py data_map --check` calistirilamadi.

## Incelenen
README bolumleri (giris, Local setup, Languages, Browser code, Roles, Database viewer, Data map, Email, Pages, Layout of the code, Tests, Adding a tab, HR), config/settings.py, config/database.py, config/access.py, config/urls.py, hr/management komutlari, docs/*.md icindeki dosya yolu ve dosya:satir atiflari.

## Incelenmeyen
Her tab bolumunun (1000+ satir) madde madde davranis dogrulamasi; data-map.md/json'in guncelligi (komut calistirilamadi); i18n.md ayrintilari; aquaculture-platform-bugs.md'nin dis kaynak (aquaculture_platform) atiflari.

## Bulgular

### 39-1 | medium | guven: high
Dosyalar: README.md:3347-3394, hr/, monitoring/
Aciklama: "Layout of the code" tablosunda `hr/` ve `monitoring/` uygulamalari hic yok; `core/` satiri da `core/ranges.py`, `core/checks.py`, `core/resources.py` gibi modulleri anlatmiyor. Tabloda `farm/health/notices.py` (README:2175 baska yerde anar) listelenmemis.
Kanit: `grep 'monitoring/' README` sadece bolum metinlerinde cikiyor, tabloda satir yok; `hr/` dizini 20+ dosya ile mevcut; config/settings.py:56-58 hr/experiments/monitoring INSTALLED_APPS'te.
Oneri: Tabloya hr/ ve monitoring/ satirlari eklensin.

### 39-2 | medium | guven: high
Dosyalar: README.md:2907-2909, config/database.py:9-20
Aciklama: Database viewer bolumu tablolarin "`farm`, `inventory`, `knowledge`, `messaging`, `reports`, `tasks`, `core`, `auth`" uygulamalarindan geldigini soyler; gercekte hr, experiments, monitoring de listede.
Kanit: config/database.py:`Section(_('People'), ('hr',))`, `Section(_('Research'), ('experiments',))`, `Section(_('Monitoring'), ('monitoring',))`.
Oneri: README listesi guncellensin veya "config/database.py'ye bakin" denilsin.

### 39-3 | medium | guven: high
Dosyalar: README.md:2912-2918, config/database.py:28-31
Aciklama: README maskelenen sutunlari yalnizca `auth_user.password` ve `messages.body` olarak verir; kodda ayrica `shift_assignments.note`, `leave_requests.reason`, `leave_requests.decision_note`, `attendance_records.note` maskeli. Guvenlik/gizlilik davranisi belgesinde eksik (hr-launch-checklist 4.3 de bunlara dayanir).
Kanit: `masked={'auth_user': ('password',), 'messages': ('body',), 'shift_assignments': ('note',), 'leave_requests': ('reason', 'decision_note'), 'attendance_records': ('note',)}`.
Oneri: README'ye HR sutunlari eklensin.

### 39-4 | medium | guven: high
Dosyalar: README.md:683-684, config/settings.py:119-122
Aciklama: Monitoring performans paragrafi "`CONN_MAX_AGE` is left alone ... no evidence for it" der; ayni README'nin Local setup bolumu ve settings.py ise `DB_CONN_MAX_AGE` ayarini (CONN_HEALTH_CHECKS ile) sonradan eklemis. Iki yer celisir gorunur.
Kanit: settings.py:121 `'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '0'))`; commit c295bb3 / 0f5bc72.
Oneri: Paragraf "varsayilan 0 birakildi (DB_CONN_MAX_AGE, bkz. Local setup)" diye netlestirilsin.

### 39-5 | medium | guven: high
Dosyalar: docs/regulatory-reports.md:3-6, 745, 437
Aciklama: Dosyanin acilisi "Phase 1 ... No app code is written in this phase" der; oysa `reports/` uygulamasi var ve ayni dosyada "5.13 As built (Phase 2)" ve "Status after Phase 2" bolumleri yer alir. Giris eskimis; okuyucu belgenin tasarim-oncesi plan oldugunu sanir.
Kanit: reports/ dizini (models, compute/, services.py...), docs/regulatory-reports.md:745 "### 5.13 As built (Phase 2)".
Oneri: Girise durum notu ("Phase 1 plani; Phase 2 insa edildi, bkz. 5.13") eklensin.

### 39-6 | low | guven: high
Dosyalar: docs/regulatory-reports.md:366, 697, 722, 725-727
Aciklama: Belge README'ye satir/yer atfi yapar: `README.md:43-44, :1722-1723` ve "README already says the cleaner-fish track comes 'later, as batches of a cleaner-fish species' (Operations > Production units, 'Not ported')". README:43-44 su an "Ported farm tabs" giris metni; alinti ifade README'de bulunamadi.
Kanit: `grep "later, as batches" README.md` bos; README.md:41-45 baska icerik.
Oneri: Satir numarasi yerine bolum adi kullanilsin; alinti guncellensin/silinsin.

### 39-7 | low | guven: high
Dosyalar: docs/regulatory-reports.md (farm/feeding/fold.py:184-191, farm/models/health.py:367-371, farm/forms/site.py:42-43, farm/handling/check.py:166 ...), docs/regulatory-reports.md:727-883
Aciklama: Kod satir atiflari kaymis. `farm/models/health.py:367-371` EventKind diye gosterilir ama EventKind health.py:434'te, 367-371 Treatment Meta'sidir; `farm/models/harvest.py:148-149` dogru gorunse de fold.py/site.py/check.py atiflari ilgisiz satirlari gosterir.
Kanit: health.py:365-372 `class Meta: db_table = 'treatments'`; health.py:434 `class EventKind`; fold.py:184-186 while dongusu, belgedeki aciklamayla uyusmaz.
Oneri: Sembol adi ile at (dosya::fonksiyon) veya belge "satirlar commit X'e gore" diye isaretlensin.

### 39-8 | low | guven: high
Dosyalar: docs/regulatory-reports.md:727, 883, docs/experiments.md:131
Aciklama: Repoda bulunmayan dosyalara atif: `coverage/COVERAGE.md` ("planning material ile saklanir"), `plan/area1/PLAN.md`, `utils/thresholds.ts` (dis kaynak). Okuyucu bunlari bulamaz; experiments.md "plan ile kod ayrilirsa kod kazanir" der ama plan repoda yok.
Kanit: `find` ile COVERAGE.md ve PLAN.md yok.
Oneri: Dis/depo-disi oldugu acikca yazilsin veya ozet repoya alinsin.

### 39-9 | medium | guven: high
Dosyalar: README.md:3258-3346, hr/urls.py, monitoring/, reports/urls.py:17-21
Aciklama: "Pages" tablosu eksik: hicbir `/hr/...` yolu, `/production/team/`, `/monitoring-boards/` ve `/reports/close/`, `/reports/duties/`, `/reports/duties/done/`, `reports/closed/<id>/reopen/` yok. Tablo kapsamli gibi sunulur.
Kanit: Tablo icinde `/hr/` ve `/production/team` sayisi 0; `grep -c "reports/duties" README.md` = 0; reports/urls.py:17-21 bu rotalari tanimlar; hr/resources/leave.py:37 `url_prefix = 'hr/leave'`.
Oneri: Eksik rotalar eklensin veya tablo "secilmis" diye isaretlensin.

### 39-10 | low | guven: medium
Dosyalar: README.md:1-40 (giris), config/access.py:16,28,68
Aciklama: "What works today" listesi Production panelini sayarken Research > Experiments, Reports (Regulatory reports), Monitoring ve Card templates'i anmaz; ayrica Roles bolumundeki erisim alani listesi (README:2850-2870) `Experiments`, `Monitoring boards`, `Card templates`, `Card template rules`, `Questions for the authority` alanlarini saymaz (ilk ikisi baska bolumlerde anlatiliyor).
Kanit: access.py:16 `Area(_('Monitoring boards') ...)`, :28 `Card template rules`, :68 `Questions for the authority`; README Roles listesinde bu adlar yok.
Oneri: Ozet listeleri guncellensin.

### 39-11 | medium | guven: high
Dosyalar: README.md:2977-2996, config/settings.py:25-30, 191-196
Aciklama: Ortam degiskenleri `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` README'de hic gecmez (yalniz DB_* ve DJANGO_MEDIA_ROOT). Varsayilanlar guvensiz (`DEBUG` varsayilan 1, sabit SECRET_KEY); uretim icin gereken ayar belgelenmemis. README gunicorn'dan bahseder ama requirements.txt'te gunicorn yok ve dagitim/deployment bolumu yoktur.
Kanit: `grep DJANGO_SECRET_KEY README.md` bos; settings.py:25 `os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-development-only')`, :28 `DEBUG ... '1'`.
Oneri: "Configuration" tablosu (tum env degiskenleri, uretim zorunluluklari) eklensin.

### 39-12 | low | guven: high
Dosyalar: README.md:2977-2988
Aciklama: Local setup yalnizca Windows yollarini (`C:\Python312\python.exe`, `.venv\Scripts\...`) verir; Linux/macOS karsiligi yok. Ayrica README "Tests" bolumu ayni sekilde `.venv\Scripts\python.exe`.
Kanit: README.md:2983-2988, 3399.
Oneri: POSIX komutlari da eklensin.

### 39-13 | low | guven: medium
Dosyalar: README.md:3251-3256, config/settings.py:191-196
Aciklama: Email bolumu SMTP icin `MAILERS` ayarina isaret eder; yalnizca console backend ornegi var, SMTP icin gereken anahtarlar (host, port, kimlik) anlatilmaz. `MAILERS` sozlesmesi Django surumune bagli oldugundan ve burada dogrulanamadigindan guven orta.
Kanit: settings.py:191-195.
Oneri: Ornek SMTP yapilandirmasi eklensin.

### 39-14 | low | guven: high
Dosyalar: README.md:3347-3394, farm/management/commands/check_withdrawal.py, reports/management/commands/check_reports.py
Aciklama: Layout tablosu `manage.py check_stock`, `check_inventory`, `check_experiments`, `generate_tasks`, `data_map`'i listeler ama `check_withdrawal`, `check_reports`, `check_hr`, `hr_roles`, `seed_hr_demo` yok; bunlar yalniz ilgili bolumlerde gecer. Hicbir yerde tum yonetim komutlarinin ozeti yok.
Kanit: komut dosyalari mevcut; README:1844, 2306, 2814-2827 ilgili bolumlerde.
Oneri: Komut ozet tablosu eklensin.

### 39-15 | info | guven: high
Dosyalar: docs/aquaculture-platform-bugs.md:7-8, README.md:3238
Aciklama: Bug belgesi dis repo (`aquaculture_platform`, commit 352aa2a8) kaynagina baglidir ve "yeni tab portlandikca buyur" der; atiflanan dosya yollari (`*.entity.ts` vb.) bu repoda yoktur ve dogrulanamaz. Belge "✔" olmayan maddelerin dogrulanmasi gerektigini kendisi belirtir; dogru ama kullanici icin ayrica bir uyari yeterli.
Kanit: belge basligi; dis yollar `find` ile bulunamadi.
Oneri: Kaynak commit'in erisilebilir oldugu notu (veya arsiv) eklensin.

### 39-16 | info | guven: high
Dosyalar: README.md:3396-3408, docs/data-map.md:1-5
Aciklama: Dogrulananlar (tutarli): komut adlari ve seed_hr_demo DEBUG kosulu ve demo kullanici adlari, DB_TEST_NAME, DJANGO_MEDIA_ROOT, KNOWLEDGE_MAX_FILE_BYTES=20 MB, STOCK_BACKDATE_DAYS=31, EXPORT_LIMIT=50.000, PAGE_SIZE=100, rail 296/110 px, AUTO_COLLAPSE_BELOW=1100, audit_log append-only trigger, hr_roles rolleri, TabRulesTests/TabTranslationTests varligi, Layout tablosundaki dosya yollarinin tamami mevcut, THIRD_PARTY.md paketleri package.json ile uyumlu.
Kanit: ilgili dosya:satirlar yukarida ve config/settings.py, core/dbgrid.py:25-26, frontend/nav-boot.ts:5.
Oneri: Yok.
