# 30 biz-core-facility: Komşu bulgu çapraz denetimi

## Doğrulananlar
- 22-2 (medium): farm/models/site.py:87 `altitude` için validator yok (max_digits=8); farm/water/chemistry.py:367 `math.pow(1 - 2.25577e-5*h, 5.25588)` h > ~44330 m için negatif tabanda ValueError verir; farm/water/read.py:340-341 site.altitude'u doğrudan pressure_atm'e verir. Hesaplayıcı 0-5000 sınırlıyor (calculation.py:228). Bu 30-6/30-15 ile aynı sınıf (Site alanı doğrulanmıyor).
- 20-13 (info): farm/models/site.py:96,176-177 lice_area yalnız değer kümesine bakıyor; enlem/bölge ile çapraz kontrol yok (30-15 ile aynı).
- 23-1 (medium): inventory/services.py:187-195 yalnız `supplier.is_deleted` ve kategori kontrol ediyor; farm/models/supplier.py:141 `status` alanı hiç okunmuyor (30-11 ile aynı kalıp: durum alanı davranışsız).

## Önem derecesi notları
- Tek bir komşu bulgunun önemini değiştirmeye yetecek kanıt bulunmadı.

## Yeni bulgular
- 30-X1 (low): Durum alanlarının okunmaması kalıbı tedarikçiye (Supplier.status) de uzanıyor; Site/System/Equipment ile aynı sorun, ortak bir "durum davranışı" kararı gerekir.
- 30-X2 (low): Site.altitude, latitude/longitude gibi doğrulayıcı taşımıyor (farm/models/site.py:80-87); sınır yalnız hesaplayıcı formunda (farm/forms/water.py:427). Doğrulama modelde olmalı.

## Komşulara sorular
- biz-water: Site.altitude'a model düzeyinde aralık eklenirse hangi aralık (0-5000 mi, negatif tuzlu göl rakımları mı) kabul edilir?
- biz-inventory: Supplier.status "askıda/engelli" iş kuralı olarak teslimatı engellemeli mi, yoksa yalnız uyarı mı?
- biz-health: lice_area için konumdan türetme (enlem/kıyı bölgesi) yasal kaynak olarak var mı?
