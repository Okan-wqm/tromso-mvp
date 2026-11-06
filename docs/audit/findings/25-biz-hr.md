# 25 - biz-hr: İş mantığı, HR modülü denetimi

## Özet
HR modülü (`hr/`) genel olarak titiz: kapsam (`hr/scope.py`), servis katmanı, DB kısıtları (exclusion constraint, self-decision trigger) ve saf kural fonksiyonları iyi ayrılmış. Doğrulanan başlıca sorunlar: (1) `plan_shifts` ile CLEAR işleminde kısmen boş hücre seçimi çökme üretir, (2) unutulan clock-out, tahtada "yok" görünürken yeni giriş engellenir, (3) çalışan ayrılış/işe giriş tarihleri vardiya, yoklama ve izin yazımlarında zorlanmaz, (4) başlamış onaylı izin hiçbir yolla düzeltilemez/kısaltılamaz, (5) `rest_rule` etiketi ile uygulama arasında tutarsızlık, (6) Production manager preset'inde Delete/yoklama giriş yetkisi eksik. Sertifika/yetkinlik (certification) konusu için HR'de hiç model yok (kapsam dışı/eksik özellik).

## İncelenen alanlar
hr/rules.py, clock.py, leave.py, scope.py, services.py, read.py, roles.py, checks.py, units.py, views.py, models/*, forms/*, resources/{attendance,employee,leave,roster}.py, migrations (0005 trigger, 0008), admin.py, apps.py, README HR bölümü, docs/hr-launch-checklist.md.

## İncelenmeyen alanlar
Testler çalıştırılmadı (DB gerekir), bulgular kod okumasına dayanır. core.crud/Resource iç işleyişi, farm tarafı (zone_of, site_today), şablonlar (templates/hr), frontend TS, hr/management/commands/seed_hr_demo.py, resources/department.py ve scheduling.py ayrıntıları, i18n.

## Bulgular

### 25-1 | Yüksek | Güven: yüksek | Kısmen mevcut hücrelerde CLEAR toplu işlemi AttributeError ile çöker
Dosyalar: hr/services.py:203-230, hr/services.py:222-230, core/audit.py:144-158
Açıklama: `plan_shifts` `shift is CLEAR and not existing` ise sadece hepsi boşsa atlar (203). Bazı hücrelerde plan var, bazılarında yoksa tüm günler `_write_cell`'e gider; `row=None` ile CLEAR dalında `audit.record(user, DELETE, None, ...)` `instance.pk` okur ve `row.soft_delete` None üzerinde çağrılır.
Kanıt: `_write_cell(user, employee, day, shift, existing.get(day), ...)` (218) mevcut olmayan gün için None verir; 228-230 `audit.record(..., row, ...)` / `row.soft_delete(user)`; audit.py:152 `str(instance.pk)`. hr/tests/test_roster.py:193 yalnızca tüm hücreler doluyken CLEAR dener.
Öneri: Mevcut olmayan günleri `_write_cell`'de (veya döngüde) `row is None and shift is CLEAR` ise atla; kısmi seçim için test ekle.

### 25-2 | Orta | Güven: yüksek | Unutulan clock-out: pano "yok" der, ama yeni giriş "zaten giriş yaptınız" ile reddedilir
Dosyalar: hr/rules.py:137-159, hr/services.py:365-380, hr/read.py:380-382
Açıklama: `rules.status` punch penceresi dışındaki (planlanan başlangıçtan `window_minutes` öncesinden eski) punch'ları saymaz; `clock_in` ise yaşına bakmadan her açık kaydı engeller. Dünden açık kalan kayıt varsa kişi panoda NOT_IN/ABSENT görünür fakat giriş yapamaz; çıkış yaparsa kayıt `now()` ile kapanır ve süre gün(ler)ce uzar. Pano ayrıca yalnızca son 2 günlük punch'ı okur.
Kanıt: services.py:375 `AttendanceRecord.objects.filter(employee=employee, clock_out__isnull=True).exists()`; rules.py:143 `earliest <= punch[0] < end`; read.py:380 `clock_in__gte=moment - timedelta(days=2)`; services.py:396 `clock_out = max(timezone.now(), ...)`. docs/hr-launch-checklist.md 2.4 sadece kısmen belgeler.
Öneri: Belirli bir süreden eski açık punch'ı "düzeltme gerekli" olarak göster, otomatik kapatma veya lead'e uyarı/rozet ekle; clock_out'ta makul üst sınır uygula.

### 25-3 | Orta | Güven: yüksek | İstihdam tarihleri (joined_on/left_on) vardiya, yoklama ve izin yazımlarında zorlanmıyor
Dosyalar: hr/services.py:183-219, 365-380, 402-418, hr/forms/roster.py:47-64, hr/forms/leave.py:75-105, hr/checks.py:15-40
Açıklama: `plan_shifts`, `ShiftAssignmentForm`, `clock_in`, `enter_presence` ve izin formu kişinin işe giriş öncesi/ayrılış sonrası günleri reddetmez (Everyone sahibi için `scope.can_reach` kısıtlamaz). Ayrılış sonrası vardiya `align_placements` ile bir kez silinir ama sonradan yeniden eklenebilir; `checks.problems` ayrılıştan sonra plan/yoklama ve işe girişten önce plan/izin için kural içermez (yalnızca posting ve izin-after-left). Ayrılmış çalışan hesabı aktifse clock_in yapabilir.
Kanıt: services.py:127 yalnızca ayrılışta tek seferlik silme; checks.py'de ShiftAssignment/AttendanceRecord sorgusu yok; clock_in (365-380) `left_on` kontrolü yok.
Öneri: Servislerde `joined_on <= day <= left_on` doğrulaması ve checks.py'ye plan/yoklama/izin kontrolleri ekle.

### 25-4 | Orta | Güven: yüksek | Başlamış onaylı izin düzeltilemez, kısaltılamaz veya iptal edilemez
Dosyalar: hr/services.py:278-292, hr/forms/leave.py:80-81
Açıklama: `can_cancel` onaylı izinde `first_day <= today` ise herkese (HR dahil) False döner; form yalnızca pending düzenler. Hatalı onaylanmış/otomatik onaylı (`needs_approval=False`) bir izin başladıktan sonra silinemez/kısaltılamaz (erken dönüş, yanlış tür). Admin salt okunur olduğundan yalnızca DB müdahalesi kalır.
Kanıt: services.py:284 `if leave_request.first_day <= today: return False`; forms/leave.py:80 `Only a pending request can be changed.`
Öneri: Everyone sahibi için başlamış izni sonlandırma/kısaltma (logged) eylemi ekle.

### 25-5 | Orta | Güven: yüksek | `rest_rule` etiketi hafta saati ve ardışık gün kurallarını da kapsıyor görünür ama kod sadece dinlenme için uygular
Dosyalar: hr/models/scheduling.py:320-321, hr/rules.py:93,97,109, hr/forms/scheduling.py:37, README.md (rules)
Açıklama: Alan etiketi "A short rest, a long week or too many days in a row" (warn/block). `rules.py` WEEK_HOURS ve CONSECUTIVE_DAYS'i sabit `WARN` üretir; yalnızca REST_SHORT `settings.rest_rule` kullanır. Model docstring/README yalnızca dinlenmeyi "warn or block" yapar. Yönetici "Block" seçip haftalık saat ve ardışık gün ihlallerinin de engelleneceğini sanabilir.
Kanıt: rules.py:97 `Finding(WEEK_HOURS, WARN, ...)`, 109 `Finding(CONSECUTIVE_DAYS, WARN, ...)`, 93 `settings.rest_rule`.
Öneri: Etiketi düzelt veya kuralları ayarla bağla; hr-launch-checklist 2.1'i netleştir.

### 25-6 | Orta | Güven: orta | Production manager preset'inde vardiya temizleme ve yoklama giriş/düzeltme yetkisi yok
Dosyalar: hr/roles.py:24-34, hr/services.py:177-180, hr/services.py:402-418, hr/resources/attendance.py:25-28
Açıklama: Preset `view/add/change_shiftassignment` verir ama `delete_shiftassignment` yok; CLEAR `hr.delete_shiftassignment` ister, yani yönetici hücreyi temizleyemez, sadece "off" yapabilir (plan kaydı "planlanmadı"ya dönmez). `add_attendancerecord`/`change`/`delete` de yok: docstring "Today & attendance" der, fakat `enter_presence` ve yoklama düzeltme/geçersiz kılma (resource docstring) yönetici için kapalıdır; unutulan clock-out'u (25-2) lead düzeltemez.
Kanıt: roles.py:24-27 izin listesi; services.py:179 `'hr.delete_shiftassignment'`; services.py:405 `hr.add_attendancerecord`.
Öneri: Hedeflenen davranış belgelenmeli ya da preset'e ilgili izinler eklenmeli (tasarım kararı olabilir, confidence orta).

### 25-7 | Orta | Güven: yüksek | `clock_in/clock_out` yalnızca `view_attendancerecord` ile yazma yapar
Dosyalar: hr/services.py:365-399, hr/roles.py:34-36
Açıklama: Kendi punch'ını yazmak "view" yetkisine bağlı: yalnızca okuma rolü verilen (ör. denetçi) ve employee kaydı olan kullanıcı da kendi yoklamasını yazabilir. Rol matrisi okuma/yazma ayrımı bu yolda geçersiz. Kasıtlı olabilir (docstring "Needs Read on Attendance") ama matristeki "Edit/Create" semantiğinden sapar.
Kanıt: services.py:368 `user.has_perm('hr.view_attendancerecord')`.
Öneri: Ayrı bir "clock" izni (örn. `hr.clock_attendancerecord`) tanımla veya belgele.

### 25-8 | Orta | Güven: yüksek | Geçmişe dönük izin ve plan değişikliği için tarih sınırı yok
Dosyalar: hr/forms/leave.py:83-105, hr/services.py:183-219
Açıklama: Form `first_day` geçmişte olabilir ve `needs_approval=False` türde geçmiş tarihli izin anında "approved" olur (kimse karar vermez, `decided_by` boş). Planlar da geçmiş günler için serbestçe değiştirilir/silinir; yalnızca audit log tutar. Geçmiş vardiya, yoklama kıyaslamasının dayanağını sessizce değiştirir.
Kanıt: forms/leave.py:102-104 `self.instance.status = APPROVED`; clean içinde `first >= today` kontrolü yok; services.plan_shifts'te geçmiş gün kontrolü yok.
Öneri: Geçmiş tarih için ek yetki/neden alanı veya kilit penceresi.

### 25-9 | Orta | Güven: orta | Yıllık izin kotası denetimi eşzamanlılığa karşı korumasız
Dosyalar: hr/forms/leave.py:95-101, hr/leave.py:57-64
Açıklama: Kota yalnızca form `clean` içinde okunup kontrol edilir; çalışan satırı kilitlenmez (plan/yoklama servislerinin aksine). Çakışmayı exclusion constraint önler ama iki ayrı tarih aralığındaki eşzamanlı talepler toplamda `annual_days`'i aşabilir. Ayrıca `needs_approval=False` ve `annual_days=None` türü sınırsız kendi kendine onay verir (tasarım gereği ama kayda değer).
Kanıt: forms/leave.py:97 `used = leave.used(...)` kilitsiz; services.py'de izin oluşturma servisi yok (form kaydı doğrudan).
Öneri: Kayıt anında `select_for_update` + yeniden doğrulama veya servis katmanına taşı.

### 25-10 | Düşük | Güven: yüksek | Onay/ay-sonu: `leave.used` her talebi YENİ talebin site'ına göre hesaplar ve N+1 sorgu üretir
Dosyalar: hr/leave.py:57-64
Açıklama: `used()` eski taleplerin gün sayısını talep sahibinin o talepteki yerleşiminden değil, çağrıya verilen `site`'tan (yeni talebin ilk günündeki site) hesaplar; çalışan yıl içinde siteler arası geçtiyse tatil günleri yanlış olabilir. Her talep için ayrı Holiday sorgusu (tablo geçirilmiyor). Ayrıca günler hep tam gün (`Decimal(1)`), yarım gün desteği yok, ayarlar/tatiller sonradan değişince bakiye geçmişe dönük değişir (saklanmaz).
Kanıt: leave.py:62-63 `charged_by_year(request.first_day, request.last_day, site)`; holidays tablosu verilmez (leave.py:35 yolu).
Öneri: Talebin kendi sitesini kullan, holiday_table'ı bir kez oku.

### 25-11 | Düşük | Güven: yüksek | Çalışan ayrılışında onaylı gelecek izinler ve sınır aşan talepler temizlenmez
Dosyalar: hr/services.py:112-137, hr/checks.py:22-24
Açıklama: `align_placements` yalnızca `first_day > left_on` olan PENDING talepleri iptal eder. Onaylı gelecek izin ile ayrılış gününü aşan talepler kalır; `away_on`/`approved_days` bunları gösterir (rapor ve pano). Sadece `check_hr` komutu bunu bildirir, otomatik uyarı yok. `leave_company` içinde `before` snapshot'ı silinen posting için hesaplanıp kullanılmaz (küçük).
Kanıt: services.py:130-131 `status=LeaveStatus.PENDING, first_day__gt=left_on`; checks.py:22.
Öneri: Onaylı gelecek izinleri iptal et veya uyarı rozeti göster.

### 25-12 | Düşük | Güven: yüksek | Yoklama düzeltmesi "self" kayıtlarda neden istemez, `via` değişmez
Dosyalar: hr/forms/attendance.py:394-397, hr/models/attendance.py:170
Açıklama: Neden zorunluluğu yalnızca `entered` kayıtlara uygulanır; lead çalışanın kendi (`self`) punch'ının saatini nedensiz değiştirebilir ve kayıt `via='self'` kalır (artık çalışanın kendi beyanı gibi görünür). Form yardım metni "Why the time was entered or corrected" der ama düzeltme için zorunlu değildir; DB check da yalnızca `via != self` için.
Kanıt: forms/attendance.py:394 `entered = adding or self.instance.via == ENTERED`.
Öneri: Düzeltmede neden zorunlu kıl ve `via`/düzeltme izini kaydet.

### 25-13 | Düşük | Güven: yüksek | İzin ile giriş yapan kişi panoda "izinde" kalır; docstring çelişir
Dosyalar: hr/rules.py:125-139
Açıklama: Docstring "Bir kayıt gerçektir... punch atan kişi present/late" der; ancak kodda `if on_leave: return ON_LEAVE` punch kontrolünden önce gelir. İzinli günde işe çağrılan/çalışan kişi panoda "izinde" kalır, yoklaması görünmez. Ayrıca gece vardiyası devam ederken `on_leave` yalnızca site'ın "bugün"ü için bakılır (read.py:402).
Kanıt: rules.py:137-138; read.py:402.
Öneri: Punch'ı olanı izin üzerinde değerlendir veya docstring'i düzelt.

### 25-14 | Düşük | Güven: orta | Kapsam kararları tek bir güne (ilk gün) bağlı; yerleşim değişimi aşan izin talebi
Dosyalar: hr/services.py:271-275, hr/resources/leave.py:158, hr/read.py:549
Açıklama: İzin karar/okuma yetkisi `first_day`'e göre `scope.can_reach` ile verilir; talep sırasında birimi değiştiren kişinin sonraki günlerinde yeni yönetici talebi göremez/karar veremez, oysa `away_on`/pano o günlerde izni gösterir.
Kanıt: services.py:275 `scope.can_reach(user, leave_request.employee, leave_request.first_day)`.
Öneri: Davranışı belgele veya gün-bazlı görünürlük ekle.

### 25-15 | Düşük | Güven: orta | Form yolu `ShiftAssignmentForm` kilitsiz değerlendirme yapar, servis yolu kilitler
Dosyalar: hr/forms/roster.py:47-64, hr/services.py:183-219
Açıklama: Tek hücre kaydı formda `evaluate` ile kuralları kilit olmadan çalıştırır; toplu yol çalışan satırını `select_for_update` ile kilitler. Eşzamanlı iki kayıt arasında kural (örn. dinlenme/çakışma) kontrolü eski plana göre yapılabilir. Ayrıca `evaluate` site/saat dilimini yalnızca `min(changes)` gününe göre seçer.
Kanıt: forms/roster.py:58 `services.evaluate(employee, {day: shift})`; services.py:193 kilit yalnızca toplu yolda; services.py:164.
Öneri: Form kaydını da aynı servise yönlendir.

### 25-16 | Düşük | Güven: yüksek | Tekrarlanan mantık ve ölü kod
Dosyalar: hr/leave.py:67-72, hr/services.py:142-147, hr/read.py:90-95, hr/rules.py:61, hr/models/scheduling.py:204-209,256-263
Açıklama: `leave.balance` hiçbir yerde çağrılmaz (form kotayı kendi yeniden uygular); `services.holiday_days` yalnızca `leave.holidays_for` sarmalayıcısı; `monday` hem rules hem read'de, `MARGIN`/`WEEK_MARGIN` iki kez 15; `Shift.paid_minutes` duvar saati farkına dayanır ve `clock.net_minutes` ile (DST) farklı sonuç verebilir; `span_minutes`'ın `or 24*60` kolu DB check ile erişilemez.
Kanıt: grep `balance(` sadece leave.py:67; services.py:144.
Öneri: Birleştir/sil; ortak sabitler.

### 25-17 | Bilgi | Güven: yüksek | Sertifika/yetkinlik/eğitim kavramı HR modülünde yok
Dosyalar: hr/models/ (employee.py, leave.py, scheduling.py)
Açıklama: Çalışan, izin, vardiya var; sertifika, eğitim veya yetkinlik (ör. balıkçılık/dalış/gıda hijyeni sertifikası) modeli yok, vardiya atama sertifika süresi kontrolü yapmaz. Repo genelinde "certif" yalnızca eski platform hata dokümanında ve tedarikçi alanında geçer (docs/aquaculture-platform-bugs.md:956 STK-72 "health certificates marked required but never checked").
Kanıt: `grep -ri certif hr/` boş.
Öneri: Kapsam kararı: ihtiyaçsa ayrı model ve vardiya/rol kuralı; değilse README'de açıkça belirt.

### 25-18 | Bilgi | Güven: orta | Rol/yetki: Everyone için kapsam kısıtı yok, ek denetim izi dayanağı ayrı
Dosyalar: hr/scope.py:523-533, hr/apps.py:13-16, hr/admin.py:5
Açıklama: `hr.all_employee` tüm çalışan, plan, izin nedeni ve yoklama için tam erişimdir; denetim logu bu modelleri yalnızca bu izne gösterir (olumlu). Admin salt okunur ve geri alma (restore) yalnızca `change_*` izniyle (soft-deleted plan/posting geri getirme, yeniden doğrulanır). Yetki ilişkisi iyi tasarlanmış; kayıt amaçlı not: PRODUCTION manager preset'i `all_production_employee` taşır, yani yöneticisiz departman için de tüm üretim izin tiplerini (karar yetkisiyle) görür (docs 3.x ile uyumlu).
Kanıt: roles.py:26; scope.py:495-505.
Öneri: Yok (bilgi).
