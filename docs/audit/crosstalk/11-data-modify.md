# Çapraz değerlendirme: data-modify (11)

Kapsam: 09 data-read, 10 data-write, 12 backup-restore, 13 audit-log, 14 migrations, 22 biz-water, 49 permissions-matrix bulgularının değiştirme/silme/geri getirme açısından incelenmesi.

## Doğrulananlar
- 10-1 (core/crud.py:724, 815): kilit altı `.get(pk=pk)` DoesNotExist yakalamıyor. Kendi 11-6 ile aynı. Doğrulandı.
- 10-2: UpdateView/RowListView IntegrityError yakalamıyor (crud.py:715-757 içinde atomic blok yalnızca version kontrolü). Doğrulandı.
- 10-6: `execute()` (core/softdelete.py:98-171) plan ile uygulama arasında kilit almıyor. Kendi 11-1 ile örtüşür.
- 10-7: RowList sil-yeniden-yaz, kendi 11-9 ile aynı.
- 10-8: Kullanıcı/rol sürümsüz, rol silme etkisiz onay; kendi 11-4/11-5.
- 12-5, 12-6: `restore()` (softdelete.py:168-203) yalnızca kaydın kendisini getirir, doküman metni de bunu söyler ("Only the record itself returns"); detach geri alınmaz. Kendi 11-3/11-8.
- 12-15: restore kilitsiz, M2M yok. Kendi 11-7.
- 12-4 / 13-16: belge dosyası silme `transaction.on_commit` ile (knowledge/models/document.py:239-241); rollback güvenli, ama commit sonrası geri dönüş yok. Doğrulandı; yetim dosya riski (11-15) ayrı yönde.
- 13-4 / 12-10: hard delete log'a değersiz düşer; kendi 11-2/11-5 ile aynı kök.
- 13-9: mesaj silme log dışı, kendi 11-12.
- 09-17: GET ile okundu işaretçisi yazımı, 10-5 ile aynı tür "GET yazar" sorunu.

## Reddedilen / nüanslı
- 10-4 (checklist TOCTOU): önem medium kalabilir ama düzeltme UpdateView'daki kilit içinde yeniden kontrol; form-düzeyi kontrol kilit öncesi olduğu için doğru gözlem. Reddedilmiyor.
- 12-11 (ATOMIC_REQUESTS yok): kritik değil; yazma yolları kendi `transaction.atomic()` blokları kullanıyor, low doğru.

## Önem derecesi önerileri
- 12-5 ve 12-6: medium yerine low/medium olabilir; kod davranışı belgeli ve tasarım gereği. Ancak çöp kutusu arayüzü olmadığı (12-16) için pratik etki yüksek; medium tutulabilir.
- 10-1/10-2: 500 hatası veri bozmaz; medium makul, 10-2 ile birleşik low/medium de savunulur.
- 13-4: medium; asıl sorun hard delete'in kendisi (11-2, 11-5) olduğundan veri kaybı açısından 12-10 ile birleştirilmeli.

## Yeni bulgular
Bkz. StructuredOutput 11-X1 ... 11-X4.

## Komşulara sorular
- 10: UpdateView'daki IntegrityError yakalama eklenince restore() yolundaki full_clean/save çakışmaları da aynı yardımcıdan geçecek mi?
- 12: Çöp kutusu arayüzü planlanırsa cascade ile silinenlerin toplu geri getirilmesi için deleted_at eşleşmesi kullanılabilir mi (aynı deleted_at/deleted_by)?
- 13: restore ve soft delete log satırlarına "önceki sürüm" alanı eklenmesini, hard delete için snapshot ile birlikte düşünüyor musunuz?
- 14: Veri migration'larında is_deleted kayıtları bilinçli mi dışlanıyor (canlı manager)?
- 49: Employees Create ölü izni (49-1) ve rol silme (11-5) aynı yetki modelini mi paylaşıyor; rol silme hangi izne bağlı?
- 09: 09-17 ile 10-5 tek bulgu olarak birleştirilebilir mi?
