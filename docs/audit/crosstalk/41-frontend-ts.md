# 41 frontend-ts: capraz denetim (komsu bulgulari)

## Dogrulananlar
- 43-5 / 44-6 (frontend/components.ts:333-366): Modal.load fetch'i try/catch'siz; 403 disinda 404/500 govdesi innerHTML'e basilir. 41-11 ile ayni kok neden.
- 43-6: submit/kapatma yolunda kirli-form kontrolu yok (components.ts:312-314, 323-325).
- 43-7: modal submit isleyicisi (components.ts:318-322) dugmeyi kilitlemiyor; ardisik tiklama iki POST yollar. Create icin sunucu tarafi korumasi ayri.
- 44-5: initTabs (components.ts:21-49) yalniz ArrowLeft/Right isliyor; Home/End yok, aria-controls/labelledby TS tarafinda atanmiyor.
- 44-9: roster.ts:61 td'ye aria-selected, roster.ts:71 aria-pressed ayarliyor (41-22 ile ayni).
- 44-19: auth.ts:12 aria-pressed ayarliyor (etiket degisimi sablon/i18n tarafinda).
- 44-20: announce.ts: ayni metin tekrar okunmaz (41-18 ile ortusuyor).
- 44-11: windows.ts:185-203 ok tuslari preventDefault ediyor; yalniz pencere icindeki odakta ve input/select/textarea ile PHONE disinda; iddia kismen abartili.
- 44-1 / 44-12 / 41-25: odak yonetimi eksikligi frontend tarafindan da dogru.
- 43-14 / 44-16: templates/app_base.html:98-99 flash-list role="status".
- 44-7 / 41-17: announce.ts yalniz kartlarin kotulesmesini duyuruyor; stale/gone icin canli bolge yok.

## Itirazlar / onem
- 44-7 high: JS tarafinda kritik kart duyurusu var (announce.ts), bagli kopmasi/stale icin yok; high yerine medium daha uygun.
- 44-11 low kalmali, kapsam dar.

## Yeni bulgular
Bkz. yapilandirilmis cikti 41-X1..X4.

## Sorular
- 43/44: modal hata cercevesi icin tek bir sozlesme (X-Modal hata govdesi) istenecek mi?
- 46-2: [hidden] ezilmesi JS'in panel.hidden/row.hidden kullanimini (components.ts:35,172) dogrudan etkiler.
- 45: JS'e giden etiketler (label(...)) data-* uzerinden mi geliyor; eksik anahtar durumu?
