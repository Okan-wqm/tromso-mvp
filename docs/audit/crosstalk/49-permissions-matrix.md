# 49 permissions-matrix: komşu bulgu çapraz denetimi

## Onaylananlar
- 02-7: monitoring/views.py:99,127 izin olarak farm.stock.views.VIEW (farm.view_stockoperation) kullanıyor (monitoring/views.py:21). Bizim 49-8 ile aynı.
- 02-13 / 24-13: tasks/views.py:79-81 add_note yalnız tasks.view_task ister; servis katmanında ayrı yetki yok. Bizim 49-9 ile aynı.
- 02-6: reports/views.py:134,202,229 yalnız reports.view_report ister; kaynak alanların izni aranmaz.
- 02-3: production manager önayarı ile matris uyuşmazlığı (bizim 49-12).
- 01-12 / 03-11: tüm-URL x rol testinin yokluğu (bizim 49-6).
- 05-1 / 05-2: config/settings.py:25 ve :28 fail-open varsayılanlar doğrulandı.

## Önem derecesi notları
- 02-13 low: yetki matrisi açısından uygun; ancak "Read" etiketi yazmayı içerdiği için kullanıcıya yanıltıcı (49-9).
- 02-7 low, yetki matrisinde "medium" yakın: farm okuma izni olmayan ama izleme izni gereken rol kurulamıyor.

## Yeni bulgular
Bkz. StructuredOutput (49-X1, 49-X2).
