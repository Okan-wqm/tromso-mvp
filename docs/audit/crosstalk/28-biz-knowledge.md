# Çapraz Değerlendirme: biz-knowledge (28)

Kapsam: biz-feeding (19), biz-health (20), biz-stock-prod (21), biz-water (22), biz-inventory (23), frontend-ts (41), timeseries (17).

## Doğrulananlar / ilgili noktalar
- 41-16 (data-autosubmit iki dosyada farklı yorum): knowledge'ın entry_list.html ve document_list.html süzgeçleri `select[data-autosubmit]` kullanıyor; `frontend/components.ts:135-137` change'de `requestSubmit()` yapıyor, `<noscript>` düğmesi var (templates/knowledge/entry_list.html:34). Knowledge tarafında davranış tutarlı; bulgu knowledge için etkisiz (poll.ts yalnız `live()` formlarında devreye girer).
- 41-10 (Modal FormData gönderen düğmeyi kaybediyor): knowledge şablonlarında `formaction` veya name/value'lu gönderen düğme bulunmadı (grep), dolayısıyla knowledge diyalogları bu hatadan etkilenmiyor.

## Reddedilen/ilgisiz
- Feeding/health/stock/water/inventory/timeseries bulgularının knowledge koduyla kesişimi yok; knowledge, bu alanların verisini okumuyor. Bu alanlar için onay/ret verilmedi.

## Yeni bulgular
- 28-X1 (low/medium): Komşu uzmanların birçok bulgusu "servis katmanı doğrulamıyor, yalnız form doğruluyor" kalıbını tekrar ediyor (21-10, 20-9, 23-10, 19-12). Knowledge'daki 28-13 ile aynı sistemik desen: doğrulama formda, servis çıplak. Ortak bir ilke/ADR yok.
- 28-X2 (info/medium): Filtre/arama için "aynı kayıtlar bellekte işleniyor" ölçeklenme kalıbı (20-11, 21-14, 23-6, 17-9) knowledge'da `knowledge/search.py` search_documents/search_entries (satır 127, 157) için de geçerli olabilir; arama sonucu Python tarafında sıralanıyor. Ölçek eşiği belgelenmemiş.
