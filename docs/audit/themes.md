# Temalar ve öncelikli düzeltme yol haritası

Bu belge, `MASTER-FINDINGS.md` içindeki tekil kayıtları tekrar eden kök nedenlere göre gruplar. Kayıt bağlantıları (F-xxx) master dosyadaki başlıklara gider. Önem etiketleri doğrulama sonrası nihai önemdir; hiçbir kayıt Yüksek düzeyde değildir. Yol haritasındaki öncelikler (P0-P3) bu konsolidasyonun önerisidir, uzmanların ortak kararı değildir.

## Tema özeti

| Tema | Öncelik | Kayıt sayısı |
|---|---|---:|
| T1 Fail-open üretim yapılandırması | P0 | 13 |
| T2 Dağıtım, CI ve operasyon hattı yok | P0 | 12 |
| T3 Yedekleme, kalıcılık ve geri dönüş | P0 | 6 |
| T4 Soft delete / restore tutarsızlıkları | P1 | 11 |
| T5 GET ile yazma | P1 | 2 |
| T6 Eşzamanlılık, kilit ve yakalanmayan istisna (500) | P1 | 11 |
| T7 Denetim izi kapsamı ve bütünlüğü | P1 | 9 |
| T8 Performans: tümünü katla, sonra sayfala | P2 | 10 |
| T9 Yetki matrisi ile gerçek yetki uyuşmazlığı | P2 | 9 |
| T10 XSS savunma zinciri | P2 | 4 |
| T11 Gözlemlenebilirlik ve sessiz hata | P2 | 7 |
| T12 Frontend: modal, erişilebilirlik ve duyuru | P3 | 8 |
| T13 Alanlar arası kural ve tanım tutarsızlıkları | P2 | 10 |
| T14 Durum makineleri ve yaşam döngüsü boşlukları | P2 | 4 |
| T15 Test boşlukları | P3 | 8 |
| T16 Mimari ve kod tekrarı | P3 | 6 |

## T1 Fail-open üretim yapılandırması (P0)

`config/settings.py` ve `docker-compose.yml` güvensiz varsayılanlara düşüyor: SECRET_KEY ve DEBUG varsayılanları, cookie/HTTPS/HSTS ayarlarının yokluğu, konsol e-posta backend'i, LOGGING yokluğu, zayıf DB parolası. Aynı kök neden en az 8 uzmanda ayrı kayıt olarak göründü ve önem dereceleri tutarsız verildi (Yüksek/Orta/Düşük); doğrulama Orta olarak sabitledi. Tek bir "üretim profili" ayarı bu kümenin büyük kısmını kapatır.

- [F-001](MASTER-FINDINGS.md#f-001) (Orta) SECRET_KEY ve DEBUG güvensiz varsayılanları (fail-open)
- [F-004](MASTER-FINDINGS.md#f-004) (Orta) Cookie/HTTPS/HSTS sertleştirme ayarları yok
- [F-014](MASTER-FINDINGS.md#f-014) (Orta) E-posta konsol backend (davet/parola sıfırlama üretime hazır değil)
- [F-033](MASTER-FINDINGS.md#f-033) (Orta) DB kimlik bilgisi/parola varsayılanı zayıf (compose/settings)
- [F-040](MASTER-FINDINGS.md#f-040) (Orta) Üretim/geliştirme yapılandırma ayrımı yok
- [F-043](MASTER-FINDINGS.md#f-043) (Orta) Üretim için LOGGING yapılandırması yok; DEBUG=False iken yakalanmayan 500 hataları hiçbir yere yazılmaz
- [F-051](MASTER-FINDINGS.md#f-051) (Orta) Content-Security-Policy tanımlı değil
- [F-171](MASTER-FINDINGS.md#f-171) (Orta) Kimlik/yapılandırma bulguları PII etkisi açısından birleşiyor: sabit SECRET_KEY + DEBUG + console e-posta
- [F-235](MASTER-FINDINGS.md#f-235) (Orta) Python/Node sürüm bildirimi yok; minimum sürüm belirsiz
- [F-241](MASTER-FINDINGS.md#f-241) (Orta) README uretim/dagitim, yedekleme ve DEBUG varsayilani konusunda sessiz
- [F-426](MASTER-FINDINGS.md#f-426) (Düşük) Yükleme boyutu global sınırları ve proxy/HTTPS başlığı ayarları yok
- [F-603](MASTER-FINDINGS.md#f-603) (Düşük) next ve e-posta bağlantıları Host başlığına güveniyor; ALLOWED_HOSTS DEBUG varsayılanına bağlı
- [F-649](MASTER-FINDINGS.md#f-649) (Düşük) Guvensiz varsayilanlar icin .env.example yok; fail-open ayarlar belgesiz

## T2 Dağıtım, CI ve operasyon hattı yok (P0)

Dockerfile, uygulama sunucusu, statik dosya hattı, CI, zamanlayıcı ve sürüm bildirimi repoda yok; README gunicorn/cron varsayar. Depo yerel geliştirme düzeyinde; "üretime hazır" varsayımı doğrulanamaz.

- [F-002](MASTER-FINDINGS.md#f-002) (Orta) GET isteklerinde materialise_due yazması
- [F-011](MASTER-FINDINGS.md#f-011) (Orta) Dockerfile/üretim imajı yok
- [F-012](MASTER-FINDINGS.md#f-012) (Orta) Statik dosya üretim hattı yok
- [F-028](MASTER-FINDINGS.md#f-028) (Orta) CI/CD pipeline yok
- [F-047](MASTER-FINDINGS.md#f-047) (Orta) Statik varlık mtime sürümleme her istekte dosya sistemi
- [F-126](MASTER-FINDINGS.md#f-126) (Orta) Repoda CI tanimi yok; `CI=1` korumasi bos
- [F-132](MASTER-FINDINGS.md#f-132) (Orta) Üretim uygulama sunucusu (gunicorn) bağımlılıklarda yok
- [F-236](MASTER-FINDINGS.md#f-236) (Orta) Migrate oncesi yedek/geri donus adimi belgelenmemis
- [F-431](MASTER-FINDINGS.md#f-431) (Düşük) README gunicorn/cron varsayar, repoda karşılığı yok
- [F-604](MASTER-FINDINGS.md#f-604) (Düşük) Compose'un DB varsayılan kullanıcısı superuser; migration'ların uzantı gereksinimi belgelenmemiş
- [F-607](MASTER-FINDINGS.md#f-607) (Düşük) TimescaleDB uzantı sürümü ile migration bağı belgesiz
- [F-614](MASTER-FINDINGS.md#f-614) (Düşük) Tek komutla (down -v) tum veri silinebilir, uyari yok

## T3 Yedekleme, kalıcılık ve geri dönüş (P0)

DB yedeği, medya (MEDIA_ROOT) yedeği, migrate öncesi geri dönüş adımı ve geri yükleme prosedürü yok; belge dosyası değiştirilince eski dosya geri dönülemez siliniyor. Doğrulama şiddeti düşürdü (dev compose), ancak üretimde karşılığı da yok.

- [F-007](MASTER-FINDINGS.md#f-007) (Orta) MEDIA_ROOT/yüklenen dosyalar için kalıcılık ve yedek yok
- [F-008](MASTER-FINDINGS.md#f-008) (Orta) PDF yükleme rollback sonrası yetim dosya
- [F-018](MASTER-FINDINGS.md#f-018) (Orta) Belge dosyası değişince eski dosya geri dönülemez
- [F-023](MASTER-FINDINGS.md#f-023) (Orta) Hiçbir yedekleme mekanizması veya geri yükleme prosedürü yok
- [F-243](MASTER-FINDINGS.md#f-243) (Orta) Geri alma/düzeltme penceresi dolunca eski kayıtlar kilitli kalıyor, yönetici düzeltme yolu yok
- [F-249](MASTER-FINDINGS.md#f-249) (Düşük) Tek adlandırılmış Docker volume, redundancy ve yedek yok

## T4 Soft delete / restore tutarsızlıkları (P1)

restore() kilitsiz, kısmi (cascade çocukları ve SET_NULL bağları dönmüyor), audit satırında değer yok; silme onayı "admin'den geri alınabilir" diyor ama admin dışı yol yok; tekrarlayan görev silme/geri yükleme planlı görevleri kaybediyor; silinen veri ise veri sahibi talebiyle çelişiyor.

- [F-003](MASTER-FINDINGS.md#f-003) (Orta) restore() kilitsiz/sürümsüz/kısmi
- [F-016](MASTER-FINDINGS.md#f-016) (Orta) Append-only audit log ile silme/KVKK talebi çelişkisi
- [F-029](MASTER-FINDINGS.md#f-029) (Orta) Tekrarlayan görev silme/geri yükleme ile planlı görevler
- [F-036](MASTER-FINDINGS.md#f-036) (Orta) SET_NULL ile kopan bağlar restore edilince geri bağlanmaz
- [F-041](MASTER-FINDINGS.md#f-041) (Orta) Silme onayı metni admin geri getirme iddiası
- [F-172](MASTER-FINDINGS.md#f-172) (Orta) restore() cascade çocuklarını geri getirmez
- [F-237](MASTER-FINDINGS.md#f-237) (Orta) Hard delete audit kayıtları değer taşımıyor: record_delete snapshot almıyor, withdraw/closure silmeleri yalnız etiket bırakıyor
- [F-427](MASTER-FINDINGS.md#f-427) (Düşük) restore/soft delete audit satırında değer yok, hard delete kurtarma bilgisi eksik
- [F-619](MASTER-FINDINGS.md#f-619) (Düşük) DueClosure hard delete ile audit referansı değersiz; şema soft-delete'e geçmeli
- [F-671](MASTER-FINDINGS.md#f-671) (Bilgi) Django admin yalnızca superuser ile erişilir; `AuditedModelAdmin.restore` günlüğe yazılmayan geri yükleme yolu
- [F-690](MASTER-FINDINGS.md#f-690) (Bilgi) Yönetici geri getirmesi yalnızca Django admin içinde; uygulama arayüzünde çöp kutusu yok

## T5 GET ile yazma (P1)

`materialise_due`, okundu işaretçisi ve audit "system" satırları okuma izniyle ve GET ile tetikleniyor; hata izolasyonu yok, çok düğümlü çalışmada çift üretim riski. Zamanlayıcı olmadığı için GET tek tetikleyici.

- [F-002](MASTER-FINDINGS.md#f-002) (Orta) GET isteklerinde materialise_due yazması
- [F-628](MASTER-FINDINGS.md#f-628) (Düşük) Scheduler yok ve cok dugumlu cron kilitsiz materialise_due ile cift gorev uretebilir

## T6 Eşzamanlılık, kilit ve yakalanmayan istisna (500) (P1)

UpdateView/RowListView, close_due, messaging.post, restore ve girdi ayrıştırma yollarında DoesNotExist/IntegrityError/ValueError yakalanmıyor; doğrulama kilit dışında. Kullanıcıya 500 döner, DEBUG açıksa ayrıntı sızar.

- [F-003](MASTER-FINDINGS.md#f-003) (Orta) restore() kilitsiz/sürümsüz/kısmi
- [F-006](MASTER-FINDINGS.md#f-006) (Orta) isdigit() Unicode rakamda 500
- [F-009](MASTER-FINDINGS.md#f-009) (Orta) UpdateView/RowListView kilit altında kayıt bulunamama (500)
- [F-024](MASTER-FINDINGS.md#f-024) (Orta) Kısmen mevcut hücrelerde CLEAR toplu işlemi AttributeError ile çöker
- [F-034](MASTER-FINDINGS.md#f-034) (Orta) UpdateView IntegrityError yakalanmıyor
- [F-204](MASTER-FINDINGS.md#f-204) (Orta) Yıllık izin kotası denetimi eşzamanlılığa karşı korumasız
- [F-252](MASTER-FINDINGS.md#f-252) (Düşük) close_due/record_duty_done/copy_template ön koşul işlem dışında
- [F-253](MASTER-FINDINGS.md#f-253) (Düşük) messaging.post silinmiş konuşmada DoesNotExist
- [F-505](MASTER-FINDINGS.md#f-505) (Düşük) Form yolu `ShiftAssignmentForm` kilitsiz değerlendirme yapar, servis yolu kilitler
- [F-621](MASTER-FINDINGS.md#f-621) (Düşük) Su gecmisi ?to=9999-12-31 OverflowError (500) ve from>to sessiz bos sonuc
- [F-642](MASTER-FINDINGS.md#f-642) (Düşük) Gerçek eşzamanlı yarış testi yok; kilit sırası ve bayat liste senaryoları doğrulanmıyor

## T7 Denetim izi kapsamı ve bütünlüğü (P1)

Kimlik doğrulama olayları audit dışında, hard delete kayıtları değer taşımıyor, "system" satırları tetikleyeni gizliyor, TRUNCATE/DROP TRIGGER negatif testi yok, audit append-only ama KVKK silme talebiyle çelişiyor.

- [F-016](MASTER-FINDINGS.md#f-016) (Orta) Append-only audit log ile silme/KVKK talebi çelişkisi
- [F-031](MASTER-FINDINGS.md#f-031) (Orta) Kimlik doğrulama olayları audit kaydında yok
- [F-237](MASTER-FINDINGS.md#f-237) (Orta) Hard delete audit kayıtları değer taşımıyor: record_delete snapshot almıyor, withdraw/closure silmeleri yalnız etiket bırakıyor
- [F-259](MASTER-FINDINGS.md#f-259) (Düşük) Mesaj silme izi ve moderasyon yok
- [F-606](MASTER-FINDINGS.md#f-606) (Düşük) Dosya okuma izi yok ve audit_log TRUNCATE'e açık: iz bırakmadan erişim ve iz silme
- [F-615](MASTER-FINDINGS.md#f-615) (Düşük) Otomatik üretilen planlı görevler log'da 'system' olarak görünür, tetikleyen kullanıcı kaybolur
- [F-616](MASTER-FINDINGS.md#f-616) (Düşük) queryset.update() yazmaları (experiments _touch/_park) version ve updated_at ile audit tutarlılığına bağımlı, değiştirilemezlik kapsamı dışı
- [F-618](MASTER-FINDINGS.md#f-618) (Düşük) audit_log action değerleri için DB CHECK yok, severity için var
- [F-645](MASTER-FINDINGS.md#f-645) (Düşük) Audit log degistirilemezligi icin TRUNCATE/DROP TRIGGER negatif testi yok

## T8 Performans: tümünü katla, sonra sayfala (P2)

İzleme duvarı, hasat listesi, envanter sayımları, rapor due listesi, su geçmişi ve DB gezgini tüm veriyi/defteri her istekte yeniden okuyup bellekte süzüyor. Önbellek/okuma modeli katmanı yok (31-X3). Doğrulayıcılar bunu ölçülmemiş varsayım olarak Orta tuttu; ölçüm yapılmadı. Menü rozeti iddiası (35-2) doğrulanamadı.

- [F-015](MASTER-FINDINGS.md#f-015) (Orta) PDF metin çıkarımı istek içinde, sınırsız
- [F-019](MASTER-FINDINGS.md#f-019) (Orta) Su geçmişi tarih aralığı sınırsız
- [F-022](MASTER-FINDINGS.md#f-022) (Orta) Envanter "Sayımlar" sekmesi her sayım satırı için tüm envanter defterini yeniden katlar (N+1, sayfa başına 20 tam yeniden hesap)
- [F-026](MASTER-FINDINGS.md#f-026) (Orta) Izleme duvari her yenilemede tum stok defterini ve tum yemleme gecmisini yeniden katliyor
- [F-027](MASTER-FINDINGS.md#f-027) (Orta) Hasat listesi butun hasat gecmisini ve tum batch defterlerini katlayip sonra sayfaliyor
- [F-039](MASTER-FINDINGS.md#f-039) (Orta) Veritabanı görüntüleyici gereksiz sorgular
- [F-044](MASTER-FINDINGS.md#f-044) (Orta) Rapor "due" listesi her cagrida tum siteleri/donemleri bastan hesapliyor; ana sayfa dahil her yerde cagriliyor
- [F-240](MASTER-FINDINGS.md#f-240) (Orta) Onbellek/okuma-modeli katmaninin yoklugu mimari bir karar olarak belgelenmemis; performans bulgularinin ortak kok nedeni
- [F-644](MASTER-FINDINGS.md#f-644) (Düşük) Satir basi silme ve audit: withdraw ve soft-delete planlari ayni O(n) sorgu desenini paylasiyor
- [F-665](MASTER-FINDINGS.md#f-665) (Düşük) Menu rozeti (okunmamis mesaj) her sayfada ve 30 sn'de bir tum Message tablosunu tarayabilir

## T9 Yetki matrisi ile gerçek yetki uyuşmazlığı (P2)

İzinler çiftlik genelinde global (satır/site kapsamı yalnız HR'de), "Read" izni bazı yerlerde yazma içeriyor, rol önayarları matrisle uyuşmuyor, envanter hareketlerinde görev ayrılığı yok, özel 403 şablonu yok.

- [F-032](MASTER-FINDINGS.md#f-032) (Orta) batch_details/matris etiketi gerçek yetkiyle uyuşmuyor
- [F-046](MASTER-FINDINGS.md#f-046) (Orta) Production manager önayarı ile matris uyumsuzluğu
- [F-049](MASTER-FINDINGS.md#f-049) (Orta) HR dışında hiçbir satır/site/departman kapsamı yok: izinler tüm çiftlik verisi için global
- [F-050](MASTER-FINDINGS.md#f-050) (Orta) Aktivite günlüğünde yalnızca HR kayıt türleri kısıtlı; diğer hassas günlükler `core.view_auditlog` sahibine açık
- [F-099](MASTER-FINDINGS.md#f-099) (Orta) `clock_in/clock_out` yalnızca `view_attendancerecord` ile yazma yapar
- [F-234](MASTER-FINDINGS.md#f-234) (Orta) Envanter: tüm hareket türleri tek izne bağlı (görev ayrılığı yok)
- [F-248](MASTER-FINDINGS.md#f-248) (Düşük) view_task sahibi her göreve not ekleyebilir (Read=yazma)
- [F-635](MASTER-FINDINGS.md#f-635) (Düşük) Mesajlaşma için otomatik URL-yetki taraması yok
- [F-825](MASTER-FINDINGS.md#f-825) (Bilgi) Özel 403 şablonu yok; raise_exception=True kullanan çok sayıda view çıplak 403 döndürür

## T10 XSS savunma zinciri (P2)

`|safe` ile basılan help_text, CSP yokluğu, innerHTML sink'leri ve aynı kökenden inline PDF birlikte düşünülmeli; tek başına her biri düşük, birlikte depolanmış HTML enjeksiyonu için zemin hazırlar (istismar için ayrıcalıklı yazma yetkisi gerekir).

- [F-005](MASTER-FINDINGS.md#f-005) (Orta) help_text \|safe ile kaçışsız basılıyor
- [F-051](MASTER-FINDINGS.md#f-051) (Orta) Content-Security-Policy tanımlı değil
- [F-246](MASTER-FINDINGS.md#f-246) (Düşük) PDF aynı kökenden inline sunum, ek başlık yok
- [F-256](MASTER-FINDINGS.md#f-256) (Düşük) innerHTML sink + CSP yok

## T11 Gözlemlenebilirlik ve sessiz hata (P2)

LOGGING yok, zorunlu kaynak hataları kaydedilmeden Unavailable'a çevriliyor, sensör kesintisinde kart OK kalıyor (fail-open), worker-yerel durum.

- [F-025](MASTER-FINDINGS.md#f-025) (Orta) monitoring.read.cards: zorunlu kaynak hatası her türlü istisnayı yutup günlüğe yazmadan Unavailable'a çevirir
- [F-043](MASTER-FINDINGS.md#f-043) (Orta) Üretim için LOGGING yapılandırması yok; DEBUG=False iken yakalanmayan 500 hataları hiçbir yere yazılmaz
- [F-244](MASTER-FINDINGS.md#f-244) (Orta) Sensör kesintisi senaryosu: bayat veri alarmı kaldırıyor ve limit yokken kart OK kalıyor (fail-open)
- [F-539](MASTER-FINDINGS.md#f-539) (Düşük) farm.placements.of: bozuk sağlayıcı her istekte günlüğe istisna basar (throttle yok), üstelik TypeError dahil her şeyi yutar
- [F-646](MASTER-FINDINGS.md#f-646) (Düşük) LOGGING, DEBUG varsayilani ve hata isleyicileri icin test yok
- [F-666](MASTER-FINDINGS.md#f-666) (Bilgi) Ters yönlü kayıt desenleri (olumlu, ama hata yutma riski)
- [F-817](MASTER-FINDINGS.md#f-817) (Bilgi) Worker-yerel durum ve gözlemlenebilirlik eksikliği aynı kökten

## T12 Frontend: modal, erişilebilirlik ve duyuru (P3)

Modal ağ/HTTP hatalarını işlemiyor, flash role=status, izleme duvarı uyarısı yalnız CSS ile, form hata/yardım metni alana bağlı değil, ok tuşu kısayolları belgesiz.

- [F-010](MASTER-FINDINGS.md#f-010) (Orta) Modal istemcisi ağ/HTTP hataları ele alınmıyor
- [F-042](MASTER-FINDINGS.md#f-042) (Orta) Form alanı kenarlık kontrastı WCAG
- [F-045](MASTER-FINDINGS.md#f-045) (Orta) İzleme duvarında "bağlantı yok / eski veri" uyarısı yalnızca CSS `::before content:` ile basılıyor
- [F-158](MASTER-FINDINGS.md#f-158) (Orta) Mobil off-canvas menü kapalıyken odaklanabilir ve ekran okuyucuya açık; odak tuzağı/`inert` yok
- [F-225](MASTER-FINDINGS.md#f-225) (Orta) Form hata mesajları alanlara bağlanmamış; zorunlu alan görsel göstergesi yok
- [F-242](MASTER-FINDINGS.md#f-242) (Orta) _field.html hata ve yardım metinlerini alana bağlamıyor
- [F-254](MASTER-FINDINGS.md#f-254) (Düşük) Flash mesajları role=status (hata dahil)
- [F-262](MASTER-FINDINGS.md#f-262) (Düşük) Hareketli pencerelerde ok tuşları gövde kaydırmasını engelliyor; klavye kısayolları belgelenmemiş

## T13 Alanlar arası kural ve tanım tutarsızlıkları (P2)

Aynı sıcaklık üç farklı tanımla hesaplanıyor, sitesiz üniteler stok defterine yansımıyor, plan/harvest çift sayımı, tedavi seçimi neden alanına bağlı, deney kayıp türü iki modülde ayrı, HR istihdam tarihleri zorlanmıyor.

- [F-020](MASTER-FINDINGS.md#f-020) (Orta) Sitesiz üretim bölümü yemlemesi yem stoğuna yansımıyor
- [F-096](MASTER-FINDINGS.md#f-096) (Orta) İstihdam tarihleri (joined_on/left_on) vardiya, yoklama ve izin yazımlarında zorlanmıyor
- [F-098](MASTER-FINDINGS.md#f-098) (Orta) `rest_rule` etiketi hafta saati ve ardışık gün kurallarını da kapsıyor görünür ama kod sadece dinlenme için uygular
- [F-238](MASTER-FINDINGS.md#f-238) (Orta) Plan kalemi ile harvest farklı haftaya düşünce planlı kesim raporunda çift sayım
- [F-239](MASTER-FINDINGS.md#f-239) (Orta) Bit raporunun tedavi seçimi neden alanına bağlı, sağlık servisi ilaç-neden ilişkisini zorlamıyor
- [F-261](MASTER-FINDINGS.md#f-261) (Düşük) Besleme çekişi silo/besleyici bağını kullanmıyor
- [F-428](MASTER-FINDINGS.md#f-428) (Düşük) Aynı sıcaklık için üç ayrı tanım (arınma, bit raporu, su kartı)
- [F-625](MASTER-FINDINGS.md#f-625) (Düşük) 31 gun geriye donuk pencere stok, tedavi voidi ve change_last_day icin ortak ama devir yolu yok
- [F-662](MASTER-FINDINGS.md#f-662) (Düşük) Rapor tamlığı kullanıcı bağlantılarına bağlı; due listesi çapraz doğrulama yapmıyor
- [F-812](MASTER-FINDINGS.md#f-812) (Bilgi) Deney sağkalımı farm.feeding.fold.LOST kümesine bağlı; kayıp türü tanımı iki modülde ortak değil

## T14 Durum makineleri ve yaşam döngüsü boşlukları (P2)

Çalışan deney kapatılamıyor, geri alma penceresi dolunca yönetici düzeltme yolu yok, form ve servis farklı geçiş kuralları uyguluyor, Supplier/Location durumları asimetrik.

- [F-013](MASTER-FINDINGS.md#f-013) (Orta) Çalışan deney kapatılamıyor (running->closed)
- [F-243](MASTER-FINDINGS.md#f-243) (Orta) Geri alma/düzeltme penceresi dolunca eski kayıtlar kilitli kalıyor, yönetici düzeltme yolu yok
- [F-429](MASTER-FINDINGS.md#f-429) (Düşük) Supplier/Location durum alanı davranışsız/asimetrik
- [F-663](MASTER-FINDINGS.md#f-663) (Düşük) Form ve servis katmanları farklı geçiş kuralları uyguluyor (atama son günü)

## T15 Test boşlukları (P3)

CI yok, tarayıcı testleri sessizce skip, CSRF/kimlik/performans/yarış testi yok, URL-yetki taraması yalnız bazı uygulamalarda.

- [F-127](MASTER-FINDINGS.md#f-127) (Orta) Tarayici (Playwright) testleri sessizce skip oluyor
- [F-128](MASTER-FINDINGS.md#f-128) (Orta) CSRF korumasi hicbir testte dogrulanmiyor
- [F-220](MASTER-FINDINGS.md#f-220) (Orta) Yeni yazilan her URL icin yetki taramasi sadece bazi uygulamalarda otomatik
- [F-371](MASTER-FINDINGS.md#f-371) (Düşük) N+1 / sorgu sayisi korumasi cok az
- [F-549](MASTER-FINDINGS.md#f-549) (Düşük) Kimlik dogrulama: yalniz temel login/logout testi, kaba-kuvvet/oturum testleri yok
- [F-635](MASTER-FINDINGS.md#f-635) (Düşük) Mesajlaşma için otomatik URL-yetki taraması yok
- [F-642](MASTER-FINDINGS.md#f-642) (Düşük) Gerçek eşzamanlı yarış testi yok; kilit sırası ve bayat liste senaryoları doğrulanmıyor
- [F-647](MASTER-FINDINGS.md#f-647) (Düşük) Performans ve kimlik olaylari bulgulari icin regresyon testi yok

## T16 Mimari ve kod tekrarı (P3)

next doğrulayıcısı birden çok kopya, void/silme şablonları kopya, farm alt paketleri arasında döngüsel bağımlılık, katman atlayan importlar.

- [F-116](MASTER-FINDINGS.md#f-116) (Orta) farm alt paketleri arasında paket-düzeyi döngüsel bağımlılık
- [F-245](MASTER-FINDINGS.md#f-245) (Düşük) next yönlendirme doğrulayıcısı çoklu kopya, tutarsız
- [F-364](MASTER-FINDINGS.md#f-364) (Düşük) Kimya sabitleri satır içi ve tekrar ediyor
- [F-636](MASTER-FINDINGS.md#f-636) (Düşük) Servis/okuma katmanlari farm.stock.dates gibi alt modullere geniş bagimli; hr, inventory, reports farm iç modüllerini import ediyor
- [F-667](MASTER-FINDINGS.md#f-667) (Bilgi) Test dosya adlandırması tutarsız
- [F-815](MASTER-FINDINGS.md#f-815) (Bilgi) Ortak 'void' diyalogu ve silme akisi sablonlari app bazinda kopya: sablon katmaninda mimari soyutlama eksik

## Yol haritası

**P0: üretime çıkmadan önce (güvenlik ve işletilebilirlik temeli)**

1. Üretim profili: SECRET_KEY zorunlu (yoksa başlama), DEBUG varsayılanı kapalı, secure cookie/HSTS/proxy başlıkları, `check --deploy` temiz; gerçek e-posta backend'i; DB parolası ortam değişkeninden (T1).
2. Dağıtım artefaktları: Dockerfile, uygulama sunucusu, STATIC_ROOT/collectstatic, zamanlayıcı (`generate_tasks`), minimum Python/Node sürümleri; CI (test + `check --deploy`) (T2).
3. Yedekleme ve geri yükleme: DB + MEDIA_ROOT birlikte yedek, migrate öncesi adım, belge dosyası silme politikası (T3).
4. LOGGING yapılandırması (T1/T11).

**P1: veri bütünlüğü ve tutarlılık**

5. restore()/soft delete: kilit + atomiklik, cascade ve SET_NULL geri yükleme kararı, audit satırlarında değer (T4, T7).
6. GET ile yazmayı kaldır: `materialise_due` yalnızca komut/zamanlayıcıdan, kilitli (T5).
7. Genel istisna koruması: UpdateView/RowListView, close_due, messaging.post, girdi ayrıştırma için ortak yardımcılar (T6).
8. Audit kapsamı: kimlik doğrulama olayları, hard delete değer anlık görüntüsü (T7).

**P2: doğruluk ve performans (ölçerek)**

9. Önce ölçüm: izleme duvarı, hasat listesi, envanter sayımları, due listesi için sorgu sayısı/süre ölçümü, sonra önbellek veya sayfalama (T8). Ölçüm yapılmadan yapılan değişiklikler doğrulayıcıların da işaret ettiği gibi varsayıma dayanır.
10. Yetki matrisi ve rol önayarları hizalama; XSS zinciri (|safe kaldırma, CSP report-only) (T9, T10).
11. Alanlar arası tanım birliği (sıcaklık, sitesiz ünite stoğu, LOST kümesi) ve durum makinesi boşlukları (deney kapatma) (T13, T14).

**P3: kalite ve ergonomi**

12. Erişilebilirlik ve modal hata yönetimi (T12); test boşlukları (T15); kod tekrarı ve katmanlama (T16).

## Önem çelişkileri

Aynı kök nedene farklı uzmanların verdiği özgün önemler birbirinden farklıydı. Aşağıdaki kümelerde özgün önem aralığı en az iki kademe:

| Kayıt | Özgün aralık | Nihai | Başlık |
|---|---|---|---|
| [F-001](MASTER-FINDINGS.md#f-001) | Yüksek..Bilgi | Orta | SECRET_KEY ve DEBUG güvensiz varsayılanları (fail-open) |
| [F-002](MASTER-FINDINGS.md#f-002) | Orta..Bilgi | Orta | GET isteklerinde materialise_due yazması |
| [F-004](MASTER-FINDINGS.md#f-004) | Orta..Bilgi | Orta | Cookie/HTTPS/HSTS sertleştirme ayarları yok |
| [F-007](MASTER-FINDINGS.md#f-007) | Yüksek..Düşük | Orta | MEDIA_ROOT/yüklenen dosyalar için kalıcılık ve yedek yok |
| [F-011](MASTER-FINDINGS.md#f-011) | Yüksek..Düşük | Orta | Dockerfile/üretim imajı yok |
| [F-013](MASTER-FINDINGS.md#f-013) | Yüksek..Düşük | Orta | Çalışan deney kapatılamıyor (running->closed) |
