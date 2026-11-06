# 43 - Kullanıcı akışları (ux-flows) denetimi

## Özet
Navigasyon verisi tek yerde (config/navigation.py + core/navigation.py) toplanmış, CRUD diyalogları (silme planı, void, sürüm çakışması) iyi düşünülmüş. Bulgular: Company/Production panel mantığındaki boşluklar (giriş sonrası iniş sayfası, gizli girişlerin menüde işaretlenmemesi, yetim "Leave types" sayfası), boş durum metinlerinin filtreleri ayırt edememesi, modal (diyalog) istemcisinin hata/kirli-form davranışları, onaysız yıkıcı eylemler ve geri alma yollarının (soft delete yalnızca admin, void geri alınamaz) kullanıcıya doğru anlatılmaması.

## İncelenen alanlar
templates/app_base.html, modal_base.html, crud/*, hr/leave_*, hr/settings_list.html, messaging/members.html|confirm.html, farm/stock_void.html ve türevleri, farm/production_units.html, home/production_home, config/navigation.py, config/views.py, core/navigation.py, core/middleware.py, core/crud.py (Create/Update/Delete view, done()), frontend/components.ts (Modal), shell.ts, nav-boot.ts, farm/admin.py, core/admin.py.

## İncelenmeyen alanlar
Tarayıcıda gerçek çalıştırma/erişilebilirlik testi, CSS/responsive görünüm, .po çevirileri, deneyler (experiments) ve rapor (reports) akışlarının tamamı, roster/monitoring/pencere TS kodu, her liste şablonunun tek tek boş durumu.

## Bulgular

### 43-1 - Giriş sonrası herkes Company özetine düşüyor; üretim çalışanı neredeyse boş sayfa görür (orta, güven: yüksek)
Dosyalar: config/settings.py:200, templates/home.html, config/views.py:25-30, core/middleware.py
Açıklama: `LOGIN_REDIRECT_URL='home'` ve `home` Company özeti; WorkspaceMiddleware paneli oturumda hatırlıyor ama girişten sonra `/` yolu company'ye ait olduğundan hatırlanan panel hemen company ile ezilir. Yalnız üretim izni olan kullanıcı, tek kutucuğu (Sites, izne bağlı) olan ve "The company’s figures will appear here" yer tutucusu gösteren sayfaya iner; Production'a panel menüsünden kendisi geçmeli.
Kanıt: `LOGIN_REDIRECT_URL = 'home'`; home.html `<section class="placeholder">...figures will appear here`; `workspace_of('/')` company döner.
Öneri: Girişte oturumdaki son paneli veya kullanıcının sunulan ilk anlamlı panelini aç (ör. yalnız Production sunuluyorsa `production_home`).

### 43-2 - Gizli (hidden) menü girişleri sayfadayken rail'de hiçbir satır aktif değil (düşük, güven: yüksek)
Dosyalar: core/navigation.py:170, config/navigation.py:70-72
Açıklama: `current_url` hidden girişler dahil hesaplanır, fakat rail yalnızca `shown_to` olanları çizer; Shifts/Holidays/Leave types sayfalarında hiçbir satır `aria-current` almaz ve üst sayfa ("Scheduling settings") işaretlenmez. Yorum "it is current there" diyor ama işaret kullanıcıya yansımıyor.
Kanıt: `current_url = max(... entry.matches(request.path) ...)`; satırlar `for entry in group.entries if entry.shown_to(...)` içinde `'current': entry.url() == current_url`.
Öneri: Hidden giriş current ise ebeveyn girişi (Scheduling settings) işaretle veya hidden girişe `parent` alanı ekle.

### 43-3 - "Leave types" sayfasına hiçbir bağlantı yok (yetim sayfa) (orta, güven: yüksek)
Dosyalar: config/navigation.py:72, hr/resources/leave.py:16, templates/hr/settings_list.html:31,38
Açıklama: Giriş `hidden=True` ve "Scheduling settings'ten erişilir" deniyor; fakat settings_list.html yalnız "Manage shifts" ve "Manage holidays" bağlantılarını içeriyor. `hr:leavetype_list` şablonlarda hiçbir yerde `{% url %}` ile geçmiyor. İzin türleri (tohumsuz, "none seeded") eklenemeden izin talebi akışı kullanılamaz; yönetici yolu bulamaz.
Kanıt: grep `leavetype_list` templates/ → yalnız leave_type_list içi `leavetype_edit/delete`; settings_list'te leave types bölümü yok.
Öneri: settings_list.html'e "Leave types" bölümü + "Manage leave types" bağlantısı ekle; izin talep formunda tür yoksa buraya yönlendir.

### 43-4 - Liste boş durumu filtre sonucunu "No X yet / Add the first" diye gösterir (düşük, güven: yüksek)
Dosyalar: templates/crud/list.html:33-38, core/crud.py:620-645
Açıklama: Boş durum yalnız `q` aramasını ayırt ediyor. `filter_list` ile (ör. `?kind=`, `?status=`) uygulanan filtre sıfır sonuç verince "No tanks yet - Add the first tank" yazar ve filtreyi temizleme bağlantısı yoktur; kayıt var olduğu halde yoktur izlenimi doğar. (production_units.html:56-66 bu ayrımı doğru yapıyor; tutarsız.)
Kanıt: `{% if query %}... {% else %}<h2>No {{ plural }} yet`.
Öneri: Filtre parametresi aktifse "No match / Clear filters" dalını göster (ListView bağlama `filtered` bayrağı versin).

### 43-5 - Modal istemcisi: ağ hatası ve 404/500 yanıtları işlenmiyor, ham HTML diyaloğa basılıyor (orta, güven: yüksek)
Dosyalar: frontend/components.ts:334-359
Açıklama: `fetch` try/catch'siz; çevrimdışı/zaman aşımında hiçbir şey olmaz (form gönderildi mi bilinmez, düğme tekrar basılır). 403 dışındaki hata durumları (404, 500, CSRF 403 dışı) `response.text()` olarak `innerHTML`'e basılıyor; tam hata sayfası diyalog içinde görünür. Çiftlik ağında kesinti beklenen bir durum.
Kanıt: `this.content.innerHTML = await response.text();` yalnız `status === 403` ayrımı var; `response.ok` kontrolü yok.
Öneri: try/catch + `response.ok` kontrolü; "Bağlantı yok / Bir şey ters gitti, tekrar dene" iletisi göster, form girdisini koru.

### 43-6 - Diyalog kirli form uyarısı vermiyor: backdrop tıklaması/Esc girilen veriyi sessizce atar (orta, güven: yüksek)
Dosyalar: frontend/components.ts:312-314, 323-325
Açıklama: Uzun kayıt formları (sekmeli, stok/su kaydı) diyalogda açılıyor. Backdrop'a yanlış tıklama, Esc veya "Cancel" değişiklik kontrolü olmadan `dialog.close()` yapar ve içerik `replaceChildren()` ile silinir. Dirty-state/onay yok.
Kanıt: `if (event.target === dialog) dialog.close();` ve close olayında `this.content.replaceChildren()`.
Öneri: Form değiştiyse (input olayı ile dirty bayrak) kapatmadan önce onay iste; en azından backdrop kapatmayı kirli formda iptal et.

### 43-7 - Çift gönderim koruması yalnız Create'te; modal/sayfa düğmeleri gönderim sırasında devre dışı bırakılmıyor (düşük, güven: orta)
Dosyalar: frontend/components.ts:318-322, core/crud.py:668-700, templates/farm/stock_void.html:18-26
Açıklama: Create `entry_key` ile idempotent; ancak void, leave approve/reject, görev tamamla, stok/su kaydı gibi POST'larda gönderim sırasında buton kilitlenmiyor, yavaş ağda çift tık ikinci isteği gönderir (void için sunucu "zaten void" hatası/çift kayıt riski servis katmanına bağlı, doğrulanmadı).
Kanıt: submit işleyicisi yalnız `preventDefault` + `load`; buton `disabled` yok.
Öneri: Submit sırasında butonu devre dışı bırak ve "Saving..." göster.

### 43-8 - Sürüm çakışmasında diyalog tam sayfaya atıyor ve kullanıcının girdisi kayboluyor (düşük, güven: yüksek)
Dosyalar: core/crud.py:726-731, core/crud.py:102-108, frontend/components.ts:342-346
Açıklama: Çakışmada `done(request, edit_url)` stay=False olduğundan modal için `X-Modal-Redirect` döner; istemci `window.location.assign` ile düzenleme formunu tam sayfa olarak açar (diyalog bağlamı kaybolur). Mesaj "make your changes again" der ama kullanıcının yazdığı değerler gösterilmez/geri verilmez.
Kanıt: `return done(request, self.url('edit', pk))` (stay yok) ve `done()` içinde `'X-Modal-Load' if stay else 'X-Modal-Redirect'`.
Öneri: Çakışmada `stay=True` kullan ve kullanıcının girdisini yan yana göster/kopyalanabilir bırak.

### 43-9 - Kayıt oluşturma sonrası akış: Create -> düzenleme formu, Update -> liste (tutarsız) (info, güven: yüksek)
Dosyalar: core/crud.py:700 (done(... stay=True)), core/crud.py:745
Açıklama: Yeni kayıt kaydedilince diyalog/sayfa aynı kaydın düzenleme formuna geçer (sekmeli; History sekmesi için gerekçeli), düzenleme kaydedilince listeye dönülür. Kullanıcı "Create" sonrası listeye dönmeyi bekler; diyalogda ikinci bir "Cancel" ile kapatmak gerekir ve kapanışta sayfa yeniden yüklenir.
Kanıt: `return done(request, self.url('edit', obj.pk), stay=True)` vs `return done(request, self.url('list'))`.
Öneri: Davranışı bilinçli belge/ipucu ile belirt (ör. "Created. Add details" başlığı) ya da basit formlarda listeye dön.

### 43-10 - Silme onayı "admin'den geri getirilebilir" diyor; admin dışı kullanıcı için geri alma yolu yok (orta, güven: yüksek)
Dosyalar: templates/crud/confirm_delete.html:47, core/admin.py:27-53, farm/admin.py:23,55
Açıklama: Soft delete sonrası metin kaydın admin'den geri getirilebileceğini söylüyor, fakat geri yükleme yalnız platform admininin Django admin eylemi (`has_restore_permission`); uygulama içinde "çöp kutusu"/geri al yok ve flash mesajında geri al bağlantısı yok. Silme sonrası yanlışlığı fark eden normal kullanıcı için akış çıkmazdır. Ayrıca void edilen stok/besleme/su kayıtları admin restore'dan bilerek hariç (farm/admin.py:23,55) yani hiç geri alınamaz.
Kanıt: confirm_delete.html:47 metni; core/admin.py:36 `has_restore_permission`; farm/admin.py:55 "a restore would bring back a value someone said was wrong".
Öneri: Metni rolüne göre doğru yaz ("yalnız platform yöneticisi geri getirebilir"); silme sonrası flash'a kısa süreli "Geri al" (restore) bağlantısı veya Activity log'dan geri yükleme ekle.

### 43-11 - Void (iptal) diyalogları geri alınamazlığı söylemiyor (orta, güven: orta)
Dosyalar: templates/farm/stock_void.html:14, farm/health_event_void.html:7, farm/water_void.html:10-12, farm/feeding_void.html
Açıklama: Metinler "stops counting, stays in the history with its reason" der; geri alma (un-void) olmadığı, düzeltmenin "void edip yeniden girme" olduğu yalnız stok metninde geçer. Water/health/feeding void'de yok. Kod tabanında un-void eylemi yok (grep: unvoid/reinstate yok), admin restore da dışarıda. Stocking void "takes its batch with it" ama etkilenen sonraki operasyonların listesi yalnız "refused" durumunda görünür.
Kanıt: grep `unvoid|reinstate` sonuçsuz; stock_void.html:14 yalnız stok için "void it and enter it again".
Öneri: Tüm void diyaloglarında "Bu geri alınamaz; yeniden girmek için ... sayfasını kullanın" cümlesi ortak partial'da; onay butonunda etkilenen kayıt sayısını göster.

### 43-12 - Onaysız tek tıkla yıkıcı/geri alınamaz eylemler: izin talebini iptal, kanaldan üye çıkarma (orta, güven: yüksek)
Dosyalar: templates/hr/leave_list.html:39, templates/hr/leave_detail.html:25, templates/messaging/members.html:22-25
Açıklama: "Cancel the request" liste satırında yalnız kırmızı ikon düğmesi (onay yok, geri alma yok; izin talebi silinemiyor, iptal son hal), detayda da tek tık. Mesajlaşmada kanaldan ayrılma (`leave`) ve mesaj silme onaylı iken (confirm.html) "Remove" (üye çıkarma) ve "Make owner" onaysız doğrudan POST; "Make owner" ile yetki devri tek tık. Aynı alan içinde onay politikası tutarsız. (Görev için `reopen` var; izin için yok.)
Kanıt: leave_list.html:39 `<form ... leaverequest_cancel ...><button type="submit" class="icon-button icon-button-danger"`; members.html:22-25 `remove_member` formu, onay şablonu yok; messaging/confirm.html yalnız leave/delete_message için kullanılıyor.
Öneri: remove_member, set_role(owner) ve leave cancel için `confirm.html`/modal onayı; mümkünse izin talebi için "Reopen".

### 43-13 - Onay ekranlarında düğme/dil tutarsızlığı: Cancel / Back, danger stili (düşük, güven: yüksek)
Dosyalar: templates/tasks/task_action.html:15-16, templates/hr/leave_reject.html:20, templates/hr/leave_approve.html:28, templates/crud/confirm_delete.html:53-55
Açıklama: İptal düğmesi bazı diyaloglarda "Cancel", görev eyleminde "Back". Reddetme ("Reject") ve "Approve" düğmeleri `button-danger` değil, oysa void/delete danger; reject'in yıkıcılığı görsel olarak ayırt edilmiyor. Leave approve/reject, crud şablonlarından farklı `class="form"` + elle yazılmış `.confirm` olmayan iskelet kullanıyor.
Kanıt: ilgili satırlar (`{% trans "Back" %}`, `<button type="submit" class="button">{% trans "Reject" %}`).
Öneri: Ortak onay partial'ı (confirm kapsayıcı, Cancel, danger bayrağı).

### 43-14 - Flash hata mesajları `role="status"` ile duyuruluyor (düşük, güven: yüksek)
Dosyalar: templates/app_base.html:99, templates/modal_base.html:13
Açıklama: Başarı ve hata (messages.error: "cannot be deleted", "Someone else changed...") aynı `role="status"` (polite) kutuda; ekran okuyucu kritik hatayı atlayabilir. Form hataları `role="alert"` kullanıyor, tutarsız.
Kanıt: `<div class="flash-list" role="status">` ve `flash-{{ message.tags }}`.
Öneri: error/warning etiketli mesajlar için `role="alert"`.

### 43-15 - Silme engelli kayıtta düğme `disabled`, ama hata nedeni yalnız üstte; Cancel bağlantısı data-modal-close'a bağımlı (info, güven: orta)
Dosyalar: templates/crud/confirm_delete.html:16-23,53-55
Açıklama: Engelleyiciler listeleniyor (iyi). `plan` yoksa (AuditedModel olmayan kayıt) "removes it permanently" gösterilir ama bağımlı kayıt etkisi (ilişkili kayıtlar) bilgisi yok; kalıcı silme tek onayla. Plan'lı kayıtta silinen/ayrılan listeleri var, hard delete dalında yok.
Kanıt: confirm_delete.html:48-49 `{% else %}<p>This removes it permanently...`; core/crud.py:772-774 `audit.record_delete ... obj.delete()` plansız.
Öneri: Hard delete'te de bağlı kayıt sayısını/PROTECT durumunu göster.

### 43-16 - Production özeti izinsiz erişilebilir ve boş yer tutucu; Company özeti yalnız tek kutucuk (düşük, güven: yüksek)
Dosyalar: config/urls.py:27, config/views.py:30-55, templates/production_home.html:35-37, templates/home.html:9-11
Açıklama: `production_home` görünümünde panel izni kontrolü yok (menü gizleme "courtesy"); izni olmayan biri `/production/` açınca yalnız boş bölümler ve "The production figures will appear here." görür (403 yerine). Her iki özet sayfası da sabit "will appear here" yer tutucusu taşıyor; tüm kutucuklar izin yoksa sayfa tamamen boş kalıyor ve boş durum/yönlendirme yok.
Kanıt: `path('production/', views.production_home...)` login dışında dekoratör yok; `<section class="placeholder">`.
Öneri: Panel sunulmuyorsa 403/yönlendirme; hiç kutucuk yoksa "Henüz görüntüleyecek bir şey yok, yöneticinize başvurun" metni.

### 43-17 - Rail altbilgisi ve varsayılan başlıklar sabit/yer tutucu: "Fish farm", "Panel" (info, güven: yüksek)
Dosyalar: templates/app_base.html:6,61,69-70
Açıklama: `rail_foot` varsayılanı "Fish farm", `eyebrow` varsayılanı "Panel", `heading` varsayılanı "Overview"; bir şablon bloğu doldurmayı unutursa yanlış bağlam ("Panel · Overview") görünür. Panel adı (Company/Production) eyebrow'da dinamik değil.
Kanıt: `{% block eyebrow %}{% trans "Panel" %}{% endblock %}`, `{% block heading %}{% trans "Overview" %}`.
Öneri: Varsayılanları `workspace.label` ve boş başlık yap; test ile doldurulmamış blok yakala.

### 43-18 - Panel rozeti toplamı ve panel anahtarı hedefi: her zaman paneli ilk girişine (özet) götürür, son sayfayı hatırlamaz (info, güven: orta)
Dosyalar: core/navigation.py:186-190, templates/app_base.html:21-22
Açıklama: Panel menüsü bağlantısı `sections[0]...entries[0]['url']` yani panelin özetidir; kullanıcı Production › Water chemistry'de iken Company'ye gidip dönerse son sayfasına değil özetine düşer (middleware `workspace` oturum anahtarı yalnız menü içeriğini hatırlar). Panel rozeti (menu-badge) toplam sayıdır ama URL'siz (`Badge(sum, '')`) olduğundan yoklanmaz, sayfa değişene dek eskir.
Kanıt: `'url': sections[0]['groups'][0]['entries'][0]['url']`, `Badge(sum(badges), '')`.
Öneri: Panelin son ziyaret edilen sayfasını oturumda sakla; rozeti de yoklanan bir fragmana bağla.

### 43-19 - Saat girişi/çıkışı (Clock in/out) ve görev/İK eylemlerinde geri bildirim `next` sayfasına dönüyor; başarısızlıkta durum tutarsız (düşük, güven: düşük)
Dosyalar: templates/hr/today.html:12-13, hr/views.py:109-118
Açıklama: Punch formları sayfa yenilemesiyle çalışıyor; `_run` hata durumunda yalnız `messages.error` verip sayfaya döner. Clock out için onay/geri alma (yanlış çıkış) kullanıcı akışı görünmüyor; düzeltme yalnız attendance kaydı düzenlemesi olabilir (doğrulanmadı).
Kanıt: today.html:12 `<form method="post" action="{% url 'hr:punch'|mounted:request 'out' %}"`.
Öneri: Yanlış basış için "Undo" (kısa pencere) veya belgelenmiş düzeltme yolu.
