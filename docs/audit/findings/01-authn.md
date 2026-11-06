# 01 - Kimlik doğrulama (authn) denetimi

## Özet
Temel iskelet sağlam: `LoginRequiredMiddleware` global açık (`config/settings.py:76`), projede tek bir açık view var (`core/views.py:16` set_language), parola değiştirme/sıfırlama Django'nun standart view'larıyla, logout POST. Zayıf alanlar: brute force/oran sınırlama yok, üretim sertleştirmesi (DEBUG/SECRET_KEY varsayılanları, cookie bayrakları, HSTS) yok, oturum/giriş olayları denetim kaydına yazılmıyor, anonim isteklerde oturum kaydı oluşuyor, e-posta üretim için yapılandırılmamış.

## İncelenen alanlar
settings (MIDDLEWARE, AUTH_*, LOGIN_*), config/urls.py, core/middleware.py, core/forms.py (UserForm, PasswordResetForm), core/resources.py (davet), core/views.py, templates/registration/*, knowledge/views.py (dosya), hr seed komutu, core/tests.py kimlik testleri.

## İncelenmeyen alanlar
Ortam/proxy/dağıtım yapılandırması (repoda yok), yetkilendirme matrisi (ayrı uzman), Django admin içi, frontend TS.

## Bulgular

### 01-1 | yüksek | güven: yüksek - Giriş/parola sıfırlama için brute force koruması yok
Dosyalar: config/settings.py, config/urls.py:27-28
Açıklama: Giriş `django.contrib.auth.urls` ile geliyor; kilitleme, gecikme, captcha veya oran sınırı yok.
Kanıt: settings.py'de AXES/ratelimit/throttle yok, MIDDLEWARE'de ilgili öğe yok (satır 64-77); `AUTHENTICATION_BACKENDS` varsayılan.
Öneri: django-axes benzeri kilitleme veya IP+kullanıcı bazlı oran sınırı; /admin/ giriş için de.

### 01-2 | yüksek | güven: yüksek - Güvensiz varsayılanlar: DEBUG=1 ve sabit SECRET_KEY
Dosyalar: config/settings.py:25,28,30
Açıklama: `DJANGO_DEBUG` verilmezse DEBUG açık; `DJANGO_SECRET_KEY` verilmezse bilinen sabit anahtar kullanılıyor. Unutulan ortam değişkeni oturum/parola-sıfırlama token imzalarını tahmin edilebilir yapar.
Kanıt: `os.environ.get('DJANGO_DEBUG', '1') == '1'`, `os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-development-only')`.
Öneri: Varsayılanı kapalı yap; DEBUG kapalıyken anahtar yoksa başlangıçta hata ver.

### 01-3 | orta | güven: yüksek - Oturum/cookie ve taşıma sertleştirmesi yok
Dosyalar: config/settings.py
Açıklama: SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, SECURE_SSL_REDIRECT, SECURE_HSTS_*, SECURE_PROXY_SSL_HEADER, SESSION_COOKIE_AGE/idle timeout tanımlı değil (yalnızca LANGUAGE_COOKIE_* satır 157-158 ayarlı). Oturum varsayılan 2 hafta, boşta zaman aşımı yok.
Kanıt: `grep SECURE_|SESSION_|CSRF_` yalnızca dil cookie'lerini buluyor.
Öneri: Üretim profilinde bayrakları aç; `manage.py check --deploy` CI'ya ekle.

### 01-4 | orta | güven: yüksek - Anonim isteklerde oturum kaydı oluşuyor (WorkspaceMiddleware sırası)
Dosyalar: core/middleware.py:12-14, config/settings.py:70-76, core/navigation.py:155-160
Açıklama: WorkspaceMiddleware, LoginRequiredMiddleware'den ÖNCE çalışır ve kimlik kontrolü yapmadan `request.session[...]` yazar. Anonim biri bir çalışma alanı sayfasına (ör. /production/) istek atınca oturum yazılır, DB'de oturum satırı oluşur ve çerez döner, sonra 302 ile girişe yönlenir. Oturum tablosunu şişirme/DoS vektörü.
Kanıt: `if key and request.session.get(...) != key: request.session[...] = key` - `request.user` kontrolü yok.
Öneri: Yalnızca `request.user.is_authenticated` ise yaz veya middleware'i LoginRequired'dan sonra koy.

### 01-5 | orta | güven: orta - Parola sıfırlama/davet e-postası üretime hazır değil (konsol backend)
Dosyalar: config/settings.py (MAILERS), README.md:3253, core/resources.py:62-69
Açıklama: E-posta yalnızca konsola basılıyor; yeni kullanıcı daveti ve "şifremi unuttum" üretimde teslim edilmez, tokenlı bağlantılar log/terminale düşer. Ayrıca `use_https=request.is_secure()` proxy arkasında SECURE_PROXY_SSL_HEADER olmadan http bağlantı üretir (01-3 ile bağlı).
Kanıt: `'BACKEND': 'django.core.mail.backends.console.EmailBackend'`; `invitation.save(request=request, use_https=request.is_secure())`.
Öneri: SMTP/sağlayıcı yapılandırması, DEFAULT_FROM_EMAIL, proxy başlığı ayarı.

### 01-6 | orta | güven: yüksek - Parola sıfırlama isteği için oran sınırı yok (e-posta bombardımanı)
Dosyalar: config/urls.py:24-26, core/forms.py:162-165
Açıklama: Bilinen bir e-postaya sınırsız sıfırlama maili tetiklenebilir; CSRF dışında koruma yok. Yanıt kullanıcı varlığını sızdırmıyor (olumlu), fakat gönderim zamanı farkı kalır (e-posta gönderen kullanıcı için daha uzun yanıt).
Kanıt: `PasswordResetView` standart; test `test_unknown_email_sends_nothing` (core/tests.py:76) sadece yok durumunu doğruluyor.
Öneri: IP/e-posta bazlı sınır; gönderimi asenkron yap.

### 01-7 | düşük | güven: yüksek - get_users, kullanılamaz parolalı hesapları da sıfırlamaya açıyor
Dosyalar: core/forms.py:162-165
Açıklama: Django'nun `has_usable_password` filtresi bilerek kaldırıldı (davet için). Sonuç: yönetici bir hesabı `set_unusable_password` ile kilitlemiş olsa (ör. dış kimlik) e-posta sahibi yine parola belirleyebilir; superuser hesapları da dahil. Ayırt edici bir "davet bekliyor" durumu yok.
Kanıt: `User._default_manager.filter(email__iexact=email, is_active=True)`.
Öneri: Davet durumunu ayrı işaretle veya yalnızca henüz parola atanmamış + davet edilmiş hesaplara izin ver.

### 01-8 | düşük | güven: orta - E-posta benzersizliği yalnızca form düzeyinde; reset birden çok hesaba gider
Dosyalar: core/forms.py:122-125 (clean_email), 162-165
Açıklama: `User.email` DB'de unique değil; benzersizlik sadece UserForm'da. Admin dışı yollar (createsuperuser, seed, shell) aynı e-postayı verebilir; `get_users` hepsine ayrı token gönderir. Admin'de User kaydı kaldırılmış (core/admin.py:72) bu yüzden risk düşük.
Kanıt: `clean_email` formda; model alanında unique yok.
Öneri: Case-insensitive unique kısıt (DB).

### 01-9 | düşük | güven: yüksek - Giriş, başarısız giriş, çıkış ve parola değişim/sıfırlama olayları denetim kaydına yazılmıyor
Dosyalar: core/audit.py, (sinyal kaydı yok)
Açıklama: `user_logged_in`, `user_login_failed`, `user_logged_out`, parola sıfırlama/değişim için sinyal veya audit yok; hesap ele geçirme sonradan izlenemez.
Kanıt: grep `user_logged_in|user_login_failed|user_logged_out` repoda sonuç vermedi.
Öneri: Bu sinyallere AuditLog yazıcısı bağla (IP, kullanıcı adı).

### 01-10 | düşük | güven: yüksek - Parola politikası asgari Django varsayılanı
Dosyalar: config/settings.py:132-145
Açıklama: Yalnızca 4 standart doğrulayıcı, minimum 8 karakter. Çiftlik konsolu (veri değiştirme yetkisi) için zayıf; yönetici hesapları için daha güçlü politika/MFA yok. /admin/ de aynı parola ile tek faktör (config/urls.py:42).
Kanıt: `MinimumLengthValidator` seçeneksiz.
Öneri: min_length 12; superuser için MFA.

### 01-11 | düşük | güven: orta - Parola sıfırlama token süresi açıkça ayarlanmamış (davet de aynı süre)
Dosyalar: config/settings.py, core/resources.py:66-69
Açıklama: `PASSWORD_RESET_TIMEOUT` yok, varsayılan 3 gün hem davet hem unutulan parola için geçerli; davet için makul, reset için uzun. Süre geçince davetli kullanıcı kendi "yeni bağlantı iste" yolunu kullanıyor (test: core/tests.py:383).
Kanıt: ayar yok.
Öneri: Süreyi bilinçli seç (ör. 1 gün) ve belgele.

### 01-12 | info | güven: yüksek - Açık (login_not_required) view envanteri
Dosyalar: core/views.py:16, config/urls.py:27-28
Açıklama: Projedeki tek `@login_not_required` `set_language`; Django auth view'ları (login, reset) kendi muafiyetini taşır. Medya dosyaları public değil, view ile korunuyor (knowledge/views.py:26-40; settings.py:177-180). Olumlu. Eksik: tüm URL'lerin korumalı olduğunu otomatik doğrulayan test yok (yalnızca `/` için test_home_requires_login, core/tests.py:34).
Kanıt: grep sonucu tek dekoratör.
Öneri: URL resolver'ı gezen "tüm yollar girişe yönlenir, beyaz liste dışında" testi.

### 01-13 | info | güven: yüksek - set_language anonim POST'a açık ve oturum hesabına yazıyor
Dosyalar: core/views.py:16-24
Açıklama: Tasarım gereği açık; CSRF korumalı, `next` Django tarafından doğrulanıyor. Sadece oturum açıksa hesap dilini kaydediyor. Sorun yok, kayıt amaçlı.
Kanıt: `request.user.is_authenticated` kontrolü satır 22.
Öneri: Yok.

### 01-14 | info | güven: yüksek - Test kapsamı boşlukları
Dosyalar: core/tests.py:34-80
Açıklama: Var olanlar: login/logout, reset akışı, bilinmeyen e-posta. Eksik: pasif kullanıcı girişi reddi ve resetten dışlanması (yalnız is_active=False kaydı test edilmiş, giriş denemesi yok), token yeniden kullanımı/süresi, parola değişince oturum, brute force, anonim oturum oluşumu (01-4), açık-yönlendirme (`next=`).
Kanıt: grep `inactive|is_active` yalnız kullanıcı formu testlerini gösteriyor.
Öneri: Bu senaryolar için testler.

### 01-15 | info | güven: orta - Demo seed'de bilinen parola (DEBUG korumalı)
Dosyalar: hr/management/commands/seed_hr_demo.py:15,46-47,75
Açıklama: `demo-password-1` sabit; komut DEBUG kapalıyken reddediyor (iyi). Ancak 01-2 nedeniyle DEBUG yanlışlıkla açık kalan bir ortamda bu koruma da düşer.
Kanıt: `if not settings.DEBUG: raise CommandError`.
Öneri: 01-2 çözülünce yeterli.
