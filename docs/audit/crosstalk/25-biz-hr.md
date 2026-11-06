# 25-biz-hr çapraz konuşma

Kapsam: komşu bulgularından HR'yi ilgilendirenler.

- 44-10 (roster'da uyarı/vardiya adı yalnızca title): ONAY. templates/hr/roster.html:65,70,71,75 title ile veriyor; 44-9 ile aynı şekilde roster.ts:61 td'ye aria-selected koyuyor. 25-5 ile birleşince hafta saati uyarısı '!' + title olarak, ekran okuyucu ve dokunmatikte görünmez.
- 38-2/38-3 (idempotency yok): HR punch (hr/views.py:180-192) entry_key taşımıyor ama DB'de ikinci açık punch reddediliyor; çift tıklama zararsız. Çift clock_out'ta ikinci istek hata mesajı üretir. Mesaj/not için HR kaynaklı ek bulgu yok.
- 19-14 (şirket vs site saati): HR'de de benzer; site_today(None) team_overview'da (hr/views.py:200) şirket saatini kullanıyor.
