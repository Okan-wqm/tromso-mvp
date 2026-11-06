# 29 biz-messaging - capraz denetim

## Dogrulamalar
- [42-3] kismen: templates/messaging/confirm.html:14 action'da request.get_full_path kullaniyor; mesajlasma tarafinda zararsiz (ayni sayfa), tutarsizlik gercek.
- [36-7] kismen: messaging/tests/test_pages.py:57-65 sabit URL listesiyle 403 sinar; hr gibi get_resolver ile tum URL taramasi yok, yeni URL eklenince atlanabilir.
- [36-4] dogrulandi: messaging rozet/liste sorgu butcesi testi yok (29-14 ile ilgili).

## Yeni bulgular
- 29-X1 (low): messaging icin otomatik URL-yetki taramasi yok (36-7 mesajlasmayi da kapsiyor).
- 29-X2 (info): messaging/confirm.html get_full_path ile ?before= gibi sorgu parametrelerini POST action'ina tasir; 29-5 ile birlesince hatali parametre POST'ta da 500 verebilir olasi, dusuk guven.
- 29-X3 (low): feeding/health/stock uyarilari yalniz view katmaninda; mesajlasma da ayni deseni izliyor (hiz siniri/asistan denetimi servis disinda) - mimari tutarlilik notu.
