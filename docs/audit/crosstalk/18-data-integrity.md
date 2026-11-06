# 18 data-integrity: komşu bulguların çapraz denetimi

Kapsam: 09 data-read, 10 data-write, 11 data-modify, 12 backup-restore, 13 audit-log, 29 biz-messaging, 20 biz-health.
Yöntem: yalnızca salt-okunur kod incelemesi; testler çalıştırılmadı. Doğrulanan kod: core/softdelete.py, messaging/models.py, messaging/services.py, messaging/views.py, farm/models/health.py, farm/health/withdrawal.py, farm/health/services.py, reports/compute/lice.py.

## Doğrulananlar

- 12-5 / 11-3 (restore yalnızca kaydın kendisini getirir): core/softdelete.py:188-203 `restore()` yalnızca `record` üzerinde `is_deleted` bayraklarını sıfırlar; `execute()` (satır 174-185) ile kaskadla silinen `plan.cascade` çocukları geri getirilmez. Veri bütünlüğü açısından ebeveyn canlı, çocuklar silinmiş kalır (parça yetim).
- 12-6 / 11-8 (SET_NULL ayırma geri alınmaz): softdelete.py:174-179 `record.detach(link, user)` bağı NULL yapar; `restore()` bu bağı geri yazmaz. Audit'te yalnızca `[before, None]` görüntü metni kalır (13-5 ile birleşir).
- 12-15 (restore kilitsiz, yalnızca doğrudan FK): softdelete.py:191-203 select_for_update yok; `version += 1` okunmuş değer üzerinden artırılır, kilitsiz.
- 20-4 (tedavi arınması anlık görüntüsüz): farm/health/withdrawal.py `Rule.of(row)` güncel `MedicineWithdrawal` satırından ve güncel `safety_margin_pct` değerinden hesaplanır; tedavi satırında hesaplanan sonuç saklanmaz. Bu, benim 18-9 (izin günleri okuma anında hesaplanır) ile aynı kalıptır: geçmiş kayıtlar referans veri değişince yeniden fiyatlanır. Kesin etki: ilaç satırı düzenlenince geçmiş tedavilerin arınma bitişi sessizce kayar.
- 20-2 (ilaç türü ile neden bağlı değil): farm/health/services.py `_check_medicine` yalnızca method/administration ve aşı/vaccination eşleşmesini denetler, SEA_LICE nedeni ile ilacın bit ilacı olması denetlenmez. reports/compute/lice.py `week_treatments` yalnızca `reason=SEA_LICE` süzer; yani yanlış nedenle girilen bit tedavisi haftalık rapordan düşer. Önem medium makul (düzenleyici rapor eksik sayımı).
- 29-3 (silinen mesaj metni DB'de kalır): messaging/models.py `Message.body` CharField; silmede yalnızca `is_deleted/deleted_at/deleted_by` ayarlanır, gövde boşaltılmaz. Veri tutarlılığı açısından da: "silinmiş" satırın içeriği duruyor, KVKK silme talebi (13-12) ile çelişir.
- 29-5 / 09-16 (isdigit ile int): messaging/views.py:72 `int(before) if before.isdigit()`; `'²'.isdigit()` True, `int('²')` ValueError. Doğrulandı. `reading_latest = not before.isdigit()` aynı satır grubunda da isdigit kullanıyor.
- 29-7 / 09-17 (GET ile okundu işaretleme): messaging/views.py:75-76 GET içinde `services.mark_read(participant, shown[-1].pk)`. Doğrulandı. Okunmuş işaretçi ileri yönlü olduğu için gösterilmeyen eski okunmamışlar da okunmuş sayılır (veri kaybı değil, sayaç sapması).
- 29-11 (iki katılımcı kuralı DB'de yok): messaging/services.py:63-67 `direct_key` yalnızca anahtar üretir; docstring "asistan" kısmı henüz uygulanmamış (29-10 ile uyumlu).
- 10-7 / 11-9 (RowList sil-yeniden-yarat): MedicineWithdrawal docstring'i satırların "toplu liste olarak kaydedildiğini, güncelleme/silme sütunu olmadığını" kendisi belirtiyor (farm/models/health.py:~195-205). Bu satırlar için pk/created_by kaybı tasarım gereği; ancak audit yalnızca liste düzeyinde kalır. Önem low doğru.

## Önem derecesi önerileri

- 11-1 (soft delete zincirinde kilitsiz tam-satır save) medium/high: katılıyorum; benim 18-4 ile aynı kök neden, birlikte ele alınmalı.
- 11-14 (info): `queryset.update()` ile version artmaması bir iyimser kilit boşluğudur, eşzamanlı düzenleyen kullanıcı üzerine yazabilir; low yapılması önerilir.
- 12-9 (void geri alınamaz, low/low): defter satırı için yanlış void'in tek çaresi yeniden giriş; stok bakiyesi açısından bu yeniden-giriş çift sayım riski taşır (18-1, 18-3 ile ilişkili). medium/low olarak yükseltilebilir.
- 20-12 (info): "units with fish now" etiketinin geçmiş haftalara güncel stokla uygulanması gerçek bir veri yanlışı (geçmiş ekranı geçmiş stoku göstermiyor); low olmalı.
- 13-14 (medium/medium): change_token'ın audit log'a bağlı olması benim "çift kaynak" kalıbımla uyumlu; medium kalabilir.
- 29-1 (yetim kanal) medium: veri bütünlüğü açısından doğru; son üye ayrılınca kanal erişilemez ama satırlar durur.

## Yeni bulgular

### 18-X1 (medium, confidence medium) Restore ebeveyni geri getirir, çocuklar silinmiş kalır; ebeveyn-çocuk durumları yarı tutarlı
core/softdelete.py:174-203. `execute()` çocukları kaskad silerken `restore()` yalnızca tek kaydı açar. Sonuç: canlı ebeveyn + silinmiş çocuk (ör. seri canlı, planlı görevler silinmiş; tasks/services.py:238-241 ile 11-3). Ek olarak `restore()` yalnızca doğrudan FK hedeflerinin silinmişliğini kontrol eder (satır 191-196), ters yönde "bu kayıtla birlikte silinenler" işaretlenmediği için hangi çocukların kaskadla silindiğini sonradan ayırt etmek mümkün değil (deleted_at eşleştirmesi dışında bir bağ alanı yok). Öneri: kaskad silmeye ortak bir silme grubu kimliği.

### 18-X2 (low, confidence medium) Silinen mesajın gövdesi duruyor ve okunmamış sayacı/zaman çizelgesi silinmişleri aynı satırdan hesaplıyor
messaging/models.py `Message.body` NOT NULL, `message_has_text` CHECK (`body ~ '\S'`) silinmiş mesajda gövdenin boşaltılmasını engelliyor: gövdeyi silerken boşaltmak mevcut CHECK nedeniyle yapılamaz, yani 29-3 düzeltmesi için kısıt da değişmelidir (ör. `is_deleted` ise muaf). Bu 29-3 önerisinin bağımlılığıdır; mevcut bulguda belirtilmemiş.

### 18-X3 (low, confidence medium) İlaç "aktif" kontrolü yalnızca yaratımda: eski tedavinin ilacı sonradan pasifleşince tedavi düzenlenemez/doğrulanamaz
farm/health/services.py `_check_medicine` (satır ~108-111): `medicine.status != ACTIVE` her çağrıda reddeder. Aynı kontrol tedavinin düzenlenmesinde de çağrılıyorsa (çağrı yerlerini tam izlemedim), pasifleşen ilaçla yapılmış eski tedavinin son günü değiştirilemez. 10-10 (pasif türdeki izin talebi düzenlenemiyor) ile aynı kalıp, iki alanda birden tutarsız. Doğrulanmadı: çağrı yolları.

### 18-X4 (low, confidence low) Arınma süresi "yukarı yuvarlama" ile gün ve derece-gün ayrı yuvarlanıyor
farm/health/withdrawal.py `Rule.of`: `used()` her iki değeri ROUND_CEILING ile tamsayıya çeker; marj sonrası derece-gün tamsayıya yuvarlanırken etiket değeri (SPC) ondalık olabiliyor (`degree_days` Decimal). Birim/yuvarlama açısından etiket ile kullanılan değer arasında tek yönlü (güvenli) sapma var; yön doğru, ancak rapor/arayüzde "etiket" ve "kullanılan" farkının gösterilmesi şart. Düşük, bilgi amaçlı.

## Komşulara sorular

- 11 / 12: Kaskadla silinen çocukları belirlemek için ortak bir silme grubu alanı (ör. `deleted_with`) düşünüldü mü? Yoksa restore'un "yalnızca kayıt" davranışı bilinçli mi?
- 13: `audit.record_delete` ile satır içeriği olmayan silme kayıtları (13-4/13-5) için log'da "önce" değer alanı olursa restore/SET_NULL geri alma otomatikleştirilebilir mi? Mevcut `{label: [before, None]}` yapısı yalnızca görüntü metni (12-7).
- 20: Tedaviye arınma bitişinin anlık görüntüsü eklenirse 20-3 (geriye dönük çakışma) ve 20-4 birlikte çözülebilir; hasat çakışması kontrolü hangi tarihi esas alıyor (hesaplanan mı kayıtlı mı)?
- 29: `message_has_text` CHECK'i silinmiş mesaj gövdesinin temizlenmesini engelliyor; 29-3 çözümü için kısıt değişikliği planlandı mı?
- 09: 09-11 (Sayımlar sekmesi her sayım için defteri yeniden katlar) benim 18-5 ile aynı fold fonksiyonunu kullanıyor mu; kullanıyorsa 18-5'teki tek-geçiş katlama ile birlikte çözülmeli.
