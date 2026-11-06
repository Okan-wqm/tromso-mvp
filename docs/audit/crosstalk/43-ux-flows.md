# 43 ux-flows: komsu bulgulara capraz denetim

Dogrulanan: 41-10/41-11 (templates/crud ve frontend/components.ts:317-366), 42-3, 42-18, 44-16, 42-2, 41-16, 50-12/38-11.

## Onaylar
- 41-11, 38-11, 50-12 (ayni kusur): frontend/components.ts:333-366 fetch try/catch yok, yalniz 403 ozel; 404/500 HTML govdesi dialoga basilir. Bizim 43-5 ile ayni.
- 41-10: components.ts:320 `new FormData(form)` gonderen dugmeyi icermez.
- 42-18: templates/crud/confirm_delete.html:48 "restored from the admin" sabit; = 43-10.
- 44-16: templates/app_base.html:99 flash-list role="status", hata varyanti da; = 43-14.
- 42-3: confirm_delete.html:52 ve crud/form.html:22 request.path, water_void.html:20 get_full_path; modal icinde sorgu dizgesi (next) kaybi riski.
- 42-2: water_void.html stock_void.html kopyasi; void diyaloglari geri alinamazligi soylemiyor (43-11) iki yerde duzeltilmeli.
- 41-16: data-autosubmit components.ts:135 ve poll.ts:345 farkli yorumlaniyor.

## Yeni bulgular
Bkz. StructuredOutput new_findings (43-X1..X3).
