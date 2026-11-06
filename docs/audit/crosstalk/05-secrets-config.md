# 05 secrets-config: komşu bulgu çapraz denetimi

## Doğrulananlar
- 01-2 / 02-2 / 03-2 / 01-3: config/settings.py:25 (SECRET_KEY sabit varsayılan), :28 (DEBUG varsayılan '1'), cookie/HSTS/CSRF_TRUSTED_ORIGINS ayarı yok. Aynı kök neden 05-1/05-2/05-4 ile örtüşüyor (tek kök, 4 uzman tekrar saymış).
- 01-5 / 05-6: e-posta backend ayarı settings.py'de yok (Django konsol/SMTP varsayılanı ortama bağlı).
- 01-15 (seed_hr_demo): hr/management/commands/seed_hr_demo.py:46-47 `settings.DEBUG` kontrolü var; DEBUG varsayılanı açık olduğundan koruma fiilen zayıf (05-11).
- 06-5: MEDIA_ROOT settings.py:180 checkout içi varsayılan; .gitignore:16 /media/ ile ignore'da; docker-compose'da media volume yok, yalnız pgdata.
- 03-12 / 04-12: password_reset_email.html:1 autoescape off, düz metin e-posta; kabul edilebilir.
- 14-12: CI/dağıtım yönergesi yok; docker-compose.yml yalnız db servisi, uygulama imajı/Dockerfile yok.

## Önem derecesi itirazları
- 01-2 high: tek başına varsayılan fail-open kod düzeyinde gerçek; "high" kabul, ama 02-2 (medium) ile aynı olguya farklı önem verilmiş. Tutarlılık için ikisi aynı seviyede (high, üretim dağıtımı varsayımıyla) olmalı.
- 01-1 high: brute force yok doğru, ancak uygulama iç araç MVP; medium da savunulabilir (ağ erişimine bağlı).

## Yeni bulgular
Bkz. StructuredOutput new_findings: 05-X1..05-X4.

## Komşulara sorular
- authn (01): WorkspaceMiddleware oturum yazması SESSION_COOKIE_* ayarlarının yokluğuyla birleşince anonim istemciye Secure olmayan çerez mi veriliyor?
- migrations (14): hr/farm migration'larının DB uzantı oluşturması (btree_gist, timescaledb) için DB kullanıcısının superuser olması gerekir; compose varsayılan kullanıcısı superuser. Üretimde beklenen yetki neydi?
- file-upload (06): DATA_UPLOAD_MAX_MEMORY_SIZE / FILE_UPLOAD_MAX_MEMORY_SIZE ayarlanmamış; reverse proxy sınırı belgelendi mi?
- csrf-xss (03): CSRF_TRUSTED_ORIGINS gereksinimi proxy/HTTPS arkasında SECURE_PROXY_SSL_HEADER ile birlikte belgelenmeli mi?
