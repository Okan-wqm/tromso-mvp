# Capraz konusma: biz-health (20)

Komsu bulgular saglik alani acisindan sorgulandi. Yalnizca kodda dogrulananlar yazildi.

## Dogrulananlar
- 21-2: farm/handling/check.py:26-29 ve farm/stock/services.py:35-41 belgeleri "Nothing is blocked (owner decision)" diyor. Davranis dogru, ancak bilincli sahip karari; onem medium -> low/info (tasarim karari, ayri yetki onerisi urun karari).
- 22-3: farm/water/degree_days.py:125-133 negatif gunluk degeri toplama katiyor; farm/health/withdrawal.py:196-215 projeksiyonda mean<=0 reddediliyor. Tutarsizlik dogru (arinma suresini uzatir, muhafazakar yonde).
- 22-15: reports/compute/lice.py:52-73 sitedeki tum 3 m derinlik noktalarinin ornek ortalamasini aliyor, unite turu/su tipi filtresi yok. Dogru; arinma hesabi ise birim gunluk ortalamasinin en dusugunu kullaniyor (iki farkli sicaklik tanimi).
- 19-12: yemleme servisinde tibbi yem engeli yok; handling check de yalnizca harvest icin arinma sorar (WITHDRAWAL_KIND = HARVEST). Dogru, 20-15 ile iliskili.

## Yeni bulgu ozeti
- 20-X1: Ayni batch icin uc farkli sicaklik tanimi (derece-gun: birim gunluk ortalamasinin minimumu; bit raporu: ornek ortalamasi; su kartlari: son deger).
