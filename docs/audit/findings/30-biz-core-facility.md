# 30 - biz-core-facility denetimi

## Özet
Alan: siteler, üretim departmanları, sistemler, tank/pond/cage (Tank), ekipman hiyerarşisi ve bunlar arası ilişkisel tutarlılık.
Genel olarak model katmanı olgun: kısmi unique kısıtlar, üretilmiş (generated) hacim/biyokütle kolonları, CHECK kısıtları ve durum makinesi var. Bulgular ağırlıkla (a) yalnızca form/clean katmanında tutulan ve DB'de tutulmayan site tutarlılığı kuralları, (b) hiçbir yerde okunmayan "ölü" durum/kapasite alanları, (c) soft-delete/restore sonrası "yetim" departmanlar ve (d) Tank durum makinesindeki çıkmaz yol üzerinde. Kod/veri değiştirilmedi.

## İncelenen alanlar
farm/models/site.py, system.py, production_department.py, tank.py, equipment.py; core/models.py, core/softdelete.py, core/admin.py; farm/forms/site.py, system.py, production_department.py, equipment.py; farm/stock/services.py (_follow_status); inventory/models.py (StorageLocation); docs/aquaculture-platform-bugs.md.

## İncelenmeyen alanlar
Testler çalıştırılmadı; migrations içeriği, frontend TypeScript, water_point.py, feeding/health modelleri, ekipman tipi kataloğunun tamamı, izin/erişim (core/access.py) derinlemesine incelenmedi.

## Bulgular

### 30-1 | orta | güven: yüksek
Dosyalar: farm/models/tank.py:488-491, farm/models/tank.py:230-240 (TRANSITIONS), farm/models/tank.py:262-263 (NEEDS_NO_FISH), farm/stock/services.py:85-86
Başlık: Balık içeren birim bakıma alınınca tekrar aktife dönemiyor (durum makinesi çıkmazı)
Açıklama: TRANSITIONS'ta MAINTENANCE yalnızca PREPARING ve INACTIVE'e gidebilir; ikisi de NEEDS_NO_FISH. Yorum "maintenance ve quarantine balıklı da olabilir" diyor. ACTIVE -> MAINTENANCE balıklıyken serbest, ama balık varken oradan çıkış yok (ACTIVE'e geçiş MAINTENANCE'tan tanımlı değil).
Kanıt: `Status.MAINTENANCE: (Status.PREPARING, Status.INACTIVE)`; `status_blocker` NEEDS_NO_FISH + has_stock() için engeller. _follow_status da yalnızca 'balıksız -> aktif' ve 'boşalınca' kuralını uygular, maintenance'ı değiştirmez.
Öneri: MAINTENANCE -> ACTIVE geçişini (balıklıysa) ekleyin ya da bakıma balıklı geçişi engelleyin; karar dokümante edilsin.

### 30-2 | orta | güven: yüksek
Dosyalar: farm/models/system.py:91-110, farm/forms/system.py:12, farm/models/tank.py:536-552
Başlık: System.site değişmezliği yalnızca formda; modelde/DB'de yok, taşınırsa içindeki tank ve alt sistemler tutarsızlaşır
Açıklama: SystemForm `fixed_after_creation=('site',)` ile siteyi kilitliyor; System.clean() site değişimini ve alt sistem (children), tank ve ekipman bağlantılarını (EquipmentSystem) kontrol etmiyor. production_department boşsa site serbestçe değiştirilebilir (programatik yol, shell/servis). Tank._check_system yalnızca tank kaydedilirken çalışır.
Kanıt: System.clean yalnızca production_department/parent site eşleşmesini ve tank-departman uyumunu kontrol eder; hiçbir CHECK/FK site tutarlılığını DB'de tutmaz.
Öneri: clean()'e "tank/çocuk/ekipman bağlantısı varken site değişemez" kuralı ekleyin (Tank._check_site gibi); tercihen model düzeyinde.

### 30-3 | orta | güven: yüksek
Dosyalar: farm/models/production_department.py:45-47, farm/forms/production_department.py:7-60, farm/models/production_department.py:84-105, core/crud.py:155-160
Başlık: Site silinince yetim kalan departmanın siteye yeniden bağlanma yolu yok
Açıklama: Site silinince departmanlar SET_NULL ile siteyi kaybeder; restore yalnızca siteyi geri getirir, departmanları yeniden bağlamaz (core/softdelete.py restore "yalnızca kayıt kendisi döner"). Form `fixed_after_creation=('site',)` yüzünden düzenlemede site alanı disabled/required=False; kullanıcı "Siteye bağla" yapamaz. Model clean() site taşımayı destekliyor ama UI erişemiyor.
Kanıt: forms/production_department.py:7 ve crud.py:157-160. Yetim departmanın ekipmanı Equipment.clean'de "not on any site" hatası verir (equipment.py:187), sistemde seçilemez (forms/system.py:43).
Öneri: Yetim departman için siteyi yalnız boşken atanabilir yapın; ya da site silmeyi departman varken bloklayın (soft delete'te CASCADE/PROTECT tercihi).

### 30-4 | orta | güven: orta
Dosyalar: farm/models/site.py:116-122, farm/stock/read.py:75-77, reports/compute/stock.py:24
Başlık: Yetim departmandaki birimler site bazlı raporlardan ve deniz sitesi kurallarından düşer
Açıklama: Site.delete_blockers yalnızca StockMovement'a bakar. Hareketi olmayan site silinirse birimler canlı kalır, siteleri yoktur; sonra stoklanabilirler (ARRIVAL_STATUSES). Rapor/derleme kodları `production_department__site=site` ile filtrelediği için bu balık hiçbir lokaliteye raporlanmaz; sea_units() de yetim birimi deniz sayamaz (temizleyici balık kuralı değişir). Stok servisinde birimin sitesinin var olduğuna dair kontrol bulamadım.
Kanıt: services.py'de site kontrolü yok (grep: yalnızca sağlık olayı eşleşmesi, :279); Tank.clean yetim departmanı reddetmez.
Öneri: Siteyi olmayan departmanın birimlerine stoklamayı reddedin ve/veya Tank/Stock kontrolü ekleyin.

### 30-5 | orta | güven: yüksek
Dosyalar: farm/models/site.py:29-33, 76, 116-122; farm/forms/site.py:13-24
Başlık: Site.status/Site.is_active hiçbir yerde okunmuyor; "Closed" yalnızca etiket
Açıklama: Site.delete_blockers mesajı "status'u Closed yap" diyor, ama Closed/Inactive/Maintenance bir site yeni departman, sistem, birim, stok girişi veya rapor görevinden dışlanmıyor. Ayrıca is_active ikinci bir bayrak olarak duruyor (docs SITE-10 "iki durum bayrağı" anti-pattern'i, ProductionDepartment ve System bunu kaldırmış). is_active formda yok, hiçbir yerde okunmuyor.
Kanıt: grep `Site.Status`/`site.status`/`is_active` (site bağlamında) model dışı sıfır sonuç; reports/due.py yalnızca Site.Type kullanıyor.
Öneri: is_active kaldırılsın; kapalı site için yeni kayıt/stoklama ve rapor kuralları tanımlansın.

### 30-6 | düşük | güven: yüksek
Dosyalar: farm/models/site.py:92-95, 101-107, 113; farm/forms/site.py:13-24
Başlık: Site'ta formdan hiç yazılamayan ölü kolonlar
Açıklama: water_capacity_m3, max_biomass_kg, established_date, facilities, settings, notes, metadata ve is_active forma konmamış; kodda başka yerde okunmuyor (grep). docs SITE-05 "kolon ya düşürülsün ya forma eklensin" der. Özellikle Site.max_biomass_kg (izin verilen azami biyokütle, MTB) düzenlenemez ve hiçbir kontrolde kullanılmaz.
Kanıt: SITE_FORM_TABS alan listesi; `grep facilities|metadata|site.settings` sonuç yok.
Öneri: Kolonları kaldırın ya da forma ekleyin; MTB için biyokütle toplamı doğrulaması düşünün.

### 30-7 | düşük | güven: yüksek
Dosyalar: farm/models/system.py:62-69, farm/models/production_department.py:54-56, farm/models/site.py:90-91
Başlık: Elle girilen kapasite alanları gerçek birimlerle ilişkisiz ve uygulanmıyor
Açıklama: System.total_volume_m3/max_biomass_kg yalnızca sistem listesinde gösteriliyor; sistemdeki Tank'ların toplam hacmi/biyokütlesiyle karşılaştırılmıyor ve stok kontrolünde kullanılmıyor (services.py:350 yalnızca birim bazlı). ProductionDepartment.capacity'nin birimi tanımsız. Zamanla gerçek birimlerden sapar (bkz. docs "hand-typed tank count would drift" mantığı).
Kanıt: grep max_biomass/total_volume_m3: yalnız şablon ve form; tank.py üretilmiş kolonları ayrı.
Öneri: Türetilmiş toplam gösterin ya da elle girilen değeri toplamla doğrulayın; capacity için birim ekleyin.

### 30-8 | düşük | güven: orta
Dosyalar: farm/models/equipment.py:178-215, inventory/models.py:85-90, 109-114
Başlık: Ekipman başka siteye taşınınca silo (StorageLocation.feeder) site tutarlılığı kontrol edilmiyor
Açıklama: StorageLocation.clean feeder'ın sitesini yalnızca kendi kaydında doğrular. Equipment.clean departman değişiminde parçaları kontrol ediyor ama `silos` ilişkisini kontrol etmiyor; EquipmentForm production_department'ı değiştirmeye izin verir (fixed_after_creation yok). Yem silosu başka sitedeki yemleyiciye bağlı kalabilir.
Kanıt: equipment.py clean() içinde `silos` yok; grep `silos` yalnız inventory/models.py:86.
Öneri: Equipment.clean'e "silosu varken site değişemez" kontrolü ekleyin.

### 30-9 | düşük | güven: orta
Dosyalar: farm/models/site.py:116-122
Başlık: Site silme engeli yalnızca stok hareketine bakıyor; diğer geçmiş (sağlık olayı vb.) DO_NOTHING ile siteye işaret ediyor
Açıklama: HealthEvent.site (farm/models/health.py:480) DO_NOTHING; silinen siteye işaret eden canlı kayıt kalabilir. Silme planı bunları "kept" sayıyor ama blocker yok. Stok hareketi olmayan ama sağlık olayı/su ölçümü olan site (örn. kuluçka öncesi) mesaj olmadan düşer.
Kanıt: Site.delete_blockers tek koşul StockMovement; softdelete _keep akışı yalnız not düşer.
Öneri: Geçmişi olan site için "Closed yap" yönlendirmesi sağlık/su kayıtlarını da kapsasın.

### 30-10 | düşük | güven: yüksek
Dosyalar: farm/models/site.py:25-27, 45-51, farm/models/system.py:22-29, farm/models/tank.py:19-22, 98-105
Başlık: Site.Type / System.Type / Tank.Kind / WaterType arasında tutarlılık kuralı yok
Açıklama: sea_cage sitesinde pond kind birim, land_based sitede cage, saltwater tank + tatlı su sitesi, RAS sistemine cage vb. engellenmiyor. Site.type değişimi (sea_cage <-> başka) mevcut stoktaki karışım kuralını (mixed(), sea_units) ve rapor yükümlülüklerini sessizce değiştirir; clean() bunu denetlemez.
Kanıt: Tank.clean ve System.clean'de type/kind karşılaştırması yok; stock/read.py:75 site.type'a bağlı kural.
Öneri: İzin matrisi (site tipi -> birim kind) veya en azından uyarı ve "stoklu sitede type değişmez" kuralı.

### 30-11 | düşük | güven: yüksek
Dosyalar: farm/models/system.py:101-110, farm/models/tank.py:536-552
Başlık: System/Equipment/ProductionDepartment/Site durumlarının hiçbir davranışı yok; yalnız Tank'ın durum makinesi var
Açıklama: System.Status (maintenance/offline/construction), Equipment.Status (decommissioned vb.), ProductionDepartment.Status ve Site.Status serbest alan; çevrimdışı sistemdeki birime stoklama, hizmet dışı ekipmanın yemleyici seçilmesi veya inactive departmana birim eklenmesi engellenmiyor (yalnız hr/units.py:57 departman statüsünü picker'da okuyor, config/views.py:46 sistem sayımı).
Kanıt: grep `System.Status|Equipment.Status|ProductionDepartment.Status` model dışı: yalnız filtre/sayım.
Öneri: Durumların iş anlamını tanımlayın (örn. decommissioned ekipman yeni silo/su noktasına bağlanamaz).

### 30-12 | düşük | güven: yüksek
Dosyalar: farm/models/tank.py:421-423, farm/models/system.py:70-72, farm/models/equipment.py:123-125, farm/models/production_department.py:69-71
Başlık: Kod benzersizliği kapsamı tutarsız (Tank/Equipment/Departman şirket genelinde, System site bazında, Site genelinde)
Açıklama: uq_tanks_code_live, uq_equipment_code_live, uq_production_departments_code_live global; uq_systems_site_code_live site bazlı. Aynı kod iki sitede sistem olabilir, birim/ekipman olamaz. Bilinçli olabilir ama dokümante değil; çoklu site ölçeklendiğinde çakışma ve yeniden kullanım sorunu doğurur.
Kanıt: Meta.constraints dosyaları.
Öneri: Kapsam kararını (şirket vs. site) belgeleyin ve tek tipe indirin.

### 30-13 | düşük | güven: orta
Dosyalar: farm/models/tank.py:421-430, 464-473
Başlık: regulatory_unit_id site bazlı tekilliği DB'de değil departman bazında; site bazı yarış durumuna açık
Açıklama: Kısıt (production_department, regulatory_unit_id); aynı sitenin iki departmanında aynı numara DB'ye girebilir, yalnızca clean()/check_stock yakalar. Kod yorumu da bunu kabul ediyor. Eşzamanlı iki kayıtta veya admin dışı yazımda kural delinir.
Kanıt: tank.py:421-430 yorumu "all a constraint can see".
Öneri: Tankta site_id denormalize kolonu (tetikleyiciyle) veya DB trigger; ya da kaydetmede site satırı kilidi.

### 30-14 | düşük | güven: orta
Dosyalar: farm/models/site.py:50-57, 148-152
Başlık: Site.TIMEZONES sabit 6 öğelik liste; zone_of geçersiz değerde bozulabilir
Açıklama: Model alanı choices ile sınırlı (form dışı yazımda doğrulanmaz, DB CHECK yok); zone_of ZoneInfo(site.timezone) yanlış değerde ZoneInfoNotFoundError atar ve HR/rapor/görev saatleri çöker. Norveç operasyonu için listede yalnız Europe/Oslo anlamlı; diğerleri (Tokyo, New York) üretim sitesi için alışılmadık. docs SITE-09 bu riski belirtmişti.
Kanıt: zone_of site.py:148-152; DB CHECK yok.
Öneri: CHECK ile choices'ı eşleyin ya da zone_of'ta geçersiz değeri yakalayın.

### 30-15 | info | güven: yüksek
Dosyalar: farm/models/site.py:70-75, 105-108; farm/models/site.py:21-27
Başlık: Site.country/region/state serbest metin; ülke-bölge-lice_area ilişkisi doğrulanmıyor
Açıklama: lice_area (kuzey/güney) kullanıcı tarafından ayrıca seçiliyor; region/lokalitet/enlem ile tutarlılığı kontrol edilmiyor, yanlış alan seçimi yanlış yasal eşik haftası uygulatır. Bilgi amaçlı.
Kanıt: forms/site.py:13-24 alanlar bağımsız; kontrol yok.
Öneri: Enlemden varsayılan öner/uyarı ver.

### 30-16 | info | güven: orta
Dosyalar: farm/models/tank.py:25-35, 236-243
Başlık: ACTIVE'ten doğrudan CLEANING geçişi yok; boş aktif birim yalnız FALLOW veya MAINTENANCE'a gidebilir
Açıklama: TRANSITIONS'ta ACTIVE -> (HARVESTING, MAINTENANCE, QUARANTINE, FALLOW); EMPTIED ACTIVE->FALLOW. Ölüm sonrası boşalan birim temizlik gerektirse CLEANING'e FALLOW'tan geçilemez (FALLOW -> PREPARING). Kaynaktaki politikayı yansıtıyor olabilir; yalnızca not.
Kanıt: tank.py TRANSITIONS.
Öneri: İş sahibi onayı ile doğrulayın.
