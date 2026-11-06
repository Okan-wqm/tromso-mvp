# Çapraz Değerlendirme: data-read (09) uzmanı

Kapsam: data-write (10), data-modify (11), backup-restore (12), audit-log (13), migrations (14), biz-health (20), performance (35). Salt-okunur inceleme.

## Doğrulananlar
- 10-1: core/crud.py:724 ve :815 `select_for_update(...).get(pk=pk)` DoesNotExist yakalamıyor. Doğrulandı. 11-6 aynı bulgunun kopyası.
- 10-2: core/crud.py içinde IntegrityError yalnızca :687'de (CreateView) yakalanıyor; UpdateView/RowListView'da yok. Doğrulandı.
- 10-5 / 13-10: tasks/resources.py:92 ve :226 GET okumasında `services.materialise_due()` çağırıyor. Doğrulandı (okuma yolunda yazma).
- 13-11 / 09-5: core/dbgrid.py içinde `audit` / `restrict` geçmiyor; core/views.py:38 ise `audit.readable` kullanıyor. Görüntüleyici kısıtı atlıyor. Doğrulandı.
- 35-2: messaging/read.py:23-28 `unread_total` Message tablosundan Exists ile sayıyor. Doğrulandı.
- 35-4: farm/water/views.py:215 `parse_date(request.GET.get(name,''))` geçersiz ama biçimli tarihte ValueError verir (09-13 ile aynı kök).
- 35-9 / 35-10: 09-1, 09-2, 09-10 ile aynı; core/dbgrid.py EXPORT_LIMIT=50_000 (09-3) ayrıca performans raporunda yok.
- 10-14 / 13-9 / 11-12: mark_read GET'te yazıyor (messaging/views.py:76, :116) — 09-17 ile ilişkili, bu GET-yazma sınıfı 10-5 ile birleştirilmeli.

## Önem derecesi
- 10-5 medium/high: okuma-yolu yazma, 09-17 ile birlikte tek "GET ile yazma" bulgusu olarak ele alınmalı; kendi başına yeterli.
- 35-9 medium kalabilir; 09-7 (readable boşsa tüm sütunlar) ayrı güvenlik boyutu taşıdığı için performans raporunda yer almıyor.
- 11-6, 10-1 aynı kusur: iki farklı önem (low/medium) verilmiş; medium'a hizalanmalı.

## Yeni bulgular
Bkz. StructuredOutput: 09-X1 (sayfa/tarih parametre ayrıştırma sınıfı tüm uygulamada tutarsız), 09-X2 (GET-yazma sınıfı birleştirme), 09-X3 (görüntüleyici silinmiş satırları ve audit.restrict'i bypass; geri alma kaynağı olarak da sızdırır).

## Sorular
- data-write: GET ile yazma (materialise_due, mark_read) için ortak politika var mı?
- audit-log: restrict kapsamını görüntüleyiciye taşırken tür eşlemesi nereden alınacak?
- performance: 35-9 ölçümü EXPLAIN ile yapıldı mı?
- backup-restore: görüntüleyici "only deleted" modu geri alma için resmi yol mu?
