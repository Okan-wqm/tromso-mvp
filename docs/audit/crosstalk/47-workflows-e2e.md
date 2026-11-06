# 47 workflows-e2e: komşu bulgu çapraz değerlendirmesi

Doğrulananlar: 20-2 (farm/health/services.py:97-116 neden-ilaç eşlemesi yok; reports/compute/lice.py:44-49 yalnız reason=SEA_LICE), 21-3 (reports/compute/slaughter.py:37-63 unplanned_of yalnız hafta içi plan kalemlerinin operation_id'sini dışlıyor), 19-10 ve 23-15 (inventory/read.py:59-67 site__isnull=False süzgeci; inventory/fold.py:237-252 çekiş yalnız site bazlı), 21-2 (47-2 ile aynı kök), 20-14 (reports/due.py:365-396; 47-10 ile ilişkili), 20-15 (farm/health/withdrawal.py:240-273 uncovered_feedings covers() ile).
Reddedilen yok. Önem değişikliği önerisi yok.

Yeni bulgu 47-X1 (low): rapor tamlığı kullanıcı bağlantılarına (tedavi nedeni, plan kalemi) bağlı; due listesi çapraz doğrulama yapmıyor.

Sorular: biz-health: tedavi nedeni ilaçtan türetilebilir mi? biz-stock-prod: planlı kalem tarihi haftayı aşınca tek rapor mu? biz-inventory: sitesiz birim yemlemesi uyarı olmalı mı?
