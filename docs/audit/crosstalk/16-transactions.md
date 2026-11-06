# Çapraz konuşma: 16 transactions uzmanı (09, 10, 11, 12, 13, 27, 45 bulguları üzerine)

## Doğrulananlar
- 10-1 / 11-6 (aynı kusur): core/crud.py:713 get_object, :724 kilit altı `.get(pk)` ve :815 RowList; kayıt iki çağrı arasında silinirse DoesNotExist (500). Önem: 10-1 medium, 11-6 low; gerçek etki yarış penceresine bağlı, low/medium. Birleştirilmeli. (Benim 16-9 aynı desenin messaging karşılığı.)
- 10-2: UpdateView (core/crud.py:715-757) ve RowList atomic bloğunda IntegrityError yakalanmıyor; form.is_valid() kilit dışında (:713-716) olduğundan validate_unique yarışı doğrudan 500 olur.
- 10-3: hr/forms/leave.py:92 `leave.used()` form clean içinde, kilitsiz; hr/leave.py:60-67 toplamı okuma anlık görüntüsünden. UpdateView kilidi yalnız talep satırını kilitler, çalışan satırını değil; eşzamanlı iki talep kotayı aşabilir. Doğrulandı.
- 10-4: core/crud.py:806 formset doğrulaması kilit (:815) öncesinde; kilit yalnız üst satırı alıyor. Doğrulandı.
- 11-2: tasks/services.py:265-271 withdraw döngüsü kendi atomic/kilidini taşımıyor; satır başına audit+delete. Çağıranın işlemine bağımlı (16-13 ile aynı politika boşluğu).
- 11-7 / 12-15: core/softdelete.py:189-203 restore kilitsiz, sürüm denetimsiz, kendi atomic bloğu yok (audit.record kayıt save'inden sonra ayrı çağrı).
- 11-14: experiments/services.py:193-200 `_touch` queryset.update() ile yazıyor, version artmaz; _park (:245) de öyle. Bilgi düzeyi doğru; iyimser kilidin deney tasarımında atlandığı ek not.
- 12-11 / 13-8: ATOMIC_REQUESTS yokluğu ve audit.record'ın işlem denetlememesi 16-13 ile aynı; doğrulandı.
- 11-15 / 12-3 / 12-4: belge dosyasının DB işlemi içinde yazılması = 16-2; aynı kök neden, tek bulgu olarak birleştirilmeli.
- 10-5 / 13-10 / 09-17: GET ile yazma (materialise_due) = 16-10; tasks/services.py:257-262 seri başına hata izolasyonu yok.
- 13-14: audit.revision() zamana/LATE_COMMIT'e bağlı = 16-11.

## Önem derecesi itirazları
- 12-11 low yerinde; ancak 16-13 ile birleştirip tek "işlem sınırı politikası" bulgusu yapılmalı.
- 11-1 medium/high makul; fakat 10-6 (low) aynı kök neden, tutarlı seviyeye çekilmeli.

## Reddedilen
Yok. 09 (okuma) bulguları işlem alanımın dışında; 09-17 (GET'te okundu yazısı) yalnız yazma yan etkisi açısından 10-5 ile aynı sınıf.

## Yeni bulgular
- 16-X1 (low): restore() `full_clean` (benzersizlik) ile `save` arasında kilit/atomic yok; arada başka bir kayıt kodu alırsa IntegrityError (admin'de 500, yalnız ValidationError yakalanıyor). Ayrıca RESTORE audit satırı save'den ayrı yazılıyor; çağıran atomic açmazsa kayıt geri gelir, log düşmez (core/softdelete.py:189-203).
- 16-X2 (low): UpdateView'da validate_unique/form doğrulaması kilit dışında, IntegrityError yakalanmadığı için 10-2 ile 10-1 birleşik kök neden: doğrulama-sonra-yaz penceresi (core/crud.py:713-724).

## Komşulara sorular
- 10 uzmanı: 10-9 e-posta atomic içinde; gönderim sonrası rollback olursa davet iletilmiş ama kayıt yok durumu doğrulandı mı?
- 11 uzmanı: withdraw (11-2) hangi çağıranlardan atomic içinde çağrılıyor?
- 13 uzmanı: audit.revision() izleme duvarında geç commit eden bir işlem için gerçekten güncelleme kaçırıyor mu (test)?
- 27 uzmanı: experiments start işlemi tank kilitlerini hangi sırayla alıyor; 27-10 move_span ile kilit sırası uyumlu mu?
- 12 uzmanı: restore sonrası hypertable (su ölçümleri) satırları için işlem sınırı belgeli mi?
