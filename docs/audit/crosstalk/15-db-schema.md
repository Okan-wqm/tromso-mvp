# 15 db-schema: komşu bulguların çapraz sorgulaması

## Doğrulananlar
- 13-1 / 15-1: audit_log yalnızca satır düzeyi trigger'a dayanıyor (core/models.py:154-157 docstring).
- 13-15: core/models.py:180 entity_type max_length=50 (şema tarafı doğru).
- 13-17 / 09-10: audit_log üzerinde created_at, entity_type ve (entity_type, entity_id) indeksleri var (core/models.py:171,180,192); entity_type tek indeksi (entity_type,entity_id) ile çakışıyor (15-2).
- 10-2 / 10-13: unique kısıtlar (ör. entry_key unique, tasks/models.py:193,363) DB'de var; IntegrityError yakalanmaması uygulama katmanı sorunu, şema doğru.
- 12-10 / 13-4: reports/services.py reopen() DueClosure'ı hard delete ediyor, audit satırı değer içermiyor.
- 11-2: Task.planned() (tasks/models.py:420-430) kilit/select_for_update içermiyor.

## Reddedilen / nüans
- 38-2 / 38-3: tasks/models.py:193 ve :363 entry_key UUID unique var (görev notu ve görev için); mesaj idempotansı ayrı model. Şema desteği mevcut, eksik uygulama katmanında.

## Yeni bulgular
Bkz. StructuredOutput new_findings (15-X1 ... ).
