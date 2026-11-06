# 07 deps-supply: komşu bulgu çapraz denetimi

## Onaylananlar
- 05-15 (requirements hash'siz, pip-audit yok): requirements.txt tam sabit `==` içeriyor ama hash yok. Bkz. 07-1, 07-3. Onay.
- 05-5 (Dockerfile/CI yok): repoda Dockerfile yok, yalnızca docker-compose.yml. Bkz. 07-10. Onay.
- 05-3 / 07-9: docker-compose.yml:14 `ports: ["${DB_PORT:-5433}:5432"]` tüm arayüzlere bağlar, parola varsayılanı `balik`. Onay.
- 17-10 (Timescale yalnızca dev compose): docker-compose.yml:4 `timescale/timescaledb:2.17.2-pg17`, digest yok. Onay; 07-8 ile ilişkili.
- 04-5 (pypdf sınırsız ayrıştırma): requirements.txt yorumu pypdf==6.21.4 için "güncel tut" diyor; süreç yok (07-4). Onay.
- 01-2 / 05-1 / 05-2: config/settings.py:25 ve :28 doğrulandı (sabit SECRET_KEY, DEBUG varsayılanı '1').

## Önem derecesi notları
- 05-7 (ALLOWED_HOSTS strip yok) medium görünüyor; settings.py:30 `if h` filtresi var, DEBUG=0 iken yanlış yapılandırma fail-closed olur (400). Önerilen: low.
- 05-15 info yerine low olmalı: hash/kilit eksikliği tedarik zinciri riski.

## Yeni bulgular
- 07-X1 (medium): Kök dizinde pyproject/.python-version yok, Python ve Node sürümü bildirilmiyor; Django 6.1 ve psycopg 3.3 için minimum Python sürümü belirsiz. 17-10 ve 05-5 üretim ortamı belgesizliğini dolaylı doğruluyor.
- 07-X2 (low): Üretim gereksinimi olan TimescaleDB uzantısı (core/migrations/0001_timescaledb.py) ile dev imajı sürümü (2.17.2) birbirine bağlı belgelenmemiş; imaj sürümü yükseltilirse migration davranışı değişebilir (17-11 ile ilgili).
- 07-X3 (low): requirements.txt'te `psycopg-binary` üretimde önerilmez (libpq'yu paketler, OS güvenlik yamaları dışında kalır); 05/01 uzmanları üretim sertleştirmesinde bunu değerlendirmedi.
- 07-X4 (info): Güvenlik uzmanlarının önerdiği "SECRET_KEY zorunlu yap, .env.example ekle" düzeltmeleri bağımlılık eklemeden yapılabilir; yeni paket (django-axes, django-csp vb.) önerilirse THIRD_PARTY.md ve requirements güncellemesi gerekir (07-5).

## Sorular
- authn (01): brute force için üçüncü taraf paket mi, yerleşik mi önerilir? Lisans/sabitleme etkisi var.
- secrets-config (05): Dockerfile/CI eklenecekse digest sabitleme ve pip-audit kapsamda mı?
- csrf-xss (03): PDF inline sunumu için pypdf güncelleme süreci tanımlı mı?
