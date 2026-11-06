# 33 error-handling: komsu bulgu capraz denetimi

## Dogrulananlar
- 34-3: core/admin.py:40-47 yalniz ValidationError yakaliyor; softdelete.restore kaynakli IntegrityError admin eyleminde 500 olur.
- 34-4: tasks/resources.py:92 ve :226 filter_list icinde services.materialise_due() try/except olmadan cagriliyor; hata liste sayfasini 500 yapar.
- 34-10: messaging/services.py:233 Conversation...get() DoesNotExist yakalamiyor (PermissionDenied yolu yalniz Participant icin, :234-236).

## Itirazlar / duzeltmeler
- 31-11: "hatalar yutuluyor" kismen yanlis. farm/placements.py:49-50 logger.exception ile kayit ediyor (sessiz degil); throttle yok (bkz 33-7). monitoring/read.py:272 `except Exception` fail-open, kayit durumu 33-4 ile ilgili.

## Yeni bulgular
- 33-X1: GET icinde yazma yapan materialise_due icin hata izolasyonu yok (34-4 ile birlestirilmeli; hata yonetimi acisindan fail-closed 500).
- 33-X2: messaging.post tutarsiz hata sozlesmesi: silinmis konusmada DoesNotExist (500), silinmis katilimcida PermissionDenied (403).
- 33-X3: core/admin.py restore ValidationError'i mesajla, IntegrityError'i hic ele aliyor; kardes hata sozlesmesi tutarsiz.

## Komsulara sorular
- frontend/components.ts modal load(): fetch hatasi kullaniciya gosteriliyor mu (44-6)? Hata yonetimi ile birlikte ele alin.
- performance: knowledge/extraction.py:69 `except Exception` sonucu DB'ye yaziliyor (33-8); sayfa siniri eklenirse hata mesaji nasil gosterilecek?
