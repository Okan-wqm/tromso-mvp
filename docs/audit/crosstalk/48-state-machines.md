# 48 state-machines - capraz degerlendirme

Komsu bulgular (19, 20, 21, 22, 23, 13) durum makinesi acisindan sorgulandi.

## Dogrulananlar
- 23-1 (kismen): inventory/services.py:176-192 tedarikci icin yalnizca is_deleted ve supplies kategorisini kontrol ediyor; tedarikci durumu (askida/engelli) kontrol edilmiyor. Bu, 48-10 (durum alanlari operasyonda uygulanmiyor) ile ayni kok neden.
- 19-7: services.set_last_day (farm/feeding/assignments.py:80-82) uzatmayi reddediyor, formun clean_valid_until'i (farm/forms/feeding_protocol.py:374-381) yalnizca alt siniri kontrol ediyor; form-servis kural kaymasi.
- 20-6: farm/stock/services.py:507-512 voided() 31 gunden eski kaydi iptal ettirmiyor; void_treatment (health/services.py:245) bu kapidan gecer. Iptal yolu kapanan bir durum olusuyor: arinma suruyor ama yanlis tedavi geri alinamiyor (terminal-benzeri kilit).
- 13-4/13-5 ile 48-7: soft delete/restore durum gecisleri log'da icerik tasimiyor; durum geri donusleri izlenemiyor.

## Onem derecesi
- 21-6 (void kapasite kontrolu yok): void, durum makinesinde geri donus; kapasite ihlaline yol acabildigi icin low yerine medium dusunulebilir.

## Yeni bulgular
- 48-X1 (medium): Void penceresi (STOCK_BACKDATE_DAYS) 31 gun sonra kayit "kilitli" duruma geciyor; duzeltme yolu yok (20-6, 21-1, 21-5 ile birlesince hatali eski kayit hic duzeltilemiyor).
- 48-X2 (low): Form ve servis katmaninda farkli gecis kurallari (19-7); 48-5 ile ayni desen.
- 48-X3 (low): Tedarikci/lokasyon durumlari kontrol asimetrik: lokasyon status kontrol ediliyor (inventory/services.py:183), tedarikci edilmiyor.

## Sorular
- biz-inventory: Supplier modelinde durum alani var mi, hangi gecisler tanimli?
- biz-stock-prod: 31 gunden eski hatali kayit icin yonetici duzeltme yolu planlandi mi?
- audit-log: RESTORE satirlari hangi onceki durumu kaydediyor?
