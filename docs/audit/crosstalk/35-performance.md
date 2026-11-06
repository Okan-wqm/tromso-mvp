# 35 performance - komsu bulgu capraz denetimi

## Dogrulananlar
- 06-2 (35-12 ile ayni kok): knowledge/models/document.py:224 save() icinde extraction.read_pdf cagriliyor; knowledge/extraction.py:61-67 sayfa siniri yok, tum sayfalar bellekte listeleniyor; bulk_create (satir 235-238) tek seferde. CRUD islemi atomic ise acik islem suresince.
- 34-4: tasks/resources.py:92 ve :226 GET icinde materialise_due(); tasks/services.py:257-261 her cagrida clocks() + TaskSeries sorgusu. 35-5 ile ayni aile (okuma yolunda yazma/hesap).
- 34-1: tasks/services.py:267 withdraw her task icin ayri record_delete + delete (satir basi sorgu); N+1 boyutu da var.
- 34-11: DB_CONN_MAX_AGE varsayilan 0 (config/settings.py:121); 35-15 ile ayni, performans acisindan da dogru.
- 32-6: reports/integrity.py:45 dongu icinde EscapeRecord.all_objects.get (N+1) dogru.

## Onem derecesi
- 34-4 medium yerine performans acisindan medium kalmali, ancak yazma+kilit nedeniyle high adayi (her liste GET'inde).

## Yeni bulgular
Bkz. StructuredOutput 35-X1..X3.

## Sorular
- concurrency: materialise_due her GET'te cagriliyor; cron/komut ile degistirilebilir mi?
- file-upload: PDF cikarimi icin sayfa ust siniri onerilecekse knowledge/extraction.py'de hangi deger?
- testing: sorgu butcesi testi eklenirse hangi sayfalar oncelikli?
