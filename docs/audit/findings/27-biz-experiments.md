# 27 - biz-experiments: Deneyler modülü denetimi

## Özet

`experiments/` uygulaması (models, services, design, read, forms, resources, integrity, allocation, migrations 0001-0002, docs/experiments.md) satır satır okundu; testler çalıştırılmadı (DB gerektirir). Modül genel olarak olgun: tasarım dondurma tetikleyicileri, bileşik FK'ler, dışlama kısıtı (bir tank aynı anda tek deneyde), kilit sırası, sürüm kontrolü ve tohumlu (sha256_v1) dağıtım iyi düşünülmüş ve test edilmiş. Bulgular çoğunlukla (a) deney başına yetkilendirmenin yokluğu, (b) deneyin yazdığı besleme atamalarının çiftlik tarafında korunmaması, (c) sağkalım ve veri sekmesi rakamlarındaki tutarlılık boşlukları, (d) tahsis (randomizasyon) tekrarlanabilirliğinin sözlenen kadar sağlam olmaması ve (e) doküman/kod sapmalarıdır. Kritik veya yüksek önemde bulgu yok.

## İncelenen alanlar

- experiments/models.py (kısıtlar, durum makinesi, Member/Replicate/ReplicateUnit)
- experiments/services.py (save_design, save_places, randomise, move_span, start, copy, release_unit, replace_unit)
- experiments/design.py (kontroller, HOLDS_AFTER_START), integrity.py, allocation.py, variables.py, read.py (overview, survival, conversion, data, deviations, chips)
- experiments/forms.py, resources.py, admin.py, urls.py, management/commands/check_experiments.py
- migrations/0001 (bileşik FK), 0002 (dondurma tetikleyicileri)
- docs/experiments.md ve çapraz referanslar (farm/feeding/assignments.py, core/codes.py, core/crud.py, core/softdelete.py, farm/models/tank.py, config/access.py)

## İncelenmeyen alanlar

- Testlerin fiilen çalıştırılması (Docker/PostgreSQL yok), şablon (templates/experiments/*) HTML içerikleri, frontend TypeScript, çeviri dosyaları (locale)
- farm.feeding.read / farm.stock.read içi hesaplar (yalnızca çağrı sözleşmeleri okundu)
- Kullanıcı rolleri matrisi (Roles verisi) ve gerçek yetki dağılımı

## Bulgular

### 27-1 - Deney başına yetkilendirme yok: change izni olan herkes her deneyi değiştirir
- Önem: medium | Güven: high
- Dosyalar: config/access.py:100-103, experiments/models.py:401, experiments/resources.py:130,288, experiments/migrations/0002_design_frozen.py:16-17
- Açıklama: `Member` satırları (lider, öğrenci vb.) hiçbir yetki kararında kullanılmıyor. Genel `experiments.change_experiment` izni olan herkes başkasının deneyini tasarlayabilir/başlatabilir, tank bırakıp değiştirebilir, ekibi (lideri dahil) yeniden yazabilir. Başladıktan sonra ekip tetikleyiciyle korunmuyor.
- Kanıt: models.py:401 "per-experiment rights come with the permissions plan, which reads this"; access.py:100-103 "Who may do what to which experiment (its team) comes with the permissions plan"; 0002 docstring: "The team (`experiment_members`) is not the design and is not guarded."; resources.py:130 `can_start` yalnız `has_perm(change)` ve duruma bakar.
- Öneri: Plan gelene kadar belgelenmiş bilinen risk olarak izlenmeli; en azından başlamış deneyde ekip/lider değişikliği için ek kontrol veya log uyarısı.

### 27-2 - Başlatmanın yazdığı besleme atamaları çiftlik arayüzünde değiştirilebilir/silinebilir (korumasız, bağlantı kolonu yok)
- Önem: medium | Güven: high
- Dosyalar: experiments/services.py:772-779, experiments/integrity.py:66-86, farm/feeding/assignments.py:31-90
- Açıklama: Deney atamaları yalnızca (unit, protocol, valid_from) üçlüsüyle bulunuyor; satırda deneye ait bağlantı yok, `farm` tarafında deney farkındalığı yok (grep: farm/feeding içinde yalnızca docstring anıyor). Çiftlik kullanıcısı bu satırı sonlandırır/siler veya üstüne parti-kapsamlı protokol atarsa deneyin ön-kayıtlı diyeti sessizce bozulur; yalnızca sonradan `check_experiments` / `ration_off_diet` sapması yakalar. `_end_diet` ise satır değiştirilmişse hiçbir şey sonlandırmadan geçer (boş döngü). Dokümandaki "tank üzerindeki kayıt kilidi" henüz yok.
- Kanıt: services.py:777 `ProtocolAssignment.objects.filter(unit=row.unit, batch__isnull=True, protocol=protocol, valid_from=row.from_on)`; assignments.py:39-40 satırda sadece `notes=f'{code} · {group}'`.
- Öneri: Atama satırına deney referansı/kilit işareti ya da farm tarafında deneydeki tankın atamalarını düzenlemeyi engelleyen/uyaran kontrol; `check_experiments` zamanlanmış çalışsın.

### 27-3 - Sağkalım: yabancı parti ve sonradan eklenen (yerine koyma olmayan) tanklarda pay/payda tutarsız
- Önem: medium | Güven: medium
- Dosyalar: experiments/read.py:201-212
- Açıklama: `start` yalnızca ilk günün (`began`) hücrelerindeki `count_at_end` ile toplanıyor; `lost` ise `row.batches`'teki tüm partilerin kayıplarını topluyor. `row.batches` sonradan giren (foreign_batch) partileri de içerir; bu partinin başlangıçta payda katkısı 0 iken ölümleri paya yazılır, sağkalım olduğundan düşük (hatta negatif) çıkabilir. Aynı şekilde bir replikata yeni bir tank farklı bir `from_on` ile (yerine koyma değil, ek tank) eklenirse başlangıç sayısına girmez ama kayıpları sayılır. Dokümandaki varsayım yalnızca "yerine koyma".
- Kanıt: `initial = cell.first == began`; `if initial: start += ...`; `lost += sum(... )` koşulsuz partiler üzerinden (read.py:205-210); `row.survival = 100*(start-lost)/start` (211-212).
- Öneri: Kayıpları yalnızca başlangıçta bulunan (start>0) parti/tank çiftleriyle sınırla veya sapma olduğunda değeri "güvenilmez" işaretle; negatif sonuca karşı sınır.

### 27-4 - Veri sekmesi yemi tür filtresi olmadan topluyor (Overview'dan farklı tanım)
- Önem: low | Güven: medium
- Dosyalar: experiments/read.py:263-276, docs/experiments.md ("Derived, never stored")
- Açıklama: Doküman "rakamlar yalnızca deneyin türünün partilerini okur" diyor; `overview` partiyi türe göre süzerken `data()` yalnızca `record.target` (üretim/temizleyici balık) ile süzüyor. Tankta başka (temizleyici olmayan) türde bir parti varsa yem kilosu denemeye yazılır, FCR ise yazılmaz.
- Kanıt: read.py:273-274 `... and record.target == target` (tür/parti kontrolü yok).
- Öneri: Tanım tek yerde birleştirilsin veya Data sekmesinde sınırlama açıkça belirtilsin.

### 27-5 - Tahsis tekrarlanabilirliği: havuz saklanmıyor, tank kodu değiştirilebilir
- Önem: medium | Güven: medium
- Dosyalar: experiments/models.py (allocation_* alanları), experiments/services.py:518-568, experiments/allocation.py:5-26, farm/models/tank.py:333, farm/forms/tank.py:99
- Açıklama: Doküman "aynı havuz ve tohum sonsuza dek aynı yerleşimi verir; hakem tekrarlayabilir" diyor. Yalnızca yöntem+tohum saklanıyor; havuz (özellikle sistem öğeleri, kodu sistem kodu) saklanmıyor, yalnızca sonuç tank yerleşimleri duruyor. Anahtar `sha256("<tohum>:<kod>")` ve tank kodu düzenlenebilir (`fixed_after_creation` yalnızca `kind`) olduğundan kod sonradan değişirse doğrulama bozulur. Havuz yalnızca denetim günlüğündeki "Places" metninden yeniden kurulabilir.
- Kanıt: models.py `allocation_method/seed/note` dışında havuz alanı yok; services.py:534-568 havuz kodları yalnız hesapta kullanılır; allocation.py:17-19 anahtar koddan türer.
- Öneri: Havuz kod listesini (kod anlık görüntüsüyle) deneyde sakla veya tahsis sırasında loga yaz; kodu bir deneyde olan tankta kod değişikliğini engelle.

### 27-6 - Randomizasyon sınırsız yinelenip üzerine yazılabilir (araştırmacı serbestlik derecesi)
- Önem: low | Güven: medium
- Dosyalar: experiments/services.py:518-568, experiments/forms.py:497
- Açıklama: Taslakta farklı tohumla `randomise` istenildiği kadar çalıştırılıp beğenilen dağılım seçilebilir; önceki denemeler yalnızca denetim günlüğünde kalır, bir "bu tahsis nihai" kilidi veya deneme sayacı yok. Form her açılışta yeni rastgele tohum öneriyor.
- Kanıt: `randomise` her çağrıda `_write_places` + `_set_allocation(RANDOMISED, seed)`; yineleme sınırı/uyarısı yok.
- Öneri: Birden fazla tahsis denemesini Start diyaloğunda uyarı olarak göster; denemeleri günlükte listele.

### 27-7 - Tank durumu/tür/balık doğrulaması zayıf: day-0 kontrolü yalnız taslakta ve yalnız gün gelince
- Önem: low | Güven: high
- Dosyalar: experiments/design.py:303-331, experiments/services.py:384-421, 822-886
- Açıklama: `_wanted` yalnız silinmiş ve site kontrolü yapar; tank `status`'una (preparing/fallow vb.) bakılmaz. `check_day_zero` yalnız `status == DRAFT` ve `starts_on <= bugün` iken çalışır: day 0 gelecekteyken başlatılan deney bu kontrolü hiç görmez, sonrasında da (status != DRAFT) bir daha çalışmaz. `replace_unit` yeni tankta balık/tür/tartı olup olmadığını denetlemez (yalnız besleme çakışması).
- Kanıt: design.py:306-309; services.py:405-411; 838-871.
- Öneri: Çalışan deneyde day-0 ve yeni tank için balık/tür uyarıları `deviations`'a eklensin.

### 27-8 - Replikatlar arası tank sayısı dengesizliği kontrol edilmiyor
- Önem: low | Güven: medium
- Dosyalar: experiments/design.py:200-213, experiments/services.py:534-568
- Açıklama: `check_balance` yalnız replikat sayısını karşılaştırır. Havuzda farklı büyüklükte sistemler (farklı tank sayısı) varsa bir replikat 2, diğeri 6 tank alabilir; hiçbir uyarı yok, oysa birim başına sonuç ve biyokütle karşılaştırılamaz.
- Kanıt: `counts` yalnız `len(design.replicates...)`; `randomise` havuz öğelerinin tank sayısını karşılaştırmaz (`tanks_of`).
- Öneri: Replikat başına tank sayısı eşitsizliği için uyarı.

### 27-9 - En az bir faktör gerekmiyor
- Önem: low | Güven: medium
- Dosyalar: experiments/design.py:136-159, 200-213
- Açıklama: Faktörsüz tek grup tasarımı hata vermeden (yalnız `one_group` uyarısı) başlatılabilir; iki faktörsüz grup ise `same_levels` hatası alır. Karşılaştırma anlamı olmayan bir "deney" ön-kayıt edilebilir.
- Kanıt: `check_groups` yalnız grup/replikat/seviye kontrol eder; faktör sayısı kontrolü yok.
- Öneri: Başlatma için en az bir faktör ve iki grup şartı (veya hata seviyesi).

### 27-10 - move_span: tank kilidi yok ve IntegrityError yakalanmıyor
- Önem: low | Güven: low
- Dosyalar: experiments/services.py:571-586, experiments/forms.py:89-93
- Açıklama: Gün 0/süre değişiminde yerleşimler `update` ile taşınıyor; `save_places`/`randomise`'ın aksine tanklar `stock_locked` ile kilitlenmiyor ve DB dışlama kısıtı ihlali (başka deneyin eşzamanlı rezervasyonu) `IntegrityError` olarak yakalanıp okunur mesaja çevrilmiyor; form kontrolü (`clashes_when_moved`) yarışa karşı korumasız. DB bütünlüğü korunur ama kullanıcı 500 görebilir (crud güncelleme yolunun IntegrityError'ı nasıl ele aldığı doğrulanmadı).
- Kanıt: move_span `ReplicateUnit.objects.filter(pk__in=...).update(from_on=..., until_on=...)` try/except yok.
- Öneri: Aynı kilit sırası ve hata çevirisi.

### 27-11 - Çalışan deneyde bırakma sonrası replikat tanksız kalabilir; bütünlük kontrolü yakalamaz
- Önem: low | Güven: medium
- Dosyalar: experiments/services.py:791-819, experiments/design.py:225-230, experiments/integrity.py
- Açıklama: `release_unit` yerine tank koymadan yerleşimi kısaltır; replikatın kalan günleri tanksız kalır. `check_places` yalnız replikatın hiç yerleşimi yoksa `slot_without_tank` üretir; kısmi günlük boşluk ne `check_experiments`'ta ne sapmalarda görünür (yalnız Overview'da FCR "gap").
- Kanıt: design.py:228-229 `if not rows:`; release_unit'te kapsama kontrolü yok.
- Öneri: Replikat-gün kapsama kontrolü (sapma olarak).

### 27-12 - Kopyalama: aynı token farklı kaynak/kullanıcıya ait kaydı döndürür
- Önem: low | Güven: medium
- Dosyalar: experiments/services.py:691-694
- Açıklama: İdempotans yalnız `entry_key` ile bakar; token başka bir kaynaktan veya kullanıcıdan yapılmış deneye aitse o kayıt "kopya" olarak döner (yalnız UUID tahmini ile mümkün, pratik risk düşük). Ayrıca yeni kopyanın `starts_on` değeri `day_0_too_old` açısından kopyalama anında doğrulanmaz (ancak Start'ta).
- Kanıt: `Experiment.all_objects.filter(entry_key=token).first()` kaynak/kullanıcı karşılaştırması yok.
- Öneri: Token eşleşmesini kaynak ve kullanıcı ile sınırla.

### 27-13 - İstatistik katmanı yok; `error_df` yalnız sayım
- Önem: info | Güven: high
- Dosyalar: experiments/read.py:77-81, experiments/variables.py, docs/experiments.md (Not here)
- Açıklama: Test, güç analizi, veri seti ve bitiş raporu bilinçli olarak kapsam dışı. `error_df` tanksız replikatları da sayar (tasarım düzeyi), yalnız `edit_extras`'ta gösterilir. Birincil uç nokta yalnız 4 çiftlik türevi (bfcr, efcr, survival, biomass_gain); ağırlık/büyüme yok. Birincil uç nokta Overview'da vurgulanmıyor.
- Kanıt: variables.py:95-99; read.py:77-81.
- Öneri: Yol haritasında izlensin.

### 27-14 - "closed" durumu erişilemez/kullanılmıyor
- Önem: info | Güven: high
- Dosyalar: experiments/models.py (TRANSITIONS), experiments/read.py:215-218, experiments/migrations/0002_design_frozen.py, docs/experiments.md
- Açıklama: `running -> closed` geçişi, tetikleyici dalları ve `window_end(closed)` var ama kapatan servis/arayüz yok ("Only Start is built here"). Deneyler sonsuza dek "running" kalır; durum filtresi "Closed" seçeneğini sunar ama sonuç hep boştur; kapalı yollar test edilmemiş kod riski taşır.
- Kanıt: services.py'de `Status.CLOSED` atayan fonksiyon yok.
- Öneri: Yaşam döngüsü planı gelene kadar belgelenmiş durum olarak kalsın.

### 27-15 - Doküman referansı olmayan dosyaya: plan/area1/PLAN.md
- Önem: info | Güven: high
- Dosyalar: docs/experiments.md ("Where the code differs from the plan")
- Açıklama: Doküman "plan/area1/PLAN.md" planından sapmaları anlatır ama depoda `plan/` dizini yok; sapma listesi doğrulanamaz.
- Kanıt: `ls /home/user/tromso-mvp/plan` -> yok.
- Öneri: Planı depoya ekle veya bölümü kaldır.

### 27-16 - Start içinde değerlendirme iki kez yapılıyor
- Önem: info | Güven: high
- Dosyalar: experiments/services.py:655-662, experiments/resources.py:307
- Açıklama: `design_module.assess(locked)` uyarılar için tekrar çağrılır (aynı işlem içinde aynı sonuç, gereksiz sorgu); görünüme de bir kez daha (kilitsiz) çağrılır. Davranış hatası değil, performans/netlik.
- Kanıt: services.py:655 ve 662.
- Öneri: İlk `assessment.warnings` metinleri `audit.source_language()` altında yeniden üretilebilir; ikinci tam değerlendirme gerekmez.

### 27-17 - Çalışan deneyde gün-0 sonrası balık/tür/tartı kontrolü hiç yenilenmez; `check_experiments` bunu da kapsamaz
- Önem: low | Güven: medium
- Dosyalar: experiments/design.py:334-337, experiments/integrity.py:52-63
- Açıklama: `HOLDS_AFTER_START = [check_experiment, check_groups, check_places]`; `check_protocols`, `check_feeding`, `check_day_zero` bilinçli dışarıda (aktif protokol emekli olabilir vb.). Sonuç: başlamış deneyin başlangıç taban çizgisi ihlalleri (ör. tankta balık yok, iki parti) hiçbir yerde kalıcı olarak raporlanmaz; yalnızca başlatma anında kabul edilen uyarı metni günlüğe düşer.
- Kanıt: design.py:334-337 yorumu; integrity `_of`.
- Öneri: Gün-0 bulgularını başlatmada deney kaydına bağlayıp sonradan gösterme (salt-okunur).
