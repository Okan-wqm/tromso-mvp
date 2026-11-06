# Çapraz görüş: authz (02)

Kapsam: authn (01), csrf-xss (03), injection (04), secrets-config (05), file-upload (06), data-modify (11), biz-inventory (23).

## Doğrulananlar
- 01-2 / 05-1 / 05-2: DEBUG ve SECRET_KEY varsayılanları authz için de önemli (02-2 ile aynı kök). Oturum/imza anahtarı bilinen değerse oturum sahteciliği tüm yetkileri aşar.
- 01-4: WorkspaceMiddleware (config/settings.py:70-76) LoginRequiredMiddleware'den ÖNCE çalışır (core/middleware.py:12-14); anonim istek çalışma alanı yoluna denk gelirse oturum yazılır. Yetki etkisi yok, düşük kalır.
- 04-1 / 03-4: templates/registration/_field.html:20 help_text|safe; tasks/forms.py:80 yer etiketini kaçışsız gömer. Yetki açısından: site/yer adı düzenleme hakkı olan düşük yetkili kullanıcı, görev formunu açan yüksek yetkili oturumda script çalıştırabilir (dikey yükselme zinciri). Orta doğru.
- 06-13: knowledge/views.py:20-30 yalnız model düzeyi view izni; indirme ayrımı yok (02-1 ile aynı desen).
- 11-4: Rol (Group) düzenlemede iyimser kilit yok; yetki matrisi eşzamanlı kayıtlarda sessizce ezilebilir (02-3 ile ilişkili).
- 11-5: Rol hard delete; onay ekranı üye/izin etkisini göstermez; yetki kaybı denetimsiz.
- 11-12 / 06-7 / 01-9: audit boşlukları yetki açısından da önemli (kim erişti/sildi izlenemez, 02-5 ile bağlı).
- 23-1: tedarikçi durumu kontrolü eksik; ayrıca yetki tarafı: inventory/views.py:43 tek izin (add_inventoryoperation) teslimat, çıkış, iade, transfer, sayım, atığı kapsıyor.

## İtiraz / önem düzeltmesi
- 01-7 (low): doğru ama yetki etkisi yok; info'ya indirilebilir.
- 11-16 (info): confirm_delete "admin'den geri alınabilir" mesajı 02-16 ile birlikte okunmalı; restore yalnız admin yetkisine bağlıdır.

## Yeni bulgular
Bkz. StructuredOutput new_findings (02-X1..).
- 02-X1 Envanter: tüm hareket türleri tek izne bağlı (inventory/views.py:43, 275, 310, 348). Sayım (stok sıfırlayabilen) ve atık için ayrı yetki yok.
- 02-X2 Envanter operasyon filtresi Supplier.all_objects ile silinmiş tedarikçileri de listeler (inventory/views.py:144).
- 02-X3 04-1 depolanmış HTML enjeksiyonu yetki sınırı aşımı olarak değerlendirilmeli.
