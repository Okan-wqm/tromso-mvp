# Çapraz değerlendirme: file-upload (06)

## Doğrulananlar
- 01-4 (anonim istekte oturum yazımı): doğru. config/settings.py:70-76 sırasında WorkspaceMiddleware, LoginRequiredMiddleware'den önce; core/navigation.py:155-160 `workspace_of` yola göre anahtar döndürüyor. Giriş yapmamış biri `/knowledge/.../file/` gibi bir yola gelince oturum yazılıyor, sonra yönlendiriliyor. Dosya servisi yolu bundan etkilenir ama veri sızmaz.
- 04-4 = 06-4 (%PDF- alt dizesi ilk 1024 baytta): doğru, knowledge/models/document.py:71-73 (`b'%PDF-' in head`). Önem low uygun.
- 04-5 = 06-2 (pypdf sınırı yok): doğru. knowledge/extraction.py:69 `except Exception` hata yakalıyor ama sayfa/süre/bellek sınırı yok. 20 MB sınırı (settings.py:185) yalnız dosya boyutunu sınırlar; sıkıştırılmış akışlar ile bellek şişirme mümkün. Önem 06-2 için medium kalmalı, 04-5'in low/medium'u hafif düşük.
- 05-10 = 06-5 (MEDIA_ROOT checkout içinde): doğru, config/settings.py:180.
- 03-14 (inline PDF, CSP sandbox yok): doğru ama etkisi düşük. knowledge/views.py:37-39 `application/pdf` ve inline sunuyor; XFrameOptionsMiddleware (settings.py:77) tüm yanıtlara X-Frame-Options ekliyor, yani çerçeveleme engelli. Tarayıcı PDF görüntüleyicisi sayfa JS'i çalıştırmaz. low/low yerine info/low de olabilir.
- 03-12/04-12 ve 15-12: 15-12 (abstract CharField 10000) doğru, knowledge/models/document.py:107; alan belge özeti, dosyayla ilgisi sınırlı.

## Önem derecesi itirazları
- 04-10 (Content-Disposition tutarsız): core/dbview.py:63 elle `filename="{table.name}.csv"` biçimlendiriyor, reports/views.py:220 `content_disposition_header` kullanıyor. Knowledge PDF için Django FileResponse doğru kodluyor (views.py:37). Yani tutarsızlık gerçek, ama dosya servisi güvenli; low/medium yerine info.
- 02-5 / 15-6 (saklama): silinmiş belge dosyaları süresiz tutuluyor (06-6); bu iki bulgu belgesel olarak birbirini destekliyor, medium kalabilir.

## Yeni bulgular
Aşağıdakiler schema çıktısında da yer alır.

- 06-X1 (low): Dosya erişimi audit'e yazılmıyor ve AuditLog append-only tetikleyicisi TRUNCATE'e açık (15-1); iki bulgu birleşince okuma izi hiç yok, değişim izi silinebilir. Kanıt: knowledge/views.py:30-40 audit çağrısı yok.
- 06-X2 (low): document_file anonim isteklerde oturum yazan middleware (01-4) nedeniyle, yetkisiz kişiye 302 yanında oturum çerezi verir; dosya servisi uygulaması 404/403/302 farkları ile kayıt varlığını açığa vermez ama (302 hepsi için aynı) sızıntı yok. Bilgi amaçlı.
- 06-X3 (info): Yalnız yükleme formu 20 MB sınırı koyuyor (KNOWLEDGE_MAX_FILE_BYTES), DATA_UPLOAD_MAX_MEMORY_SIZE/FILE_UPLOAD_MAX_MEMORY_SIZE ayarı config'te yok (Grep sonucu boş); büyük gövde doğrulamadan önce diske/belleğe alınır (06-3 ile aynı).

## Komşulara sorular
- authn (01): Anonim isteklerde oturum yazımı (01-4) için hangi yol kümeleri etkilendiğini sayıp media yolunu dahil ettiniz mi?
- db-schema (15): audit_log TRUNCATE engeli eklenirse knowledge dosya silme/restore olayları için ayrı bir action değeri gerekir mi (15-3 CHECK ile)?
- secrets-config (05): MEDIA_ROOT için yedek/kalıcı depolama gereksinimi .env.example kapsamında belgelenecek mi?
- data-write (10): Belge dosyası değişiminde on_commit silme (Document modeli) ile UpdateView IntegrityError (10-2) yarışı yetim dosya bırakır mı?
- csrf-xss (03): PDF için `Content-Security-Policy: sandbox` ve `X-Content-Type-Options` eklenmesini 03-1 çözümüne dahil eder misiniz?
