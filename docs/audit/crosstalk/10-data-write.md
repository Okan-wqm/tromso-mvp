# Çapraz değerlendirme: data-write (10)

Kapsam: data-read (09), data-modify (11), backup-restore (12), audit-log (13), migrations (14), biz-stock-prod (21), templates (42). Kanıtlar kodda doğrulandı; testler çalıştırılmadı.

## Doğrulananlar
- 09-17 / 13-10 (GET'in yazma yapması): `messaging/views.py:66-77` GET ile `services.mark_read` çağırıyor; `tasks/services.py:257-262` `materialise_due()` tasks/views.py:142 ve tasks/resources.py:92,226 üzerinden GET'te çalışıyor. Bu, 10-5 ile aynı kök neden (GET yazması).
- 09-16: `messaging/views.py:72,74` `before.isdigit()` + `int()`; '²' gibi karakterlerde ValueError (500). 10-14 ile aynı alan.
- 09-13: `farm/water/views.py:214-216` `parse_date`, '2026-13-45' için ValueError fırlatır; 500.
- 11-1, 11-2, 11-6, 11-7, 11-9: bunlar 10-1, 10-6, 10-7, 10-13 ile örtüşüyor; birleştirilmeli.
- 11-7 / 12-15: `core/softdelete.py:189-203` restore kilitsiz; `select_for_update` yok, sürüm kontrolü yok.
- 11-5 / 13-4: `core/crud.py:781-785` rol silme hard delete; yazma tarafında onay ekranı etkilenen kullanıcıları göstermiyor (10-8).
- 12-5: `restore` docstring'i "Only the record itself returns" diyor; kod bunu doğruluyor.

## Önem derecesi
- 12-15 low kalabilir; ancak 11-7 ile birleştirilip tek bulgu olarak medium düşünülebilir (kilitsiz restore + yalnızca doğrudan FK kontrolü).
- 09-17 low yerinde; yazma nedeniyle 10-5 ile aynı sınıf.

## Yeni bulgular
Bkz. yapılandırılmış çıktı (10-X1 ... 10-X3).

## Komşulara sorular
- 11: restore() için `version` karşılaştırması neden yok; admin eylemi `core/admin.py` ile eşzamanlı düzenleme nasıl korunuyor?
- 13: GET yolunda yazılan 'system' audit satırı (materialise) için aynı transaction kuralı denetlendi mi?
- 21: servis katmanı doğrulama eksikliği (21-10) yazma yolunda import/seed komutlarını da kapsıyor mu?
- 42: form action `request.path` vs `get_full_path` (42-3) POST sonrası filtre/sayfa bağlamını kaybettiriyor mu?
