# 42 - Templates denetimi

## Özet
Şablon katmanı genel olarak düzenli: `crud/list|form|detail|confirm_delete` ile kalıtım, her POST formunda `{% csrf_token %}` (betikle doğrulandı), `|safe` yalnızca bir yerde, satır içi `<script>` yok, `target="_blank"` hepsinde `rel` var. Bulgular tekrar (void formları, sekme çubukları, sayfalayıcı, `<head>`), `mounted` kullanımında tutarsızlık, form `action` tutarsızlığı, markup'ta mantık sızması ve şablon testlerinin yetersizliği üzerinde.

## İncelenen alanlar
templates/ altındaki tüm .html dosyaları (app_base, auth_base, modal_base, crud/*, farm/*void*, hr/*, monitoring/_card, registration/_field, _row_list, knowledge/document_text vb.), şablon kalıtım zinciri, csrf/safe/inline script-style taraması, URL kullanımı (`mounted`), N+1 (şablonda `.all`) ve ilgili `prefetch_related` kontrolü, core/tests_templates.py.

## İncelenmeyen alanlar
Şablon etiketleri/filtrelerinin (templatetags) iç mantığı, CSS/TS tarafı, çeviri (.po) tamlığı, tarayıcıda render, erişilebilirlik testi, her şablonun satır satır tam okunması (örneklem + grep).

## Bulgular

### 42-1 - `registration/_field.html` help_text'i `|safe` ile basıyor (orta, güven: orta)
Dosyalar: templates/registration/_field.html:20, farm/forms/water.py:180
Açıklama: Tüm formların yardım metni escape'siz basılıyor. Tek HTML üreten yer `format_html_join` (zaten SafeString, escape eder); diğer formlardaki düz metin help_text'ler (model/DB'den, ör. `parameter.help`) `<`/`&` içerirse ham basılır. `|safe` gereksiz ve gelecekte stored-XSS yüzeyi.
Kanıt: `{{ field.help_text|safe }}`; water.py:180 `help_text = format_html_join(' ', '{}', ...)`.
Öneri: `|safe` kaldır; HTML gereken yerler `format_html/mark_safe` ile SafeString döndürsün.

### 42-2 - Void diyalogları üç şablonda kopya, `water_void` `stock_void` formunu kopyalıyor (orta, yüksek)
Dosyalar: templates/farm/water_void.html:13-25, templates/farm/stock_void.html:17-29
Açıklama: stock_void.html "entry" bloğu ile türetilebilir bir iskelet (feeding/lice/treatment/health_event bunu `extends` ediyor) iken water_void.html aynı form/reason/Cancel/Void gövdesini baştan yazıyor. Birinde yapılan düzeltme (ör. buton, hata alanı) diğerine gitmez.
Kanıt: iki dosyada aynı `<form method="post" action="{{ request.get_full_path }}" novalidate>…{% with field=form.reason %}…button-danger`.
Öneri: water_void `farm/stock_void.html`'i extend etsin (entry bloğunu doldursun) veya ortak `_void_form.html` include edilsin.

### 42-3 - POST form `action` tutarsızlığı: `request.path` ve `request.get_full_path` (düşük, yüksek)
Dosyalar: templates/crud/form.html:22, crud/confirm_delete.html:52 (request.path); farm/stock_void.html:18, farm/water_record.html, inventory/dialog.html, tasks/task_action.html vb. (get_full_path)
Açıklama: CRUD formları sorgu dizgisini düşürür (ör. roster'dan `?employee=` ile açılan create formu geçersiz yanıtta/yeniden gönderimde sorguyu kaybeder), diğer ~15 şablon korur. Aynı kavram için iki davranış.
Kanıt: `action="{{ request.path }}"` vs `action="{{ request.get_full_path }}"` (grep).
Öneri: tek kural seç (tercihen boş `action` veya get_full_path) ve ortak include kullan.

### 42-4 - `mounted` filtresi yalnızca hr'nin bazı şablonlarında; kalan ~182 `{% url %}` sabit (düşük, orta)
Dosyalar: templates/hr/leave_list.html, hr/employee_list.html (mounted); hr/holiday_list.html:16, hr/shift_list.html:17, hr/leave_type_list.html:15, hr/department_list.html:28 (mounted'sız); hr/resources/*.py (`mounts = (Mount(...))`)
Açıklama: Sayfalar iki yerden (mount) sunulabildiği için `mounted` gerekli (core/templatetags/crud.py:9). Hangi kaynağın mount'lu olduğu şablondan görünmüyor; bir kaynağa sonradan mount eklenirse ilgili şablon sessizce yanlış alana link verir. Şu an mount'sız kaynaklar için doğru, ama kural şablonlarda örtük.
Kanıt: grep: `{% url 'hr:` satırlarının mounted'lı/mounted'sız dağılımı; tests_crud_mount.py yalnızca crud tarafını sınar.
Öneri: crud şablonlarında URL'leri görünümden gelen değişkenlere (`edit_url`, `delete_url` zaten var) bağla; `mounted` testine "mount'lu resource şablonları mounted kullanır" denetimi ekle.

### 42-5 - Liste satırı eylem ikonları (Düzenle/Sil) ~35 liste şablonunda kopya (orta, yüksek)
Dosyalar: templates/farm/site_list.html:30-31, farm/supplier_list.html:54-55, hr/holiday_list.html:19-20, hr/shift_list.html:24-25, farm/tank_list.html, farm/equipment_list.html vb.
Açıklama: `icon-button` + `blocktrans Edit/Delete {{ name }}` + `sr-only` üçlüsü her listede elle yazılı; ayrıca `can_change/can_delete` ve başlık bağlantısı aynı. crud/list.html başlık/boş durum/ekle'yi ortaklaştırmış ama satır eylemleri ortaklaşmamış. Metin ve ARIA değişikliği 38 dosya gerektirir.
Kanıt: aynı `{% if can_change %}<a class="icon-button" href="{% url '…_edit' x.pk %}" data-modal title="{% blocktrans with name=… %}Edit {{ name }}…` desenleri.
Öneri: `crud/_row_actions.html` include (`edit_url`, `delete_url`, `name`) ya da simple_tag.

### 42-6 - Sekme çubuğu (`view-tabs`) 10+ şablonda ayrı yazılmış, üç farklı "aktif" işareti (düşük, yüksek)
Dosyalar: hr/leave_list.html:9 (class `is-current`), tasks/task_list.html:15, inventory/storage.html:11, experiments/experiment_detail.html:24, reports/report_list.html:10, farm/_harvest_tabs.html:4, farm/_water_tabs.html:3-5, farm/production_units.html:14-15
Açıklama: Çoğu `aria-current="page"` kullanırken hr/leave_list.html `is-current` sınıfı kullanıyor (erişilebilirlik/stil tutarsız). Sayı rozeti koşulu `item.count is not None` (task_list:15) vs `tab.count` (report_list:10): 0 sayısı biri gösterir, diğeri gizler. `_harvest_tabs` tek sekmede gizler, `_water_tabs` gizlemez.
Kanıt: ilgili satırlar.
Öneri: `_view_tabs.html` ortak include; aktif işareti tek biçim.

### 42-7 - Sayfalayıcı: knowledge/document_text.html kendi kopyasını taşıyor ve davranışı farklı (düşük, yüksek)
Dosyalar: templates/knowledge/document_text.html:17-25, templates/crud/_pager.html
Açıklama: Kopya `pager_query` desteklemez, "Page n of m" göstermez. Metinler aynı `msgid` ("{{ first }}–{{ last }} of {{ total }}") kullanıyor ama biçim farklı.
Kanıt: document_text.html:19-22 `href="?page=…"`; _pager.html:5-7 `?{{ pager_query }}&page=`.
Öneri: `crud/_pager.html` include et (page ve pager_query ver).

### 42-8 - `<head>` iskeleti üç yerde kopya; Google Fonts dış bağımlılığı (düşük, yüksek)
Dosyalar: templates/app_base.html:6-17, auth_base.html:6-17, farm/water_calculator_report.html:7-16
Açıklama: meta/font/favicon/module_map/CSS blokları kopya (rapor sayfası fontu hiç yüklemiyor, nav-boot.js yok - tutarsız). Fontlar `fonts.googleapis.com`'dan: gizlilik/CSP ve çevrimdışı (çiftlik ağı) bağımlılığı; çiftlik panelinde internet kopması durumunda render gecikmesi.
Kanıt: app_base.html:9-11, auth_base.html:9-11.
Öneri: ortak `_head.html`/`base.html`; fontu self-host et.

### 42-9 - Marka adı "Suderra" şablonlara sabit gömülü, çevrilemez ve repo adıyla uyumsuz (info, yüksek)
Dosyalar: templates/app_base.html:9, auth_base.html:6,18, _workspace_brand.html:3, farm/water_calculator_report.html:10
Açıklama: 5 yerde ham metin; repo "tromso-mvp". Marka değişimi şablon taraması gerektirir.
Kanıt: `· Suderra</title>`, `<p class="brand">Suderra</p>`.
Öneri: tek context değişkeni/ayar (`BRAND_NAME`).

### 42-10 - monitoring/_card.html tek satırda mantık: bölüm adı eşlemesi ve iç içe if zinciri (düşük, yüksek)
Dosyalar: templates/monitoring/_card.html:23, :31
Açıklama: `view.hidden` -> "Feeding/Water/Health/Tasks" eşlemesi ve `state.basis` -> etiket eşlemesi (satır 31, `else` her şeyi "Health" yapar) şablonda. Yeni bir kaynak eklenirse `else` dalı yanlış etiket basar ("Tasks" ya da "Health" olarak). Aynı eşleme iki yerde farklı kodla (satır 23 `else`=Tasks, 31 `else`=Health).
Kanıt: `{% if view.hidden == "feeding" %}…{% else %}…section=_("Tasks")` ve `{% elif name == "water" %}…{% else %}{% trans "Health" %}`.
Öneri: görünüm modelinde `view.hidden_label` / `state.basis_labels` üret.

### 42-11 - `monitoring/_card.html` satır içi `style="{{ view.style }}"` (düşük, orta)
Dosyalar: templates/monitoring/_card.html:23, monitoring/cards/render.py:40, farm/production_units.html:112, farm/_unit_capacity.html:4
Açıklama: Stil Python'da dize olarak üretiliyor (şu an yalnızca tamsayılar, güvenli) ve CSP `style-src` kısıtlanırsa kırılır. Genişlik çubukları da satır içi style. Değerler sayısal olmaktan çıkarsa enjeksiyon yüzeyi.
Kanıt: `return f'--x:{self.x};--y:{self.y};…'`; `style="width: {{ stock.capacity|bar_width }}%"`.
Öneri: `data-x`/`data-w` + CSS/TS ya da `<progress>`; CSP kararı ile hizala (05-secrets-config bulgularıyla ilişkili).

### 42-12 - Çoğul formları: `{{ count }} due` tekil/çoğul aynı (düşük, orta)
Dosyalar: templates/reports/report_list.html:43
Açıklama: `blocktrans count … {{ count }} due{% plural %}{{ count }} due` - iki biçim aynı; Türkçe/diğer dillerde gereksiz çeviri maliyeti, anlamsız plural. Diğer yerlerde (task_list:64, inbox:27) doğru kullanılmış.
Kanıt: satır 43.
Öneri: plural'ı kaldır, düz `trans` kullan.

### 42-13 - Liste arama formu `request.GET.items` ile çok değerli parametreleri tek değere indiriyor (düşük, orta)
Dosyalar: templates/crud/list.html:15
Açıklama: Gizli input'lar `request.GET.items` (her anahtar için son değer) ile üretiliyor; çok değerli filtre (`?a=1&a=2`) aranınca kaybolur. Ayrıca `supplier_list.html:7-10` filtre formu yalnızca `q`'yu taşıyor, `unit`/başka parametreleri düşürüyor: iki form arasında filtre durumu korunması tutarsız.
Kanıt: `{% for key, value in request.GET.items %}…<input type="hidden"`; supplier_list.html: `{% if query %}<input type="hidden" name="q"…`.
Öneri: görünümde `hidden_params` listesi (urlencode/lists) üret; filtre formlarında ortak include.

### 42-14 - Şablonlarda DB'ye gidebilen ilişki erişimleri prefetch'e bağımlı (düşük, orta)
Dosyalar: templates/farm/treatment_list.html:83, farm/health_event_list.html:54, tasks/task_list.html:88, core/user_list.html:23, knowledge/document_list.html:44
Açıklama: `.units.all`, `.assignees.all`, `.groups.all`, `.species.all` listelerde kullanılıyor; şablon tarafında prefetch yapıldığını gösteren bir ipucu/test yok. Denetlenen görünümlerin hepsinde prefetch var (farm/health/views.py:110, tasks/resources.py:214, core/resources.py:49, knowledge/resources/document.py:43) ama `farm/_unit_drawer.html:159` `operation.acknowledgements.all` ve `farm/feeding_protocol_form.html:19` için doğrulanmadı.
Kanıt: ilgili grep; `_unit_drawer.html:159`.
Öneri: `assertNumQueries` testleri; bağımlılığı şablon başlık yorumuna yaz.

### 42-15 - Şablonlar için otomatik denetim yalnızca "çok satırlı {# #}" kuralı (düşük, yüksek)
Dosyalar: core/tests_templates.py:1-24
Açıklama: Şablon kuralı testi tek: çok satırlı yorum. csrf eksikliği, `|safe`, `target=_blank` rel, ham (çevrilmemiş) metin, kırık `{% url %}`/`include` yolu ve eksik ikon (`icons/<name>.svg` dinamik include; `entry.icon`, `empty_icon`) için statik denetim yok. (Betikle şu an csrf eksiği ve eksik sabit ikon bulunmadı.)
Kanıt: dosya içeriği; `icons/_icon.html:1` `{% include "icons/"|add:name|add:".svg" %}` - prod'da eksik dosya sessiz boş SVG.
Öneri: tüm şablonları derleyen + csrf/`|safe` allowlist testi ekle.

### 42-16 - Başlık hiyerarşisi: sayfa `<h1>` sonrası doğrudan `<h3>` ve modalda `h2` + `h3` (info, yüksek)
Dosyalar: templates/crud/form.html:28,50, crud/_row_list.html:7, app_base.html:~82 (h1), modal_base.html:7 (h2)
Açıklama: Form sekme panelleri `h3 panel-title` kullanıyor; sayfa modunda h1 -> h3 seviye atlıyor. Liste boş durumu `h2`. Ekran okuyucu gezinmesi için tutarsız.
Kanıt: ilgili satırlar.
Öneri: `h2` yap ya da bölüm başlıklarını CSS sınıfıyla ayır.

### 42-17 - `crud/confirm_delete.html` döngü değişkeni `group` sayfa bağlamındaki `group` ile çakışıyor (düşük, orta)
Dosyalar: templates/crud/confirm_delete.html:5,22-45; crud/list.html:8, form.html:8
Açıklama: Aynı şablonda eyebrow `{{ group }}` (menü grubu), `plan.*_groups` döngüsü `group` adını yeniden kullanıyor. Döngü dışında etkisiz, ama content bloğuna eklenecek ek bir `{{ group }}` yanlış değer verir; adlandırma bağlam değişkenini gölgeliyor.
Kanıt: `{% for group in plan.deleted_groups %}` ve `{% block eyebrow %}{{ group }} · {{ title }}`.
Öneri: döngü değişkenini `bucket` yap.

### 42-18 - Silme onayı iki kopya metin: yumuşak silme metni "admin'den geri alınabilir" iddiası şablonda sabit (düşük, orta)
Dosyalar: templates/crud/confirm_delete.html:48-51
Açıklama: `plan` varsa metin "restored from the admin" der; `plan` yoksa "removes it permanently". Hangi modelin hangisi olduğunu görünüm belirliyor, ama geri alma yolu (admin) UI'da vaat ediliyor: admin'de ilgili model kayıtlı değilse metin yanlış olur.
Kanıt: satırlar 48, 50.
Öneri: metni `plan.can_restore` veya görünümden gelen bayrakla koşullandır; admin kaydını test et (10-data-write ile ilişkili).

### 42-19 - `_field.html` dinamik etiket adı ve yardım/hata kimlikleri (düşük, orta)
Dosyalar: templates/registration/_field.html:3-4, 20-21
Açıklama: `<{{ tag }}>` dinamik eleman adı (div/fieldset); fieldset için `<legend>` var ama `aria-describedby` yardım kimliğine (`{{ field.auto_id }}_helptext`) bağlanması widget'ın `aria-describedby`'ine bağlı; use_fieldset alanlarında yardım/hata `legend` ile ilişkilendirilmiyor. `{{ field.errors }}` kimliksiz.
Kanıt: satır 20-21.
Öneri: hata listesine `id="{{ field.auto_id }}_error"` ve widget attrs'a describedby ekle.

### 42-20 - Standalone rapor sayfası temel şablon dışı: `<html>` öncesi `{% comment %}` ve eksik `nav-boot` (info, orta)
Dosyalar: templates/farm/water_calculator_report.html:1-6, 69
Açıklama: `<!doctype html>` doğru yerde ama kalıtım yok; `components.js` elle ekleniyor, `shell.js`/`poll.js` yok (bilinçli olabilir). Kopya head için bkz. 42-8.
Kanıt: dosya başı.
Öneri: `report_base.html` oluştur.
