# Çapraz görüş: audit-log uzmanı (13)

Kapsam: data-read (09), data-write (10), data-modify (11), backup-restore (12), migrations (14), biz-tasks (24).

## Doğrulananlar
- 11-12 / 10-14: `messaging/services.py:266-275` delete_message audit.record çağırmıyor; yalnız is_deleted/deleted_by/deleted_at yazar (13-9 ile aynı).
- 12-7 / 12-10 / 24-6: `reports/services.py:135-138`, `tasks/services.py:265-271` hard delete öncesi audit.record_delete çağrılıyor; `core/audit.py:175-176` değer geçirmiyor, yani silinen içerik log'da yok (13-4).
- 09-5 / 09-21 / 09-6: restrict ve readable kapsamı görüntüleyicide/form geçmişinde uygulanmıyor, okumalar loglanmıyor (13-11 ile örtüşür).
- 10-5 / 24-3 / 09-17: GET'te yazma doğru; audit açısından ek boyut: `tasks/services.py:250` audit.record_create(None, ...) kaydı 'system' adına yazar, tetikleyen gerçek okuyucu kaybolur.
- 11-14: `experiments/services.py:199-200` _touch queryset.update() ile yazar; version artmaz. Log ayrı yazılıyor ama change_token/revision (13-14) bu yazmaları görmez.
- 12-8 / 14-6: saklama politikası yok, audit_log tablosunda tam tarama/trigger engeli riski.

## Önem derecesi
- 12-7 (medium): log değerleri görüntü metni; geri alma kaynağı olamaz. Tasarım gereği, low/info olabilir.
- 12-11 (low): 13-8 ile birleştirilmeli; audit ile değişiklik atomikliği tek risk noktası, medium olabilir.
- 09-6 (info): KVKK bağlamında okuma izlenmemesi 13-12 ile birlikte düşünülmeli.

## Yeni bulgular
Bkz. yapılandırılmış çıktı (13-X1 ... 13-X4).

## Komşulara sorular
- 10: UpdateView IntegrityError/DoesNotExist 500'lerinde audit satırı ve değişiklik aynı transaction'da geri alınıyor mu?
- 11: restore (core/admin.py) audit'e RESTORE yazıyor; cascade ile birlikte silinen çocuklar için ayrı satır var mı?
- 12: audit_log'un yedeklenip geri yüklenmesinde append-only trigger nasıl atlanacak?
- 14: Veri migration'ları (reports 0005 vb.) audit satırlarını tetikleyiciyi atlayarak mı yazıyor?
- 24: withdraw bir transaction içinde mi çağrılıyor; yarım kalırsa audit DELETE satırları gerçekte silinmemiş görev için kalır mı?
