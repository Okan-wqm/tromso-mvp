# 42 templates: capraz degerlendirme

Kapsam: frontend-ts (41), ux-flows (43), accessibility (44), i18n (45), css-static (46), permissions-matrix (49), architecture (31). Kod degistirilmedi.

## Dogrulananlar

- 45-1: templates/inventory/void.html:6 ve templates/farm/stock_void.html:12 `get_kind_display|lower` kullaniyor; templates/farm/_unit_drawer.html:106 `get_status_display|lower` ile ucuncu bir yer (45-1 bunu saymamis). Turkce `I/i` hatasi gercek.
- 43-10: templates/crud/confirm_delete.html:47 "restored from the admin" sabit metin.
- 43-14 / 44-16: templates/app_base.html:99 ve templates/modal_base.html:13 flash listesi `role="status"`; hata etiketi (flash-error) icin ayrim yok. Ayni blok iki dosyada kopya.
- 44-2: templates/registration/_field.html icinde aria-describedby / aria-required / required yok (grep bos).
- 44-9: templates/farm/production_units.html:32,37,41 `<a aria-pressed>`; templates/hr/roster.html:21-23 dugmelerde aria-pressed gecerli (sorun yalniz a/td/tr).
- 44-14: templates/_language_switcher.html:6 `aria-label="{{ name }}"` gorunen "TR/NB" metnini ezer (Label in Name). Ayrica `next` degeri request.get_full_path (42-3 ile ayni kaynak tutarsizligi).
- 44-17: templates/monitoring/_card.html:7 `<h3>` sayfada h2 yokken (42-16 ile ayni).
- 46-9: `badge-leave-*` / `badge-state-*` siniflari templates/hr/leave_list.html:31 ve templates/hr/_board.html:21'de uretiliyor, static/css altinda hic tanim yok (grep bos).
- 46-10: templates/experiments/experiment_detail.html:31 `plain-list` kullaniyor; sinif yalniz static/css/hr.css:14'te, sablon ve crud/detail.html `extra_head` ile hr.css yuklemiyor.
- 46-4: templates/app_base.html:10 Google Fonts (42-8 ile ayni).
- 41-10: templates/experiments/_places.html:30 modal icinde dugme name/value kullanimi sablon tarafindan da dogrulanmali; sablon bu dugmeyi `data-modal` formunda gonderiyor olabilir (confidence orta, sablon tarafi okunmadi).

## Itirazlar / notlar

- 44-1, 44-12 (surukleme/cekmece): sablon tarafinda dogrulanmadi, yalniz JS/CSS ile ilgili.
- 43-4 sablon tarafi dogru yer (templates/crud/list.html), karar view'dedir; sablon yalniz `{% empty %}` ayrimi yapmiyor.

## Onem derecesi onerileri

- 46-9 low kalabilir ama rozet bilgisi renksiz kalir; metin etiketi var oldugu icin bilgi kaybi yok.
- 43-14/44-16 low yerine medium dusunulebilir: hata flash'i her sayfada ve modalda status oluyor, iki sablonda kopya.

## Yeni bulgular

Bkz. StructuredOutput new_findings (42-X1 ... 42-X4).

## Sorular

- frontend-ts: Modal.load donen HTML'de `data-modal-close` ve baslik bekliyor mu? Sablonlar (stock_void.html) iptal icin `<a data-modal-close>` kullaniyor.
- css-static: .button-danger ve .confirm sinifi hangi dosyada; void sablonlari `button-inline` kullaniyor, tanim var mi?
- i18n: `|lower` yerine hangi cozum (etiket zaten kucuk harf mi) onerilir?
- accessibility: _field.html tek duzeltme noktasi; tum formlar ortak oldugu icin oncelik yuksek mi?
