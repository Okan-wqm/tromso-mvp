# Çapraz görüş: migrations (14)

## Doğrulananlar
- 12-13: farm/migrations/0023_reports_fields.py:45 ve :91 `RunPython.noop` ile geri alıyor (14-4 ile aynı bulgu).
- 13-1 (kısmen): core/migrations/0003_audit_log_append_only.py yalnızca `BEFORE UPDATE OR DELETE ... FOR EACH ROW` trigger'ı kuruyor; TRUNCATE ve DROP TRIGGER korunmuyor. Ayrıca bu trigger, audit_log üzerindeki herhangi bir sonraki veri migration'ını (UPDATE) engeller (14-6).
- 13-15: core/migrations/0002_audit_log.py:26 entity_type max_length=50 (entity_label 255).
- 12-12/12-14: hypertable ve frozen trigger geri yükleme adımları belgesiz; 14-7/14-13/14-16 ile örtüşür.

## Önem derecesi
- 13-15 (low) uygun; sütun genişletme migration'ı audit_log üzerinde tam yeniden yazım gerektirmez (varchar genişletme) ama trigger'a takılmaz, risk düşük.
- 13-1 medium makul; migration açısından asıl risk audit_log'a yönelik gelecekteki UPDATE'lerin trigger'a takılmasıdır.

## Yeni bulgular
- 14-X1 (low): audit_log migration'ları 0006/0007 CHECK/index ekliyor; severity için chk_audit_log_severity CHECK var ancak action seçenekleri (void) için DB CHECK yok, yalnızca Django choices; 13-7 critical akışı ile tutarlı değil.

## Komşulara sorular
- data-modify/backup-restore: restore/rollback akışlarında migration geri alma (noop) dikkate alındı mı?
- audit-log: audit_log'a ileride ALTER/UPDATE gerekirse trigger kaldırma/yeniden kurma prosedürü nedir?
