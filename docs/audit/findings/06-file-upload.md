# 06 - Dosya yükleme/indirme ve PDF işleme denetimi (file-upload)

## Özet
Repodaki tek yükleme yüzeyi knowledge uygulamasındaki `Document.file` (PDF). Tasarım genel olarak sağlam: dosya adı sunucuda üretiliyor (`knowledge/documents/<uuid>.pdf`), MEDIA_URL rotası yok, dosya yalnızca `document_file` görünümüyle ve `knowledge.view_document` izniyle sunuluyor, uzantı + boyut + `%PDF-` kontrolü var, `nosniff` SecurityMiddleware'den geliyor. Başlıca zayıflıklar: (1) kaydı geri alınan/başarısız kayıtlarda yeni yüklenen dosyanın yetim kalması, (2) PDF metin çıkarımının istek içinde, sayfa/süre sınırı olmadan çalışması (DoS yüzeyi), (3) boyut sınırının yalnızca model doğrulamasında olması (Django gövdeyi önce diske yazıyor, ön sunucu sınırı yalnızca dokümanda), (4) medya dosyaları için yedek/kalıcılık/saklama politikasının olmaması, (5) magic-byte kontrolünün "başlangıç" değil "ilk 1024 bayt içinde" olması. Başka uygulamada (messaging, tasks, farm vb.) FileField/dosya yükleme yok.

## İncelenen alanlar
knowledge/models/document.py, knowledge/views.py, knowledge/forms/document.py, knowledge/extraction.py, knowledge/resources/document.py, knowledge/urls.py, knowledge/admin.py, knowledge/tests/test_documents.py ve helpers.py, templates/knowledge/widgets/file_input.html, templates/crud/form.html, core/crud.py (Create/UpdateView, request.FILES), core/softdelete.py (restore), config/settings.py (MEDIA_ROOT, KNOWLEDGE_MAX_FILE_BYTES, MIDDLEWARE), config/urls.py, docker-compose.yml, requirements.txt, .gitignore, README Library bölümü, frontend FormData kullanımı.

## İncelenmeyen alanlar
Gerçek dağıtım (nginx client_max_body_size, gunicorn zaman aşımı, dosya sistemi izinleri), pypdf'in gerçek kötü niyetli PDF'lerle davranışı (fuzz/zip-bomb denemesi yapılmadı), testlerin çalıştırılması (PostgreSQL gerekir), tarayıcı PDF görüntüleyici davranışı, antivirüs altyapısı.

## Bulgular

### 06-1 | orta | güven: yüksek - Geri alınan/başarısız kayıtta yeni yüklenen dosya depoda yetim kalıyor
Dosyalar: knowledge/models/document.py:217-242, core/crud.py:672-686, core/crud.py:728-737, knowledge/tests/test_documents.py:157-162
Açıklama: `Document.save` içinde `super().save()` FileField'ın pre_save'iyle yeni dosyayı hemen depoya yazar; yalnızca ESKİ dosya için `transaction.on_commit` silmesi kayıtlı. Yeni dosya için "işlem geri alınırsa sil" mantığı yok. CreateView'de `audit.record_create`/`after_save`/IntegrityError (aynı anda DOI çakışması, `constraint_error`), UpdateView'de `audit.record_update` hatası veya sonraki bir istisna işlemi geri alır; satır yoktur ama `MEDIA_ROOT/knowledge/documents/<uuid>.pdf` kalır. Mevcut test yalnızca eski dosyanın korunmasını doğruluyor.
Kanıt: `transaction.on_commit(partial(self.file.storage.delete, stored))` (yalnızca `stored`); yeni dosya adı için benzer bir on_rollback/temizlik yok. test_a_file_that_is_not_a_pdf_is_refused yalnızca form doğrulama aşamasında `media_files() == []` kontrol ediyor.
Öneri: Yeni dosya yazıldıktan sonra rollback'te silen bir mekanizma (örn. try/except ile atomic dışında silme veya yetim dosya süpürme komutu); yetim tarayan bir management command ve test.

### 06-2 | orta | güven: orta - PDF metin çıkarımı istek içinde, sayfa/süre/bellek sınırı olmadan çalışıyor (DoS)
Dosyalar: knowledge/extraction.py:56-75, knowledge/models/document.py:223-238, core/crud.py:721-737, README.md (Its text paragrafı)
Açıklama: 20 MB'a kadar bir PDF, `PdfReader` ile tüm sayfalar için `extract_text()` çağrılarak istek iş parçacığında çözümlenir; sayfa sayısı, toplam metin uzunluğu, süre sınırı yok. Binlerce sayfalık/şişirilmiş akışlı PDF CPU ve bellek tüketir, ardından tüm sayfalar `bulk_create` ile tek seferde eklenir (sınırsız satır). UpdateView'de bu iş `select_for_update` satır kilidi tutulurken ve `transaction.atomic` içinde yapılır; gunicorn işçisi bloke olur. README bunu "MVP için kabul" olarak not ediyor ve pypdf'in sürümünü kasıtlı güncel tutuyor, ancak kodda koruma yok. Yalnızca `except Exception` var; takılma/uzun döngü yakalanamaz.
Kanıt: `pages = [Page(...) for number, page in enumerate(reader.pages, 1)]` sınırsız; `DocumentPage.objects.bulk_create([...])` sınırsız; `with transaction.atomic(): current = ...select_for_update(...)` içinde `obj.save()` → `read_pdf`.
Öneri: Maksimum sayfa sayısı ve toplam metin üst sınırı, çıkarımı arka plan işine (zaman sınırlı) taşımak veya en azından kilidi tutmadan okumak; sınır aşıldığında FAILED durumu.

### 06-3 | orta | güven: yüksek - İstek gövdesi boyut sınırı uygulamada yok; yalnızca model doğrulaması ve "ön sunucu kapsın" notu
Dosyalar: config/settings.py:182-185, knowledge/models/document.py:58-72, docker-compose.yml
Açıklama: `KNOWLEDGE_MAX_FILE_BYTES` yalnızca form/model doğrulamasında (`file.size > limit`) uygulanır; Django çok parçalı gövdeyi önce geçici dosyaya yazar (settings yorumu bunu kabul ediyor). `FILE_UPLOAD_MAX_MEMORY_SIZE`, `FILE_UPLOAD_TEMP_DIR`, `DATA_UPLOAD_MAX_NUMBER_FILES/FIELDS` ayarlanmamış (varsayılanlar), ve repoda gerçek bir ön sunucu yapılandırması (nginx/Dockerfile) yok; sınır yalnızca yorum/README'de. Oturum açmış, library `add/change` izni olan biri 20 MB üstü gövdeyi sınırsız diske yazdırabilir. Ayrıca bir istek içinde birden çok `file` alanı aynı anda gönderilebilir (tek alan okunur, diğerleri geçici dosya olarak kalır ve istek sonunda silinir).
Kanıt: settings.py:182-185 yorumu "The web server in front of Django must cap a request's body too"; settings.py'de `grep UPLOAD` yalnızca bu yorum ve `KNOWLEDGE_MAX_FILE_BYTES`; ön sunucu config dosyası yok.
Öneri: Dağıtım şablonuna (nginx/Dockerfile) `client_max_body_size` ekle, `DATA_UPLOAD_MAX_MEMORY_SIZE`/`FILE_UPLOAD_*` değerlerini açıkça belirle, testle `RequestDataTooBig` (413) davranışını doğrula.

### 06-4 | düşük | güven: yüksek - Magic-byte kontrolü "başlangıçta" değil "ilk 1024 baytın herhangi bir yerinde" `%PDF-` arıyor; doküman ile çelişiyor
Dosyalar: knowledge/models/document.py:58-72, README.md (The file paragrafı)
Açıklama: Kod `b'%PDF-' in head` ile 1024 baytın içinde arar. PDF spesifikasyonu başlığın ilk 1024 bayt içinde olmasına izin verdiği için bu bilinçli olabilir, ama docstring ve README "first bytes say %PDF-" diyor. Sonuç: HTML/ZIP/başka biçimlerle polyglot dosyalar (başında başka içerik, ilk KB'de `%PDF-`) doğrulamayı geçer. Etki, `Content-Type: application/pdf` + nosniff sunumu ve inline görüntüleme nedeniyle sınırlı. Ayrıca doğrulama yapısal değil: `%PDF-1.4\nnot really a PDF` kabul edilir (test bunu FAILED olarak saklıyor).
Kanıt: `if b'%PDF-' not in head: raise ValidationError(_('This file is not a PDF.'))`; testte `upload(b'%PDF-1.4\nnot really a PDF')` kabul ediliyor (test_a_damaged_pdf_is_kept...).
Öneri: Ya ofset 0'ı zorunlu kıl ya da docstring/README'yi "ilk 1024 bayt" olarak düzelt; isteğe bağlı olarak pypdf ile başarılı açılışı yükleme kabulüne koşul yap.

### 06-5 | orta | güven: orta - Medya dosyaları için kalıcılık/yedek yok: compose'ta medya hacmi yok, varsayılan MEDIA_ROOT checkout içinde
Dosyalar: config/settings.py:180, docker-compose.yml:15-17, .gitignore (/media/), README.md (MEDIA_ROOT notu)
Açıklama: DB için `pgdata` hacmi var, yüklenen PDF'ler için hiçbir hacim/yedek tanımı yok; varsayılan `MEDIA_ROOT = BASE_DIR / 'media'` uygulama dizini içinde (README "dışında tutun" diyor ama ayar zorlamıyor). Konteynerleştirilirse yüklenen dosyalar yeniden dağıtımda kaybolur; DB geri yüklenirse (soft-delete "restore" tasarımı dosya+sayfa saklamaya dayanıyor) satırlar var, dosyalar yok olur. Görünüm bunu 404'e çevirerek tolere ediyor, ama `file`/`file_size`/`text_status` DB'de "dosya var" der. DB ↔ depo tutarlılığını doğrulayan komut yok.
Kanıt: docker-compose.yml:15 `volumes: [pgdata:/var/lib/postgresql/data]` ve yalnızca `pgdata` tanımı; `views.document_file` FileNotFoundError → Http404.
Öneri: Medya için ayrı hacim/nesne depolama ve yedek politikası; DB ile dosya sistemini karşılaştıran bir denetim komutu; DEBUG kapalıyken MEDIA_ROOT'un açık verilmesini zorunlu kıl.

### 06-6 | düşük | güven: yüksek - Silinmiş belgelerin dosyaları süresiz tutuluyor, kalıcı silme/saklama politikası yok
Dosyalar: knowledge/models/document.py:89-91, knowledge/admin.py:8-15, core/softdelete.py:189-205
Açıklama: Soft-delete'te dosya ve sayfalar bilinçli olarak saklanır; kalıcı silme (purge) yolu yok. Admin üzerinden hard delete yapılırsa (AuditedModelAdmin'in delete izni kontrol edilmedi) `on_delete` hiçbir dosya silme tetiği yok, dosya yetim kalır. KVKK/GDPR veya telif nedeniyle bir PDF'in gerçekten kaldırılması gerekirse yöntem yok ("Remove the file" yalnızca canlı kayıtta, geri dönülmez şekilde dosyayı siler ama silinmiş belge için çalışmaz).
Kanıt: kodda `Document` için delete/post_delete sinyali veya purge komutu yok (`grep storage.delete` yalnızca models/document.py:241).
Öneri: Saklama süresi + purge komutu; model `delete()`/post_delete'te dosyayı silme; admin'de hard delete kapatma.

### 06-7 | düşük | güven: orta - Yükleme/indirme olayları denetim kaydına yazılmıyor; dosya içeriği değişimi izlenemiyor
Dosyalar: knowledge/views.py:26-40, knowledge/resources/document.py:81-89
Açıklama: `document_file` erişimi (açma/indirme) audit log'a yazılmaz; kimin hangi PDF'i indirdiği izlenemez. Denetim anlık görüntüsü (`snapshot`) yalnızca `file_name`, `text_status`, `page_count` içerir; dosya değiştiğinde aynı adla yeni içerik yüklenirse log farkı yalnızca sayfa sayısı değişirse görünür; boyut/özet (hash) kaydedilmez.
Kanıt: `snapshot` yalnızca `document.file_name`, `text_status`, `page_count` değerlerini ekler; `document_file` içinde `audit` çağrısı yok.
Öneri: Dosya SHA-256 ve `file_size` değerlerini model alanı/snapshot olarak ekle; hassas içerik için indirme olayını günlükle.

### 06-8 | düşük | güven: yüksek - Önbellek başlığı `private, no-cache` ama ETag/Last-Modified/Range yok; her açılışta tam indirme
Dosyalar: knowledge/views.py:37-39
Açıklama: `FileResponse` Django'da Range isteklerini desteklemez; ETag/Last-Modified de verilmez, `no-cache` her seferinde tam 20 MB'a kadar dosyayı yeniden akıtır. Büyük PDF'te tarayıcı görüntüleyici ilerleyici (range) yükleme kullanamaz. İşlevsel hata değil, verimlilik.
Kanıt: `response['Cache-Control'] = 'private, no-cache'`; başka başlık yok.
Öneri: Dosya UUID adı değişmez olduğundan `ETag`'i (örn. depo adı + boyut) ver; koşullu GET desteği ekle; gerekirse X-Accel-Redirect ile sunumu ön sunucuya devret.

### 06-9 | düşük | güven: orta - Satır içi (inline) PDF sunumu için ek savunma başlıkları yok (CSP sandbox, Content-Disposition varsayılanı)
Dosyalar: knowledge/views.py:37-40, config/settings.py:64-78
Açıklama: Varsayılan olarak yüklenen PDF aynı kökende `inline` gösterilir (`as_attachment` yalnızca `?download` ile). Kullanıcı kontrollü, doğrulaması yalnızca imza düzeyinde olan içerik uygulama kökeninde sunulur. `X-Content-Type-Options: nosniff` SecurityMiddleware ile geliyor (testte doğrulanmış), `X-Frame-Options` (DENY) de var; ancak `Content-Security-Policy: sandbox` gibi bir ek önlem yok. Polyglot (bkz. 06-4) bir dosya PDF dışı olarak yorumlanırsa nosniff + application/pdf bunu büyük oranda engeller; kalan risk tarayıcının PDF görüntüleyicisindeki betik/açık bağlantı davranışıdır.
Kanıt: `FileResponse(stream, as_attachment='download' in request.GET, ..., content_type='application/pdf')`; test_the_file_is_sent... nosniff'i doğrular, CSP yok.
Öneri: Yanıta `Content-Security-Policy: sandbox` (veya `default-src 'none'`) ekle; mümkünse medya için ayrı köken.

### 06-10 | düşük | güven: orta - Yüklenen dosya adı denetimsiz saklanıyor; Windows yolu/kontrol karakterleri ve `text_error` içinde ham pypdf mesajı
Dosyalar: knowledge/models/document.py:258-264, knowledge/extraction.py:69-70, knowledge/models/document.py:253-254
Açıklama: `_file_name` yalnızca `os.path.basename` ile kırpar (Linux'ta `\` ayırıcısını ve kontrol karakterlerini temizlemez; Django'nun `UploadedFile.name` zaten bazı temizlik yapar ama `\` korunabilir). Ad, Content-Disposition ve arayüzde gösterilir (Django başlığı kaçışlar, şablon otomatik kaçışlar; doğrudan zafiyet yok). `text_error` ise `f'{type(error).__name__}: {error}'` ile ham istisna mesajını (pypdf iç ayrıntıları) kullanıcıya gösterir (500 karakter).
Kanıt: `name = os.path.basename(name or '') or 'document.pdf'`; `Extraction(FAILED, error=f'{type(error).__name__}: {error}'[:ERROR_LENGTH])`.
Öneri: Adı `get_valid_filename` benzeri bir normalleştirmeden geçir; hata metnini sabit kullanıcı mesajıyla değiştirip ayrıntıyı log'a yaz.

### 06-11 | düşük | güven: düşük - Metin temizliği yalnız `Cc` kategorisini atıyor; yalnız (lone) surrogate PostgreSQL/psycopg'de 500 üretebilir
Dosyalar: knowledge/extraction.py:50-53, knowledge/models/document.py:235-238
Açıklama: `clean` NFKC sonrası yalnızca kontrol karakterlerini (Cc) çıkarır. Bozuk kodlamalı bir PDF'ten gelen tek başına surrogate (kategori `Cs`) karakteri UTF-8'e kodlanamadığı için `bulk_create` sırasında istisna oluşturabilir; bu çağrı `read_pdf`'in try/except'inin dışında olduğundan FAILED'e dönüşmez, kullanıcı 500 görür. Doğrulayamadım (pypdf'in bu durumda tam olarak ne döndürdüğü denenmedi).
Kanıt: `''.join(ch for ch in text if ch in KEPT_CONTROLS or unicodedata.category(ch) != 'Cc')`; `bulk_create` try dışında.
Öneri: `Cs` (ve gerekirse `Cn`) kategorilerini de at veya `encode('utf-8','replace')` ile temizle; hatalı sayfaya karşı test ekle.

### 06-12 | düşük | güven: yüksek - Aynı dosyanın tekrar yüklenmesi/yinelenen içerik denetimi yok; kötü amaçlı yazılım taraması yok
Dosyalar: knowledge/models/document.py:115-124, knowledge/forms/document.py
Açıklama: İçerik özeti (hash) saklanmıyor; aynı PDF birden çok belge olarak yüklenebilir (yalnızca DOI benzersizliği var, DOI boşsa hiçbir kontrol yok). Yüklemeler virüs/zararlı içerik taramasından geçmiyor; PDF'ler diğer kullanıcılara sunuluyor (06-9 ile ilişkili).
Kanıt: Modelde hash/checksum alanı yok; yükleme yolunda tarayıcı entegrasyonu yok.
Öneri: SHA-256 alanı ve uyarı; dağıtımda ClamAV gibi bir tarama adımı değerlendirilmeli.

### 06-13 | düşük | güven: orta - Yetkilendirme yalnızca model düzeyi `view` izni; dosya için ayrı izin ve çalışma-alanı kapsamı yok
Dosyalar: knowledge/views.py:20-30, core/crud.py (Resource.perm)
Açıklama: `document_file` yalnızca `DocumentResource.perm('view')` kontrol eder; kütüphaneyi okuyabilen herkes tüm PDF'leri indirir (README'deki tasarımla uyumlu, bilinçli). Dosyayı görmek ile referansı görmek ayrı yetkilendirilemez; kapsamlı/özel belgeler (gizli sözleşme PDF'i) için ayrım yok. Not: dosya erişimi `Document.objects` (canlı kayıt) ile sınırlı, silinmiş belge 404 veriyor (test var).
Kanıt: `_allowed(request, DocumentResource, 'view')` ve `get_object_or_404(Document.objects, pk=pk)`.
Öneri: Gerekiyorsa belge başına görünürlük/`download_document` izni; mevcut tasarım belgelenmiş olduğundan bilgi amaçlı.

### 06-14 | bilgi | güven: yüksek - Test kapsamı boşlukları
Dosyalar: knowledge/tests/test_documents.py
Açıklama: Test edilenler: sahte PNG, boş dosya, yanlış uzantı, sınır +-1 bayt, uzun ad, sunum başlıkları, izin, 405, depodan eksik dosya, geri alma ile eski dosya korunması. Eksikler: yeni dosya yetimi (06-1), çok sayfalı/büyük PDF ve süre, şifreli PDF (parola gerekli/yalnız owner parolası), polyglot başlık, Range/ETag, çok parçalı gövde 413, `DATA_UPLOAD_*` sınırları, kalıcı silme. Şifreli PDF için kodda dal var (`reader.decrypt('')`) ama bunu doğrulayan test aranmadı.
Kanıt: grep ile test adları (test_a_pdf_without_text..., test_a_file_above_the_limit..., test_a_save_that_is_rolled_back_keeps_the_file).
Öneri: Yukarıdaki durumlar için testler ekle.

### 06-15 | bilgi | güven: yüksek - Yükleme yüzeyi tek (knowledge Document.file); doğrulama istemci tarafına da dayanıyor ama sunucuda tekrarlanıyor
Dosyalar: knowledge/forms/document.py:66, knowledge/models/document.py:115-118
Açıklama: `accept="application/pdf,.pdf"` yalnızca istemci ipucu; sunucu doğrulaması (uzantı, boyut, imza) ayrıca var ve `file_size`/`file_name` istemciden değil sunucudan türetiliyor. Repoda başka FileField/ImageField, ek dosya veya messaging eki yok (docs/aquaculture-platform-bugs.md'deki MSG-01 gibi ek sorunları bu portta yok). Bilgi amaçlı olarak olumlu bulgu: dosya adı depoda UUID, MEDIA_URL rotası yok (`/media/...` 404 testi var), `.gitignore`'da `/media/`.
Kanıt: config/urls.py'de media rotası yok; test_the_storage_has_no_public_address.
Öneri: Yeni yükleme yüzeyleri eklenirse aynı kalıp (sunucu adı, görünüm ile sunum, imza kontrolü) kullanılsın.
