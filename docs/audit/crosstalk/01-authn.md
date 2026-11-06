# Çapraz görüş: authn (01) -> authz, csrf-xss, injection, secrets-config, file-upload, data-write, transactions

Doğrulama dayanağı: config/settings.py:24-28 (SECRET_KEY/DEBUG varsayılanı), :64-78 (MIDDLEWARE), :199-200 (LOGIN_URL), templates/registration/_field.html:20, templates/registration/password_reset_email.html, core/forms.py:146-148 (get_users), core/middleware.py (WorkspaceMiddleware), hr/views.py:35-41, tasks/views.py:28-34, inventory/views.py:58-62.

## Doğrulananlar
- 05-1/05-2 (SECRET_KEY, DEBUG): config/settings.py:25,28 doğru. Authn etkisi: sıfırlama belirteci SECRET_KEY ile HMAC'lenir ama belirteç kullanıcının parola karması ve last_login'ini de içerir; bu yüzden bilinen anahtarla tek başına sahte sıfırlama bağlantısı üretilemez (DB sızıntısı gerekir). Oturumlar DB'de (SESSION_ENGINE ayarlı değil), imzalı çerez değil; yani anahtar bilgisi tek başına oturum sahteciliği vermez. Önem "high" kalabilir (DEBUG=1 bilgi sızdırır) ama authn etkisi dolaylıdır.
- 05-4 / 03-2 (cookie/HTTPS): settings.py'de SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, SESSION_COOKIE_AGE vb. yok. Doğrulandı; 01-3 ile aynı kök neden (üç uzman aynı şeyi ayrı yazmış).
- 05-6 (e-posta konsol backend'i): sıfırlama bağlantısı loga düşer; 01-5 ile aynı.
- 03-10 / 04-11 (next doğrulaması 5 biçim): doğrulandı. hr/views.py:38 `url_has_allowed_host_and_scheme(require_https=request.is_secure())`; inventory/views.py:60 `startswith('/')` + url_has_allowed_host_and_scheme (require_https yok); tasks/views.py:31-33 yalnız `startswith(base)` ve '//' / '\\' elemesi. Hiçbiri açık yönlendirme açığı üretmiyor ama ortak yardımcı yok. Giriş sayfasındaki `next` ise Django LoginView'de (güvenli).
- 03-12 (autoescape off sıfırlama e-postası): düz metin e-postada kabul edilebilir; `user.get_username` e-postada ham basılır, kullanıcı adı alanında satır sonu olamaz (Django doğrulayıcısı), bu yüzden başlık/gövde enjeksiyonu yok. Doğrulandı, info.
- 10-9 (davet e-postası transaction içinde, sonuç kontrolsüz): authn açısından önemli; davet edilen kişinin parola kurma bağlantısı sessizce yitebilir (01-5 ile birleşir).
- 02-2: 01-2/05-1 ile aynı bulgu; üçlü tekrar.

## Önem derecesi itirazları
- 03-1 (CSP yok) medium: kimlik doğrulama açısından XSS ile oturum çalma, HttpOnly çerez (Django varsayılanı SESSION_COOKIE_HTTPONLY=True) nedeniyle sınırlı; low-medium daha uygun. Ancak 04-1 ile birleşince (depolanmış HTML enjeksiyonu + CSP yok) kimlik doğrulanmış oturumda eylem yaptırma mümkün; bu zincir 04-1'i medium tutar.
- 02-3 (Production manager önayarı Team listesi hakkı kazanır): authn dışı, itiraz yok.
- 05-7 (ALLOWED_HOSTS strip yok) medium görünüyor; DEBUG=0 + boş ALLOWED_HOSTS Django'da 400 verir (fail-closed), yani güvenlik riski değil işletim sürtünmesi: low öner.
- 05-12 (parola politikası min 8) low: 01-10 ile aynı; çoğaltma.

## Reddedilen/Kısmen
- Hiçbiri tümden reddedilmedi. 04-1 ile 03-4 aynı kök neden (`|safe` _field.html:20 ve tasks/forms.py:80'de yer adı `%` ile gömülüyor); iki ayrı ID tek kayıt sayılmalı. Not: tasks/forms.py:80 yalnızca hata anında silinmiş yer adı gösteriyor, istismar için yer adı yazma yetkisi gerekir (yani zaten ayrıcalıklı kullanıcı).

## Yeni bulgular (authn x diğer alanlar)
- 01-X1: LoginRequiredMiddleware, WorkspaceMiddleware'den SONRA geliyor (settings.py:74-76); anonim istek oturum satırı üretiyor (01-4). Ek: 02-5/13 (audit) ve 08 (privacy) alanları bunu görmemiş: sayfa anahtarı yalnız path'ten türetiliyor, anonim botlar django_session tablosunu şişirebilir.
- 01-X2: Kimlik doğrulama olayları (login/logout/başarısız giriş/parola değişimi) denetim kaydında yok (01-9) ve 02-5 "yalnız HR türleri kısıtlı" diyor; 13-audit-log ve 02 uzmanları authn olaylarını kapsam dışı bırakmış gibi görünüyor. Sahipsiz bir boşluk.
- 01-X3: Parola sıfırlama/davet bağlantısı (e-posta) + `get_users` (core/forms.py:146-148) yalnızca is_active=True filtreler; set_unusable_password olan hesaplar için Django varsayılanı `has_usable_password` kontrolünü atladığımız için (01-7) bu uygulamada davet edilmiş ama pasif olmayan hesaplara sıfırlama gider. 10-9 ve 05-6 ile birlikte: davet e-postası konsolda, kullanıcı hesabı oluşturulmuş, parola belirlenmemiş.
- 01-X4: Rol/yetki değişimi (10-8: kullanıcı/rol düzenlemede sürüm yok) oturumu iptal etmiyor; izinler her istekte DB'den okunduğu için (Django ModelBackend önbelleği istek başınadır) etki anlık, ama parola değişiminde diğer oturumlar için Django'nun `update_session_auth_hash` ve session auth hash doğrulaması çalışır. Rol silme/kullanıcı pasifleştirmede açık oturumların geçerlilik süresi SESSION_COOKIE_AGE'e (2 hafta varsayılan, açıkça ayarlı değil) bağlı. Doğrulanmadı: pasifleştirilen kullanıcının var olan oturumu AuthenticationMiddleware'de is_active=False nedeniyle ModelBackend.get_user'da reddedilir (Django davranışı); confidence=low.
- 01-X5: Parola sıfırlama isteği e-posta var/yok ayrımı yapmaz (Django varsayılanı iyi) ama e-posta benzersizliği yalnız formda (01-8) olduğundan, aynı e-postayı paylaşan iki hesap için sıfırlama iki e-posta gönderir; `get_users` bunu hesaba katıyor ama invite akışı (10-9) ve admin dışı yollar aynı e-postayı tekrar kullanabilir.
- 01-X6: Hata sayfaları: DEBUG=1 varsayılanı (05-2) ile yetkisiz kullanıcı için 500 ayrıntılı sayfası ayarları (SECRET_KEY maskelenir ama DB host/yol, ortam değişkenleri maskelenir) gösterir; 10-1/10-2 (UpdateView'de 500) bu bilgi sızıntısını tetikleyebilir. Bulgular ayrı ayrı var, zincir yok sayılmış.

## Komşulara sorular
- authz: LoginRequiredMiddleware dışında @login_not_required işaretli view sayısı 1 (core/views.py:16) olarak gördüm; anonim erişen başka view (ör. set_language, password_reset_*) için izin/kapsam testi var mı?
- secrets-config: Üretim için SESSION_COOKIE_AGE / PASSWORD_RESET_TIMEOUT politikası belgelenmiş mi? Dağıtım rehberinde check --deploy çıktısı var mı?
- csrf-xss: Giriş formu ve parola sıfırlama formunda CSRF testi (anonim + zorunlu) var mı? 03-11 testlerin CSRF'yi zorlamadığını söylüyor; giriş için de geçerli mi?
- data-write: Davet akışı (10-9) kullanıcıyı oluşturup e-posta başarısız olursa kullanıcı yetim kalıyor mu, yeniden davet yolu var mı?
- transactions: Parola değişimi/oturum güncellemesi için atomic sınır belirlenmiş mi (16-13)?
- file-upload / injection: authn ile doğrudan kesişim yok; 06-13 dosya erişiminin yalnız view izniyle yapılması, oturum süresi uzunluğuyla birleşince önem dikkate alınmalı.
