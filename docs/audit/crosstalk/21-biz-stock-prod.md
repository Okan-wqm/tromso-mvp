# 21-biz-stock-prod: komsu bulgu capraz denetimi

## Onaylar
- 20-5: farm/health/services.py change_last_day yalnizca Treatment satirini kilitliyor (select_for_update of=self); void_treatment de oyle. Birim kilidi yok, hasatla yaris mumkun. Stok tarafi icin ayni desen 21-6 (void kapasite) ile tutarli.
- 20-6: farm/stock/services.py voided() entry.date < site_earliest(site) ise reddediyor; tedavi voidi de ayni yoldan geciyor, 31 gunden eski tedavi iptal edilemez. 21-1 ile ayni 31 gun duvari.
- 20-3: record_treatment (farm/health/services.py:165-215) yalnizca handling() ve _has_fish kontrol ediyor; baslangictan sonra yapilmis hasatla cakisma kontrolu yok.
- 20-7: farm/handling/check.py withdrawal uyarisi batch bazli; canli teslim yolu icin ayri dogrulama yapilmadi (low).

## Yeni bulgular
- 21-X1 (medium): Tedavi/handling ack ile hasat uyarisi ayni yetkiyle geciliyor; stok servisi (21-2) ve saglik servisi (20-3) arasinda geriye donuk tedavi-hasat tutarsizligi iki yonde de yakalanmiyor.
- 21-X2 (low): 31 gun duvari (STOCK_BACKDATE_DAYS) stok, tedavi voidi ve change_last_day icin ortak ama devir/import yolu yok (21-1, 20-6).
