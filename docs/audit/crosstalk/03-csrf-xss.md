# Çapraz görüş: csrf-xss (03)

## Doğrulananlar
- 04-1 (help_text + |safe): tasks/forms.py:80 `gettext(...) % {'place': places.label(chosen)}` kaçışsız; templates/registration/_field.html:20 `help_text|safe`. Doğrulandı. Benim 03-4 ile aynı kök neden; tek düzeltme (|safe kaldır veya format_html) ikisini kapatır.
- 01-3 / 02-2 / 05-4 (cookie/HTTPS ayarları yok): config/settings.py içinde SESSION_COOKIE_*/CSRF_COOKIE_*/SECURE_* grep sonucu boş; yalnız MIDDLEWARE satırı (64) eşleşti. Doğrulandı. Aynı bulgu 4 uzmanda tekrar; tek kayıt olarak birleştirilmeli.
- 04-12: autoescape off yalnız templates/registration/password_reset_email.html:1-7 (düz metin e-posta). Doğrulandı; kullanıcı adı alanı e-postada HTML olarak yorumlanmaz.
- 04-11: next doğrulaması tutarsız; 03-10 ile aynı.
- 06-9: knowledge/views.py:37-40 FileResponse inline application/pdf, CSP sandbox yok; 03-14 ile aynı.
- 06-4/04-4 ve 06-8: doğrulandı (knowledge/views.py:37-39 Cache-Control 'private, no-cache').

## Önem derecesi
- 05-1/05-2 (high): XSS/CSRF açısından değil, ama sabit SECRET_KEY oturum/CSRF imzasını tahmin edilebilir kılar; high uygun.
- 01-3 medium uygun; 05-4 medium uygun (tek başına, TLS arkasında aksi halde HttpOnly/Secure eksikliği).
- 04-1 medium: depolanmış HTML enjeksiyonu için yer adını yazabilen bir yetkili gerekir ve kaçış sonrası de bile yalnız help_text'e gider; medium makul, düşük yönde de savunulabilir.

## Yeni bulgular
Bkz. StructuredOutput 03-X1..: (1) 06-9/03-14 ve 03-1 CSP eksikliği tek kök neden; (2) FileResponse PDF'de X-Frame-Options SAMEORIGIN ile aynı kökenden gömülebilir; (3) audit'te X-Content-Type-Options nosniff SecurityMiddleware ile varsayılan açık.

## Komşulara sorular
- authn: LoginRequiredMiddleware, CSRF reddinde (403) kullanıcıya ne gösteriliyor, CSRF_FAILURE_VIEW özel mi?
- file-upload: nosniff'in PDF yanıtında fiilen gönderildiği testle doğrulandı mı?
- secrets-config: SECURE_PROXY_SSL_HEADER/CSRF_TRUSTED_ORIGINS bir ters proxy arkasında gerekli mi, belgelenmiş mi?
