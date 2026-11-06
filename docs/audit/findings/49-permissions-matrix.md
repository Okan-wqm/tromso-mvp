# 49 - URL x rol (permissions-matrix) denetimi

## Özet
Tüm URL'ler üç katmanla korunuyor: (1) `LoginRequiredMiddleware` (config/settings.py:76) her sayfayı oturuma bağlar, yalnızca `@login_not_required` ve Django auth görünümleri (giriş, parola sıfırlama, `core:set_language`) açık; (2) jenerik CRUD `Resource` rotaları (core/crud.py:546-570) `allows(action)` + `has_perm(app.<action>_<model>)` ister, kayıt erişimi `scoped()` ile 404'e çevrilir; (3) elle yazılmış sayfalar `@permission_required(..., raise_exception=True)` veya fonksiyon içi `has_perm` ile korunur. Menü (config/navigation.py) ile görünüm izinleri CRUD tarafında birebir örtüşüyor; "menüde gizli ama URL ile açık" durumlar bilinçli (hidden/show_when/ara sayfalar) ve hepsi aynı izne bağlı. Kritik/yüksek bulgu yok. Ana bulgular: (a) varsayılan "açık" tasarım (dekoratörsüz view = her oturumlu kullanıcı) ve URL x rol matrisini süpüren otomatik test yok, (b) HR'da Employees "Create" sütunu Everyone dışı roller için ölü izin (403), (c) HR liderinin kendi/başka bölüm ekip üyesini yönetmediği bölüme taşıyabilmesi, (d) Deneyler ve Üretim organizasyon şeması gibi çapraz-alan okuma sızıntıları, (e) /admin/ salt-okunur sayfalarının DB görüntüleyicideki maskelemeyi uygulamaması, (f) özel 403/404 şablonu yok.

### URL x rol matrisi (kısa)
Roller: A = anonim, U = oturumlu ama rolsüz, R = ilgili alanda Read, C/E/D = Create/Edit/Delete, SU = platform yöneticisi (superuser). "ilişki" = satır kapsamı/üyelik/atanma.
| URL (kaynak) | A | U | Gerekli izin | Menüde |
|---|---|---|---|---|
| /accounts/login, password_reset*, /language/ (config/urls.py:21-27, core/views.py:16) | açık | açık | yok | - |
| /accounts/password_change, logout | - | açık | oturum | kullanıcı menüsü |
| / (config/views.py:22), /production/ (config/views.py:30) | - | açık | yok (kutucuklar has_perm ile süzülür) | Overview |
| Jenerik CRUD: /<prefix>/, new/, <pk>/, <pk>/delete/, row-list, <pk>/view/ (core/crud.py:546) | - | 403 | `<app>.view/add/change/delete_<model>` (+ scoped/allowed) | R varsa |
| /roles/, /users/ (core/resources.py) | - | 403 | auth.* (matriste yok: yalnız SU) | auth.view_* |
| /database/*, export.csv (core/dbview.py:14) | - | 403 | core.browse_database (matriste yok: yalnız SU), GET-only | evet |
| /activity/ (core/views.py:35) | - | 403 | core.view_auditlog (matriste var) + audit.readable | evet |
| /admin/ | - | yönlendirme | is_staff (UserForm'da yok: yalnız createsuperuser) | yok |
| /operations/units/* (farm/urls.py:25-33) | - | 403 | view/add/delete_stockoperation (void=delete; batch_details=add) | R |
| /operations/feeding/*, water/*, health/*, harvests/ | - | 403 | feedingrecord / watermeasurement / treatment,licecount,healthevent / harvestrecord (+void=delete) | R |
| /operations/storage/* (inventory/urls.py) | - | 403 | inventoryoperation view/add/delete | R |
| /operations/monitoring/, cards/ | - | 403 | farm.view_stockoperation (monitoring.* değil) | R |
| card-templates/preview, <pk>/copy | - | 403 | change_cardtemplate / add_cardtemplate | gizli (araç) |
| /operations/tasks/<pk>/start|tick|complete | - | 403 | tasks.view_task + (atanan VEYA change_task) | R |
| /operations/tasks/<pk>/notes/ | - | 403 | yalnız tasks.view_task | R |
| /operations/tasks/<pk>/cancel|reopen | - | 403 | view_task + change_task | R |
| /reports/<pk>/submit,close,reopen,duties/done,undo | - | 403 | reports.change_report | R |
| /reports/<pk>/correct | - | 403 | reports.add_report | R |
| /reports/<pk>/export.*, print/ , duties/ | - | 403 | reports.view_report | R |
| /messages/* (messaging/urls.py) | - | 403 | messaging.view_conversation + üyelik (404); kanal=add_conversation; üyelik yönetimi=kanal sahibi | R |
| /knowledge/library/<pk>/file|text | - | 403 | knowledge.view_document | R |
| /knowledge/entries/<pk>/review | - | 403 | change_knowledgeentry | E |
| /hr/*, /production/team/* (hr/urls.py) | - | 403 | ilgili hr.* izni + hr.scope.team (satır kapsamı) + realm | R |
| /hr/today/clock-in|out | - | 403 | hr.view_attendancerecord + kendi Employee satırı (hr/services.py:365-395) | R |
| /hr/schedule/plan/ | - | 403 | hücre başına add/change/delete_shiftassignment (hr/services.py:200-203) | R |
| /hr/settings/{shifts,holidays,leave-types} | - | 403 | hr.view_* | gizli (hidden=True) |
| /research/experiments/* | - | 403 | view/add(copy)/change(design,places,start,release,replace)/delete_experiment | R |

## İncelenen alanlar
config/urls.py ve tüm `*/urls.py`; core/crud.py (Resource, ResourceView, CRUD görünümleri, mount); core/access.py, config/access.py (AREAS), config/navigation.py, core/navigation.py; core/views.py, core/dbview.py, core/resources.py, core/forms.py, core/admin.py; config/views.py; hr/views.py, hr/scope.py, hr/services.py, hr/roles.py, hr/resources/*, hr/forms/employee.py|leave.py, hr/read.py (org_tree); farm/{stock,feeding,water,health,harvest}/views.py dekoratör taraması; inventory/views.py; tasks/views.py+services.py; messaging/views.py+services.py; reports/views.py; knowledge/views.py; monitoring/views.py+resources.py; experiments/resources.py+read.py; şablonlarda `perms.` kullanımı; test varlığı (URL süpüren test araması). Mevcut 02-authz bulgularıyla çakışmamaya çalışıldı; çakışanlar çapraz referanslandı.

## İncelenmeyen / sınırlı incelenen alanlar
Uygulama çalıştırılmadı (DB gerekli), testler koşulmadı; bulgular statik kod okumasına dayanır. Her farm/ `Resource` alt sınıfının form düzeyindeki alan yetkileri, frontend TypeScript, şablonlardaki her düğme gizleme kararı, dbgrid SQL güvenliği, reports/compute içeriği tek tek incelenmedi.

## Bulgular

### 49-1 | Orta | Güven: orta
**Employees "Create" sütunu Everyone dışı roller için ölü izin: form görünür, kayıt her zaman 403**
- Dosyalar: hr/services.py:25-27,50-55; hr/resources/employee.py:90-99; hr/forms/employee.py:78-81; config/access.py (Employees alanı); README.md (Team list bölümü)
- Açıklama: Matris Employees için `add` sütununu her role sunuyor ve `can_add` yalnızca `has_perm` ile hesaplanıyor (core/crud.py:~585). Ancak yeni kişinin yerleşimi `services.move` -> `_allowed` -> `scope.can_reach` ile denetleniyor; yeni kişi henüz kimsenin ekibinde olmadığı için Everyone (`hr.all_employee`) olmayan biri için PermissionDenied oluşur. CreateView kaydı `transaction.atomic` içinde yapıp `after_save` içinde 403 fırlattığından kayıt geri alınır; kullanıcı doğrulama hatası yerine düz 403 görür. README "yalnızca Everyone sahibi yeni kişi oluşturabilir" diyor, ama matris/UI bunu yansıtmıyor.
- Kanıt: `_allowed`: `if not any(user.has_perm(perm) ...) or not scope.can_reach(user, employee): raise PermissionDenied`; `after_save` -> `services.move(request.user, employee, ...)`.
- Öneri: `add_employee` iznini Everyone'a bağla (örn. create_view içinde erken kontrol / matriste yalnız Everyone satırında göster) ya da formda anlaşılır hata ver; test ekle.

### 49-2 | Orta | Güven: orta
**Employees Edit sahibi lider, ekip üyesini (ve kendini) yönetmediği herhangi bir bölüme taşıyabilir; kendi satırında self_plan benzeri koruma yok**
- Dosyalar: hr/forms/employee.py:81-84; hr/units.py:47-59; hr/services.py:50-55; hr/resources/employee.py (allowed override yok); karşılaştırma: hr/resources/attendance.py:55, roster.py:46
- Açıklama: Düzenleme formunda bölüm seçenekleri `kinds=None` ile TÜM aktif üretim ve ofis bölümlerini listeler (`kinds` yalnız `adding` iken daraltılır). `services.move` yalnızca kişinin ekipte olmasını ister (hedef bölümün yöneticisi olmayı değil). Yani `change_employee` sahibi lider: (i) ekibindeki birini başka yöneticinin bölümüne ya da ofis/üretim arasında taşıyabilir (realm değişir), (ii) kendi `Employee` satırını (kapsamda olduğu için) düzenleyip kendi yerleşimini/ünvanını/`left_on`'unu değiştirebilir. Katılım ve vardiya için kendi kaydını yazma yasağı (`self_plan`) var, çalışan kaydında yok.
- Kanıt: `units.choices(include=..., kinds=[realm] if realm and adding else None)`; `EmployeeResource` içinde `allowed` tanımı yok (core/crud.py:463 varsayılan True).
- Öneri: Hedef bölüm için de `can_reach`/yönetici koşulu uygula veya Everyone iste; kendi satırında yerleşim/left_on değişimini engelle.

### 49-3 | Düşük | Güven: yüksek
**Üretim organizasyon şeması tüm üretim bölümlerini ve yöneticilerini ekip kapsamından bağımsız gösterir; yalnız hr.view_employee ister**
- Dosyalar: hr/read.py:492-509; hr/views.py:215-227; config/navigation.py (Production › Team › Organization chart)
- Açıklama: `org_tree(realm=PRODUCTION)` her `ProductionDepartment`'ı site ve yönetici adıyla listeler; yalnızca kişi sayıları kapsamla (`head_counts`) daraltılır. `hr.view_employee` takım-kapsamlı bir izindir (lider yalnız ekibini görür), ama şemada tüm bölümler/yöneticiler görünür. Şirket tarafında aynı sayfa `hr.view_officedepartment` ister: iki farklı izin modeli aynı görünümü korur.
- Kanıt: `ProductionDepartment.objects.select_related('site', 'manager').order_by('name')` filtresiz; `organisation_chart`: `has_perm(place.entry.perm)` (mount'a göre değişir).
- Öneri: Tasarım kararı olarak belgele veya yalnız erişilebilen bölümleri göster.

### 49-4 | Orta | Güven: yüksek
**Deney okuma sayfaları, farm okuma izni olmadan beslenme/stok/ölüm rakamlarını gösterir**
- Dosyalar: experiments/resources.py:118-146; experiments/read.py:129-164 (yalnız satır 478'de has_perm); experiments/resources.py:33-47 (data_links ise has_perm ile süzülüyor)
- Açıklama: `experiments.view_experiment` sahibi `/research/experiments/<pk>/view/` Overview/Data sekmesinde parti kodları, tanktaki balık/biyokütle, sağkalım, dönüşüm oranı (FCR) gibi rakamları `farm.view_stockoperation`/`view_feedingrecord` olmadan görür. Bağlantılar izne göre süzülürken veriler süzülmüyor: tutarsız. (README: "It reads the farm and nothing reads it", ama matris bu çapraz okumayı göstermiyor.) 02-6 raporlar için benzer bulgu.
- Kanıt: `overview()` içinde `stock_read.Presence.of_units`, `Batch.all_objects`, `feeding_read.Conversion` doğrudan çağrılıyor; izin kontrolü yok.
- Öneri: Rakamları ilgili farm izinlerine göre gizle ya da matriste "Experiments Read çiftlik rakamlarını içerir" diye belgele.

### 49-5 | Düşük | Güven: orta
**/admin/ salt-okunur detay sayfaları HR özel alanlarını (izin nedeni, yoklama/vardiya notu) gösterebilir; DB görüntüleyici bunları maskeliyor**
- Dosyalar: hr/admin.py:1-6; core/admin.py:12-24,56-67; config/database.py:masked
- Açıklama: `register_audited('hr')` HR modellerini ReadOnlyAdmin ile kaydeder; görüntüleme izni olan (superuser) kullanıcıya alanlar salt-okunur formda tam gösterilir (`exclude`/`readonly_fields` ile gizleme yok). Oysa `/database/` `leave_requests.reason|decision_note`, `attendance_records.note`, `shift_assignments.note`, `messages.body` sütunlarını maskeler ve HR günlüğü `audit.restrict` ile kısıtlıdır. Erişim yalnız `is_staff` (UserForm'da ayarlanamaz) olduğundan etki düşük, ama maskeleme politikası iki yerde farklı.
- Kanıt: `masked={'leave_requests': ('reason', 'decision_note'), ...}` vs `AuditedModelAdmin` alan gizlemesi yok. Çalıştırılarak doğrulanmadı.
- Öneri: Admin'de aynı maskeli sütunları `exclude` et veya HR'ı admin'den çıkar; politikayı tek yerde tanımla.

### 49-6 | Orta | Güven: yüksek
**Varsayılan "açık" (fail-open) tasarım ve URL x rol matrisini süpüren otomatik test yok**
- Dosyalar: config/settings.py:75-76; hr/views.py:60-130,197-212 (punch/plan/approve/leave_request fonksiyon içi kontrol); config/views.py:22-53; core/tests.py:436; core/test_database.py:93; monitoring/tests/test_templates_db.py (resolver kullanımı yalnız şablonlar için)
- Açıklama: Dekoratörsüz bir görünüm her oturumlu kullanıcıya açıktır. Birçok görünüm izni dekoratörle değil, gövdede (`has_perm`/servis) kontrol eder (`hr.views.punch`, `plan`, `approve`, `reject`, `cancel`, knowledge `_allowed`, `today*`). Tüm `get_resolver()` rotalarını dolaşıp "ya login_not_required ya izin bildirimi" doğrulayan ya da rol başına 200/403/404 matrisini test eden bir test bulunamadı; yalnız seçili URL'ler için 403 testi var. Yeni bir rotada dekoratör unutulursa sessizce tüm oturumlu kullanıcılara açılır.
- Kanıt: grep (`get_resolver|urlpatterns`) testlerde yalnızca core/tests_crud_mount.py, hr/tests/test_scope.py, monitoring testlerinde çıkıyor; core/tests.py:436 yalnız roles/users için.
- Öneri: Rota başına izin bildirimi (ör. `PERM` özniteliği) + tüm rotaları kapsayan sözleşme testi; ya da `LoginRequiredMiddleware`'e ek bir "izin bildirilmemiş görünüm" denetimi.

### 49-7 | Düşük | Güven: yüksek
**Özel 403/404/500 şablonu yok; yetkisiz erişimler düz Django yanıtı verir (modal istekleri dahil)**
- Dosyalar: templates/ (403.html/404.html/500.html yok); `handler403` tanımı yok (grep boş); core/crud.py:553-557 (PermissionDenied)
- Açıklama: Tüm yetki reddi `PermissionDenied` ile 403 üretir; kullanıcı menüye dönüş bağlantısı olmayan çıplak "403 Forbidden" görür. `X-Modal` ile açılan diyalog (core/crud.py:86-87) 403 olduğunda modal içinde çıplak metin gösterebilir.
- Kanıt: `find templates -name "40*"` boş.
- Öneri: Marka şablonlu 403/404 sayfaları ve modal için kısa parça.

### 49-8 | Düşük | Güven: yüksek
**Monitoring sayfası tüm kart panolarını ve site/bölüm/sistem/tank adlarını yalnız farm.view_stockoperation ile verir; monitoring.view_monitorboard ve ilgili farm Read izinleri aranmaz**
- Dosyalar: monitoring/views.py:99-120; config/navigation.py:124; config/access.py (Monitoring boards yorumu)
- Açıklama: Menü girişi ve görünüm `farm.view_stockoperation` ister (tasarım: "anyone who may read Monitoring may choose a board"), fakat bağlamda `MonitorBoard.objects`, `Site`, `ProductionDepartment`, `System`, `Tank` listeleri izin süzmeden gelir. 02-7 ile örtüşür (orada yalnız filtre listeleri); pano listesi de ekleniyor.
- Kanıt: `boards=MonitorBoard.objects.order_by('name')`, `sites=Site.objects.order_by('name')`.
- Öneri: Seçenekleri `has_perm` ile süz veya matrise not düş.

### 49-9 | Düşük | Güven: yüksek
**Tasks: "Read" izni yazma içerir: view_task sahibi herhangi bir göreve (atanmış olmasa da) kalıcı not ekleyebilir**
- Dosyalar: tasks/views.py:67-76; tasks/services.py:190-205; config/access.py (Tasks yorumu: "Read ... and adding a note")
- Açıklama: `add_note` yalnız `tasks.view_task` ister; `start/tick/complete` ise atanan veya `change_task` ister (`may_work_on`). Notlar silinemez/düzenlenemez ve tam metniyle denetim günlüğüne yazılır (02-5). Salt-okur rolün kalıcı yazma yetkisi var; belgelenmiş ama "Read" sütununun anlamını genişletir.
- Kanıt: `@permission_required(VIEW...) def add_note` -> `services.add_note(request.user, task, body)`; services'te `may_work_on` kontrolü yok.
- Öneri: Notu atanan/`change_task` ile sınırla veya ayrı sütun ver.

### 49-10 | Info | Güven: yüksek
**Menüde gizli ama URL ile erişilebilen uçların listesi (hepsi aynı izne bağlı, ek sızıntı yok)**
- Dosyalar: config/navigation.py:70-72 (hidden=True: Shifts, Holidays, Leave types), 49-77 (`show_when=NOT_PRODUCTION_ONLY`), `LEADS`; farm/urls.py:33-36,41 (water calculator/results/report, unit chart); monitoring/resources.py:99-102 (preview, copy); hr/urls.py:39 (mount çifti); experiments/resources.py:174-185
- Açıklama: (1) `hidden=True` girişler menüde yok, `/hr/settings/...` rotaları `hr.view_shift|holiday|leavetype` ile açık (settings sayfası bağlantıyı `perms.` ile gösterir: templates/hr/settings_list.html:31,38; LeaveType için bağlantı yok). (2) `show_when` ile HR satırları üretim-yalnız kullanıcıdan gizlenir; sayfalar izin sahibine yine cevap verir (kod yorumu açık: "menu courtesy"). Aynı kayıtlar hem /hr/... hem /production/team/... altında realm filtresiyle sunulur. (3) Calculator/chart/preview/copy/design/places/start/release/replace uçlarının menü girişi yoktur; izinleri Water Read, Card templates Edit/Create, Experiments Edit/Create'tir.
- Kanıt: `Entry.shown_to` (core/navigation.py:~66-76) yalnız menüyü süzer; `ResourceView.as_view` (core/crud.py:553-557) gerçek denetimdir.
- Öneri: Yok; matris belgesine eklenebilir. (Leave types için settings sayfasında bağlantı yok: kullanıcı yalnız URL ile ulaşır, küçük UX tutarsızlığı.)

### 49-11 | Düşük | Güven: orta
**Messages: Read sahibi her kullanıcı, Messages iznine sahip tüm aktif hesapların (platform yöneticisi dahil) adlarını listeleyebilir**
- Dosyalar: messaging/services.py:47-58; messaging/views.py (start/new, add_members)
- Açıklama: `contacts()` tüm aktif `messaging.view_conversation` sahiplerini (+ superuser) döndürür; yeni konuşma/kanal üye seçicisi bunu gösterir. Roller arası kişi dizini sızıntısı (HR kapsamından bağımsız): üretim işçisi ofis çalışanlarının/yöneticilerin adını görebilir. Tasarım gereği olabilir.
- Kanıt: `get_user_model().objects.with_perm(USE, is_active=True, include_superusers=True)`.
- Öneri: Belgele veya iletişim listesini rol/bölüm ile sınırla.

### 49-12 | Düşük | Güven: yüksek
**Rol önayarı ile matris/menü uyumsuzluğu: Production manager önayarında view_employee yok ama menüde Production › Team › People girdileri onu ister**
- Dosyalar: hr/roles.py:9-12,28-32; config/navigation.py (Team › People: hr.view_employee)
- Açıklama: Önayar `all_production_employee` verir, `view_employee` vermez (ekip listesi/şema kasıtlı kapalı). Rol formu matrisi kaydedilince `implied()` Read ekler (02-3). Ayrıca `all_production_employee` izninin `view_employee` olmadan kullanıcı görünür etkisi yalnız `scope.managed` içinde; yani izin tek başına kısmen "gizli" çalışıyor. Önayarın yetki kümesi ile matrisin ürettiği küme farklıdır.
- Kanıt: hr/roles.py:31 izin listesi; core/access.py `implied`.
- Öneri: 02-3 ile birlikte karara bağla; önayar testine "matriste kaydedince küme değişmez" ekle.

### 49-13 | Düşük | Güven: orta
**Matris etiketi "Create/Delete" fiilleri bazı alanlarda gerçek davranışla örtüşmüyor (void, kayıt dışı yazma)**
- Dosyalar: config/access.py (Health events: Delete=void; Production units: Create= tüm işlemler + batch_details); farm/stock/views.py:502-522; farm/resources/health_event.py:28; farm/harvest/views.py:31
- Açıklama: Production units "Create" sütunu şu işlemleri kapsar: stok girişi, ölüm, tartım, transfer, derecelendirme, ayıklama, hasat, parti ayrıntısı düzenleme (Batch alanı matriste yok: 02-4). Hasat "void" izni `delete_stockoperation`'dır (Harvested alanı yalnız view). Health events alanı "Delete" gösterir ama Resource `actions=('add','change')`'tir; Delete yalnız `void_event` için kullanılır. Rol yöneticisi matristen tam yetki kapsamını okuyamaz; sütun adı ile fiil eşleşmesi alan bazında farklı.
- Kanıt: `harvest/views.py:31 VOID = 'farm.delete_stockoperation'`; `health_event.py:28 actions = ('add', 'change')`; `void_event` `@permission_required(EVENTS['delete'])`.
- Öneri: Matris yardım metnine fiil haritası ekle (veya Harvest/Batch için ayrı satır).

### 49-14 | Info | Güven: yüksek
**Doğrulanan olumlu noktalar (denetim kapsamı)**
- Dosyalar: core/crud.py:546-570,592-596; core/resources.py; core/dbview.py:14-15; core/forms.py:97-113; core/admin.py:72
- Açıklama: Roller/kullanıcılar yalnız SU (auth.* matriste yok); /database/ yalnız SU ve `require_safe`; `UserForm` `is_staff/is_superuser` alanı sunmaz (yetki yükseltme yolu yok); Django admin'in Group/User kayıtları kaldırılmış; DeleteView/UpdateView `visible()` ile kilit altında kapsam yeniden doğrulanır; mount'lu HR rotaları `scoped` ile realm daraltır; mesajlaşmada üye olmayan 404; `document_file` login+izin ister ve MEDIA için URL rotası yok. IDOR/yatay yükseltme bulunamadı.
- Kanıt: bkz. dosyalar.
- Öneri: Yok.
