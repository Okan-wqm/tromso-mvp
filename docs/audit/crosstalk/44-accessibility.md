# Capraz degerlendirme: accessibility (44)

## Dogrulananlar
- 41-17 / 44-7: poll.ts stale/gone ve kritik kart bildirimi yalnizca CSS (dogrulandi, canli bolge yok).
- 41-25 / 44-1, 44-12: mobil ray ve acilir menulerde odak yonetimi eksik.
- 41-22 / 44-9: roster.ts:61 `aria-selected` td uzerinde.
- 41-18 / 44-20: duyuruda ayni metin tekrar okunmaz.
- 41-5, 41-11, 43-5 / 44-6: Modal ve fetch hatalari sessiz.
- 41-6: aria-invalid bos degerle eklenmesi, ARIA gecersizligi olarak dogru.
- 42-19 / 44-2: templates/registration/_field.html:3-4,20-21 aria-describedby/aria-invalid yok; yardim div'i id tasiyor ama hicbir yerden referans verilmiyor.
- 42-16 / 44-17: baslik atlamasi.
- 43-14 / 42: templates/app_base.html:99 ve templates/modal_base.html:13 `role="status"` ile hata mesaji (44-16 ile ayni).
- 46-11 / 44-3: kenarlik kontrasti 1.68:1.
- 46-1: a.button hover kontrasti (`static/css/base.css:144` `a:hover{color:var(--speck)}`) erisilebilirlik acisindan da gecerli.
- 46-2: `[hidden]` bazi siniflarca eziliyor; gizli icerigin ekran okuyucuya acik kalmasi riski.
- 46-12: opaklikla azaltilmis metin kontrasti.
- 43-12, 43-11: onaysiz yikici eylem ve void geri alinamazlik bilgisi eksikligi, bilissel erisilebilirlik acisindan da onemli.

## Itirazlar / dikkat
- 42-1 (help_text|safe): templates/registration/_field.html:20 dogrulandi; erisilebilirlik yonunden, HTML iceren yardim metni okuyucuya yapi olarak ulasir, ama asil risk guvenliktir.
- 43-13 / 42-3: erisilebilirlik acisindan belirleyici degil.

## Onem derecesi onerileri
- 41-17 medium dogru; 44-7 ile birlikte WCAG 4.1.3 ihlali, medium kalmali.
- 41-25 low yetersiz: odak tuzagi/inert yoklugu klavye kullanicisi icin medium.
- 41-22 low dogru (gecersiz ARIA ama islevsel etkisi sinirli).
- 43-14 low yerine medium: hata mesajlari role=status ile sayfa yuklemede duyurulmuyor.

## Yeni bulgular
- 44-X1: `_field.html` her hata/yardim icin id uretmiyor, `field.errors` ul-sinifli ciktisi alana baglanmiyor.
- 44-X2: Turkce `|lower` (45-1) ekran okuyucu telaffuzunu da bozar; lang destekli CSS text-transform tercih edilmeli.
- 44-X3: Mesaj listesi (templates/messaging/inbox.html:31) `aria-live="polite"` ile tum liste/append sesli okunur; poll append ile birlikte gurultu riski.
- 44-X4: Giris sayfasinda (01-1 brute force) hata mesaji genel ve role=alert; kilitleme eklenirse durum mesaji erisilebilir olmali.

## Komsulara sorular
- frontend-ts: Modal kapatma/odak iadesi (components.ts) icin focus-return var mi?
- css-static: `[hidden]` ezilmesi gorsel olarak gizli ama erisilebilir agacta kalan ogeler olusturuyor mu?
- i18n: lang attribute'u modal yanitlarinda/parcalarda ayrica ayarlaniyor mu?
- authn: Oran siniri/kilit mesaji icin kullanici bildirimi tasarlandi mi?
