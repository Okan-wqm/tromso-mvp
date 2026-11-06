# 02 - Yetkilendirme (authz) denetimi

## Özet
Yetkilendirme modeli bilinçli ve büyük ölçüde tutarlı kurulmuş: tüm sayfalar `LoginRequiredMiddleware` ile oturum ister (config/settings.py:76), roller Django `Group` + "erişim alanları" matrisi (config/access.py, core/access.py) ile veri olarak tanımlanıyor, roller/kullanıcılar yalnızca platform yöneticisi (superuser) tarafından yönetiliyor (matriste olmayan `auth.*` izinleri), jenerik CRUD (core/crud.py:557, 592) her fiilde izin + `scoped` satır kapsamı uyguluyor, HR için ekip kapsamı (hr/scope.py) ve mesajlaşmada üyelik tabanlı 404 var. Kritik/yüksek bir IDOR veya yatay yetki yükseltme bulunmadı. Bulgular çoğunlukla: (1) HR dışındaki tüm alanlarda satır/site kapsamının hiç olmaması (tasarım kararı ama risk), (2) izin-alanı eşlemesindeki tutarsızlıklar (batch_details, rapor sunma, rol önayarları), (3) çapraz-alan okuma sızıntıları (izleme filtreleri, raporlar), (4) üretimde tehlikeli varsayılan ayarlar.

## İncelenen alanlar
config/access.py, core/access.py, core/crud.py (izin/scoped/allowed), core/resources.py, core/forms.py (Rol/Kullanıcı formu), core/admin.py, core/dbview.py, core/audit.py, hr/scope.py, hr/views.py, hr/services.py, hr/resources/*, hr/forms/employee.py, hr/roles.py, messaging/views.py+services.py, tasks/views.py+services.py, reports/views.py, knowledge/views.py, monitoring/views.py (+read.sources_for), farm/stock|feeding|water|health|harvest views (dekoratör taraması), inventory/views.py, experiments/resources.py, config/settings.py, tüm urls.py dosyaları.

## İncelenmeyen / sınırlı incelenen alanlar
Her farm Resource alt sınıfının tek tek `scoped/allowed` override'ı, şablonlardaki `perms` kullanımı ve düğme gizleme, frontend TypeScript, test kapsamı (testler çalıştırılmadı), reports/compute içeriğinin hangi alanlardan veri okuduğunun satır satır doğrulanması, dbgrid SQL güvenliği (başka uzmanın alanı).

## Bulgular

### 02-1 | Orta | Güven: yüksek
**HR dışında hiçbir satır/site/departman kapsamı yok: izinler tüm çiftlik verisi için global**
- Dosyalar: core/crud.py:453-472, config/access.py (tamamı), farm/*/views.py
- Açıklama: `Resource.scoped` varsayılanı "her satır" (core/crud.py:455-463). Yalnızca HR (hr/scope.py) ve mesajlaşma üyeliği satır kapsamı uygular. Bir rolde `farm.add_stockoperation` olan kişi, hangi site/departmanda çalışırsa çalışsın tüm tank/sitelerde işlem kaydedebilir ve geçersiz kılabilir (farm/stock/views.py:422, 525). Orijinal sistemdeki site-atama kontrolü (docs/aquaculture-platform-bugs.md FDR-10) bilinçli olarak "tek şirket" modeline indirgenmiş.
- Kanıt: core/crud.py:455 `The default is every row.`; farm/stock/views.py:526 `get_object_or_404(StockOperation, pk=pk)` site filtresiz.
- Öneri: Çok siteli işletme hedefleniyorsa site/departman kapsamı için `scoped` kullanan bir mekanizma belgelenmeli; tek şirket varsayımı README'de açık yazılmalı.

### 02-2 | Orta | Güven: yüksek
**Üretimde tehlikeli varsayılanlar: SECRET_KEY, DEBUG=1, DB parolası, oturum çerezi sertleştirmesi yok**
- Dosyalar: config/settings.py:25, 28, 30, 115
- Açıklama: `DJANGO_SECRET_KEY` yoksa bilinen sabit anahtara düşüyor; `DJANGO_DEBUG` yoksa DEBUG açık; DB parolası varsayılan `balik`. Bilinen SECRET_KEY ile oturum çerezleri ve parola sıfırlama token'ları üretilebilir (hesap ele geçirme), ayrıca audit'teki "private text" HMAC özeti (core/audit.py:98) tersine denenebilir. `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_*` ayarı hiç yok (grep boş).
- Kanıt: `SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-development-only')`; `DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'`.
- Öneri: Ortam değişkeni yoksa (DEBUG kapalıyken) başlatmayı reddet; varsayılan DEBUG=0; üretim için cookie/HSTS ayarları ekle.

### 02-3 | Orta | Güven: orta
**Rol önayarı "Production manager" matriste kaydedilince sessizce Team listesi hakkı kazanır**
- Dosyalar: hr/roles.py:9-12, 28-31; core/access.py (`implied`); config/access.py (Employees `all_production`)
- Açıklama: Önayar `hr.all_production_employee` verir ama `hr.view_employee` vermez ("No Team list" - hr/roles.py:10). `implied()` bir alanda herhangi bir eylem seçilince Read'i ekler; rol formu matris üzerinden bir kez kaydedildiğinde `hr.view_employee` eklenir ve Team listesi/ kişi sayfaları açılır. Önayarın belgelenen yetki kümesi ile matrisin ürettiği küme tutarsız.
- Kanıt: hr/roles.py:31 izin listesinde `view_employee` yok; core/access.py `implied`: `if READ in area.actions and any(area.perm(action) in names ...): names.add(area.perm(READ))`.
- Öneri: Önayara `view_employee` açıkça eklenip davranış belgelensin ya da `all_production` Read'i ima etmesin; test ekle.

### 02-4 | Orta | Güven: yüksek
**Düzenleme/ekleme yetkisiyle başka kaynağın (Batch) değiştirilmesi: `batch_details` yalnızca `add_stockoperation` ister**
- Dosyalar: farm/stock/views.py:502-522
- Açıklama: Parti (Batch) yıl sınıfı/yabani-çiftlik bilgisi, matriste Batch alanı olmadığı için "stok işlemi Create" izniyle POST ile değiştirilebiliyor; satır kapsamı yok, rol matrisi bu yazmayı göstermiyor. Yetki matrisi ile gerçek yetki uyuşmuyor (matris yalnızca işlem kaydı gösteriyor).
- Kanıt: `@permission_required(RECORD)` ... `form = BatchDetailsForm(request.POST, instance=batch); form.save(request.user)`.
- Öneri: Matriste açıklamaya ekle ya da ayrı izin (`farm.change_batch`) ile koru.

### 02-5 | Orta | Güven: yüksek
**Aktivite günlüğünde yalnızca HR kayıt türleri kısıtlı; diğer hassas günlükler `core.view_auditlog` sahibine açık**
- Dosyalar: core/audit.py:25-43, hr/apps.py:14, core/views.py:28-58
- Açıklama: `restrict()` sadece HR'ın 5 modeli için kullanılıyor. Kullanıcı/rol değişiklikleri (e-posta, atanan roller), kanal üyelikleri ve görev notlarının tam metni (tasks/services.py:196-198) günlük okuyucusuna açık. Ayrıca HR kısıtı `hr.all_employee` sahibine bağlı: `all_production` sahibi (müdür) HR günlüğünü göremez, tutarlı ama `LeaveType`, `Shift`, `Holiday` gibi diğer HR modelleri kısıtsız.
- Kanıt: core/audit.py:39-43 `readable` yalnızca `_restricted` türlerini dışlar; tasks/services.py:198 `audit.record(... {str(NOTE): [None, body]})`.
- Öneri: Roller/kullanıcılar/kanallar için `restrict` listesi gözden geçirilsin; günlük görüntüleme hakkı bilinçli olarak yönetici düzeyinde tutulsun.

### 02-6 | Orta | Güven: orta
**Raporlar (`reports.view_report`) başka alanların verisini o alanların izni olmadan gösterir ve dışa aktarır**
- Dosyalar: reports/views.py:202-241, 33-38, 41-52
- Açıklama: `export` ve `print_page` yalnızca `view_report` ister; içerik `compute.compute(report).content` ile stok, yem, ilaç, bit sayımı vb. kayıtlardan canlı hesaplanır (taslakta). İzleme modülü bölüm başına izin uygular (monitoring/read.py:107-110) fakat raporlar uygulamaz; Reports Read izni, Production units/Treatments/Lice Read izninin yerini tutar. Tasarım gereği olabilir (rapor sahibi yasal rapor çıkarır) ama matris bunu belirtmiyor.
- Kanıt: reports/views.py:33-37 `_content`: `return compute.compute(report).content, False`.
- Öneri: Bu sızıntı belgelenmeli veya Reports Read için ön koşul izinleri tanımlanmalı.

### 02-7 | Düşük | Güven: yüksek
**İzleme sayfası Site/Departman/Sistem/Tank listelerini ilgili Read izni olmadan filtre seçeneği olarak sunar**
- Dosyalar: monitoring/views.py:112-120
- Açıklama: `monitoring.view_monitorboard` sahibi, `farm.view_site/system/tank` izni olmasa da tüm site, departman, sistem ve tank (kod) adlarını bağlamda alıyor. Kart içeriği izne göre filtreleniyor ama yapı adları sızıyor.
- Kanıt: `sites=Site.objects.order_by('name'), departments=..., systems=..., all_units=Tank.objects.order_by('code')`.
- Öneri: `_counts` (config/views.py:15) gibi `has_perm` ile filtrele.

### 02-8 | Düşük | Güven: yüksek
**Rapor "sunuldu" kaydı geri alınamaz işlem olduğu halde sıradan `change_report` izniyle yapılıyor (görev ayrılığı yok)**
- Dosyalar: reports/views.py:55-57, 94, 123, 147, 178; config/access.py (Regulatory reports yorumu)
- Açıklama: Taslağı dolduran kişi aynı izinle raporu "filed" yapıp dondurabilir; kapatma/yeniden açma ve "dış görev yapıldı" da aynı izin. Ayrı "gönder/onayla" hakkı yok.
- Kanıt: `@permission_required('reports.change_report', ...)` `def submit`.
- Öneri: Ayrı bir `submit` izni ya da matriste ayrı sütun düşün.

### 02-9 | Düşük | Güven: yüksek
**Bilgi girişinin kendi kaydını inceleme (dört göz) kontrolü yok**
- Dosyalar: knowledge/views.py:54-85; knowledge/models/entry.py:175-177; README.md ("Owner decision open")
- Açıklama: `change_knowledgeentry` sahibi kendi oluşturduğu girişi `reviewed` yapabilir; sadece belgelenmiş açık karar.
- Kanıt: `review_entry` yalnızca `_allowed(request, KnowledgeEntryResource, 'change')` kontrol eder, `reviewed_by != created_by` yok.
- Öneri: Karar verilene dek bu risk kabul listesinde izlensin; DB CHECK + ayrı Review sütunu.

### 02-10 | Düşük | Güven: orta
**Deney ekibi (`Member`) yetkiye etki etmiyor; `change_experiment` sahibi her deneyi düzenler/başlatır**
- Dosyalar: experiments/resources.py:93-100 (yalnızca "Mine" filtresi), experiments/resources.py:175-185; README.md ("permissions plan")
- Açıklama: Ekip yalnızca bilgi; "öğrenci yalnız ekibi olduğu deneyleri düzenler" henüz yok (docs/experiments.md:16). Ekip listesini de `change` sahibi herhangi biri değiştirebilir.
- Kanıt: `objects.filter(members__user=request.user)` yalnızca liste görünümünü daraltır.
- Öneri: `Resource.scoped/allowed` ile ekip tabanlı kural uygula veya "kullanılmıyor" diye belgele.

### 02-11 | Düşük | Güven: orta
**Ekip kapsamındaki yönetici, kendi Employee kaydını düzenleyebilir (yerleşim, işe giriş/ayrılış tarihi, istihdam türü)**
- Dosyalar: hr/services.py:25-28, 50-52; hr/forms/employee.py:77-81; hr/resources/employee.py:40-42; hr/scope.py:127-135
- Açıklama: `self_plan` yalnızca vardiya/yoklama/izin için kendi kaydı engelliyor. `EmployeeResource.allowed` tanımlı değil (varsayılan True), `scope.team` kişinin kendisini içerir; `change_employee` sahibi kendi yerleşimini taşıyabilir, `joined_on/left_on` değiştirebilir. `user` alanı yalnızca `all` sahibine açık (iyi).
- Kanıt: hr/scope.py:135 `Q(user=user) | Q(pk__in=members)`; hr/resources/employee.py'de `allowed` override yok.
- Öneri: `EmployeeResource.allowed` içinde `self_plan` benzeri kural.

### 02-12 | Düşük | Güven: yüksek
**Toplu vardiya planı (`plan`) mount'un realm'ini uygulamıyor**
- Dosyalar: hr/views.py:56-80 (`scope.team(request.user)` realm'siz), hr/views.py:72
- Açıklama: Üretim > Takım adresi ile ofis kişisi (ulaşılabiliyorsa) planlanabilir, diğer sayfalar realm ile daralıyor. Yetki yükseltmesi değil, tutarsızlık; yazma kapsamı okuma kapsamından geniş. Vardiya (`Shift`) de site/realm'e bağlanmıyor.
- Kanıt: `reachable = {... scope.team(request.user).filter(pk__in=...)}`.
- Öneri: `scope.team(request.user, realm=scope.realm_for(request))`.

### 02-13 | Düşük | Güven: yüksek
**Herhangi bir `tasks.view_task` sahibi her göreve not ekleyebilir; atanan/Edit şartı yok**
- Dosyalar: tasks/views.py:79-90; tasks/services.py:190-205
- Açıklama: start/complete/tick için `may_work_on` (Edit veya atanan) var, `add_note` için yok; notlar "iş kaydının parçası, silinemez" (tasks/services.py:191). Read-only rol kalıcı not yazabilir. README'de "adding a note" Read'e dahil diye yazıyor, yani tasarım ama yazma yetkisi okuma altında.
- Kanıt: `add_note` içinde izin çağrısı yok.
- Öneri: Notu en az atanan/Edit ile sınırla veya matriste belirt.

### 02-14 | Düşük | Güven: orta
**Mesajlaşma: `start_direct` soft-delete edilmiş konuşmayı döndürür; kişi dizini `messaging.view_conversation` sahibi herkese açık**
- Dosyalar: messaging/services.py:95-110, 47-52
- Açıklama: `Conversation.all_objects.filter(direct_key=key).first()` silinmiş bir konuşmayı döndürebilir; sonrasında `member()` `is_deleted=False` filtresiyle 404 verir (kullanıcı konuşmaya giremez). Ayrıca `contacts()` tüm aktif kullanıcıları (ad/soyad) Messages izni olan her role listeler.
- Kanıt: `found = Conversation.all_objects.filter(direct_key=key).first(); if found is not None: return found`.
- Öneri: Silinmiş doğrudan konuşmayı canlandır veya yeni oluştur; kişi dizinini belgele.

### 02-15 | Düşük | Güven: orta
**Envanter sayımı/silme ve yazma ayrımı: sayım onayı ve iptal (void) aynı "Delete" izniyle; iki kişi kuralı yok**
- Dosyalar: inventory/views.py:275-348, 416-420; docs/aquaculture-platform-bugs.md STR-22
- Açıklama: `add_inventoryoperation` sahibi her tür (atık, düzeltme, sayım) kaydedebilir; belgedeki "count second person" kuralı uygulanmadı ("later (Q-S7)").
- Kanıt: inventory/views.py:416 `@permission_required(VOID)`; sayım için ayrı onay yok.
- Öneri: Açık karar olarak izle.

### 02-16 | Bilgi | Güven: yüksek
**Django admin yalnızca superuser ile erişilir; `AuditedModelAdmin.restore` günlüğe yazılmayan geri yükleme yolu**
- Dosyalar: core/admin.py:28-55, 72; config/urls.py:41
- Açıklama: `UserForm` is_staff/is_superuser vermiyor, yönetici dışında kimse admin'e giremez. Admin `restore` eylemi `softdelete.restore` çağırır (günlüğe yazıp yazmadığı bu denetimde doğrulanmadı). /admin/ herkese açık adreste ve 2FA/oran sınırı yok (authn alanı).
- Kanıt: core/admin.py:32-35 `has_restore_permission`.
- Öneri: Admin'i ağ düzeyinde kısıtla; restore'un denetim izini doğrula.

### 02-17 | Bilgi | Güven: yüksek
**Doğrulanan olumlu kontroller (bulgu değil)**
- Dosyalar: core/crud.py:557, 592-596; core/dbview.py:14-15; core/database.py:20; messaging/services.py:69-75; hr/services.py:271-276
- Açıklama: Her CRUD fiili izin + `scoped` ile korunuyor, kapsam dışı kayıt 404; veritabanı görüntüleyici `core.browse_database` ister ve matriste sunulmaz; mesaj konuşmaları üyelik dışı 404; izin kararları izin kontrolü sunucuda (düğme gizlemeye güvenilmiyor); izin onayında kendi talebini onaylama engelli (`_own`); sahte `next` yönlendirmeleri doğrulanıyor (hr/views.py:34-40, tasks/views.py:36-40).
- Kanıt: bkz. dosyalar.
- Öneri: Yok.
