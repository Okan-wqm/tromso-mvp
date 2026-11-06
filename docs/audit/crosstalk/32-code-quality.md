# 32 code-quality capraz denetim

## Dogrulananlar
- 33-13: hr/views.py:80-81 ve 114-115 `except PermissionDenied: raise` anlamsiz (kod kalitesi acisindan olu kod).
- 35-6: farm/management/commands/check_withdrawal.py:16 `read.stock_of(units)` her eleman icin comprehension icinde cagriliyor; tek seferlik degiskene alinmali.
- 25-10: hr/leave.py:57-64 `used` her talep icin `charged_by_year` cagiriyor (N+1 / dongude hesap).
- 25-16: hr/services.py:142-147 `holiday_days` yalnizca `leave.holidays_for` icin ince bir sarmal; gereksiz katman.
- 36-12: core test dosya adlandirmasi tutarsiz; 32-13 ile ayni bulgu.
- 31-4: genel yardimcilar farm altinda; 32-15 (ayni adli yardimcilarin cok app'te tekrari) ile ayni kok neden.

## Yeni bulgular
- 32-X1: `_day` ve `_days` adlari farkli anlamlarla (tarih ayristirici vs gun listesi) farkli modullerde (hr/scope.py:122, experiments/read.py:297, farm/health/withdrawal.py:63).
- 32-X2: hr/services.py'de `CLEAR = object()` sentinel'i; `shift is CLEAR` kontrolleri dagilmis, 25-1 hatasinin kod-kalitesi yonu.

## Sorular
- architecture: ortak `_day/_back/_is_uuid` icin core'da tek yardimci modul onerir misiniz (31-4 ile birlikte)?
- error-handling: 33-13 ile 32-12 birlikte tek duzeltmede ele alinabilir mi?
