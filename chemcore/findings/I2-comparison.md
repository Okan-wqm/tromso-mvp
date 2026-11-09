# I2: tatlı suyun iyonik şiddeti — v1 ile v3 yan yana (sahibin kararı için)

Tarih: 2026-11-09. Uygulama hâlâ **v1** ile hesaplıyor; v3 yalnızca çekirdekte ve testlerde var
(`chemcore/core/src/fresh.rs`, `chemcore/golden/v3`, `farm/tests/test_golden_v3.py`). Geçiş sizin kararınızla olur.

## Kısaca sorun

Bugünkü model (v1) suyun "iyonik şiddetini" (suda çözünmüş tuzların toplam etkisi) yalnızca **tuzluluktan** alıyor.
Tuzluluk 0 girilen bir tatlı su "ideal su" sayılıyor: içinde hiç iyon yokmuş gibi. Oysa sert bir tatlı suda
(kalsiyum, magnezyum, bikarbonat) iyonik şiddet 0,01 civarındadır ve bu, pH metrenin okuduğu değeri ve hesapları
birkaç yüzde değiştirir. Üniversite tankları çoğunlukla tatlı su olduğu için bu, modelin en görünür sınırıdır
(ayrıntı: `chemcore/findings/B1.md`, I2).

## v3 ne yapıyor

Tuzluluk **5 ‰'nin altındaysa** iyonik şiddeti ölçülen değerden alıyor, şu sırayla (ilk bulunan):

1. **İletkenlik** (µS/cm): I = 1,6 × 10⁻⁵ × iletkenlik (Russell 1976).
2. **Sertlik + alkalinite**: ölçülen iyonlar ve onları dengeleyen en az tek değerlikli iyon (alt sınır).
3. **Tuzluluk** (0'dan büyükse): deniz suyu formülüyle (DOE 1994).
4. **Yalnız alkalinite**: sodyum bikarbonat gibi (yine alt sınır).

Sonra **Davies denklemiyle** (Davies 1962) her iyonun aktivite katsayısını hesaplıyor ve tatlı su sabitlerini
(K1, K2, Kw, KB, KH₂S) buna göre düzeltiyor; pH metrenin okuduğu pH da serbest H⁺'ya bu katsayıyla çevriliyor.
**Tuzluluk 5 ‰ ve üstünde hiçbir şey değişmiyor**: v3 = v1, bit bit aynı (test ediliyor).

## Karşılaştırma (12 °C)

CO₂: suyun pH'ı ve alkalinitesindeki serbest CO₂ (mg/L). NH₃ payı: TAN'ın zehirli NH₃ olan kısmı (%), suyun pH'ında.
pH farkı: serbest pH − ölçülen (NBS) pH; v1'de tatlı suda hep 0.

| Su | pH | Alkalinite (mg/L CaCO₃) | Ne ölçülmüş | İyonik şiddet (v3) | CO₂ v1 | CO₂ v3 | Fark | NH₃ payı v1 | NH₃ payı v3 | Fark | pH farkı v1 | pH farkı v3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Yumuşak tatlı su | 7,0 | 20 | iletkenlik 50 µS/cm | 0,0008 | 4,905 | 4,741 | −3,3 % | 0,2168 | 0,2096 | −3,3 % | 0 | −0,015 |
| Tipik tatlı su (kuyu, RAS) | 7,0 | 80 | iletkenlik 300 µS/cm | 0,0048 | 19,617 | 18,132 | −7,6 % | 0,2168 | 0,2004 | −7,5 % | 0 | −0,034 |
| Tatlı su, yalnız alkalinite | 7,0 | 80 | hiçbir şey | 0,0016 | 19,617 | 18,713 | −4,6 % | 0,2168 | 0,2068 | −4,6 % | 0 | −0,020 |
| Sert tatlı su | 7,5 | 200 | sertlik 300 mg/L | 0,0090 | 15,484 | 13,944 | −10,0 % | 0,6823 | 0,6153 | −9,8 % | 0 | −0,045 |
| Sert tatlı su | 7,5 | 200 | iletkenlik 1000 µS/cm | 0,0160 | 15,484 | 13,539 | −12,6 % | 0,6823 | 0,5977 | −12,4 % | 0 | −0,058 |
| Acı su 2 ‰ | 7,5 | 120 | yalnız tuzluluk | 0,0399 | 7,540 | 7,657 | +1,5 % | 0,5776 | 0,5640 | −2,4 % | −0,065 | −0,083 |
| Acı su 2 ‰ | 7,5 | 120 | iletkenlik 3700 µS/cm | 0,0592 | 7,540 | 7,435 | −1,4 % | 0,5776 | 0,5480 | −5,1 % | −0,065 | −0,096 |
| Acı su 4,99 ‰ | 7,5 | 120 | yalnız tuzluluk | 0,0999 | 6,723 | 7,138 | +6,2 % | 0,5367 | 0,5266 | −1,9 % | −0,085 | −0,113 |
| Acı su 5 ‰ | 7,5 | 120 | — | 0,1001 | 6,721 | 6,721 | 0 | 0,5366 | 0,5366 | 0 | −0,085 | −0,085 |
| Acı su 10 ‰ | 7,5 | 120 | — | 0,2013 | 5,960 | 5,960 | 0 | 0,5002 | 0,5002 | 0 | −0,098 | −0,098 |
| Deniz suyu 33 ‰ | 8,0 | 115 | — | 0,6801 | 1,231 | 1,231 | 0 | 1,3435 | 1,3435 | 0 | −0,080 | −0,080 |

## Ne anlama geliyor

- **Tatlı suda** v3, aynı pH ve alkalinitede **daha az CO₂** ve **daha az NH₃** gösteriyor: yumuşak suda %3,
  tipik suda %5–8, sert suda %10–13. Yön literatürle uyumlu: iyonca zengin suda pH metre aynı değeri okurken gerçek
  H⁺ derişimi ve bikarbonatın etkin miktarı farklıdır (Stumm & Morgan 1996).
- **Güvenlik açısından**: v1 tatlı suda CO₂ ve NH₃'ü biraz **fazla** gösteriyor, yani ihtiyatlı taraftadır. v3'e
  geçiş, sınırlara yakın sularda bir değeri "uyarı"dan "güvenli"ye çevirebilir; bu yüzden geçiş sizin kararınız.
- **Tuzluluk titremesi** sorunu (B1.md'deki: 0 ile 0,1 ‰ arasında gidip gelen tuzluluk CO₂'yi %4,5 oynatıyordu)
  v3'te iletkenlik varken tamamen, yoksa büyük ölçüde kalkıyor: 12 °C, 80 mg/L, pH 7'de 0 → 0,1 ‰ ile CO₂ v1'de
  19,617 → 18,729 (−%4,5), v3'te 18,713 → 18,616 (−%0,5); pH 7,5'te NH₃ payı v1'de −%4,2, v3'te −%0,5.

## Zayıf noktalar (dürüstçe)

- **5 ‰ sınırında sıçrama var.** Yalnız tuzluluk bilinen acı suda, 4,99 ‰'de v3 CO₂'yi v1'den %6,2 yüksek
  veriyor, 5 ‰'de ise v1'e dönüyor: aynı su için 0,01 ‰ farkla %6 sıçrama. Sebep: 1 ‰'nin üstünde deniz
  suyu kökenli acı suda Millero'nun deniz suyu sabitleri (ölçülmüş, iyon çiftlerini de içeriyor) Davies'ten daha
  doğru. Tuzluluk–yalnız yolunda v1 ile v3 1 ‰'ye kadar %1'in içinde (CO₂: 0,1 ‰'de −%0,6, 1 ‰'de +%0,1),
  sonra ayrılıyor. **Önerim:** sınırı 5 ‰ yerine **1 ‰** yapmak (v3 yalnız gerçek tatlı suda, I ≲ 0,02); orada
  sıçrama CO₂'de %0,1, NH₃'te %2. Şu anki kod görevde istendiği gibi 5 ‰ kullanıyor; değiştirmek tek sabit
  (`FRESH_BELOW`) ve golden v3'ün yeniden kaydı demek.
- **Sertlik ve yalnız alkalinite yolları alt sınırdır**: ölçülmeyen iyonlar (sodyum, klorür, sülfat) iyonik
  şiddeti artırır; gerçek düzeltme biraz daha büyüktür. İletkenlik varsa o kullanılır ve en iyisidir.
- **Uygulamada iletkenlik ve sertlik henüz suyun girdisi değil**: iletkenlik bir sensör büyüklüğü olarak var
  (`conductivity_us_cm`), sertlik hiç yok. v3'e geçmek, okuma tarafında bu değerleri suya bağlamayı da gerektirir.
- **Sıcaklığa bağlı dielektrik sabiti (I1)** hâlâ sabit 79; v3 yalnız iyonik şiddeti değiştirsin diye ona
  dokunulmadı. Bunun 12 °C'deki etkisi küçük değil: aşağıdaki koşul 1.
- Ω (kalsit/aragonit) çizgileri 5 ‰'nin altında zaten çizilmiyor; v3 Ksp'ye dokunmuyor.

## v3'ü açmadan önce koşullar (çapraz inceleme, 2026-11-09)

Bunlar yerine gelmeden v3 uygulamaya bağlanmamalı:

1. **Sıcaklığa bağlı dielektrik sabiti (I1, inceleme F2).** Davies'in A katsayısı sabit ε = 79 ile hesaplanıyor; bu
   yalnız 25 °C civarında doğru (A ≈ 0,503; literatür 0,509). Çiftlik sıcaklıklarında A fazla çıkıyor: 12 °C'de
   yaklaşık %7,5, 2 °C'de %15 (Malmberg & Maryott 1956'nın ε(t)'siyle gerçek A 12 °C'de ≈ 0,500, 2 °C'de ≈ 0,493;
   sabit 79 ile 0,538 ve 0,568). log γ, A ile orantılı olduğundan yukarıdaki tablodaki 12 °C kaymaları kendi
   büyüklüklerinin **%7–8'i kadar abartılı**: örneğin tipik tatlı suda CO₂ −%7,6 yerine yaklaşık −%7,0. Koşul: ε(t)'yi
   çekirdeğe almak (I1'i kapatmak) ve Davies/A için 5 °C ve 12 °C'de tablo değerlerine karşı testler eklemek; bugünkü
   testler yalnız 25 °C'de olduğu için soğuk sudaki hatayı göstermiyor.
2. **İyonik şiddet sınırı (F3, yapıldı).** Davies yaklaşık I ≤ 0,5'e kadar geçerli. Tatlı su yolu artık 0,5'in üstünü
   açık bir hatayla reddediyor ("ionic strength above 0.5"): örneğin tuzluluğu girilmemiş bir deniz suyunun
   iletkenliği ya da µS/cm yerine mS/cm okunması. Önceden 1 000 000 µS/cm sessizce +2,15'lik bir pH farkı veriyordu.
3. **İletkenlik 25 °C'ye göre düzeltilmiş olmalı (F8).** 1,6 × 10⁻⁵ katsayısı 25 °C'deki özgül iletkenlik içindir.
   v3 bağlandığında yalnız sıcaklık telafili (25 °C) iletkenlik okunmalı ya da önce telafi edilmeli; ham iletkenlik
   soğuk suda iyonik şiddeti olduğundan düşük gösterir.
4. **Okuma tarafı.** İletkenlik ve sertlik suyun girdisi olarak bağlanmalı (yukarıda, zayıf noktalar).

## Sınır kararı: 1 ile 5 ‰ arasında sürekli geçiş (2026-11-09, sahibin devrettiği karar)

Sahibin kararıyla v3 açılıyor ve tatlı su ile deniz suyu yolu arasındaki sınırı seçmek bana bırakıldı. Önce eski 5 ‰
sınırındaki sıçramayı ölçtüm, sonra sıçramasız bir geçiş seçtim.

**Ölçülen sıçrama, eski 5 ‰ sınırında** (sıcaklığa bağlı A ile, I1 kapandıktan sonraki çekirdek; pH 7,5; aynı su
4,99 ‰ ve 5,00 ‰'de; `chemcore/scripts` dışında, çekirdeğin kendisiyle ölçüldü):

| Su (ne ölçülmüş) | °C | CO₂ 4,99 ‰ | CO₂ 5,00 ‰ | Sıçrama | NH₃ payı 4,99 ‰ | NH₃ payı 5,00 ‰ | Sıçrama |
|---|---|---|---|---|---|---|---|
| Yalnız tuzluluk, alk. 120 | 2 | 9,350 | 8,632 | −%7,7 | 0,2419 | 0,2387 | −%1,3 |
| Yalnız tuzluluk, alk. 120 | 12 | 7,272 | 6,591 | −%9,4 | 0,5363 | 0,5470 | +%2,0 |
| İletkenlik 3700 µS/cm | 2 | 9,703 | 8,632 | −%11,0 | 0,2509 | 0,2387 | −%4,9 |
| İletkenlik 3700 µS/cm | 12 | 7,551 | 6,591 | −%12,7 | 0,5565 | 0,5470 | −%1,7 |
| İletkenlik 8700 µS/cm (≈ 5 ‰) | 2 | 9,141 | 8,632 | −%5,6 | 0,2365 | 0,2387 | +%0,9 |
| İletkenlik 8700 µS/cm (≈ 5 ‰) | 12 | 7,106 | 6,591 | −%7,2 | 0,5243 | 0,5470 | +%4,3 |
| Sertlik 300 + alk. 120 | 2 | 10,805 | 8,632 | −%20,1 | 0,2791 | 0,2387 | −%14,5 |
| Sertlik 300 + alk. 120 | 12 | 8,425 | 6,591 | −%21,8 | 0,6198 | 0,5470 | −%11,8 |
| Sertlik 1000 + alk. 120 | 2 | 10,150 | 8,632 | −%15,0 | 0,2623 | 0,2387 | −%9,0 |
| Sertlik 1000 + alk. 120 | 12 | 7,906 | 6,591 | −%16,6 | 0,5822 | 0,5470 | −%6,0 |
| Yalnız alkalinite 20 | 2 | 1,556 | 1,436 | −%7,7 | 0,2419 | 0,2387 | −%1,3 |
| Yalnız alkalinite 20 | 12 | 1,209 | 1,095 | −%9,4 | 0,5363 | 0,5470 | +%2,0 |

2 ile 25 °C arasında en kötüsü: yalnız tuzluluk CO₂ %12,9 / NH₃ %6,0; iletkenlik 3700 %16,2 / %4,9; iletkenlik 8700
%10,9 / %8,5; sertlik 300 %25,1 / %14,5; sertlik 1000 %20,1 / %9,0; yalnız alkalinite %13,0 / %6,0. Bu sıçramalar
girdilerin ölçüm hatasından çok büyük: pH ölçümündeki ±0,02 (iyi bir pH metre) CO₂'yi %4,5, NH₃ payını %4,7 oynatır;
tuzluluktaki 0,1 ‰ ise %1'in altında. Yani 5 ‰'de keskin sınır kabul edilemezdi; 1 ‰'ye çekmek de (önceki önerim)
sıçramayı yalnız küçültürdü, kaldırmazdı.

**Seçim: iki yol arasında sürekli, tekdüze bir karışım.** 1 ‰'ye kadar yalnız tatlı su yolu, 5 ‰'den itibaren yalnız
deniz suyu yolu; arada deniz yolunun ağırlığı doğrusal olarak 0'dan 1'e çıkıyor (`fresh.rs` `sea_weight`), her sabit iki
yolun geometrik ortalaması (logaritmada doğrusal), pH farkı doğrusal. Neden bu iki uç:

- **1 ‰**: Millero vd. (2006, *Mar. Chem.* 100: 80) K1 ve K2'yi tuzluluk 1 ile 50 arasında **ölçtü** (denklemlerini 0'a
  kadar geçerli saysalar da 1'in altı ölçülmedi). 1 ‰'nin altında tatlı suyun iyonları deniz suyunun oranında değildir
  (kalsiyum-bikarbonat ağırlıklı), deniz suyu sabitleri oraya taşınmamalı.
- **5 ‰**: deniz yolunun pH ölçeklerine ve boratına giren Dickson (1990) KSO₄ ve KB yalnız 5–45 ‰ arasında geçerli.
  Davies ise iyonik şiddet 0,5'e kadar kullanılabilir (5 ‰ = I 0,10, sınırın çok içinde), yani tatlı su yolu bandın
  her yerinde kendi geçerlilik alanında.

**Sonuç, aynı ölçümle** (0–30 °C, pH 6,5 / 7,5 / 8,5, tuzluluk 0–6 ‰ 0,01 adımla):

| Su | 1 ve 5 ‰'de sıçrama | 0,1 ‰ başına en dik değişim, CO₂ | NH₃ | En büyük geri dönüş, CO₂ | NH₃ |
|---|---|---|---|---|---|
| Yalnız tuzluluk | 2·10⁻⁸ % (yok) | %1,27 | %0,52 | %0 | %0,44 |
| İletkenlik 3700 µS/cm | 2·10⁻⁸ % | %1,40 | %0,34 | %0,32 | %2,16 |
| İletkenlik 8700 µS/cm | 2·10⁻⁸ % | %1,18 | %0,44 | %1,48 | %3,08 |
| Sertlik 300 + alk. 120 | 2·10⁻⁸ % | %1,27 | %0,52 | %0 | %0,44 |
| Sertlik 1000 + alk. 120 | 2·10⁻⁸ % | %1,27 | %0,40 | %0,02 | %0,68 |
| Yalnız alkalinite 20 | 2·10⁻⁸ % | %1,38 | %0,52 | %0 | %0,44 |

Sıçrama yok; bant içinde 0,1 ‰ tuzluluk farkı en çok %1,4 değiştiriyor, pH'taki ±0,02'nin üçte biri. Karışımın ağırlığı
tekdüze; çıktılar ise bir yerde hafifçe geri dönebiliyor, çünkü iki yol 5 ‰'de birbirinden farklı (deniz suyu sabitleri
iyon çiftlerini içeriyor): yalnız tuzlulukta NH₃ payı en çok %0,44 geri dönüyor (30 °C, alk. 20, pH 6,5). İletkenliği
sabit tutup tuzluluğu 0'dan 6'ya sürmek (tutarsız bir çift: 8700 µS/cm yaklaşık 5 ‰ demektir) %3,1'e kadar geri dönüş
veriyor; bu da pH hatasının etkisinin altında. Doğrusal ağırlık "yumuşak basamak"tan (3x² − 2x³) daha küçük geri dönüş
verdi (%0,44'e karşı %0,71), o yüzden doğrusal seçildi.

**İyonik şiddet kuralında bir düzeltme de geldi.** Eski sırada küçük bir tuzluluk (örneğin 0,01 ‰, I 0,0002) suyun
alkalinitesinin kendi iyonlarını (80 mg/L'de en az 0,0016) yok sayıyordu: 0 ile 0,01 ‰ arasında %7,7'lik basamak. Şimdi
kural: önce bir **tahmin** (iletkenlik, yoksa 0'dan büyük tuzluluk), ama ölçülen iyonların **alt sınırı** (sertlik ve
alkalinite, yoksa yalnız alkalinite) daha büyükse alt sınır. Hiçbir şey ölçülmemişse (tuzluluk 0, alkalinite yok)
iyonik şiddet 0: v1'in ideal suyu, ihtiyatlı taraf. Birkaç girdi birden varsa kullanılan: iletkenlik (yoksa tuzluluk),
ama sertlik+alkalinite ya da yalnız alkalinitenin verdiği alt sınırın altına hiçbir zaman inmeden.

## Karar için seçenekler

1. v3'ü olduğu gibi (5 ‰ sınırıyla) açmak.
2. v3'ü **1 ‰ sınırıyla** açmak (önerim) — golden v3 yeniden kaydedilir.
3. v1'de kalmak; v3 test ve karşılaştırma için durur.

Hangi seçenek olursa olsun geçiş ayrı bir adım olur: okuma tarafı (iletkenlik/sertlik), golden'ın yeni sürümü ve
ekranlarda "hangi iyonik şiddetle hesaplandı" notu birlikte gelir.

Kaynaklar: Davies (1962) *Ion Association*; Russell (1976) *J. AWWA* 68: 2; Stumm & Morgan (1996) *Aquatic
Chemistry*, 3. baskı, bölüm 3.4; Plummer & Busenberg (1982) *GCA* 46: 1011; DOE (1994) *Handbook of methods*, bölüm 5;
Millero vd. (2006) *Mar. Chem.* 100: 80.
