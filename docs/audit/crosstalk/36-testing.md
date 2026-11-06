# 36 testing - komsu uzmanlara capraz degerlendirme

Salt-okunur dogrulama; kod degistirilmedi.

## Dogrulamalar
- 13-1 (kismen): audit log tek-satir UPDATE korumasi test ediliyor (core/tests.py:132) ama TRUNCATE/DROP TRIGGER testi yok. monitoring/tests/test_templates_db.py:121-125 TRUNCATE'in tetikleyiciyi atladigini testte fiilen kullaniyor.
- 33-2: config/settings.py:28 DEBUG varsayilan '1'; core/tests_settings.py bunu denetlemiyor, 33-1 icin LOGGING tanimi yok (settings.py'de LOGGING gecmiyor) - dolayisiyla log testi de yok.
- 33-3: handler400/403/404/500 hicbir .py dosyasinda yok (grep bos); test de yok.
- 32-13 / 31-9: core test adlandirmasi tutarsiz (tests.py, tests_*.py, test_*.py) - 36-12 ile ayni.
- 35-6: check_withdrawal yalniz tek basit "lists the fish held" testine sahip (farm/tests/test_health.py:844); olcek/sorgu sayisi testi yok.
- 34-4: materialise_due testi yalniz tasks/tests/test_series.py icinde; GET'te yazma ve hata izolasyonu icin ayri test yok.
- 35: assertNumQueries yalniz 5 yerde (monitoring ve core/tests.py:214); performans bulgulari regresyona karsi korunmuyor (36-4).

## Onem derecesi
- 33-1 high ve 33-4 high makul; test acigi nedeniyle ek risk. 13-1 medium uygun.

## Yeni bulgular
- 36-X1: Denetim-log degistirilemezligi icin TRUNCATE/DROP TRIGGER negatif testi yok; mevcut test TRUNCATE'i normal arac sayiyor.
- 36-X2: Hata isleyici/LOGGING/DEBUG varsayilani icin test yok (33-1..33-3).
- 36-X3: Giris/cikis/sifre olaylarinin loglanmamasi (13-3) icin ne test ne beklenen davranis tanimli.

## Komsulara sorular
- error-handling: monitoring.read.cards (33-4) hata dalini test eden bir test var mi, yoksa yalniz mutlu yol mu? (test_read.py yalniz basari yolunu gosteriyor.)
- performance: 35-1/35-3 icin olcek/sorgu sayisi esigi hangi degerle test edilmeli?
- concurrency: yaris bulgulari (34-1, 34-3) icin hangi test altyapisi (TransactionTestCase/thread) onerirsiniz? Su an tek-DB testi var (36-13).
