# 38 api-contracts çapraz değerlendirme

## Doğrulananlar
- 33-3 (özel 400/403/404/500 yok): config/ altında handler40x/handler50x yok (grep boş). Doğrulandı. İlgili 49-7 ile aynı bulgu.
- 33-12: monitoring/views.py:188,193 sabit İngilizce JSON hata, hr/views.py:63,73 gövdesiz 400. Doğrulandı; 38-12 ile birleşir.
- 34-4: tasks/resources.py:92,226 ve tasks/views.py:142 GET içinde materialise_due. Doğrulandı; 38-9 ile aynı kök, sözleşme açısından GET güvenli olmalı.
- 33-9/33-10: sunucu hataları sessiz; 38-11/38-12 ile örtüşüyor.

## Önem derecesi
- 33-1 high/medium: API sözleşmesi açısından 500'lerin kaydedilmemesi orta olarak değerlendirilebilir (yalnız DEBUG=False için).

## Yeni bulgu
- 38-X1: monitoring önizleme JSON uçları (413/400 JsonResponse) ile hr 400 (gövdesiz) aynı uygulamada iki farklı hata zarfı kullanıyor; 33-12 yalnız dil tarafını yakalıyor, biçim tutarsızlığı ayrı.

## Sorular
- error-handling: 33-3 şablonları eklenirse JSON/X-Modal isteklerine HTML 403/404 dönmesi nasıl engellenecek?
- concurrency: 34-4 materialise_due GET'ten çıkarılırsa tetikleyici ne olacak (cron tanımsız)?
