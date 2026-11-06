# 22 biz-water - capraz degerlendirme

## Dogrulananlar
- 35-4 (medium dogru): farm/water/views.py:226-227 `read.history(list(samples))` tum pencereyi degerlendirir, Paginator (231) sonra keser; alerts filtresi de bellekte.
- 35-21 (dogru, low): farm/water/read.py:377-390 her nokta/slot icin ArrayAgg('id') ile 30 gunluk pencere idleri toplanir.
- 21-13 (kismen): kapasite kontrolu su kimyasi ile ilgisiz; degerlendirilmedi.

## Yeni bulgu
- 22-X1: reports/compute/lice.py:63-73 deniz sicakligi ornek ortalamasi; farm/health/withdrawal.py derece-gun sicakligi birimin gunluk ortalamasindan (farm/water/degree_days.py) gelir. Iki ayri sicaklik tanimi ayni fiziksel nicelik icin (rapor: 3 m derinlik noktalari ortalamasi; arinma: batch gunluk ortalamasi). Tutarsizlik 20-16/22-15 ile iliskili. confidence=low.

## Sorular
- feeding/19-1: tek sicaklik sutunlu tablo hangi sicakligi kullaniyor, su analizinden mi? 
- health/20-4: arinma icin sicaklik duzeltmesi anlik hesaplandigi icin su sicakligi duzeltilince eski tedavi bitisi degisiyor mu?
