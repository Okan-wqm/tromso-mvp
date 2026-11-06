# Çapraz Değerlendirme: ci-devops (37)

## Doğrulananlar
- 33-1 (LOGGING yok): config/ altında LOGGING tanımı yok (grep boş). Önem high uygun; 37-7 ile aynı kök neden.
- 33-2 (DEBUG açık varsayılan): config/settings.py:28 `DJANGO_DEBUG` varsayılanı '1'; ALLOWED_HOSTS boş (settings.py:30). Ayrıca SECRET_KEY güvensiz varsayılanı (settings.py:25). Tek başına medium, ancak dağıtım tarafında high'a yakın (prod ayar ayrımı yok, 37-9).
- 33-3 (özel hata sayfaları): config/ altında handler400/403/404/500 yok.
- 35-6 (check_withdrawal O(n^2)): farm/management/commands/check_withdrawal.py:16 `read.stock_of(units)` liste kapsamı içinde her birim için çağrılıyor. Doğrulandı.
- 35-23 / 35-15 (statik sunucu, CACHES, CONN_MAX_AGE): settings.py:121 CONN_MAX_AGE varsayılan 0; STATIC_ROOT yok (settings.py:173-174).
- 34-11 (dağıtım/worker tanımı yok): doğrulandı; README.md:2991 gunicorn'dan söz ediyor ama repoda gunicorn/Dockerfile yok.
- 34-4 / 34-5 (GET'te materialise_due): tasks/resources.py:92,226 ve tasks/views.py:142; ayrıca `generate_tasks` komutu cron için var (README.md:1923) ama zamanlayıcı tanımı yok (37-8). GET tabanlı üretim bu eksikliği örtüyor; cron kurulmazsa tek tetikleyici sayfa ziyareti.
- 34-13 (FAILED_AT süreç-yereli): monitoring/read.py:86; çoklu worker'da her süreç ayrı log throttle'ı tutar, 33-6 ile birleşir.

## Önem derecesi önerileri
- 33-2: medium -> high (güvensiz SECRET_KEY + DEBUG varsayılanı + güvenlik başlıkları yok birlikte; dağıtımda yanlışlıkla açık kalma riski).
- 33-1: high doğru; 33-4 ile birlikte "gözlemlenebilirlik yok" tek kök neden.
- 35-23: low -> medium (STATIC_ROOT/collectstatic hattı olmadan DEBUG=False çalışan uygulama statik dosya sunamaz).

## Yeni bulgular
Bkz. şema çıktısı (37-X1 ... 37-X3).

## Komşulara sorular
- security/authn: SECURE_*, SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, HSTS ayarları hiç yok (config/ grep boş); bunu kendi raporunuzda ele aldınız mı?
- performance (35): CACHES yokken çok-worker dağıtımda 35-1/35-2 çözümü için hangi önbellek (Redis/DB) öneriliyor? Compose'ta yok.
- concurrency (34): materialise_due'nun GET'ten cron'a taşınması serileştirme kilidini (34-5) nasıl etkiler?
- state-machines (48): 48-15 PDF yeniden deneme için yönetim komutu/iş kuyruğu gerekirse, zamanlayıcı altyapısı yok; beklenen mekanizma nedir?
