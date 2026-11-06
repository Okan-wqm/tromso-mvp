# 23 biz-inventory: çapraz değerlendirme

## Doğrulananlar
- 19-10 ve 18-2: inventory/read.py:62 `unit__production_department__site__isnull=False` süzgeci sitesiz departman ünitelerinin yemlemesini düşürüyor. farm/models/production_department.py:45-47 site silinince SET_NULL olduğunu doğruluyor. Stok defteri yemi fazla gösterir. Tek kök neden, tek bulgu olarak birleştirilmeli (medium önerilir, silinmiş site senaryosunda sessiz sapma).
- 18-16: inventory/integrity.py:56-79 yalnız lot numarası boşluğu, LOT_REQUIRED eksikleri ve fiziksel fazlayı denetliyor. Pasif konuma giriş ve silinmiş lot/item yetimi kontrolü yok (satır 64-69 yalnız feed_id None).

## Notlar
- 24-1 / 19-8 / 18-4 (geri yükleme asimetrisi) envanter için de geçerli olabilir: Item/Lot/Location silme-geri yükleme yolu kontrol edilmeli.
