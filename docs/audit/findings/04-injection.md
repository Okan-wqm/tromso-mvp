# 04 - Injection denetimi

## Özet
SQL, komut, yol, SSRF, deserialization ve CSV enjeksiyonu yüzeyleri genel olarak sağlam: ham SQL yalnızca parametreli (`%s`) kullanılıyor, tsquery operandları kaçışlanıyor, dosya adları sunucuda üretiliyor, kullanıcı girdisiyle `subprocess`/`eval`/`pickle`/giden HTTP yok. Doğrulanan asıl sorun: `help_text` içine kullanıcı verisi (yer/sistem adı) kaçışsız eklenip `registration/_field.html` içinde `|safe` ile basılıyor (depolanmış HTML/şablon-bağlamı enjeksiyonu). Diğer bulgular düşük/info.

## İncelenen alanlar
`.raw/.extra/cursor.execute/RawSQL` (inventory/services.py, knowledge/search.py, core/codes.py, core/database.py), `filter(**...)`/`order_by` dinamik anahtarlar (tasks/resources.py, core/dbgrid.py, monitoring/resources.py), CSV dışa aktarma (core/dbgrid.py, core/dbview.py, reports/exports.py), PDF yükleme/sunma (knowledge/models/document.py, knowledge/views.py, knowledge/extraction.py), `mark_safe`/`|safe`/`format_html`, `render_to_string` + JSON önizleme (monitoring/views.py), `next` yönlendirmeleri (hr, inventory), Content-Disposition başlıkları, `subprocess/pickle/yaml/eval` taraması, frontend `innerHTML`.

## İncelenmeyen alanlar
Şablon motoruna kullanıcı verisiyle `Template(...)`/`from_string` çağrısı bulunmadı (yalnız testlerde). pypdf/bağımlılık sürüm zafiyetleri (requirements) incelenmedi; dinamik test/exploit denenmedi; `farm/` ve `hr/` alt modüllerinin tamamı satır satır okunmadı, grep tabanlı tarama yapıldı.

## Bulgular

### 04-1 | orta | güven: yüksek - `help_text`'e kaçışsız kullanıcı verisi + `|safe` (depolanmış HTML enjeksiyonu)
Dosyalar: templates/registration/_field.html:20, tasks/forms.py:80, farm/forms/equipment.py:114
Açıklama: `_field.html` her alanın `help_text`'ini `|safe` ile basar (hem crud/form.html:33 hem task_action.html:16 üzerinden). Su kalite formu bunu bilerek `format_html_join` ile kaçışlıyor, ama iki yerde `gettext(...) % {...}` ile düz string oluşturuluyor ve yer/sistem adı (kullanıcı tarafından girilen `name`) kaçışsız gömülüyor. Silinmiş bir yerin/sistemin adı `<img onerror=...>` içerirse, görevi/ekipmanı düzenleyen başka kullanıcının tarayıcısında çalışır.
Kanıt: tasks/forms.py:80-81 `gettext('Its place, %(place)s, is deleted: choose another.') % {'place': places.label(chosen)}`; farm/forms/equipment.py:114-116 `', '.join(dropped)` (`str(link.system)`) `help_text`'e; _field.html:20 `{{ field.help_text|safe }}`.
Öneri: `format_html(...)` kullanın ya da `_field.html`'den `|safe`'i kaldırın (SafeString zaten korunur) ve water.py'deki kaçışlama sözleşmesini tek yerde toplayın.

### 04-2 | düşük | güven: yüksek - CSV formül koruması yalnız Char/Text alanlarda ve sınırlı önek listesiyle
Dosyalar: core/dbgrid.py:32,38,268-272, reports/exports.py:196
Açıklama: `FORMULA_STARTS = ('=','+','-','@','\t','\r')`; `\n` ve baştaki boşluk+`=` gibi biçimler kapsanmıyor. `export_text` yalnızca `CharField/TextField` için koruma uyguluyor; JSON/dizi/seçim/FK etiketi gibi metin üreten başka sütun türleri korumasız (JSON `[`/`{`/`"` ile başladığından bugün zararsız). reports/exports.py yalnızca `str` değerleri koruyor; sayı olarak gelen ama aslında metin olan değerler atlanır.
Kanıt: dbgrid.py:268-272 `if isinstance(column.field, (models.CharField, models.TextField)): return formula_safe(text)`.
Öneri: Tüm metin çıktısına uygula (tür yerine çıktı string'ine göre), önek listesine `\n` ekle; sayıları ayrı biçimle yaz.

### 04-3 | düşük | güven: yüksek - Önizleme (`preview`) JSON'u şablona veri olarak gider, kısıtlı ama doğrulama validate.validate'e bağlı
Dosyalar: monitoring/views.py:186-211
Açıklama: `json.loads(request.body)` 64 KB sınırıyla alınıyor, `validate.validate` hata verirse çizim yapılmıyor; `render_to_string` ile standart şablon (otomatik kaçışlı) kullanılıyor, şablon kaynağı kullanıcıdan gelmiyor. Güvenlik tamamen `validate`/`render` modüllerindeki kaçışlamaya dayanıyor (bu denetimde `monitoring/cards/*` derinlemesine incelenmedi).
Kanıt: views.py:190 `asked = json.loads(request.body)`; :211 `render_to_string('monitoring/_card.html', ...)`.
Öneri: Kart şablonunda `|safe` yokluğunu test ile sabitleyin.
(güven: orta bakımından kapsam sınırlı)

### 04-4 | düşük | güven: yüksek - PDF doğrulaması yalnız ilk 1 KB içinde `%PDF-` alt dizesine bakıyor
Dosyalar: knowledge/models/document.py:58-72, knowledge/views.py:36-39
Açıklama: `b'%PDF-' in head` imzanın dosya başında olmasını şart koşmuyor; polyglot (ör. HTML+PDF) dosya kabul edilir. Yanıt `content_type='application/pdf'` ile geldiği ve Django `nosniff` varsayılanı açık olduğu için bugün kullanılabilir bir saldırı yok, fakat savunma derinliği zayıf. Ayrıca `Content-Disposition` dosya adını kullanıcıdan alıyor (`file_name`); `FileResponse` bunu güvenli kodluyor.
Kanıt: document.py:71 `if b'%PDF-' not in head`.
Öneri: `head.startswith(b'%PDF-')` (en fazla birkaç baytlık BOM/boşluk toleransı) kullanın.

### 04-5 | düşük | güven: orta - PDF ayrıştırma (pypdf) güvenilmeyen girdiyi yüklemede eşzamanlı işliyor
Dosyalar: knowledge/extraction.py:1-60, knowledge/models/document.py:224
Açıklama: Hatalar `FAILED`'e çevriliyor (iyi), ancak çok sayfalı/sıkıştırma bombası PDF için sayfa sayısı/bellek/süre sınırı bulunmadı; yalnız dosya boyutu (`KNOWLEDGE_MAX_FILE_BYTES`) sınırlı. Bir enjeksiyon değil, ayrıştırıcı kötüye kullanımı (DoS).
Kanıt: extraction.py `read_pdf` içinde sayfa/zaman sınırı yok.
Öneri: Sayfa sayısı ve çıkarılan metin boyutu üst sınırı; ayrı işçi/zaman aşımı.

### 04-6 | info | güven: yüksek - Ham SQL kullanımları parametreli ve sabit
Dosyalar: inventory/services.py:75-76, knowledge/search.py:109-114, core/codes.py:12-13, core/database.py:127-132
Açıklama: Tüm `cursor.execute` çağrıları sabit SQL + `%s` parametresi kullanıyor; `lexeme()` tsquery operandını tırnaklayıp `\` ve `'` kaçışlıyor. `.raw/.extra/RawSQL` yok. Tablo adları (`core/database.py`) model kayıt defterinden geliyor, istekten değil.
Kanıt: search.py:21-23 `quoted = "'" + text.replace('\\', '\\\\').replace("'", "''") + "'"`.
Öneri: Yok; bu kalıbı koruyun, `lexeme` için tsquery metakarakter testleri bulunsun.

### 04-7 | info | güven: yüksek - Dinamik `filter(**{...})`/`order_by` anahtarları beyaz listeden geliyor
Dosyalar: tasks/resources.py:111,122,128, core/dbgrid.py:137-168
Açıklama: `filter(**{key: ...})` anahtarları sabit (`priority`,`category`,`due_date__gte/lte`, `places.field_of`), değerler `Priority.values`/`Category.values` ile doğrulanıyor; dbgrid'de `sort`/`f_<ad>` yalnızca `by_name` sütun sözlüğünde varsa kullanılıyor. ORM alan adı enjeksiyonu (ör. `filter(**request.GET)`) bulunmadı.
Kanıt: dbgrid.py:138 `sort = self.by_name.get(params.get('sort'))`.
Öneri: Yok.

### 04-8 | info | güven: yüksek - Yol geçişi ve SSRF yüzeyi yok
Dosyalar: knowledge/models/document.py:53-55, knowledge/views.py:30-39, config/settings.py:177-180
Açıklama: Depolama adı `uuid4().hex + '.pdf'` ile sunucuda üretiliyor, yüklenen ad yalnız `file_name` (basename) olarak saklanıyor; indirme `document.file.name` (DB'den) ile yapılıyor, istekten yol alınmıyor. `requests/urllib/httpx` ile giden istek kodu yok; `url`/`doi` alanları yalnızca bağlantı olarak saklanıp çıktılanıyor (`URLValidator(schemes=['http','https'])`).
Kanıt: document.py:55 `return f'knowledge/documents/{uuid.uuid4().hex}.pdf'`.
Öneri: Yok.

### 04-9 | info | güven: yüksek - Komut/deserialization yüzeyi test dışında yok
Dosyalar: core/tests_settings.py:13, core/test_catalogs.py:236-243
Açıklama: `subprocess` yalnızca testlerde ve sabit argümanlarla; `pickle/yaml.load/eval/exec/os.system` üretim kodunda yok. `json.loads` tek istek-gövdesi kullanımı monitoring/views.py:190 (boyut sınırlı).
Kanıt: grep sonucu; üretim kodunda eşleşme yok.
Öneri: Yok.

### 04-10 | düşük | güven: orta - `Content-Disposition` dosya adı biçimlendirmesi tutarsız
Dosyalar: core/dbview.py:63, reports/views.py:220
Açıklama: reports `content_disposition_header` (güvenli) kullanırken core/dbview.py elle `f'attachment; filename="{table.name}.csv"'` kuruyor. `table.name` model kaydından geldiği için bugün güvenli; ama tutarsız ve gelecekte kullanıcı kontrollü ada geçerse başlık enjeksiyonuna açık.
Kanıt: dbview.py:63.
Öneri: Her yerde `django.utils.http.content_disposition_header` kullanın.

### 04-11 | düşük | güven: yüksek - `url_has_allowed_host_and_scheme` kullanımı tutarsız (yalnız `startswith('/')` kontrollü olanlar var)
Dosyalar: hr/views.py:35-41, inventory/views.py:58-62
Açıklama: Açık yönlendirme koruması her ikisinde var, fakat inventory ek `startswith('/')` ile, hr `require_https` ile farklı uyguluyor; paylaşılan tek yardımcı yok (03-xss raporundaki öneriyle aynı). `//evil.com` yolu inventory'de `startswith('/')`'i geçer ama `url_has_allowed_host_and_scheme` tarafından reddedilir (doğru).
Kanıt: inventory/views.py:60.
Öneri: Tek `safe_next` yardımcısı.

### 04-12 | info | güven: yüksek - Şablon enjeksiyonu yok; `autoescape off` yalnız düz metin e-postada
Dosyalar: templates/registration/password_reset_email.html:1, core/templatetags/assets.py:41, knowledge/citation.py:111-115
Açıklama: Kullanıcı verisiyle `Template()/from_string` yok. `autoescape off` düz metin e-postada (HTML değil) kullanılıyor, uygun. `citation.reference` ve `highlight` `escape` ile `mark_safe` ediyor (doğru). Importmap `json.dumps` `</script>` kaçışı yok (03-3'te kayıtlı; girdi geliştirici kontrolünde).
Kanıt: citation.py:113-115.
Öneri: Yok.
