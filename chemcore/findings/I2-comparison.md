# I2: tatlı suyun iyonik şiddeti — v1 ile v3 yan yana, ve v3'e geçiş

Tarih: 2026-11-09. **Sahibin kararıyla uygulama artık formül 3 (v3) ile hesaplıyor** (`FORMULA_VERSION` 3). Aşağıda
önce ilk karşılaştırma (karardan önceki, tarihî hâliyle), sonra geçişte yapılanlar: sıcaklığa bağlı dielektrik sabiti
(I1), sınır kararı, iletkenlik ve sertliğin girdi olması, önce/sonra sayıları ve soğuk su testleri. Formül 1 (v1)
çekirdekte durur ve yalnız adıyla istenince hesaplanır (golden v1, eski bir değeri aynen yeniden üretmek için).

## Kısaca sorun

Bugünkü model (v1) suyun "iyonik şiddetini" (suda çözünmüş tuzların toplam etkisi) yalnızca **tuzluluktan** alıyor.
Tuzluluk 0 girilen bir tatlı su "ideal su" sayılıyor: içinde hiç iyon yokmuş gibi. Oysa sert bir tatlı suda
(kalsiyum, magnezyum, bikarbonat) iyonik şiddet 0,01 civarındadır ve bu, pH metrenin okuduğu değeri ve hesapları
birkaç yüzde değiştirir. Üniversite tankları çoğunlukla tatlı su olduğu için bu, modelin en görünür sınırıdır
(ayrıntı: `chemcore/findings/B1.md`, I2).

## v3 ne yapıyor (ilk sürüm; geçişteki hâli aşağıda, "Geçiş")

Tuzluluk **5 ‰'nin altındaysa** iyonik şiddeti ölçülen değerden alıyor, şu sırayla (ilk bulunan):

1. **İletkenlik** (µS/cm): I = 1,6 × 10⁻⁵ × iletkenlik (Russell 1976).
2. **Sertlik + alkalinite**: ölçülen iyonlar ve onları dengeleyen en az tek değerlikli iyon (alt sınır).
3. **Tuzluluk** (0'dan büyükse): deniz suyu formülüyle (DOE 1994).
4. **Yalnız alkalinite**: sodyum bikarbonat gibi (yine alt sınır).

Sonra **Davies denklemiyle** (Davies 1962) her iyonun aktivite katsayısını hesaplıyor ve tatlı su sabitlerini
(K1, K2, Kw, KB, KH₂S) buna göre düzeltiyor; pH metrenin okuduğu pH da serbest H⁺'ya bu katsayıyla çevriliyor.
**Tuzluluk 5 ‰ ve üstünde hiçbir şey değişmiyor**: v3 = v1, bit bit aynı (test ediliyor).

## Karşılaştırma (12 °C; ilk sürüm, sabit ε = 79 ve 5 ‰ sınırıyla — tarihî)

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

## Zayıf noktalar (ilk sürüm, dürüstçe)

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

## v3'ü açmadan önce koşullar (çapraz inceleme, 2026-11-09; dördü de yerine getirildi, aşağıda "Geçiş")

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

## Geçiş: yapılanlar (2026-11-09)

Koşulların dördü de yerine getirildi:

1. **I1 kapandı.** Davies'in A katsayısı artık suyun kendi sıcaklığından: A = 1,824812·10⁶ √ρ (εT)^−3/2, ε Malmberg &
   Maryott (1956) denkleminden, ρ Kell (1975) denkleminden. Hamer'ın (1968) tablosuyla %0,03, farklı bir ε kullanan
   USGS tablosuyla (Nordstrom vd. 1984) %0,3 içinde (ayrıntılı tablo: `chemcore/findings/B1.md`, I1). Aynı A deniz
   suyu yolunun NBS dönüşümüne de girdi: bu, 10 ‰'nin üstünde CO2SYS'in Takahashi vd. (1982) kuralına her sıcaklıkta
   daha yakın (35 ‰'de 0 °C'de fark −0,073'ten −0,048'e, 40 °C'de +0,051'den +0,034'e).
2. **Davies sınırı** (I ≤ 0,5) zaten vardı; tatlı su yolu bant içinde de bunun üstünü reddediyor. Uygulamada böyle bir
   su (ör. 50 000 µS/cm iletkenlik, tuzluluk girilmemiş) NH₃'ü göstermiyor, nedenini yazıyor.
3. **İletkenlik yalnız 25 °C'ye telafi edilmiş olarak okunuyor** (F8). Yeni su parametresi
   `conductivity_25_us_cm` ("25 °C'de iletkenlik, sıcaklık telafili"); sensörlerdeki eski `conductivity_us_cm`
   büyüklüğü "suyun kendi sıcaklığında, telafisiz" diye adlandırıldı ve kimya onu **hiç okumuyor**. Ölçerin sıcaklık
   telafisi açık ve referansı 20 değil 25 °C olmalı (alanın yardım metni söylüyor).
4. **İletkenlik ve sertlik suyun girdisi**: elle ve laboratuvar örneğinde birer sütun (veritabanı denetimiyle), birer
   sensör büyüklüğü, hesaplayıcının Su sekmesinde birer alan, birimin grafiğinde ve tekrar oynatmada (replay) girdi.
   Bir TAN örneğinin NH₃'ü, tuzluluk gibi bulunan değerlerle hesaplanır: alkalinite, iletkenlik ve sertlik önce
   örneğin kendisinden, yoksa noktanın o andaki taze değerinden, yoksa birimin orta noktasından; bayat bir değer
   hiçbir hesaba girmez.

**Birkaç girdi birlikte varsa hangisi kullanılır:** bir tahmin (önce iletkenlik, yoksa 0'dan büyük tuzluluk), ama
ölçülen iyonların alt sınırının (sertlik + alkalinite, yoksa yalnız alkalinite) altına hiç inmeden. Hiçbiri yoksa
iyonik şiddet 0: v1'in ideal suyu, yani ihtiyatlı taraf. 1–5 ‰ arasında sabitler tatlı ve deniz yolunun karışımı
(yukarıda, sınır kararı).

**Her değer formülünü söylüyor.** Hesaplanan hiçbir değer saklanmıyor (NH₃-N, NH₄-N, oksijenin öbür birimi okuma
anında hesaplanıyor; rapor anlık görüntülerinde kimya yok). Bu yüzden eski bir örneğin NH₃'ü bugün formül 3 ile
gösterilir; bunu sessizce yapmamak için her hesaplanmış değerin başlığında (geçmiş ve son değerler tablosu, birim
çekmecesi, izleme kartları) "Formula 3: ionic strength 0.0072, from the conductivity at 25 °C." gibi bir not var;
hesaplayıcıda "Ionic strength" satırı ve aynı not. Eski formülün değeri istenirse çekirdek onu aynen yeniden üretir.

## Önce / sonra: tipik Norveç tatlı suları ve RAS suları (2, 5, 8, 12 °C)

"Önce" bugüne kadar gösterilen formül 1, "sonra" formül 3. Sular örnektir (literatür değeri değil): pH ve alkalinite
çiftlik tipik değerleri, iletkenlikler buna uygun seçildi. CO₂ mg/L, NH₃ payı TAN'ın yüzdesi, pH farkı serbest pH −
ölçülen (NBS) pH.

| Su | °C | pH | Alk. | CO₂ önce | CO₂ sonra | Fark | NH₃ payı önce (%) | sonra | Fark | pH farkı önce | sonra | İyonik şiddet (kaynak) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Yumuşak yüzey suyu (Norveç) | 2 | 6,8 | 10 | 4,98 | 4,86 | −%2,4 | 0,0614 | 0,0599 | −%2,4 | 0,000 | −0,011 | 0,0005 (conductivity) |
| Yumuşak yüzey suyu (Norveç) | 5 | 6,8 | 10 | 4,59 | 4,48 | −%2,4 | 0,0786 | 0,0767 | −%2,4 | 0,000 | −0,011 | 0,0005 (conductivity) |
| Yumuşak yüzey suyu (Norveç) | 8 | 6,8 | 10 | 4,25 | 4,15 | −%2,4 | 0,1000 | 0,0976 | −%2,4 | 0,000 | −0,011 | 0,0005 (conductivity) |
| Yumuşak yüzey suyu (Norveç) | 12 | 6,8 | 10 | 3,89 | 3,80 | −%2,4 | 0,1369 | 0,1336 | −%2,4 | 0,000 | −0,011 | 0,0005 (conductivity) |
| Kuyu / kireçlenmiş kuluçka suyu | 2 | 7,0 | 40 | 12,55 | 11,98 | −%4,6 | 0,0973 | 0,0928 | −%4,6 | 0,000 | −0,020 | 0,0019 (conductivity) |
| Kuyu / kireçlenmiş kuluçka suyu | 5 | 7,0 | 40 | 11,57 | 11,03 | −%4,6 | 0,1245 | 0,1187 | −%4,6 | 0,000 | −0,021 | 0,0019 (conductivity) |
| Kuyu / kireçlenmiş kuluçka suyu | 8 | 7,0 | 40 | 10,73 | 10,23 | −%4,6 | 0,1584 | 0,1511 | −%4,6 | 0,000 | −0,021 | 0,0019 (conductivity) |
| Kuyu / kireçlenmiş kuluçka suyu | 12 | 7,0 | 40 | 9,81 | 9,35 | −%4,7 | 0,2168 | 0,2067 | −%4,6 | 0,000 | −0,021 | 0,0019 (conductivity) |
| RAS tatlı su (smolt) | 2 | 7,2 | 120 | 23,75 | 21,69 | −%8,7 | 0,1540 | 0,1407 | −%8,6 | 0,000 | −0,039 | 0,0080 (conductivity) |
| RAS tatlı su (smolt) | 5 | 7,2 | 120 | 21,88 | 19,98 | −%8,7 | 0,1971 | 0,1800 | −%8,7 | 0,000 | −0,039 | 0,0080 (conductivity) |
| RAS tatlı su (smolt) | 8 | 7,2 | 120 | 20,30 | 18,52 | −%8,8 | 0,2508 | 0,2290 | −%8,7 | 0,000 | −0,040 | 0,0080 (conductivity) |
| RAS tatlı su (smolt) | 12 | 7,2 | 120 | 18,56 | 16,92 | −%8,8 | 0,3431 | 0,3131 | −%8,7 | 0,000 | −0,040 | 0,0080 (conductivity) |
| RAS tatlı su, yalnız alkalinite | 2 | 7,2 | 120 | 23,75 | 22,54 | −%5,1 | 0,1540 | 0,1462 | −%5,1 | 0,000 | −0,023 | 0,0024 (alkalinity) |
| RAS tatlı su, yalnız alkalinite | 5 | 7,2 | 120 | 21,88 | 20,76 | −%5,1 | 0,1971 | 0,1871 | −%5,1 | 0,000 | −0,023 | 0,0024 (alkalinity) |
| RAS tatlı su, yalnız alkalinite | 8 | 7,2 | 120 | 20,30 | 19,26 | −%5,1 | 0,2508 | 0,2380 | −%5,1 | 0,000 | −0,023 | 0,0024 (alkalinity) |
| RAS tatlı su, yalnız alkalinite | 12 | 7,2 | 120 | 18,56 | 17,60 | −%5,2 | 0,3431 | 0,3255 | −%5,1 | 0,000 | −0,023 | 0,0024 (alkalinity) |
| RAS tatlı su, sertlik 100 | 2 | 7,2 | 120 | 23,75 | 22,33 | −%6,0 | 0,1540 | 0,1449 | −%5,9 | 0,000 | −0,027 | 0,0034 (hardness) |
| RAS tatlı su, sertlik 100 | 5 | 7,2 | 120 | 21,88 | 20,57 | −%6,0 | 0,1971 | 0,1853 | −%6,0 | 0,000 | −0,027 | 0,0034 (hardness) |
| RAS tatlı su, sertlik 100 | 8 | 7,2 | 120 | 20,30 | 19,08 | −%6,0 | 0,2508 | 0,2358 | −%6,0 | 0,000 | −0,027 | 0,0034 (hardness) |
| RAS tatlı su, sertlik 100 | 12 | 7,2 | 120 | 18,56 | 17,43 | −%6,1 | 0,3431 | 0,3225 | −%6,0 | 0,000 | −0,027 | 0,0034 (hardness) |
| RAS acı su 3 ‰ | 2 | 7,3 | 120 | 15,16 | 15,03 | −%0,9 | 0,1531 | 0,1582 | +%3,3 | −0,085 | −0,080 | 0,0600 (salinity) |
| RAS acı su 3 ‰ | 5 | 7,3 | 120 | 13,84 | 13,81 | −%0,2 | 0,1982 | 0,2030 | +%2,4 | −0,082 | −0,079 | 0,0600 (salinity) |
| RAS acı su 3 ‰ | 8 | 7,3 | 120 | 12,71 | 12,77 | +%0,5 | 0,2552 | 0,2591 | +%1,5 | −0,078 | −0,079 | 0,0600 (salinity) |
| RAS acı su 3 ‰ | 12 | 7,3 | 120 | 11,45 | 11,62 | +%1,5 | 0,3544 | 0,3558 | +%0,4 | −0,074 | −0,078 | 0,0600 (salinity) |
| RAS acı su 12 ‰ (post-smolt) | 2 | 7,4 | 150 | 12,23 | 11,65 | −%4,8 | 0,1633 | 0,1714 | +%5,0 | −0,120 | −0,099 | 0,2420 (seawater) |
| RAS acı su 12 ‰ (post-smolt) | 5 | 7,4 | 150 | 11,12 | 10,67 | −%4,1 | 0,2134 | 0,2224 | +%4,2 | −0,114 | −0,096 | 0,2420 (seawater) |
| RAS acı su 12 ‰ (post-smolt) | 8 | 7,4 | 150 | 10,16 | 9,81 | −%3,4 | 0,2773 | 0,2868 | +%3,4 | −0,108 | −0,094 | 0,2420 (seawater) |
| RAS acı su 12 ‰ (post-smolt) | 12 | 7,4 | 150 | 9,07 | 8,85 | −%2,5 | 0,3896 | 0,3992 | +%2,5 | −0,100 | −0,089 | 0,2420 (seawater) |
| Deniz suyu 34 ‰ | 2 | 7,6 | 120 | 4,61 | 4,36 | −%5,4 | 0,2184 | 0,2306 | +%5,6 | −0,112 | −0,089 | 0,7014 (seawater) |
| Deniz suyu 34 ‰ | 5 | 7,6 | 120 | 4,19 | 3,99 | −%4,7 | 0,2881 | 0,3016 | +%4,7 | −0,103 | −0,083 | 0,7014 (seawater) |
| Deniz suyu 34 ‰ | 8 | 7,6 | 120 | 3,82 | 3,67 | −%3,9 | 0,3777 | 0,3923 | +%3,9 | −0,093 | −0,076 | 0,7014 (seawater) |
| Deniz suyu 34 ‰ | 12 | 7,6 | 120 | 3,39 | 3,30 | −%2,8 | 0,5368 | 0,5517 | +%2,8 | −0,079 | −0,067 | 0,7014 (seawater) |

Okuma:

- **Tatlı su**: CO₂ ve NH₃ payı birlikte düşüyor: yumuşak suda %2,4, kuyu suyunda %4,6, RAS'ta %5–9. Sıcaklıkla neredeyse
  değişmiyor (A soğukta küçüldüğü, iyonik şiddet aynı kaldığı için etki sabit). Önceki tablodaki 12 °C kaymaları
  (örn. tipik suda −%7,6) sabit ε = 79 yüzünden %7–8 abartılıydı; şimdiki değerler o abartıdan arınmış.
- **Acı su 3 ‰** (bantta): değişim küçük (CO₂ −%0,9 ile +%1,5, NH₃ +%0,4 ile +%3,3).
- **Deniz suyu ve 12 ‰**: yalnız NBS dönüşümünün A'sı değişti: soğukta CO₂ %3–5 düşük, NH₃ %3–6 **yüksek** görünüyor
  (2 °C'de en çok). NH₃ tarafı ihtiyatlı yönde; CO₂ tarafı değil.

## Soğuk su testleri (0–12 °C)

`farm/tests/test_cold_water.py`, çekirdekten bağımsız kaynaklara karşı:

- NH₃ payı, Emerson vd. (1975) tablosuyla (US EPA 1985'in yeniden basımı; 0, 5, 10, 12 °C; pH 7,0 / 7,5 / 8,0): hiçbir
  şey ölçülmemiş suda (I = 0) tablonun %0,6'sı içinde (en kötü 0 °C, pH 7,5: −%0,5).
- pK1, pK2: Plummer & Busenberg (1982) ifadeleri (USGS PHREEQC veritabanının sayıları) ile 0–12 °C'de 0,002 içinde;
  pKw Harned & Hamer (wateq4f) ile 0,007 içinde (çekirdek 0,005–0,006 yukarıda); CO₂ çözünürlüğü (Weiss 1974) 0,002 log
  içinde.
- Serbest CO₂: Plummer & Busenberg sabitleri, Davies ve Hamer'ın A tablosuyla yazılmış bağımsız bir hesapla, tipik
  Norveç suları için 2, 5, 8, 12 °C'de %0,5 içinde.
- PyCO2SYS (GPL) ve PHREEQC'nin kodu kullanılmadı ve kopyalanmadı; yalnız PHREEQC veritabanının (kamu malı) analitik
  ifadelerinin katsayıları sayı olarak alındı.

## Zayıf noktalar (geçişten sonra, dürüstçe)

- **Deniz suyunda soğukta CO₂ biraz daha düşük görünüyor** (2 °C'de −%5,4). Takahashi'ye göre daha doğru, ama CO₂ sınırına
  yakın bir deniz suyu birimi "uyarı"dan "güvenli"ye geçebilir. NH₃ ise aynı yerde %5,6 daha yüksek (ihtiyatlı).
- **Tatlı suda CO₂ ve NH₃ daha düşük görünüyor** (%2–9): bu bilinçli ve literatüre uygun, ama sınıra yakın bir su
  "uyarı"dan "güvenli"ye geçebilir. İletkenlik yanlış girilirse (ör. telafisiz ya da mS/cm) iyonik şiddet yanlış olur;
  0,5'in üstü reddedilir, altındaki hatalar yakalanmaz.
- **Sertlik ve yalnız alkalinite alt sınırdır**; ölçülmeyen iyonlar (Na, Cl, SO₄) iyonik şiddeti artırır. İletkenlik
  ölçülürse en iyisi o.
- **Bant içinde çıktı hafifçe geri dönebiliyor** (yalnız tuzlulukta NH₃ en çok %0,44; tutarsız iletkenlik–tuzluluk
  çiftinde %3,1). Sıçrama yok.
- **Dozlama ve simülatör** suyun dozdan önceki iyonik şiddetini kullanıyor; bir dozun kendi iyonları (ör. NaHCO₃'ün
  sodyumu) eklenmiyor. Tipik dozlarda etki küçük, ama ölçülmedi.
- **Kaynak doğrulaması**: Malmberg & Maryott (1956) ve Hamer (1968) tabloları birincil kaynaktan okundu; Kell (1975)
  katsayıları ikincil (NIST 1992 kopyası, bir baskı hatası düzeltilerek); Davies (1962) sayfa numarası, Stumm & Morgan
  tablo 3.3, Russell (1976) 1,6·10⁻⁵ katsayısı birincil kaynaktan **doğrulanamadı** (yalnız ikincil); Takahashi fH
  formülü seacarb/CO2SYS kodundan.

Kaynaklar: Davies (1962) *Ion Association*, Butterworths; Russell (1976) *J. AWWA* 68: 2; Snoeyink & Jenkins (1980)
*Water Chemistry*; Stumm & Morgan (1996) *Aquatic Chemistry*, 3. baskı, bölüm 3.4; Plummer & Busenberg (1982) *GCA* 46:
1011; DOE (1994) *Handbook of methods*, bölüm 5; Millero vd. (2006) *Mar. Chem.* 100: 80; Dickson (1990) *J. Chem.
Thermodyn.* 22: 113 ve *Deep-Sea Res.* 37: 755; Malmberg & Maryott (1956) *J. Res. NBS* 56: 1; Kell (1975) *J. Chem. Eng.
Data* 20: 97; Hamer (1968) NSRDS-NBS 24; Nordstrom vd. (1984) USGS WRI 84-4186; Takahashi vd. (1982) GEOSECS Pacific
Expedition 3; Zeebe & Wolf-Gladrow (2001) *CO₂ in Seawater*; Emerson vd. (1975) *J. Fish. Res. Board Can.* 32: 2379;
Harned & Hamer (1933) *JACS* 55: 2194; Weiss (1974) *Mar. Chem.* 2: 203; APHA *Standard Methods* 2510.
