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
  dokunulmadı.
- Ω (kalsit/aragonit) çizgileri 5 ‰'nin altında zaten çizilmiyor; v3 Ksp'ye dokunmuyor.

## Karar için seçenekler

1. v3'ü olduğu gibi (5 ‰ sınırıyla) açmak.
2. v3'ü **1 ‰ sınırıyla** açmak (önerim) — golden v3 yeniden kaydedilir.
3. v1'de kalmak; v3 test ve karşılaştırma için durur.

Hangi seçenek olursa olsun geçiş ayrı bir adım olur: okuma tarafı (iletkenlik/sertlik), golden'ın yeni sürümü ve
ekranlarda "hangi iyonik şiddetle hesaplandı" notu birlikte gelir.

Kaynaklar: Davies (1962) *Ion Association*; Russell (1976) *J. AWWA* 68: 2; Stumm & Morgan (1996) *Aquatic
Chemistry*, 3. baskı, bölüm 3.4; Plummer & Busenberg (1982) *GCA* 46: 1011; DOE (1994) *Handbook of methods*, bölüm 5;
Millero vd. (2006) *Mar. Chem.* 100: 80.
