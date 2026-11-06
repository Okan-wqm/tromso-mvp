# 27 biz-experiments: komşu bulgulara çapraz değerlendirme

## Doğrulananlar
- 19-7 (atama son günü formda uzatılabilir, servis yalnız kısaltır): experiments/services.py:772-781 `_end_diet` aynı `assignments.end` yolunu kullanır (farm/feeding/assignments.py:76-82). 27-2 ile aynı kök neden.
- 19-11 (yem toplamı tanımları farklı): 27-4 ile aynı örüntü, deney Veri sekmesi üçüncü bir tanım.
- 21-7 (survival tanımı birim-kalış bazlı): experiments/read.py:187-212 kendi tanımını kullanıyor (replikat ilk günü sonundaki adet, kayıplar farm.feeding.fold.LOST: MORTALITY/CULL/ADJUSTMENT). Çiftlik ekranıyla sayılar uyuşmayabilir.
- 10-7 (RowList sil-yeniden-yarat): experiments/resources.py:53 TeamList bunu kullanır; Member satırı id/created_at kaybeder. Başka tablo Member'a FK vermediği için etkisi düşük.

## Reddedilen
Yok.

## Önem derecesi
- 19-7 low yeterli. 21-7 deney yönünden low-medium.

## Yeni bulgular
- 27-X1: `_end_diet` atamayı (unit, protocol, valid_from) ile bulur, bağlantı kolonu yok. Çiftlik arayüzünde atamanın protokolü/başlangıcı değiştirilirse release/replace diyeti sessizce bitirmez (experiments/services.py:772-781).
- 27-X2: experiments/read.py:34 LOST, farm.feeding.fold'dan alınıyor; ESCAPE tipi sağkalıma sayılmıyor olabilir (confidence low), ve 21-5 ADJUSTMENT'ı ölü kod/yanlış neden olarak işaretliyor.

## Komşulara sorular
- feeding: ProtocolAssignment için deney bağlantısı eklenip formda kilitlenebilir mi (19-7/27-2)?
- stock-prod: survival için tek tanım (21-7) belirlenirse experiments/read.py:_survival onu kullansın mı?
