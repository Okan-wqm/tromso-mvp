# MASTER-FINDINGS: tekilleştirilmiş denetim bulguları

Kaynak: 50 uzman bulgu dosyası (`findings/*.md`, 831 kayıt) + 50 çapraz görüş dosyası (`crosstalk/*.md`, 126 yeni kayıt). Aynı kök nedeni anlatan kayıtlar birleştirilmiştir (62 küme); toplam **838 tekil kayıt** (826 bulgu, 10 olumlu doğrulama, 2 meta not).

Okuma kılavuzu:

- **Önem**: doğrulama sonuçları uygulanmış nihai önemdir; uzmanların özgün önemi "özgün" alanında verilir. İki doğrulayıcı farklı önem verdiyse yüksek olan alınmıştır, ikisi de belirtilir.
- **Güven**: uzmanın verdiği güven; çapraz görüş kaynaklı yeni bulgularda güven belirtilmemiştir (kayıtta "belirtilmedi").
- **Doğrulama**: `doğrulandı` / `çürütüldü/şüpheli` / `doğrulanmadı` (24 kayıt dışında hiçbir bulgu ikinci kez doğrulanmamıştır).
- **Kaynaklar**: uzman bulgu kimlikleri (`NN-M`) ve çapraz görüş kimlikleri (`NN-XM`; bu etiketler çalıştırma sırasında atanmıştır, `crosstalk/NN-*.md` dosyalarındaki yerel numaralarla birebir örtüşmeyebilir).
- Dosya:satır kanıtları uzmanların raporlarından aynen alınmıştır; bu konsolidasyon adımında kod yeniden okunmamıştır, yalnızca verilen doğrulama sonuçları uygulanmıştır.
- Başlıkları ASCII yazılmış kayıtlar (ör. 35-*, 36-*) kaynak dosyadaki biçimiyle bırakılmıştır.

## İçindekiler

- Yüksek: 0 bulgu
- Orta: 244 bulgu
- Düşük: 421 bulgu
- Bilgi: 161 bulgu
- Olumlu doğrulamalar ve meta notlar (kusur değil)

## Yüksek önem (0)

Doğrulama sonrası bu düzeyde bulgu kalmamıştır. Uzmanların "yüksek" işaretlediği 20 kayıtın tamamı iki bağımsız doğrulayıcıdan geçmiş ve en fazla Orta'ya indirilmiştir; çapraz görüşte yüksek işaretlenen 08-X1 de Orta'ya düşmüştür.

## Orta önem (244)

### F-001 SECRET_KEY ve DEBUG güvensiz varsayılanları (fail-open)

Önem: **Orta** | özgün: Yüksek/Orta/Düşük/Bilgi | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulandı

- Kaynaklar: `01-2`, `02-2`, `05-1`, `05-2`, `08-10`, `33-2`, `40-10`, `50-14`, `03-X3`, `05-X1`
- Dosyalar: config/settings.py:25,28,30
- Açıklama: `DJANGO_DEBUG` verilmezse DEBUG açık; `DJANGO_SECRET_KEY` verilmezse bilinen sabit anahtar kullanılıyor. Unutulan ortam değişkeni oturum/parola-sıfırlama token imzalarını tahmin edilebilir yapar.
- Kanıt: `os.environ.get('DJANGO_DEBUG', '1') == '1'`, `os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-development-only')`.
- Öneri: Varsayılanı kapalı yap; DEBUG kapalıyken anahtar yoksa başlangıçta hata ver.
- Birleştirilen kayıtlar:
  - `02-2` (Orta): Üretimde tehlikeli varsayılanlar: SECRET_KEY, DEBUG=1, DB parolası, oturum çerezi sertleştirmesi yok
  - `05-1` (Yüksek): SECRET_KEY sabit, bilinen varsayılana düşüyor (fail-open)
  - `05-2` (Yüksek): DEBUG varsayılanı açık (fail-open)
  - `33-2` (Orta): DEBUG varsayılanı açık (fail-open): ortam değişkeni unutulursa hata sayfaları ayrıntı sızdırır
  - `50-14` (Düşük): DEBUG varsayılanı açık; hata sayfaları ve loglama yapılandırılmamış
  - `08-10` (Düşük): `DEBUG` varsayılan açık: hata sayfaları kişisel veriyi sızdırabilir
  - `40-10` (Düşük): Varsayılan zayıf kimlik bilgileri/SECRET_KEY kodda ve compose'da
  - `05-X1` (Bilgi): Dört uzman aynı kök ayarı ayrı bulgu olarak sayıyor; seviyeler tutarsız
  - `03-X3` (Bilgi): Önem derecesi çelişkisi: aynı cookie/DEBUG/SECRET_KEY konusu 01'de high, 02'de medium
- Doğrulama `01-2`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. config/settings.py:25 SECRET_KEY ve :28 DEBUG varsayılanları kodda doğrulandı (fail-open).
- Doğrulama `05-1`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. config/settings.py:25 sabit SECRET_KEY varsayılanı; hata fırlatan başka denetim yok.
- Doğrulama `05-2`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. config/settings.py:28 DEBUG varsayılanı "1"; başka ayar dosyası/prod override yok.

### F-002 GET isteklerinde materialise_due yazması

Önem: **Orta** | özgün: Orta/Düşük/Bilgi | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `16-10`, `34-4`, `50-4`, `09-X2`, `10-X2`, `11-X4`, `33-X3`, `35-X2`, `37-X3`
- Dosyalar: tasks/resources.py:92, tasks/resources.py:226, tasks/views.py:142, tasks/services.py:257-262
- Açıklama: Görev listesi, seri listesi ve üretim özeti her okumada seri başına transaction açıp `select_for_update` ile kilitler ve görev satırları ekler. Çoklu worker/eşzamanlı kullanıcıda her sayfa yüklemesi seri satırlarında bloklanır. Bir serideki hata (örn. kısıt ihlali, bozuk veri) `materialise_due` içinde yakalanmadığından tüm görev sayfalarını ve üretim özetini (tasks/views.py:142) düşürür; seri başına `try/except` yok.
- Kanıt: `return [task for series in behind for task in materialise(series)]` hata izolasyonsuz. Cron komutu `generate_tasks` var (tasks/management/commands/generate_tasks.py) ama tetikleyen zamanlayıcı repoda tanımlı değil.
- Öneri: Üretimi zamanlanmış işe taşıyın ya da GET'te en azından `skip_locked` + seri başına hata izolasyonu kullanın.
- Birleştirilen kayıtlar:
  - `16-10` (Düşük): `tasks.materialise_due` okuma isteklerinde çalışıyor ve seri başına hata izolasyonu yok
  - `50-4` (Orta): GET isteklerinde yazma: tasks.materialise_due sayfa okumalarına bağlı
  - `09-X2` (Orta): GET ile yazma sınıfı: materialise_due, mark_read ve materialise 'system' audit satırları okuma izniyle tetiklenir
  - `10-X2` (Düşük): GET yazmalarının üç ayrı örneği (okundu işaretçisi, materialise, audit 'system') ortak politikaya bağlı değil
  - `11-X4` (Bilgi): Aynı 'GET yazar' sınıfı: materialise_due, okundu işaretçisi ve system log tek ortak ilkeyle ele alınmalı
  - `33-X3` (Orta): GET liste görünümlerinde yazma yolu (materialise_due) hata izolasyonsuz; okuma hataya karşı kırılgan
  - `35-X2` (Orta): GET'te materialise_due + tum okuma yollarinda clocks() hesabi: salt-okunur istek yazma maliyeti tasiyor
  - `37-X3` (Düşük): Zamanlayıcı yokken GET tabanlı görev üretimi tek tetikleyici

### F-003 restore() kilitsiz/sürümsüz/kısmi

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `11-7`, `34-3`, `50-6`, `10-X1`, `11-X2`, `16-X1`, `33-X2`, `50-X2`
- Dosyalar: core/softdelete.py, core/admin.py
- Açıklama: (a) `restore` yalnızca kaydın kendisini geri getirir; silmeyle birlikte silinen CASCADE çocukları ve SET_NULL ile koparılan bağlar geri gelmez (belgelenmiş ama kurtarma yolu manuel). (b) `restore` satırı kilitlemez ve `version` kontrolü yapmaz; eşzamanlı bir düzenleme/silmeyle yarışabilir. (c) Geri yükleme yalnız Django admin eylemi; uygulama arayüzünde yok. Sonuç: yanlışlıkla silinen ağaç (ör. saha) geri alınırken çocuklar tek tek elle geri getirilmeli.
- Kanıt: core/softdelete.py:189-203 (docstring: "Only the record itself returns"; `select_for_update` yok); core/softdelete.py:171-186 (detach/cascade kaydı log'a yazılır ama geri alınmaz); core/admin.py:36-50.
- Öneri: Silme planını (audit kaydı) kullanan "plan ile geri al", restore'da `select_for_update` ve version kontrolü.
- Birleştirilen kayıtlar:
  - `11-7` (Düşük): `restore` kilitsiz, sürümsüz ve yalnızca `ValidationError` yakalar; eşzamanlı restore/çakışmada `IntegrityError` 500'e düşer
  - `34-3` (Düşük): `softdelete.restore` kilitsiz ve yalnızca `ValidationError` yakalanıyor
  - `10-X1` (Düşük): restore() yalnızca kendi kaydında version artırıyor ama kilitsiz; eşzamanlı düzenleme sessizce ezilir
  - `11-X2` (Düşük): restore() sonucu hata türü ve eşzamanlı restore/edit çakışması: version artırımı kilitsiz yapılıyor
  - `16-X1` (Düşük): restore() kilitsiz ve atomik değil: full_clean ile save arasında yarış, audit ayrı yazılıyor
  - `50-X2` (Orta): restore() ve soft delete zinciri kilitsiz; yarışta sürüm çakışması ile sessiz geri yazma
  - `33-X2` (Düşük): core/admin.py restore eylemi ValidationError'ı mesajlıyor, IntegrityError'ı hiç ele almıyor

### F-004 Cookie/HTTPS/HSTS sertleştirme ayarları yok

Önem: **Orta** | özgün: Orta/Bilgi | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-3`, `03-2`, `05-4`, `03-X1`, `37-X1`
- Dosyalar: config/settings.py
- Açıklama: `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_SECURE`, `LANGUAGE_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS` tanımlı değil. TLS arkasında bir proxy ile yayınlanırsa Django `request.is_secure()` false görür; HTTPS'te Origin/Referer kontrolü (CSRF) proxy'de reddedilebilir ve cookie'ler HTTP üzerinden de gidebilir. Yalnızca `LANGUAGE_COOKIE_SAMESITE='Lax'` (satır ~151) tanımlı. Konu 01-3 ile örtüşür; burada CSRF yönüyle kaydedildi.
- Kanıt: settings.py'de `grep -n "SECURE_\|CSRF_\|SESSION_COOKIE"` yalnızca LANGUAGE_COOKIE_* satırlarını bulur. README'de dağıtım/HTTPS bölümü yok (yalnızca runserver anlatımı).
- Öneri: Ortam bayrağına bağlı üretim profili ekle (Secure cookie'ler, HSTS, proxy header, trusted origins) ve CI'da `check --deploy`.
- Birleştirilen kayıtlar:
  - `01-3` (Orta): Oturum/cookie ve taşıma sertleştirmesi yok
  - `05-4` (Orta): Cookie/HTTPS sertleştirme ayarları hiç yok
  - `37-X1` (Orta): Güvenli-çerez/HSTS/SSL yönlendirme ayarları hiç tanımlı değil
  - `03-X1` (Bilgi): Cookie/CSP/XSS savunma eksikleri 5 uzmanda ayrı ayrı kayıtlı; tek kök neden

### F-005 help_text |safe ile kaçışsız basılıyor

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-4`, `04-1`, `42-1`, `02-X3`, `08-X2`
- Dosyalar: templates/registration/_field.html:20, tasks/forms.py:80, farm/forms/equipment.py:114
- Açıklama: `_field.html` her alanın `help_text`'ini `|safe` ile basar (hem crud/form.html:33 hem task_action.html:16 üzerinden). Su kalite formu bunu bilerek `format_html_join` ile kaçışlıyor, ama iki yerde `gettext(...) % {...}` ile düz string oluşturuluyor ve yer/sistem adı (kullanıcı tarafından girilen `name`) kaçışsız gömülüyor. Silinmiş bir yerin/sistemin adı `<img onerror=...>` içerirse, görevi/ekipmanı düzenleyen başka kullanıcının tarayıcısında çalışır.
- Kanıt: tasks/forms.py:80-81 `gettext('Its place, %(place)s, is deleted: choose another.') % {'place': places.label(chosen)}`; farm/forms/equipment.py:114-116 `', '.join(dropped)` (`str(link.system)`) `help_text`'e; _field.html:20 `{{ field.help_text|safe }}`.
- Öneri: `format_html(...)` kullanın ya da `_field.html`'den `|safe`'i kaldırın (SafeString zaten korunur) ve water.py'deki kaçışlama sözleşmesini tek yerde toplayın.
- Birleştirilen kayıtlar:
  - `03-4` (Düşük): `registration/_field.html` form `help_text`'ini `|safe` ile basıyor (örtük güven sözleşmesi)
  - `42-1` (Orta): `registration/_field.html` help_text'i `|safe` ile basıyor
  - `02-X3` (Orta): Depolanmış HTML enjeksiyonu yetki sınırını aşma aracı olarak değerlendirilmeli
  - `08-X2` (Düşük): Kullanıcı girdisi içeren help_text |safe ile basılıyor; yer etiketi kişisel veri içeren serbest metin olabilir

### F-006 isdigit() Unicode rakamda 500

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `09-16`, `29-5`, `38-4`, `09-X1`, `50-X1`
- Dosyalar: messaging/views.py:72, 74, 113
- Açıklama: `str.isdigit()` '²' için True, `int('²')` ValueError (Python'da doğrulandı). Yetkili bir kullanıcı `/messages/<id>/?before=²` veya `/new/?after=²` ile 500 üretir. Testlerde kötü parametre denemesi yok.
- Kanıt: `int(before) if before.isdigit() else None`; `int(after) if after.isdigit() else 0`.
- Öneri: `isdecimal()`+`isascii()` ya da try/except ile ayrıştırın; üst sınır koyun.
- Birleştirilen kayıtlar:
  - `09-16` (Düşük): Mesajlaşma ve raporlarda `isdigit()` ile doğrulanan değer `int()`'e verilir; "²" gibi karakterler 500 üretir
  - `38-4` (Düşük): `<int>.isdigit()` kontrolü Unicode rakamlarda 500 üretir
  - `09-X1` (Düşük): Sorgu parametresi ayrıştırma tutarsız: isdigit/isdecimal+int ve parse_date ValueError'ları ortak yardımcı olmadan dağınık
  - `50-X1` (Düşük): Girdi ayrıştırma hataları için ortak koruma yok: parse_date, isdigit+int, isdecimal+int ayrı ayrı 500 üretiyor

### F-007 MEDIA_ROOT/yüklenen dosyalar için kalıcılık ve yedek yok

Önem: **Orta** | özgün: Yüksek/Orta/Düşük | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulandı

- Kaynaklar: `05-10`, `06-5`, `12-3`
- Dosyalar: config/settings.py:180, knowledge/models/document.py:52-55,115-118, README.md:2992-2993, .gitignore
- Açıklama: Belge dosyaları yerel dosya sistemindeki `MEDIA_ROOT`'ta (varsayılan checkout içinde `media/`), kayıtlar ise veritabanında. docker-compose'da medya için volume yok. README yalnızca "back it up with the database" der; nasıl, hangi sırayla, tutarlı anlık görüntü nasıl alınır anlatılmaz. DB geri yüklenip medya eski/eksik olursa `Document.file` kayıtları yok dosyaya işaret eder; tersi durumda artık dosyalar kalır.
- Kanıt: `MEDIA_ROOT = Path(os.environ.get('DJANGO_MEDIA_ROOT', BASE_DIR / 'media'))`; dosya adı `knowledge/documents/{uuid}.pdf`.
- Öneri: Medyayı kalıcı volume/obje depolamaya taşıyın (sürümlemeli), DB yedeğiyle birlikte aynı zaman noktasında alın, bir bütünlük kontrol komutu (kayıt <-> dosya) ekleyin.
- Birleştirilen kayıtlar:
  - `05-10` (Düşük): MEDIA_ROOT varsayılanı checkout içinde
  - `06-5` (Orta): Medya dosyaları için kalıcılık/yedek yok: compose'ta medya hacmi yok, varsayılan MEDIA_ROOT checkout içinde
- Doğrulama `12-3`: doğrulandı; doğrulayıcı önemleri Orta/Düşük -> nihai Orta. config/settings.py:180 MEDIA_ROOT, knowledge/models/document.py:52-55 dosya adı doğrulandı; yedek kapsamı yalnız veritabanı. Şiddet abartılı bulundu.

### F-008 PDF yükleme rollback sonrası yetim dosya

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-1`, `16-2`, `50-9`, `34-X1`
- Dosyalar: knowledge/models/document.py:217-242, core/crud.py:672-686, core/crud.py:728-737, knowledge/tests/test_documents.py:157-162
- Açıklama: `Document.save` içinde `super().save()` FileField'ın pre_save'iyle yeni dosyayı hemen depoya yazar; yalnızca ESKİ dosya için `transaction.on_commit` silmesi kayıtlı. Yeni dosya için "işlem geri alınırsa sil" mantığı yok. CreateView'de `audit.record_create`/`after_save`/IntegrityError (aynı anda DOI çakışması, `constraint_error`), UpdateView'de `audit.record_update` hatası veya sonraki bir istisna işlemi geri alır; satır yoktur ama `MEDIA_ROOT/knowledge/documents/<uuid>.pdf` kalır. Mevcut test yalnızca eski dosyanın korunmasını doğruluyor.
- Kanıt: `transaction.on_commit(partial(self.file.storage.delete, stored))` (yalnızca `stored`); yeni dosya adı için benzer bir on_rollback/temizlik yok. test_a_file_that_is_not_a_pdf_is_refused yalnızca form doğrulama aşamasında `media_files() == []` kontrol ediyor.
- Öneri: Yeni dosya yazıldıktan sonra rollback'te silen bir mekanizma (örn. try/except ile atomic dışında silme veya yetim dosya süpürme komutu); yetim tarayan bir management command ve test.
- Birleştirilen kayıtlar:
  - `16-2` (Orta): Yüklenen dosya DB işlemi içinde depolamaya yazılıyor; rollback'te yetim dosya kalıyor
  - `50-9` (Orta): PDF yükleme: rollback'te yetim dosya, istek içinde senkron ayrıştırma
  - `34-X1` (Düşük): PDF yükleme save() içinde yarım kalırsa depolamada yetim dosya ve açık işlemde ağır iş

### F-009 UpdateView/RowListView kilit altında kayıt bulunamama (500)

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-1`, `11-6`, `38-7`, `16-X2`
- Dosyalar: `core/crud.py:724`, `core/crud.py:815`
- Açıklama: `UpdateView.post` ve `RowListView.post`, kaydı önce `get_object` (404 üretir) ile okur, sonra kilit için `r.visible(request).select_for_update(of=('self',)).get(pk=pk)` çağırır. Bu iki okuma arasında kayıt başka biri tarafından silinirse (soft delete) ikinci sorgu `DoesNotExist` fırlatır ve yakalanmaz. `DeleteView` aynı yerde `get_object_or_404` kullanıyor, yani üç view tutarsız.
- Kanıt: `current = r.visible(request).select_for_update(of=('self',)).get(pk=pk) # not the joined rows` (satır 724) ve satır 815; ikisinde de `try/except ObjectDoesNotExist` ya da `get_object_or_404` yok.
- Öneri: İki yerde de `get_object_or_404(r.visible(request).select_for_update(of=('self',)), pk=pk)` kullanın veya kayıt silinmişse "başkası sildi" mesajı gösterin.
- Birleştirilen kayıtlar:
  - `38-7` (Düşük): `UpdateView`/`RowListView` kilit altında `.get(pk=pk)` DoesNotExist'ı yakalamaz
  - `11-6` (Düşük): `UpdateView` kilit altındaki `.get(pk=pk)` kayıt bu arada silinmişse 500 üretir
  - `16-X2` (Düşük): UpdateView/RowList: doğrulama kilit dışında, IntegrityError yakalanmadığı için 10-1 ve 10-2 tek kök neden

### F-010 Modal istemcisi ağ/HTTP hataları ele alınmıyor

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-5`, `50-12`, `41-X1`, `43-X1`
- Dosyalar: frontend/components.ts:334-359
- Açıklama: `fetch` try/catch'siz; çevrimdışı/zaman aşımında hiçbir şey olmaz (form gönderildi mi bilinmez, düğme tekrar basılır). 403 dışındaki hata durumları (404, 500, CSRF 403 dışı) `response.text()` olarak `innerHTML`'e basılıyor; tam hata sayfası diyalog içinde görünür. Çiftlik ağında kesinti beklenen bir durum.
- Kanıt: `this.content.innerHTML = await response.text();` yalnız `status === 403` ayrımı var; `response.ok` kontrolü yok.
- Öneri: try/catch + `response.ok` kontrolü; "Bağlantı yok / Bir şey ters gitti, tekrar dene" iletisi göster, form girdisini koru.
- Birleştirilen kayıtlar:
  - `50-12` (Düşük): Modal formda ağ hatası ele alınmıyor
  - `41-X1` (Orta): Modal hata yonetimi uc uzmanda ayri ayri raporlanmis: tek kok neden Modal.load
  - `43-X1` (Düşük): Modal sunucu hatasinda dialog icinde tam sayfa HTML; kullanici akisi bozulur

### F-011 Dockerfile/üretim imajı yok

Önem: **Orta** | özgün: Yüksek/Düşük | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulandı

- Kaynaklar: `07-10`, `37-2`
- Dosyalar: docker-compose.yml:1-20
- Açıklama: compose dosyası yalnızca "Local development database" (db servisi). Uygulama imajı, reverse proxy, migrate/collectstatic adımı, üretim topolojisi tanımsız. Dağıtım tekrarlanabilir değil.
- Kanıt: docker-compose.yml:1-2 "Local development database: PostgreSQL 17 ..."; tek servis `db`; `ls Dockerfile*` bulunamadı.
- Öneri: Çok aşamalı Dockerfile (node build -> python runtime), üretim compose/manifest ve migrate/init adımı.
- Birleştirilen kayıtlar:
  - `07-10` (Düşük): Uygulama için Dockerfile/üretim imajı yok; üretim bağımlılık yolu tanımsız
- Doğrulama `37-2`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. docker-compose.yml yalnız db servisi; Dockerfile/Procfile/CI/proxy yok.

### F-012 Statik dosya üretim hattı yok

Önem: **Orta** | özgün: Yüksek/Orta | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulandı

- Kaynaklar: `37-4`, `46-5`
- Dosyalar: config/settings.py:173-174, config/urls.py:57-75, .gitignore:6-9
- Açıklama: STATIC_ROOT tanımlı değil, `collectstatic` çalışmaz; whitenoise/CDN/nginx yapılandırması yok; urls.py'de static route yok. DEBUG=0 iken Django statik dosyaları sunmaz, tüm CSS/JS (ve import map) 404 olur. .gitignore `staticfiles/` içeriyor ama ayarda karşılığı yok. STORAGES ile hashed/manifest depolama da yok.
- Kanıt: settings.py:173-174 yalnızca STATIC_URL ve STATICFILES_DIRS; `grep -rn "STATIC_ROOT\|whitenoise\|collectstatic"` kodda eşleşme yok.
- Öneri: STATIC_ROOT + collectstatic adımı ve whitenoise veya proxy ile servis; Dockerfile'da build sırası.
- Birleştirilen kayıtlar:
  - `46-5` (Orta): Uretim icin statik dosya sunumu tanimli degil
- Doğrulama `37-4`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. config/settings.py:173-174 yalnız STATIC_URL/STATICFILES_DIRS; STATIC_ROOT/whitenoise yok.

### F-013 Çalışan deney kapatılamıyor (running->closed)

Önem: **Orta** | özgün: Yüksek/Düşük | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulandı

- Kaynaklar: `47-6`, `48-1`
- Dosyalar: experiments/models.py:50-54, experiments/services.py:653-669, experiments/migrations/0002_design_frozen.py:56, docs/experiments.md:51
- Açıklama: `TRANSITIONS` ve DB tetikleyicisi `running -> closed` geçişine izin veriyor, ancak `experiments/services.py` içinde yalnızca `start` (draft->running) var; `Status.CLOSED` atayan hiçbir servis, form veya view yok. Dokümantasyon "closing is not built" diyor. Başlayan her deney sonsuza kadar `running` kalır; silinemez (`delete_blockers`), tasarımı değişemez, kapanışa bağlı okuma mantığı (`read.py` `closed`) hiç tetiklenmez.
- Kanıt: `grep Status.CLOSED experiments/*.py` yalnızca experiments/read.py:163'te okuma; experiments/models.py:147-155 "Close it instead" mesajı olmayan bir eylemi gösteriyor.
- Öneri: `close` servisi (kilit + audit + tetikleyiciye uyumlu) eklenmeli ya da silme mesajı düzeltilmeli.
- Birleştirilen kayıtlar:
  - `47-6` (Düşük): Deney yaşam döngüsü yarım: RUNNING -> CLOSED geçişi için servis/arayüz yok
- Doğrulama `48-1`: doğrulandı; doğrulayıcı önemleri Orta/Düşük -> nihai Orta. experiments/models.py:52-53 TRANSITIONS running->closed izinli, 0002_design_frozen.py:56 tetikleyici de kabul ediyor; ama kodda kapatma yolu yok. Doğrulayıcı biri bunu belgelenmiş kapsam sınırı sayıyor.

### F-014 E-posta konsol backend (davet/parola sıfırlama üretime hazır değil)

Önem: **Orta** | özgün: Orta/Düşük | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-5`, `05-6`, `08-9`, `37-16`
- Dosyalar: config/settings.py (MAILERS), README.md:3253, core/resources.py:62-69
- Açıklama: E-posta yalnızca konsola basılıyor; yeni kullanıcı daveti ve "şifremi unuttum" üretimde teslim edilmez, tokenlı bağlantılar log/terminale düşer. Ayrıca `use_https=request.is_secure()` proxy arkasında SECURE_PROXY_SSL_HEADER olmadan http bağlantı üretir (01-3 ile bağlı).
- Kanıt: `'BACKEND': 'django.core.mail.backends.console.EmailBackend'`; `invitation.save(request=request, use_https=request.is_secure())`.
- Öneri: SMTP/sağlayıcı yapılandırması, DEFAULT_FROM_EMAIL, proxy başlığı ayarı.
- Birleştirilen kayıtlar:
  - `08-9` (Düşük): E-posta tek başına console backend: davet/şifre sıfırlama bağlantıları ve e-postalar stdout'a yazılır
  - `37-16` (Orta): E-posta üretimde konsol backend'inde: şifre sıfırlama/davet postaları gönderilmez
  - `05-6` (Orta): E-posta üretim için yapılandırılmamış (konsol arka ucu), parola sıfırlama sızıntısı riski

### F-015 PDF metin çıkarımı istek içinde, sınırsız

Önem: **Orta** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-2`, `28-7`, `35-12`, `35-X1`
- Dosyalar: knowledge/extraction.py:56-75, knowledge/models/document.py:223-238, core/crud.py:721-737, README.md (Its text paragrafı)
- Açıklama: 20 MB'a kadar bir PDF, `PdfReader` ile tüm sayfalar için `extract_text()` çağrılarak istek iş parçacığında çözümlenir; sayfa sayısı, toplam metin uzunluğu, süre sınırı yok. Binlerce sayfalık/şişirilmiş akışlı PDF CPU ve bellek tüketir, ardından tüm sayfalar `bulk_create` ile tek seferde eklenir (sınırsız satır). UpdateView'de bu iş `select_for_update` satır kilidi tutulurken ve `transaction.atomic` içinde yapılır; gunicorn işçisi bloke olur. README bunu "MVP için kabul" olarak not ediyor ve pypdf'in sürümünü kasıtlı güncel tutuyor, ancak kodda koruma yok. Yalnızca `except Exception` var; takılma/uzun döngü yakalanamaz.
- Kanıt: `pages = [Page(...) for number, page in enumerate(reader.pages, 1)]` sınırsız; `DocumentPage.objects.bulk_create([...])` sınırsız; `with transaction.atomic(): current = ...select_for_update(...)` içinde `obj.save()` → `read_pdf`.
- Öneri: Maksimum sayfa sayısı ve toplam metin üst sınırı, çıkarımı arka plan işine (zaman sınırlı) taşımak veya en azından kilidi tutmadan okumak; sınır aşıldığında FAILED durumu.
- Birleştirilen kayıtlar:
  - `28-7` (Orta): PDF metin cikarma istek icinde, zaman/bellek/sayfa siniri olmadan calisir.
  - `35-12` (Orta): PDF metin cikarimi istek icinde ve model.save() icinde (acik islem sirasinda), sayfa sayisi sinirsiz
  - `35-X1` (Orta): PDF yukleme: sayfa metni tek listede bellekte, ardindan tek bulk_create; sinirsiz boyutta bellek ve DB yuku

### F-016 Append-only audit log ile silme/KVKK talebi çelişkisi

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-2`, `13-12`, `08-X3`
- Dosyalar: `core/migrations/0003_audit_log_append_only.py`, `core/audit.py:129-143`, `core/resources.py:55-61`, `docs/hr-launch-checklist.md:59`, `core/models.py` (AuditLog)
- Açıklama: Trigger platform admin dahil herkesin UPDATE/DELETE yapmasını engeller (`docs/data-map.md` bunu "by design" yazar). `user_name` (kullanıcı adı) her satıra, kullanıcı oluşturma/değiştirme snapshot'ı ise e-posta, ad, soyadı (`UserForm` alanları) düz metin yazar. Silme/itiraz (KVKK m.7, GDPR m.17) talebinde bunları kaldırmanın yolu yoktur; hesaplar zaten silinmez, yalnız pasifleştirilir. Çakışma kontrol listesinde 4.2 olarak "owner karar verir" diye açık bırakılmış.
- Kanıt: `record(...)`: `user_name=user.get_username()`; `core/resources.py:58-59`: `fields = [... UserForm.tabs ...]; audit.snapshot(user, fields, ...)` (alanlar: username, first_name, last_name, email); trigger metni.
- Öneri: Günlükte kişisel alanları sözde-isimle (user id + ayrı çözümleme tablosu) tutun ya da yasal saklama süresi bitince anonimleştirmeye izin veren denetimli bir yol tanımlayın; kararı belgeleyin.
- Birleştirilen kayıtlar:
  - `13-12` (Düşük): Kişisel verinin silinmezliği: append-only log ile KVKK/GDPR silme talebi çatışması çözülmemiş; log'da e-posta/ad kalıcı
  - `08-X3` (Orta): Silme/geri yükleme (soft delete + restore) ile veri sahibi silme talebi çelişiyor

### F-017 Silinen mesaj gövdesi DB'de duruyor

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-4`, `29-3`, `18-X2`
- Dosyalar: `messaging/services.py:268-276`, `messaging/models.py:138`, `messaging/views.py:269`
- Açıklama: `delete_message` yalnız `is_deleted/deleted_at/deleted_by` işaretler; `body` boş bırakılmaz/silinmez. Docstring "the text is never shown again" der ama metin satırda ve yedeklerde kalır; `Participant.last_read`/PROTECT ilişkileri nedeniyle satır da asla gerçek silinmez. Gövde yalnız DB görüntüleyicide maskelidir (`config/database.py`). Silme isteği fiilen silme olmaz.
- Kanıt: `message.is_deleted, message.deleted_at, message.deleted_by = True, timezone.now(), user; message.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])`.
- Öneri: Silmede `body`'yi boşaltın/yerine tombstone yazın (CHECK `message_has_text` buna göre gevşetilmeli) veya saklama süresi sonunda gövdeleri temizleyin.
- Birleştirilen kayıtlar:
  - `29-3` (Orta): Silinen mesajın metni veritabanında durur
  - `18-X2` (Düşük): message_has_text CHECK kısıtı silinmiş mesaj gövdesinin temizlenmesini engelliyor (29-3 çözümünün bağımlılığı)

### F-018 Belge dosyası değişince eski dosya geri dönülemez

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-4`, `13-16`, `12-X2`
- Dosyalar: knowledge/models/document.py:239-241 (ve 90-91)
- Açıklama: Dosya değiştirildiğinde/temizlendiğinde eski PDF commit sonrası `storage.delete` ile fiziksel olarak silinir. Belge yumuşak silinirse dosya kalır, ama düzenleme sonrası eski sürüm için geri alma yok; AuditLog yalnızca dosya adı/boyutu gibi meta verileri tutar. Yanlış dosya yüklenirse orijinal yedek yoksa kaybolur.
- Kanıt: `transaction.on_commit(partial(self.file.storage.delete, stored))`.
- Öneri: Eski dosyayı hemen silmeyin; gecikmeli temizlik (örn. 30 gün) veya depolama sürümlemesi kullanın.
- Birleştirilen kayıtlar:
  - `13-16` (Düşük): Belge dosyası değiştirilince eski dosya commit'te silinir, log yalnızca dosya adını tutar
  - `12-X2` (Orta): Belge dosyasi on_commit silme ile DB-MEDIA kirik baglanti uretir

### F-019 Su geçmişi tarih aralığı sınırsız

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `09-12`, `35-4`, `17-X2`
- Dosyalar: farm/water/views.py:218-232, farm/water/read.py:469-505, farm/water/read.py:242-262
- Açıklama: `_history` `from`/`to` sorgu parametrelerini sinirlamadan kabul ediyor (varsayilan 30 gun ama kullanici cok eski bir `from` verebilir). `read.history(list(samples))` butun ornekleri `select_related` ile cekip her biri icin `context.readings` + `judge` calistiriyor; `Paginator(rows, 50)` bundan sonra uygulaniyor. `Context` ayrica ilgili birimlerin tum stok satirlarini (`Presence.of_units`) ve tuzluluk serisini (`since - WINDOW`) yukluyor. Sayfa basina 50 satir gostermek icin tum araligin maliyeti odeniyor. Ek olarak sayfa uzerinde `services.earliest(sample.point)` nokta basina ayri cagriliyor (`setdefault` arguman olarak da degerlendirildigi icin her satirda hesaplaniyor).
- Kanıt: `rows = read.history(list(samples))` ... `page = Paginator(rows, PAGE_SIZE).get_page(...)` (farm/water/views.py:228-232); `first = earliest.setdefault(sample.point_id, services.earliest(sample.point))` (views.py:238) - `services.earliest` her satirda degerlendirilir.
- Öneri: Araligi ust sinirla (ornegin 366 gun) ve sayfalamayi `samples_of` sorgusu uzerinde yap, sadece sayfadaki ornekleri `history()`'e ver; "yalniz alarmlar" filtresi icin veritabanında durum sutunu ya da ayri hesap gerekir. `earliest` icin `if point_id not in earliest` kullan.
- Birleştirilen kayıtlar:
  - `09-12` (Orta): Su geçmişi tarih aralığını sınırsız alır: tüm örnekler belleğe çekilip bellekte yargılanır, sayfalama sonradan yapılır
  - `17-X2` (Düşük): Su gecmisi zaman araligi ust sinirsiz; hypertable'da cok chunk taranir

### F-020 Sitesiz üretim bölümü yemlemesi yem stoğuna yansımıyor

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `19-10`, `47-8`, `23-X1`
- Dosyalar: `inventory/read.py:59-65` (`_feeding`), `README.md:61,80` (site silinince departman sitesiz kalır)
- Açıklama: Depo, yemlemeyi `unit__production_department__site_id` ile siteye bağlıyor ve `site__isnull=False` filtresi koyuyor. README'ye göre bir site silinince üretim bölümleri ve birimleri sitesiz kalıyor, yemleme kayıtları ise duruyor. Bu kayıtlar ne depodan düşülüyor ne de "karşılanmamış besleme" olarak raporlanıyor; yani tüketim kaybolur ve stok fazla görünür.
- Kanıt: `FeedingRecord.objects.filter(feed_id__in=feed_ids, unit__production_department__site__isnull=False)`.
- Öneri: Sitesiz kayıtları ayrı bir "siteye bağlanmamış besleme" satırı olarak göster (veya site silmeyi, yemlemesi olan birimlerde engelle).
- Birleştirilen kayıtlar:
  - `19-10` (Düşük): Sitesiz üretim bölümündeki ünitelerin yemlemesi yem stoğu defterine hiç yansımıyor
  - `23-X1` (Düşük): Envanter besleme çekimi (site,gün) anahtarıyla sitesiz üniteleri kaçırıyor; yem raporları ile defter ayrışır

### F-021 Giriş/parola sıfırlama için brute force koruması yok

Önem: **Orta** | özgün: Yüksek | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulandı

- Kaynaklar: `01-1`
- Dosyalar: config/settings.py, config/urls.py:27-28
- Açıklama: Giriş `django.contrib.auth.urls` ile geliyor; kilitleme, gecikme, captcha veya oran sınırı yok.
- Kanıt: settings.py'de AXES/ratelimit/throttle yok, MIDDLEWARE'de ilgili öğe yok (satır 64-77); `AUTHENTICATION_BACKENDS` varsayılan.
- Öneri: django-axes benzeri kilitleme veya IP+kullanıcı bazlı oran sınırı; /admin/ giriş için de.
- Doğrulama `01-1`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. config/urls.py:31 `accounts/` altında django.contrib.auth.urls (login, password_reset); config/settings.py MIDDLEWARE (64-77) içinde kilitleme/oran sınırı yok.

### F-022 Envanter "Sayımlar" sekmesi her sayım satırı için tüm envanter defterini yeniden katlar (N+1, sayfa başına 20 tam yeniden hesap)

Önem: **Orta** | özgün: Yüksek | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulandı

- Kaynaklar: `09-11`
- Dosyalar: inventory/views.py:49,219-234; inventory/read.py:69-80, 338-350
- Açıklama: `_counts` sayfadaki her sayım için `read.count_variances(operation)` çağırır. Bu fonksiyon o konumda satırı olan tüm kalemleri çekip `folds(items)` çalıştırır; `folds` her çağrıda `_lines(items)`, `_counts()` (tüm sayımlar), `_places()` ve `_feeding(...)` okur. Sayfa başına 20 sayım = 20 kez tüm defter/sayımların yeniden yüklenmesi ve katlanması; veri büyüdükçe karesel yavaşlama. Oysa hesap tüm sayfa için tek seferde yapılabilir.
- Kanıt: `'variances': read.count_variances(operation)` (views.py:231) döngü içinde; `for fold in folds(items).values():` (read.py:343).
- Öneri: Sayfanın sayımlarını/konumlarını tek seferde katla ve sonuçları operasyon bazında dağıt; ya da varyansı sayım kaydedilirken saklı değere çevir.
- Doğrulama `09-11`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. inventory/views.py:226-231 sayfadaki her sayım için read.count_variances çağırıyor (COUNTS_PAGE=20); read.py:341-343 defteri yeniden katlıyor.

### F-023 Hiçbir yedekleme mekanizması veya geri yükleme prosedürü yok

Önem: **Orta** | özgün: Yüksek | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulandı

- Kaynaklar: `12-1`
- Dosyalar: docker-compose.yml, README.md:2975-2993, scripts/ (yalnızca mark-esm.mjs), docs/
- Açıklama: Repoda pg_dump/pg_basebackup/WAL arşivleme/pgBackRest/cron/yedek konteyneri yok; docs/ altında backup, dump, recover geçen hiçbir belge yok. Çiftlik üretim kayıtları, tıbbi ilaç bekleme süreleri ve resmi rapor verisi (filed reports) tek bir PostgreSQL örneğinde duruyor.
- Kanıt: `ls scripts` -> yalnızca `mark-esm.mjs`; `grep -iE "backup|dump|recover" docs/*.md` boş; docker-compose.yml yalnızca `db` servisi içerir.
- Öneri: Yazılı bir yedekleme politikası (RPO/RTO), otomatik mantıksal (pg_dump -Fc) ve fiziksel/WAL yedek, yedeğin tatbikatlı geri yükleme testi ve docs/ altında bir runbook ekleyin.
- Doğrulama `12-1`: doğrulandı; doğrulayıcı önemleri Düşük/Orta -> nihai Orta. scripts/ yalnız mark-esm.mjs; docker-compose.yml yalnız db + pgdata; yedek yok. Doğrulayıcılar şiddeti düşürdü (docker-compose.yml:1 "Local development database").

### F-024 Kısmen mevcut hücrelerde CLEAR toplu işlemi AttributeError ile çöker

Önem: **Orta** | özgün: Yüksek | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulandı

- Kaynaklar: `25-1`
- Dosyalar: hr/services.py:203-230, hr/services.py:222-230, core/audit.py:144-158
- Açıklama: `plan_shifts` `shift is CLEAR and not existing` ise sadece hepsi boşsa atlar (203). Bazı hücrelerde plan var, bazılarında yoksa tüm günler `_write_cell`'e gider; `row=None` ile CLEAR dalında `audit.record(user, DELETE, None, ...)` `instance.pk` okur ve `row.soft_delete` None üzerinde çağrılır.
- Kanıt: `_write_cell(user, employee, day, shift, existing.get(day), ...)` (218) mevcut olmayan gün için None verir; 228-230 `audit.record(..., row, ...)` / `row.soft_delete(user)`; audit.py:152 `str(instance.pk)`. hr/tests/test_roster.py:193 yalnızca tüm hücreler doluyken CLEAR dener.
- Öneri: Mevcut olmayan günleri `_write_cell`'de (veya döngüde) `row is None and shift is CLEAR` ise atla; kısmi seçim için test ekle.
- Doğrulama `25-1`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. hr/services.py:203 yalnız hiç satır yokken atlıyor; kısmi hücrelerde CLEAR yazma yoluna giriyor (217-218).

### F-025 monitoring.read.cards: zorunlu kaynak hatası her türlü istisnayı yutup günlüğe yazmadan Unavailable'a çevirir

Önem: **Orta** | özgün: Yüksek | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulandı

- Kaynaklar: `33-4`
- Dosyalar: monitoring/read.py, monitoring/views.py
- Açıklama: cards() içindeki geniş 'except Exception as error: raise Unavailable(str(error)) from error' (monitoring/read.py:335-336) için hiçbir logger çağrısı yok. View'lar Unavailable'ı yakalayıp 503 döndürüyor (monitoring/views.py:110, 142, 204) ve istisna oradan başka bir yerde kaydedilmiyor. Böylece kaynak okuma hatası (SQL hatası, TypeError/AttributeError gibi programlama hatası, kod regresyonu) izlenemez; yalnız duvar ekranı 'stale' görünür. Opsiyonel kaynaklar (_optional, satır 272-277) ise logger.exception ile kaydediliyor: iki yol arasında tutarsızlık var, ve kritik olanı kayıtsız. Geniş catch ayrıca gerçek hataları 'geçici kullanılamıyor' gibi maskeliyor (Retry-After: 30).
- Kanıt: monitoring/read.py:335-336; monitoring/views.py:66-71, 110, 142, 204; kıyas: monitoring/read.py:277 logger.exception.
- Öneri: Unavailable'a çevirmeden önce logger.exception (aynı 60 sn throttle ile) çağırın; yalnızca DatabaseError/beklenen okuma hatalarını yakalayın, programlama hatalarını yükseltin.
- Doğrulama `33-4`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. monitoring/read.py:335-336 `raise Unavailable(str(error))`, logger çağrısı yok (zorunlu kaynaklar için).
- Çapraz görüş itirazı `33-4`: concurrency: monitoring/read.py:272-278 _optional throttle'lı logger.exception içeriyor; iddia yalnız zorunlu kaynaklar için geçerli olabilir, kapsamı net değil.

### F-026 Izleme duvari her yenilemede tum stok defterini ve tum yemleme gecmisini yeniden katliyor

Önem: **Orta** | özgün: Yüksek | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulandı

- Kaynaklar: `35-1`
- Dosyalar: monitoring/read.py:315-336, monitoring/read.py:103, monitoring/read.py:460-472, farm/stock/read.py:33-48, farm/stock/read.py:327-335, farm/feeding/read.py:58-69, farm/feeding/read.py:77-96, farm/feeding/read.py:149-160, farm/water/read.py:231-252, monitoring/views.py:128-146
- Açıklama: `cards()` her cagrida `stock_read.stock_of(units)` ile, goruntulenen birimlerde stogu olan her batch'in TUM StockMovement gecmisini (`ledger`) cekip Python'da `fold` ediyor. Ardindan `feeding_read.figures(..., ration=True)` -> `project()` -> `lineage()` birimlerin bagli oldugu butun batch/birim agini transitif olarak genisletiyor ve `feedings(unit_ids)` `since` olmadan bu birimlerin TUM FeedingRecord'larini yukluyor. `water_read.latest()` -> `Context` -> `SpeciesBook` -> `Presence.of_units` yine tum stok satirlarini okuyor. Degisiklik belirteci dakika kovasi (TOKEN_BUCKET=60) icerdigi icin hicbir sey degismese bile her ekran en az dakikada bir tam yeniden hesap yaptiriyor; her denetim kaydi yazimi (herhangi bir kayit) tum ekranlari 15 sn icinde tam hesaba zorluyor. Maliyet gecmis boyutuyla (yillar) buyur, kart sayisindan bagimsiz sabit bir taban var.
- Kanıt: `stock = stock_read.stock_of(units) if STOCK in sections else {}` (monitoring/read.py:323); `records = feedings(unit_ids)` ve `walk(ledger(batch_ids), records, days, projector=projector)` (farm/feeding/read.py:149-160, `since` yok); `TOKEN_BUCKET = 60` ve `str(int(now.timestamp() // TOKEN_BUCKET))` (monitoring/read.py:103, 470); `MONITOR_POLL_SECONDS = 15` (config/settings.py:239). `lineage` dongusu "until nothing is added" (feeding/read.py:77-96) transfer yoluyla birbirine baglanan tum birimleri iceri aliyor.
- Öneri: Defter katlamasini birim/batch basina "son olcum noktasi" anlik goruntusu (snapshot tablosu veya audit revizyonuna anahtarli onbellek) olarak sakla; `project()` icin tarihi son olcum noktasindan baslat; kart cevabini (kullanici bolumleri + sorgu + revision anahtari) kisa sureli onbellege al ki ayni duvari izleyen birden fazla ekran tek hesaplamayi paylassin.
- Doğrulama `35-1`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. monitoring/read.py:323 cards() her çağrıda stock_of ile tüm ledger'ı katlıyor; "high" ölçülmemiş varsayım, medium tutuldu.

### F-027 Hasat listesi butun hasat gecmisini ve tum batch defterlerini katlayip sonra sayfaliyor

Önem: **Orta** | özgün: Yüksek | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulandı

- Kaynaklar: `35-3`
- Dosyalar: farm/harvest/read.py:39-50, farm/harvest/read.py:98-114, farm/harvest/views.py:94-99, farm/harvest/views.py:60-90
- Açıklama: `harvests(lines)` filtreye uyan TUM hasat satirlarini (`list(lines.select_related(...))`) ve bunlarin operasyon, kayit, kayip, plan, onay satirlarini yukluyor; `add_book` ise bu satirlarin tum batch'leri icin `moved_grams` ile defteri bastan katliyor. `Paginator(rows, PAGE_SIZE)` ancak bunlarin hepsi bellekte hazir olduktan sonra uygulaniyor, yani sayfa 1 bile tum gecmisin maliyetini oduyor. Ek olarak filtre secenekleri (`choices`) `movements__in=harvested` alt sorgusu uzerinde `.distinct()` birlesimleri; her filtre icin `values_list('pk')` tam kume cekiliyor.
- Kanıt: `rows = read.harvests(lines)` ... `page = Paginator(rows, PAGE_SIZE).get_page(...)` (farm/harvest/views.py:97-99); `moved = moved_grams({line.batch_id for line in lines})` (farm/harvest/read.py:46); `'site': Site.all_objects.filter(production_departments__tanks__movements__in=harvested).distinct()` (views.py:66).
- Öneri: Sayfalamayi sorgu duzeyinde yap (operasyon id sayfasi), sonra yalniz o sayfanin batch'leri icin kitap hesabi yap; toplamlari (Total) ayri bir agregasyon sorgusuyla hesapla.
- Doğrulama `35-3`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. farm/harvest/views.py:96-99 read.harvests tüm satırları yükleyip Paginator'ı bellekteki listeye uyguluyor.

### F-028 CI/CD pipeline yok

Önem: **Orta** | özgün: Yüksek | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulandı

- Kaynaklar: `37-1`
- Dosyalar: (yok: .github/, .gitlab-ci.yml vb.), THIRD_PARTY.md:7
- Açıklama: Repoda hiçbir CI tanımı yok; oysa THIRD_PARTY.md "Used to build and test ... on a developer's machine or in CI" diyerek CI'ı varsayıyor. Büyük bir test paketi (monitoring/tests, farm/tests, TS testleri, axe/playwright tarayıcı testi), `check_*` bütünlük komutları, `tsc --noEmit`, `makemigrations --check` hiçbir otomatik kapıda çalışmıyor.
- Kanıt: `ls .github` -> "No such file"; `git ls-files` içinde workflow/CI dosyası yok; `.git/hooks` boş.
- Öneri: Python testleri (TimescaleDB servisiyle), `manage.py check --deploy`, `makemigrations --check`, `npm run check && npm test`, compile_catalogs ve audit/lint adımlarını içeren bir pipeline ekleyin.
- Doğrulama `37-1`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. .github, Makefile, tox, pre-commit tanımı yok; git ls-files ile doğrulandı.

### F-029 Tekrarlayan görev silme/geri yükleme ile planlı görevler

Önem: **Orta** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-2`, `11-3`, `24-1`
- Dosyalar: tasks/services.py:238-241, core/softdelete.py:189-203, tasks/models.py:434-440
- Açıklama: Seri silinince dokunulmamış planlı görevleri `deleted_with` ile soft delete olur. `restore` yalnızca serinin kendisini döndürür. `materialise` "bir gün zaten görevi varsa, canlı ya da silinmiş, atla" kuralıyla `Task.all_objects` kullanır; böylece seri geri geldiğinde cascade ile silinmiş günler `taken` sayılır, bu günler yeniden üretilmez. `generated_until` değeri de ilerlediği için kalıcı boşluk (eksik görev) oluşur. Dokümanın "kişinin sildiği görev silik kalır" gerekçesi cascade ile silinenler için geçerli değil.
- Kanıt: `taken = set(Task.all_objects.filter(series=series, occurrence_date__in=days)...)` (services.py:240); restore yalnızca `record` üzerinde çalışır (softdelete.py:198-203).
- Öneri: Cascade ile silinen planlı görevleri `deleted_by`/zaman damgasıyla ayırt edip seri restore'unda geri getir ya da `taken` hesabını yalnızca kullanıcı tarafından silinenlerle sınırla.
- Birleştirilen kayıtlar:
  - `11-2` (Orta): Tekrarlayan görev `withdraw`, planlı görevleri kilitlemeden ve yeniden doğrulamadan hard delete eder
  - `24-1` (Orta): Tekrarlayan görev silinip geri yüklenince planlı görevleri kalıcı kaybolur

### F-030 Anonim isteklerde oturum satırı (middleware sırası)

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-4`, `01-X3`
- Dosyalar: core/middleware.py:12-14, config/settings.py:70-76, core/navigation.py:155-160
- Açıklama: WorkspaceMiddleware, LoginRequiredMiddleware'den ÖNCE çalışır ve kimlik kontrolü yapmadan `request.session[...]` yazar. Anonim biri bir çalışma alanı sayfasına (ör. /production/) istek atınca oturum yazılır, DB'de oturum satırı oluşur ve çerez döner, sonra 302 ile girişe yönlenir. Oturum tablosunu şişirme/DoS vektörü.
- Kanıt: `if key and request.session.get(...) != key: request.session[...] = key` - `request.user` kontrolü yok.
- Öneri: Yalnızca `request.user.is_authenticated` ise yaz veya middleware'i LoginRequired'dan sonra koy.
- Birleştirilen kayıtlar:
  - `01-X3` (Düşük): Anonim istek oturum satırı yazıyor ve LoginRequired sonrasına alınabilir

### F-031 Kimlik doğrulama olayları audit kaydında yok

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-9`, `01-X1`
- Dosyalar: core/audit.py, hr/apps.py, config/settings.py
- Açıklama: Kimlik doğrulama olayları denetim kapsamında sahipsiz
- Birleştirilen kayıtlar:
  - `01-9` (Düşük): Giriş, başarısız giriş, çıkış ve parola değişim/sıfırlama olayları denetim kaydına yazılmıyor

### F-032 batch_details/matris etiketi gerçek yetkiyle uyuşmuyor

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-4`, `49-13`
- Dosyalar: farm/stock/views.py:502-522
- Açıklama: Parti (Batch) yıl sınıfı/yabani-çiftlik bilgisi, matriste Batch alanı olmadığı için "stok işlemi Create" izniyle POST ile değiştirilebiliyor; satır kapsamı yok, rol matrisi bu yazmayı göstermiyor. Yetki matrisi ile gerçek yetki uyuşmuyor (matris yalnızca işlem kaydı gösteriyor).
- Kanıt: `@permission_required(RECORD)` ... `form = BatchDetailsForm(request.POST, instance=batch); form.save(request.user)`.
- Öneri: Matriste açıklamaya ekle ya da ayrı izin (`farm.change_batch`) ile koru.
- Birleştirilen kayıtlar:
  - `49-13` (Düşük): Matris etiketi "Create/Delete" fiilleri bazı alanlarda gerçek davranışla örtüşmüyor (void, kayıt dışı yazma)

### F-033 DB kimlik bilgisi/parola varsayılanı zayıf (compose/settings)

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-3`, `07-9`
- Dosyalar: docker-compose.yml:7-9, docker-compose.yml:13
- Açıklama: `POSTGRES_PASSWORD` varsayılanı `balik`; port `0.0.0.0` üzerinden yayınlanıyor. Yalnızca "yerel geliştirme" notlu olsa da dosya olduğu gibi sunucuda çalıştırılırsa açık bir DB olur. (05-3 ile örtüşür; burada imaj/compose yönünden kayda geçti.)
- Kanıt: `POSTGRES_PASSWORD: ${DB_PASSWORD:-balik}`; `ports: ["${DB_PORT:-5433}:5432"]`.
- Öneri: `127.0.0.1:${DB_PORT:-5433}:5432`; parolayı zorunlu yap veya compose'u dev-only olarak adlandır.
- Birleştirilen kayıtlar:
  - `05-3` (Orta): Veritabanı kimlik bilgileri kodda varsayılan, parola kullanıcı adıyla aynı

### F-034 UpdateView IntegrityError yakalanmıyor

Önem: **Orta** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-2`, `50-1`
- Dosyalar: `core/crud.py:715-757`, `core/crud.py:801-833`, karşılaştırma: `core/crud.py:687-702`
- Açıklama: `CreateView` yarışta oluşan unique/exclusion ihlalini yakalayıp `constraint_error` ile forma yazıyor. `UpdateView` aynı yarışı (iki kişi aynı kodu/ismi aynı anda başka kayıtlara veriyor, iki izin talebi çakışıyor) korumasız bırakıyor: form kontrolleri kilit öncesinde yapıldığından ikisi de geçer, ikinci `obj.save()` IntegrityError ile 500 döner. Satır kilidi yalnızca aynı kaydı korur; başka kayıtla çakışma (kısmi unique, `excl_leave_requests_employee_days`, `excl_attendance_employee_span`) korunmaz.
- Kanıt: `UpdateView.post` içinde `try/except IntegrityError` yok; `CreateView.post` satır 687'de var ve `constraint_error` (satır 262 civarı) hazır bir yardımcı.
- Öneri: `UpdateView` kaydını `CreateView` gibi `IntegrityError` -> `constraint_error(form, error)` ile sarın (transaction dışına çıkarak), formu 200 ile yeniden gösterin.
- Birleştirilen kayıtlar:
  - `50-1` (Orta): Genel UpdateView IntegrityError yakalamıyor (eşzamanlı benzersizlik ihlali 500 verir)

### F-035 Kullanıcı/rol düzenlemede iyimser kilit yok

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-8`, `11-4`
- Dosyalar: core/crud.py:158-164, 725-737, core/resources.py:14-47
- Açıklama: `TabbedForm.version` alanı model `version` alanı yoksa silinir; `Group` ve `User` Django modelleridir. `UpdateView` `versioned = 'version' in form.fields` olmadığı için sürüm kontrolü atlanır, yalnızca satır kilidi alınır. İki yönetici aynı rolü açıp farklı izinler işaretlerse ikincisi birincinin izin değişikliğini uyarısız ezer (`permissions` m2m tamamen `set` edilir); aynı durum kullanıcının `groups`/`is_active` alanı için geçerli. Güvenlik açısından izin matrisi sessizce geri alınabilir.
- Kanıt: `if not any(f.name == 'version' ...): del self.fields['version']` (crud.py:161-162); `versioned = 'version' in form.fields` (crud.py:725).
- Öneri: Rol/Kullanıcı formuna bir gizli sürüm (ör. `updated_at` damgası veya Profile üzerinde sayaç) ekleyip kilit altında karşılaştır.
- Birleştirilen kayıtlar:
  - `10-8` (Düşük): Kullanıcı ve rol düzenlemesinde sürüm (iyimser kilit) yok; rol silme etkilenen kullanıcıları göstermiyor

### F-036 SET_NULL ile kopan bağlar restore edilince geri bağlanmaz

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `11-8`, `12-6`
- Dosyalar: core/softdelete.py:168-174 (detach), 185-203, core/models.py:55-60
- Açıklama: Silinen kaydın SET_NULL çocukları (ör. silinen sitenin üretim departmanları) `detach` ile bağını kaybeder ve yeni bir UPDATE audit satırı yazılır; kaydı geri getirmek bu bağları yeniden kurmaz. Eski değer yalnızca AuditLog.changes içinde metin etiketi (`str(getattr(record, link))`) olarak durur, kimlik (pk) saklanmaz, dolayısıyla otomatik geri bağlama da yapılamaz.
- Kanıt: `before = str(getattr(record, link))`; `audit.record(user, UPDATE, record, {label: [before, None]})`; `restore` içinde detach'lerin tersi yok.
- Öneri: Audit satırına bağlı kaydın pk'sini de yazın veya silme planını (detach/cascade listesi) saklayıp geri getirmede tersini uygulayın.
- Birleştirilen kayıtlar:
  - `11-8` (Düşük): SET_NULL ayırma (`detach`) geri alınamaz: restore bağı geri koymaz

### F-037 Hypertable PK dönüşümü geri alınamaz/Django durumu ile uyumsuz

Önem: **Orta** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-7`, `15-7`
- Dosyalar: farm/migrations/0014_water.py:91-103, farm/migrations/0019_water_points.py:186-205
- Açıklama: PK elle `(id, measured_at)` yapılıyor, Django durumu `id` PK diyor (state_operations yok). Bu bilinçli ve yorumlu, ancak (a) migration sonrası `water_measurements` üzerinde sonraki şema değişiklikleri (0019: AlterField NOT NULL, RemoveField, FK) hypertable'ın chunk'larında kilit ve tam tarama gerektirir; (b) `reverse_sql=noop` yalnızca CreateModel'in tabloyu düşürmesine güvenir: 0014 geri alınmadan, tablo veri taşırken tek başına RunSQL geri alınırsa PK/hypertable durumu kalır; (c) `FK` → `water_measurements.point` hypertable üzerinde `DO_NOTHING` ve `db_index=False`. 0019 sonrası tablo büyük hacimliyse tek transaction'da 3 ALTER + UPDATE içerir.
- Kanıt: 0014:96-103 RunSQL listesi; README.md:1065 aynı ayrışmayı not ediyor.
- Öneri: Hypertable adımının ve sonraki ALTER'ların prod'da boş/küçük tabloya yapıldığını belgelemek; docs'a TimescaleDB sürüm/yedek gereksinimini (12-backup-restore bulgusuna bağlı) eklemek.
- Birleştirilen kayıtlar:
  - `15-7` (Orta): Hypertable dönüşümü geri alınamaz ve PK ile Django durumu ayrışık

### F-038 Özel hata şablonları/handler yok

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-3`, `45-2`
- Dosyalar: templates/, config/urls.py, core/crud.py
- Açıklama: templates/ altında 400.html/403.html/404.html/500.html yok; config/urls.py'de handler400/403/404/500 tanımı yok; CSRF_FAILURE_VIEW da yok. Uygulama sürekli PermissionDenied (core/crud.py:557, hr/views.py, @permission_required(raise_exception=True)) ve Http404 (kapsam dışı kayıtlar için bilinçli 404) kullanıyor; kullanıcı bu durumlarda Django'nun düz İngilizce ('Forbidden', 'Not Found', 'Server Error (500)') sayfasını görür: menü yok, dil seçimi yok (uygulama EN/NB/TR çok dilli), geri dönüş bağlantısı yok. frontend/poll.ts GONE=401/403/404 durumlarına özel davranıyor ama sayfa tarafında karşılığı yok.
- Kanıt: find . -name '404.html' -o -name '500.html' -o -name '403.html' (node_modules hariç) -> sonuç yok; grep handler404|handler500|csrf_failure -> yok.
- Öneri: templates/ kökünde 400/403/404/500.html (app/auth base'ten türeyen, çevrilmiş, ana sayfaya link veren) ekleyin; 500.html bağlam işlemcisi olmadan statik güvenli olmalı; CSRF_FAILURE_VIEW tanımlayın; locale katalogları ekleyin.
- Birleştirilen kayıtlar:
  - `45-2` (Düşük): Özel 403/404/500 ve CSRF hata şablonu yok; hata sayfaları çevrilmiyor

### F-039 Veritabanı görüntüleyici gereksiz sorgular

Önem: **Orta** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `09-1`, `35-9`
- Dosyalar: core/dbgrid.py:156-172, core/dbgrid.py:51-65, core/database.py:115-122, core/dbview.py:25-40, core/dbgrid.py:20-21
- Açıklama: `browse` bir gorunumde `table.counts()` (COUNT(*) + filtreli COUNT) ve `Paginator.count` (ikinci bir COUNT(*) filtreli sorgu) calistiriyor; hypertable (`water_measurements`) ve audit_log gibi buyuk tablolarda bu tam tarama. Arama kutusu her okunabilir sutunu `Cast(..., TextField)` + `ILIKE` ile OR'layip hicbir indeksi kullanamaz; siralama herhangi bir sutuna izinli (indeksiz sirala + `OFFSET`). `overview` her tablo icin ayri bir COUNT calistiriyor (cok sayida tablo). Disa aktarma 50.000 satira kadar (`EXPORT_LIMIT`) `.iterator()` ile akisla gonderiliyor ve bu sirada ayni sorguyla tam tarama yapiliyor. Yalniz platform yoneticisine acik oldugu icin etki sinirli.
- Kanıt: `return Paginator(self.queryset(), PAGE_SIZE).get_page(self.page_number)` (dbgrid.py:172); `counts = self.model._base_manager.aggregate(counted)` (database.py:121); `'tables': [{'table': table, table.counts()} for table in tables]` (dbview.py:27); `Q(IContains(Cast(field.attname, models.TextField()), term))` (dbgrid.py:65).
- Öneri: Satir sayisi icin `pg_class.reltuples` tahmini kullan (tam sayim yalniz filtreli goruntude); arama yalniz secilen sutun filtresiyle; genel bakista kestirimli sayilar.
- Birleştirilen kayıtlar:
  - `09-1` (Orta): Veritabanı görüntüleyici genel bakışı her tablo için ayrı tam `COUNT(*)` çalıştırır (hypertable dahil)

### F-040 Üretim/geliştirme yapılandırma ayrımı yok

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `05-5`, `37-9`
- Dosyalar: config/settings.py:25-30, README.md:2979-2988, .gitignore:5
- Açıklama: Tek settings.py; DEBUG varsayılanı '1', ALLOWED_HOSTS boş, SECRET_KEY sabit yedek (DJANGO_SECRET_KEY eksikse sessizce yerel anahtar). `.env` ignore ediliyor ama okuyan kod yok ve `.env.example` yok; ortam değişkenleri yalnızca README paragrafında dağınık (DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS, DJANGO_MEDIA_ROOT, DB_*, DB_CONN_MAX_AGE). Kurulum komutları `C:\Python312\python.exe` ve `.venv\Scripts\` ile yalnızca Windows; Linux/CI karşılığı yok. (Güvenlik boyutu: 05-secrets-config.md.)
- Kanıt: settings.py:25,28,30; README.md:2982-2987.
- Öneri: Ortam değişkeni referans tablosu/.env.example, prod ayarlarında zorunlu env doğrulaması, platformdan bağımsız kurulum.
- Birleştirilen kayıtlar:
  - `05-5` (Orta): Üretim/geliştirme ayrımı ve dağıtım artefaktları yok

### F-041 Silme onayı metni admin geri getirme iddiası

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-18`, `43-10`
- Dosyalar: templates/crud/confirm_delete.html:47, core/admin.py:27-53, farm/admin.py:23,55
- Açıklama: Soft delete sonrası metin kaydın admin'den geri getirilebileceğini söylüyor, fakat geri yükleme yalnız platform admininin Django admin eylemi (`has_restore_permission`); uygulama içinde "çöp kutusu"/geri al yok ve flash mesajında geri al bağlantısı yok. Silme sonrası yanlışlığı fark eden normal kullanıcı için akış çıkmazdır. Ayrıca void edilen stok/besleme/su kayıtları admin restore'dan bilerek hariç (farm/admin.py:23,55) yani hiç geri alınamaz.
- Kanıt: confirm_delete.html:47 metni; core/admin.py:36 `has_restore_permission`; farm/admin.py:55 "a restore would bring back a value someone said was wrong".
- Öneri: Metni rolüne göre doğru yaz ("yalnız platform yöneticisi geri getirebilir"); silme sonrası flash'a kısa süreli "Geri al" (restore) bağlantısı veya Activity log'dan geri yükleme ekle.
- Birleştirilen kayıtlar:
  - `42-18` (Düşük): Silme onayı iki kopya metin: yumuşak silme metni "admin'den geri alınabilir" iddiası şablonda sabit

### F-042 Form alanı kenarlık kontrastı WCAG

Önem: **Orta** | özgün: Orta/Düşük | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-3`, `46-11`
- Dosyalar: `static/css/base.css:10,47,165`, `static/css/components.css:70,959`, `static/css/components.css` (`.water-date input` ~597)
- Açıklama: Form kontrollerinin tek görsel sınırı olan `border: 1.5px solid var(--sage)` (#C3CBB2) beyaz zeminde 1.68:1, `--mist` zeminde 1.47:1 kontrast veriyor; bileşen sınırı için gereken 3:1 sağlanmıyor. Dil seçici segmentinin kenarlığı da aynı renk. Kontrol hover'da `--muted` (6.13:1) olduğuna göre uygun bir token zaten mevcut.
- Kanıt: Hesaplanan oranlar sage/white 1.68, sage/mist 1.47; `base.css:47`.
- Öneri: Varsayılan kenarlığı en az 3:1 bir tona (örn. `--muted`) çek, hover'ı koyulaştır.
- Birleştirilen kayıtlar:
  - `46-11` (Düşük): Form alani kenari (sage) kontrasti 1.68:1

### F-043 Üretim için LOGGING yapılandırması yok; DEBUG=False iken yakalanmayan 500 hataları hiçbir yere yazılmaz

Önem: **Orta** | özgün: Yüksek | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulandı

- Kaynaklar: `33-1`
- Dosyalar: config/settings.py
- Açıklama: config/settings.py içinde LOGGING, ADMINS, EMAIL_* veya SERVER_EMAIL tanımı yok. Django'nun varsayılan günlükleme ayarında console handler'ı yalnızca DEBUG=True iken, mail_admins ise DEBUG=False iken çalışır ve ADMINS boşsa hiçbir şey göndermez. Sonuç: DEBUG kapalı bir dağıtımda view içindeki yakalanmayan istisnalar ve 5xx cevapları kalıcı olarak kaydedilmez (yalnızca WSGI sunucusunun kendi çıktısı kalır). Uygulamada logger kullanan yalnızca 3 modül var (monitoring/read.py:60, monitoring/cards/resolve.py:24, farm/placements.py:18); core, hr, knowledge, reports, messaging, tasks, inventory, experiments altında hiç logger yok.
- Kanıt: grep: LOGGING|ADMINS|EMAIL -> config/settings.py'de eşleşme yok; 'logger\.|logging\.' yalnızca monitoring/read.py, monitoring/cards/resolve.py, farm/placements.py.
- Öneri: settings.py'ye açık bir LOGGING sözlüğü ekleyin (console/stderr handler, django.request ve uygulama logger'ları INFO/ERROR, yapılandırılabilir seviye); gerekirse ADMINS/Sentry benzeri bir 5xx bildirim yolu tanımlayın.
- Doğrulama `33-1`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. config/ altında LOGGING/ADMINS yok; DEBUG=False iken yakalanmayan 500 kaydedilmez.

### F-044 Rapor "due" listesi her cagrida tum siteleri/donemleri bastan hesapliyor; ana sayfa dahil her yerde cagriliyor

Önem: **Orta** | özgün: Yüksek | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulandı

- Kaynaklar: `35-5`
- Dosyalar: reports/due.py:139-160, reports/due.py:196-233, reports/due.py:399-417, reports/resources.py:158-175, reports/views.py:41-49, reports/views.py:88, reports/views.py:139, reports/services.py:116, config/views.py:23-28
- Açıklama: `due.due()` her site icin tum Tank'lari, tum StockMovement varligini (`Presence.of_units`) ve `reports_from`'dan bugune tum haftalik/aylik donemleri uretip her donem icin tum (birim, batch) zaman cizelgelerini tarıyor (`_periodic_line`: donem x timeline x present_between, O(D x T)). Sonuc hicbir yerde onbellege alinmiyor ve sirasiyla: sirket ana sayfasi (`overview_upcoming`, `report.view` izni olan herkes), rapor listesi, `outside_duties`, `_due_row` (kapatma linki) ve `close_due` (ayrica dogrulama icin tekrar) icinde cagriliyor. Rapor listesi ayrica `no_longer_match()` cagiriyor: son ~1 yilin her kayitli raporu icin `compute.scope(report)` + `fingerprint` hesaplaniyor (rapor basina sorgular), yani rapor sayisiyla dogrusal.
- Kanıt: `owed = due.due()` (config/views.py uzerinden reports/views.py:46, resources.py:168); `for period in periods.periods_between(...)` icinde `any(... presence.present_between(unit, batch, ...) for unit, batch in presence.timelines)` (due.py:225-227); `for report in filed: ... compute.fingerprint(compute.scope(report))` (due.py:411-414).
- Öneri: `due()` sonucunu audit revizyonu + gun anahtariyla kisa sureli onbellekle; ana sayfa ozetini ayri/hafif hesapla; `Presence` zaman cizelgesini donem basina degil site basina bir kez indeksle (sorted days + bisect).
- Doğrulama `35-5`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. reports/due.py:139-156 due() önbelleksiz; her çağrıda tüm Site/Tank/Report kayıtları yeniden yükleniyor.

### F-045 İzleme duvarında "bağlantı yok / eski veri" uyarısı yalnızca CSS `::before content:` ile basılıyor

Önem: **Orta** | özgün: Yüksek | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulandı

- Kaynaklar: `44-7`
- Dosyalar: `static/css/monitor.css:5-21`, `templates/monitoring/monitor.html:37`, `frontend/poll.ts:143-147`, `templates/monitoring/_windows.html:5`
- Açıklama: Poll 2 başarısızlıktan sonra `data-poll-state="stale"`, 401/403/404'te `gone` yazıyor; kullanıcıya görünen metin CSS `content: attr(data-stale-text)` ile üretiliyor. Bu metin canlı bölgede değil, tutarlı biçimde erişilebilirlik ağacına açılmıyor ve değişiklik duyurulmuyor. `announce.ts` yalnızca kartın durumu kötüleştiğinde konuşuyor; bağlantının kopması (kart verisinin eskimesi güvenlik açısından kritik: balık çiftliği izleme duvarı) ekran okuyucu kullanıcıya hiç bildirilmiyor. Pencere gövdesi için de aynı.
- Kanıt: `monitor.css:17-18` `content: attr(data-stale-text)`; `announce.ts` yalnızca `poll:merged` olayını dinliyor, `data-poll-state` değişimini dinlemiyor.
- Öneri: `poll:stale`/`gone` durumunda `#monitor-announce` assertive bölgesine metni yaz veya DOM'da `role="status"` bir eleman yönet.
- Doğrulama `44-7`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. static/css/monitor.css:16-19 stale/gone metni yalnız ::before content ile; frontend/poll.ts:143-147,161-165 yalnız dataset.pollState yazıyor.

### F-046 Production manager önayarı ile matris uyumsuzluğu

Önem: **Orta** | özgün: Orta/Düşük | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-3`, `49-12`
- Dosyalar: hr/roles.py:9-12, 28-31; core/access.py (`implied`); config/access.py (Employees `all_production`)
- Açıklama: Önayar `hr.all_production_employee` verir ama `hr.view_employee` vermez ("No Team list" - hr/roles.py:10). `implied()` bir alanda herhangi bir eylem seçilince Read'i ekler; rol formu matris üzerinden bir kez kaydedildiğinde `hr.view_employee` eklenir ve Team listesi/ kişi sayfaları açılır. Önayarın belgelenen yetki kümesi ile matrisin ürettiği küme tutarsız.
- Kanıt: hr/roles.py:31 izin listesinde `view_employee` yok; core/access.py `implied`: `if READ in area.actions and any(area.perm(action) in names ...): names.add(area.perm(READ))`.
- Öneri: Önayara `view_employee` açıkça eklenip davranış belgelensin ya da `all_production` Read'i ima etmesin; test ekle.
- Birleştirilen kayıtlar:
  - `49-12` (Düşük): Rol önayarı ile matris/menü uyumsuzluğu: Production manager önayarında view_employee yok ama menüde Production › Team › People girdileri onu ister

### F-047 Statik varlık mtime sürümleme her istekte dosya sistemi

Önem: **Orta** | özgün: Orta/Düşük | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-5`, `46-19`
- Dosyalar: core/templatetags/assets.py:19-41
- Açıklama: `versioned()` her `{% asset %}` çağrısında `finders.find` ile diske bakar, `module_map()` her render'da tüm finder'ları gezip `static/js/*.js` listeler; önbellek yok. Ayrıca `?v=mtime` yalnızca kaynak STATICFILES_DIRS'ten okunur: collectstatic/konteyner kopyalamada mtime değişir (her dağıtımda cache geçersizlenir, replikalar arası farklı v değerleri olabilir). Derlenmemiş static/js (npm build unutulursa) sessizce `static(path)` döner, 404 olur, hata vermez.
- Kanıt: assets.py:25-28 `finders.find(path)`; assets.py:35-40 döngü, lru_cache/CACHES yok (settings.py'de CACHES yok).
- Öneri: İçerik hash'li ManifestStaticFilesStorage veya süreç düzeyi önbellek; eksik derleme çıktısını build/check'te başarısız kılın.
- Birleştirilen kayıtlar:
  - `46-19` (Düşük): `?v=mtime` surumleme: her istekte dosya sistemi taramasi ve dagitima bagli degisken surum

### F-048 Parola sıfırlama isteği için oran sınırı yok (e-posta bombardımanı)

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-6`
- Dosyalar: config/urls.py:24-26, core/forms.py:162-165
- Açıklama: Bilinen bir e-postaya sınırsız sıfırlama maili tetiklenebilir; CSRF dışında koruma yok. Yanıt kullanıcı varlığını sızdırmıyor (olumlu), fakat gönderim zamanı farkı kalır (e-posta gönderen kullanıcı için daha uzun yanıt).
- Kanıt: `PasswordResetView` standart; test `test_unknown_email_sends_nothing` (core/tests.py:76) sadece yok durumunu doğruluyor.
- Öneri: IP/e-posta bazlı sınır; gönderimi asenkron yap.

### F-049 HR dışında hiçbir satır/site/departman kapsamı yok: izinler tüm çiftlik verisi için global

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-1`
- Dosyalar: core/crud.py:453-472, config/access.py (tamamı), farm/*/views.py
- Açıklama: `Resource.scoped` varsayılanı "her satır" (core/crud.py:455-463). Yalnızca HR (hr/scope.py) ve mesajlaşma üyeliği satır kapsamı uygular. Bir rolde `farm.add_stockoperation` olan kişi, hangi site/departmanda çalışırsa çalışsın tüm tank/sitelerde işlem kaydedebilir ve geçersiz kılabilir (farm/stock/views.py:422, 525). Orijinal sistemdeki site-atama kontrolü (docs/aquaculture-platform-bugs.md FDR-10) bilinçli olarak "tek şirket" modeline indirgenmiş.
- Kanıt: core/crud.py:455 `The default is every row.`; farm/stock/views.py:526 `get_object_or_404(StockOperation, pk=pk)` site filtresiz.
- Öneri: Çok siteli işletme hedefleniyorsa site/departman kapsamı için `scoped` kullanan bir mekanizma belgelenmeli; tek şirket varsayımı README'de açık yazılmalı.

### F-050 Aktivite günlüğünde yalnızca HR kayıt türleri kısıtlı; diğer hassas günlükler `core.view_auditlog` sahibine açık

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-5`
- Dosyalar: core/audit.py:25-43, hr/apps.py:14, core/views.py:28-58
- Açıklama: `restrict()` sadece HR'ın 5 modeli için kullanılıyor. Kullanıcı/rol değişiklikleri (e-posta, atanan roller), kanal üyelikleri ve görev notlarının tam metni (tasks/services.py:196-198) günlük okuyucusuna açık. Ayrıca HR kısıtı `hr.all_employee` sahibine bağlı: `all_production` sahibi (müdür) HR günlüğünü göremez, tutarlı ama `LeaveType`, `Shift`, `Holiday` gibi diğer HR modelleri kısıtsız.
- Kanıt: core/audit.py:39-43 `readable` yalnızca `_restricted` türlerini dışlar; tasks/services.py:198 `audit.record(... {str(NOTE): [None, body]})`.
- Öneri: Roller/kullanıcılar/kanallar için `restrict` listesi gözden geçirilsin; günlük görüntüleme hakkı bilinçli olarak yönetici düzeyinde tutulsun.

### F-051 Content-Security-Policy tanımlı değil

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-1`
- Dosyalar: config/settings.py:64-78
- Açıklama: MIDDLEWARE listesinde CSP middleware'i ve ayarlarda `SECURE_CSP`/`SECURE_CSP_REPORT_ONLY` yok. Bir kaçış hatası olduğunda ikinci savunma hattı yok. Kod tabanı katı CSP'ye elverişli: şablonlarda satır içi çalıştırılan betik yok (yalnızca `json_script` veri blokları ve tek `importmap`), `on*=` olay işleyicisi yok; yalnızca 3 `style="..."` özniteliği ve `_card.html`'de `style="{{ view.style }}"` var.
- Kanıt: `grep -rn "CSP\|CONTENT_SECURITY" --include=*.py` yalnızca monitoring dışı alakasız eşleşme verdi; MIDDLEWARE'de `django.middleware.csp` yok. `core/templatetags/assets.py:41` importmap'i satır içi `<script>` olarak basıyor (nonce gerektirir).
- Öneri: Django'nun yerleşik CSP desteğiyle önce Report-Only başlat (`default-src 'self'; script-src 'self' nonce; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`); importmap için nonce kullan; `style-src-attr` için karar ver.

### F-052 Gizli bilgi alanı (SECRET_KEY) çoklu amaçlı kullanılıyor; rotasyon yolu yok

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-8`
- Dosyalar: config/settings.py:25, core/audit.py:98
- Açıklama: `SECRET_KEY_FALLBACKS` tanımlı değil; anahtar değişince tüm oturumlar düşer ve audit HMAC özetleri eski kayıtlarla karşılaştırılamaz hale gelir. Audit özeti için ayrı bir anahtar yok.
- Kanıt: settings.py'de `SECRET_KEY_FALLBACKS` yok; audit.py:99 doğrudan SECRET_KEY kullanır.
- Öneri: Audit için ayrı anahtar ve `SECRET_KEY_FALLBACKS` ile rotasyon planı.

### F-053 İstek gövdesi boyut sınırı uygulamada yok; yalnızca model doğrulaması ve "ön sunucu kapsın" notu

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-3`
- Dosyalar: config/settings.py:182-185, knowledge/models/document.py:58-72, docker-compose.yml
- Açıklama: `KNOWLEDGE_MAX_FILE_BYTES` yalnızca form/model doğrulamasında (`file.size > limit`) uygulanır; Django çok parçalı gövdeyi önce geçici dosyaya yazar (settings yorumu bunu kabul ediyor). `FILE_UPLOAD_MAX_MEMORY_SIZE`, `FILE_UPLOAD_TEMP_DIR`, `DATA_UPLOAD_MAX_NUMBER_FILES/FIELDS` ayarlanmamış (varsayılanlar), ve repoda gerçek bir ön sunucu yapılandırması (nginx/Dockerfile) yok; sınır yalnızca yorum/README'de. Oturum açmış, library `add/change` izni olan biri 20 MB üstü gövdeyi sınırsız diske yazdırabilir. Ayrıca bir istek içinde birden çok `file` alanı aynı anda gönderilebilir (tek alan okunur, diğerleri geçici dosya olarak kalır ve istek sonunda silinir).
- Kanıt: settings.py:182-185 yorumu "The web server in front of Django must cap a request's body too"; settings.py'de `grep UPLOAD` yalnızca bu yorum ve `KNOWLEDGE_MAX_FILE_BYTES`; ön sunucu config dosyası yok.
- Öneri: Dağıtım şablonuna (nginx/Dockerfile) `client_max_body_size` ekle, `DATA_UPLOAD_MAX_MEMORY_SIZE`/`FILE_UPLOAD_*` değerlerini açıkça belirle, testle `RequestDataTooBig` (413) davranışını doğrula.

### F-054 Python bağımlılıkları için kilit dosyası ve hash yok; geçişli bağımlılıklar sabitlenmemiş

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-1`
- Dosyalar: requirements.txt:1-13
- Açıklama: Liste elle tutulan, düz `==` sabitlemeli bir dosya. `cryptography` (cffi -> pycparser) ve `pypdf` gibi paketlerin geçişli bağımlılıkları listede yok, dolayısıyla temiz kurulumda sürümleri zamana göre değişir. `--require-hashes`/pip-compile çıktısı yok; yeniden üretilebilir ve doğrulanabilir kurulum sağlanmıyor.
- Kanıt: `cryptography==50.0.2` (satır 4) var, `cffi`/`pycparser` yok; hiçbir satırda `--hash=` yok; repoda requirements.in/constraints/pyproject yok.
- Öneri: pip-tools veya uv ile hash'li tam kilit dosyası üret; kurulumda `--require-hashes` kullan.

### F-055 Python ve Node sürümü hiçbir yerde bildirilmiyor

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-2`
- Dosyalar: requirements.txt, package.json:14-29, README.md:2982
- Açıklama: Django 6.1 / paket sürümleri belirli bir Python sürümü gerektirir ancak `python_requires`, `.python-version`, Dockerfile veya README'de açık sürüm şartı yok (README yalnızca Windows yolu olarak `C:\Python312\python.exe` örneği veriyor). package.json'da `engines` ve `.nvmrc` yok; `@types/node` 22.x kullanılırken Node sürümü belirsiz (testler `node --test` ve ESM'e dayanıyor).
- Kanıt: `git ls-files` çıktısında .python-version, .nvmrc, Dockerfile, pyproject.toml yok; package.json'da `engines` alanı yok; README.md:2982 yalnızca `C:\Python312\python.exe`.
- Öneri: Python alt sınırını ve Node sürümünü (`engines`, `.nvmrc`) belgele ve CI'da zorla.

### F-056 Otomatik güvenlik açığı taraması ve güncelleme mekanizması yok (CI, Dependabot, pip-audit, npm audit)

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-3`
- Dosyalar: (yok) .github/ dizini mevcut değil, requirements.txt, package.json
- Açıklama: Sabitlenmiş sürümler zamanla CVE alır; bunları izleyen ya da PR açan bir mekanizma yok. requirements.txt yorumu (satır 8-9) pypdf'in "her yamada" hostile PDF sorunlarını kapattığını söylüyor, ancak güncel tutmayı sağlayan süreç tanımlı değil. README `CI=1` ortamından söz ediyor (README.md:3405) fakat repoda CI tanımı yok.
- Kanıt: `ls .github` -> "No such file or directory"; repoda dependabot/renovate yapılandırması yok.
- Öneri: Dependabot/Renovate ekle, CI'da `pip-audit` ve `npm audit --omit=dev` çalıştır.

### F-057 pypdf güvenilmeyen kullanıcı PDF'ini okuyor; bu paket yüksek riskli yüzey ve güncellik süreci yok

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-4`
- Dosyalar: requirements.txt:8-10, knowledge/extraction.py:24
- Açıklama: pypdf yüklenen PDF'leri ayrıştırıyor (DoS/bellek tüketimi geçmişi olan bir sınıf). Sürüm güncel görünüyor (6.21.4) ancak güncelleme izleme olmadan bu sabitleme zamanla eskir (bkz. 07-3). `cryptography` yalnızca AES şifreli PDF için isteniyor; sürüm hem pypdf hem Django ile ilgisiz şekilde sabitlenmiş, uyumluluk testi tek bir test dosyasına dayanıyor.
- Kanıt: `from pypdf import PdfReader` (knowledge/extraction.py:24); `pypdf==6.21.4` (requirements.txt:10).
- Öneri: pypdf'i öncelikli izlenen paket olarak işaretle; ayrıştırmayı kaynak sınırlı alt süreçte çalıştırmayı değerlendir (ayrı alan: injection/dos uzmanı).

### F-058 THIRD_PARTY.md Python paketlerinin lisanslarını listelemiyor; psycopg LGPL

Önem: **Orta** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-5`
- Dosyalar: THIRD_PARTY.md:1-5, THIRD_PARTY.md:7-16, requirements.txt:5-7
- Açıklama: Belge sunucunun çalıştırdığı Python paketlerini "requirements.txt'te" diye havale ediyor, lisans tablosu yalnızca dev npm araçlarını kapsıyor. Oysa dağıtılan/çalışan asıl bağımlılıklar (Django BSD-3, psycopg ve psycopg-binary LGPL-3.0 - binary paketi libpq/OpenSSL de taşır, cryptography Apache-2.0/BSD, pypdf BSD-3, Babel BSD-3) lisans bildirimi gerektirir. LGPL'in yeniden bağlama/değiştirme koşulları belgelenmemiş.
- Kanıt: THIRD_PARTY.md:1-5 yalnızca "The Python packages the server runs are in requirements.txt" der; tabloda yalnızca typescript, @types/node, playwright-core, axe-core var.
- Öneri: Python paketleri için lisans tablosu ekle (ve geçişli bağımlılıklar), LGPL notunu yaz; lisans listesini araçla üret.

### F-059 Kontak e-posta/telefonu silinemez denetim günlüğüne düz metin yazılıyor

Önem: **Orta** | Güven: yüksek | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-1`
- Dosyalar: `farm/resources/contact.py:14-20`, `core/crud.py:341-371`, `core/migrations/0003_audit_log_append_only.py`
- Açıklama: Site/tedarikçi kontak listesi kaydedilirken `RowList.save` eski/yeni özeti `describe()` ile günlüğe yazar. `ContactList.describe` ad, rol, e-posta ve telefon'u içerir. Bu özel veri `private_fields` mekanizmasından geçmez ve günlük tablosu DB trigger'ı ile UPDATE/DELETE'e kapalıdır. Kontak satırının kendisi silinse de (delete-all/insert-all) üçüncü kişinin e-postası/telefonu günlükte kalıcıdır.
- Kanıt: `describe`: `details = [value for value in (contact.role, contact.email, contact.phone) if value]`; `save`: `audit.record(user, UPDATE, obj, {str(cls.label): [before, after]}, ...)`; trigger `audit_log_append_only` "rows cannot be changed or deleted".
- Öneri: Kontak günlük özetinde e-posta/telefonu yazmayın (yalnızca ad/rol veya "değişti" + keyed digest) ya da günlük için anonimleştirme/redaksiyon yolu tasarlayın.

### F-060 Kodda saklama süresi, silme, anonimleştirme ve veri sahibi erişim/dışa aktarma mekanizması yok

Önem: **Orta** | Güven: yüksek | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-3`
- Dosyalar: `hr/resources/employee.py:25-28`, `core/resources.py:42`, `hr/management/commands/` (check_hr, hr_roles, seed_hr_demo), `core/management/commands/`, `docs/hr-launch-checklist.md:56-59`
- Açıklama: Çalışan (`actions = ('add','change')`) ve kullanıcılar (`'people are deactivated, not deleted'`) asla silinmez; ayrılan çalışana yalnız `left_on` konur. Yoklama, izin, vardiya, yerleştirme, mesaj, görev notu kayıtları için temizleyen/anonimleştiren bir management komutu, zamanlanmış iş veya ayar yoktur. Veri sahibine erişim/taşınabilirlik dışa aktarımı yoktur. Bunlar yalnızca checklist 4.1'de "DPO belirler" diye kutucuk olarak duruyor.
- Kanıt: management komutları listesi (retention/purge/anonymize adı yok); depoda `retention` yalnızca README:1016 (yem kaydı bağlamında) ve checklist'te geçer.
- Öneri: Alan başına saklama süresi ayarı + denetimli anonimleştirme komutu (ayrılan çalışan, pasif kullanıcı, eski izin/yoklama) ve veri sahibi dışa aktarma ekleyin.

### F-061 Görev notları, tamamlama notu ve iptal sebebi aktivite günlüğüne düz metin yazılıyor

Önem: **Orta** | Güven: yüksek | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-5`
- Dosyalar: `tasks/services.py:37,200-202`, `tasks/models.py:357,493`, `core/audit.py:28-45`, `hr/apps.py:14`
- Açıklama: HR'deki izin sebebi/yoklama notu "kişinin kendi sözleri" olarak `private_fields` ile gizlenir; oysa görev notunun tam metni (`{str(NOTE): [None, body]}`) ve `completion_note`/`cancel_reason` (`LOGGED_AFTER`) günlüğe olduğu gibi yazılır. Görev günlük kayıtları `restrict` kapsamında değildir; `core.view_auditlog` sahibi herkes okur. Serbest metin kişisel veri (ör. bir çalışanın durumu, adı) içerebilir ve günlük silinemez (08-2).
- Kanıt: `audit.record(user, AuditLog.Action.UPDATE, task, {str(NOTE): [None, body]})`; `LOGGED_AFTER = [..., 'completion_note', ..., 'cancel_reason']`.
- Öneri: Bu alanları `private` (anahtarlı özet) kuralıyla günlüğe yazın veya günlükte yalnızca "not eklendi" gösterin; Task günlüğünü de kısıtlamayı düşünün.

### F-062 Etkinlik günlüğü sayfası her istekte tüm günlük üzerinde iki `DISTINCT` taraması ve `icontains` araması yapar

Önem: **Orta** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-10`
- Dosyalar: core/views.py:28-58, core/models.py:154-196
- Açıklama: Filtre açılır listeleri için `readable.order_by('user_name').values_list('user_name', flat=True).distinct()` ve `...'entity_type'...distinct()` her sayfa yüklemesinde (filtre/sayfa değişiminde de) tüm `audit_log` üzerinde çalışır; günlük salt-eklemeli ve sınırsız büyür. Yalnızca `created_at` ve `(entity_type, entity_id)` indeksleri var; `user_name` indeksi yok. `q` araması `entity_label ILIKE '%q%'` (indeks dışı), sonra Paginator `COUNT(*)`.
- Kanıt: `'users': readable.order_by('user_name').values_list('user_name', flat=True).distinct()` (core/views.py:53-54).
- Öneri: Kullanıcı/tür listelerini önbellekle ya da ayrı küçük tabloya al; `user_name` için indeks; arama için trigram indeks.

### F-063 `reports.due.due()` tüm çiftlik için ağır hesabı her rapor listesi ve her ana sayfa yüklemesinde çalıştırır

Önem: **Orta** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-14`
- Dosyalar: reports/resources.py:168-169; reports/views.py:41-52; config/views.py:26; reports/due.py:139-165, 320-360
- Açıklama: Rapor listesinin `filter_list`'i (arama, filtre, sayfa değişimi dahil her GET) `due.due()` ve `due.no_longer_match()` çağırır; bunlar her site için stok varlık zaman çizelgeleri (`Presence.of_units`), tüm `Report`'lar, tüm `HarvestRecord`/`EscapeRecord` (movement prefetch'leriyle) ve sağlık olaylarını sınırsız okur. Aynı hesap şirket genel bakış sayfasında (`overview_upcoming`) `reports.view_report` sahibi her kullanıcı için her ana sayfa yüklemesinde de çalışır. Sonuç önbelleklenmez; `?q=`/`?page=2` isteği de yeniden hesaplar.
- Kanıt: `owed = due.due()` (resources.py:168); `'upcoming': overview_upcoming(request.user)` (config/views.py:26); `for report in Report.objects.filter(corrects__isnull=True):` (due.py:172).
- Öneri: Hesabı istek içi/kısa süreli önbellekle; ana sayfada yalnızca özet sayım hesapla; `_existing` ve harvest/escape okumalarını dönemle sınırla.

### F-064 GET isteği yazma yapıyor: görev listeleri ve genel bakış `materialise_due()` çağırıyor

Önem: **Orta** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-5`
- Dosyalar: `tasks/resources.py:91-92`, `tasks/resources.py:225-226`, `tasks/views.py:138-142`, `tasks/services.py:256-262`
- Açıklama: Görev listesi, tekrarlayan görev listesi ve üretim genel bakışı kutucukları her açılışta `materialise_due()` ile yeni görev satırı, kontrol listesi satırı, atama ve denetim kaydı yazıyor. Yalnızca "okuma" izni olan bir kullanıcının GET'i bile veritabanına yazar (`created_by` boş, denetim kaydı `user=None`). Bir serinin üretimi hata verirse (örn. unique ihlali) sayfa tamamen 500 olur. Eşzamanlı GET'ler seri satırı kilidinde sıraya girer (bu iyi) ama her sayfa açılışında kilit/yazma maliyeti oluşur. Dosyanın kendisi bunu belgelemiş (`generate_tasks` komutu da var), yani bilinçli ama yan etkili GET.
- Kanıt: `services.materialise_due()` doğrudan `filter_list` ve `overview_tiles` içinde.
- Öneri: Üretimi `generate_tasks` zamanlanmış komutuna bırakın veya GET'te yalnızca bayat olduğunu belirleyip istek dışı bir tetikleyiciyle çalıştırın; hata durumunda sayfayı düşürmeyin.

### F-065 Soft delete zincirinde kilitsiz alt kayıtlara tam-satır `save()`: eşzamanlı düzenleme sessizce ezilir, `version` çakışır

Önem: **Orta** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-1`
- Dosyalar: core/softdelete.py:174-185, core/models.py:53-59, core/softdelete.py:99-115, core/crud.py:775-780
- Açıklama: `DeleteView.post` yalnızca silinen kökü `select_for_update` ile kilitler. `plan_delete` alt kayıtları (CASCADE ve `deleted_with` ile planlanan DO_NOTHING çocukları) kilitsiz `model.objects.filter(...)` ile okur; `execute` bunları `record.soft_delete(user)` ile siler. `soft_delete` `self.save()` (tüm sütunlar) yazar ve `version += 1`'i bellekteki eski değerden hesaplar. Plan ile yürütme arasında başka bir işlem alt kaydı değiştirirse (ör. görev başlatma/tamamlama, formdan düzenleme) bu değişiklik eski değerlerle ezilir ve versiyon sayacı geri/çakışık gider. `detach` ise `update_fields` kullandığı için bu sorun yok; yalnızca soft_delete yolu etkilenir.
- Kanıt: `record.soft_delete(user)` (softdelete.py:180) → `self.version += 1; self.save()` (models.py:57-59); çocuklar `list(model.objects.filter({link: obj}))` (softdelete.py:110), kilit yok.
- Öneri: Plan çocuklarını yürütmeden önce `select_for_update` ile yeniden oku (pk sırasıyla) ya da `soft_delete`'i `update_fields=['is_deleted','deleted_at','deleted_by','updated_by','version','updated_at']` ile yaz ve versiyonu `F('version')+1` ile artır.

### F-066 Sert silme (hard delete) kullanan yerler audit ile kurtarılamaz

Önem: **Orta** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-10`
- Dosyalar: tasks/services.py:267-271, reports/services.py:130-138, 169-174, core/crud.py:782-785, farm/feeding/protocols.py:65, farm/forms/equipment.py:186, experiments/services.py:231,444, core/crud.py:364
- Açıklama: AuditedModel olmayan satırlar (DueClosure, OutsideDutyDone, bazı RowList satırları, protokol bantları, ekipman-sistem bağları, deney yerleşimleri) fiziksel silinir. Audit satırı yalnızca etiket metni yazar; kayıt geri getirilemez. Ekipman-sistem bağlarında `_save_m2m` tüm bağları silip yeniden oluşturur; silinmiş sistemlerin bağlarının da kaybolduğu kodda açıkça yazılı (feature olarak) ama bu, silinmiş sistem geri getirilince bağın geri gelmeyeceği anlamına gelir; README:162 ise "Saving the equipment drops its links to deleted systems" diyerek bunu kabul eder.
- Kanıt: `closure.delete()`, `record.delete()`, `self.instance.system_links.all().delete()`.
- Öneri: Bu kayıtlar için "kurtarılamaz" olduğunu belgeleyin; kritik olanlarda (rapor kapanışları) yumuşak silme veya silinen değerleri audit'e tam yazma.

### F-067 Silinen kaydı geri getirmek yalnızca kaydın kendisini geri getirir; CASCADE ile silinen çocuklar elle geri getirilmeli

Önem: **Orta** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-5`
- Dosyalar: core/softdelete.py:185-203 (restore), 168-182 (execute), core/admin.py:39-53
- Açıklama: `execute` CASCADE çocuklarını kendi kayıtlarıyla siler; `restore` ise "Only the record itself returns, not what was deleted with it" der. Admin eylemi yalnızca seçilen kayıtları geri getirir; hangi çocukların birlikte silindiğine dair bir bağ (silme grubu/aynı `deleted_at` ile eşleme/işlem kimliği) tutulmaz. Yönetici, bir sistemi geri getirdiğinde silinen alt kayıtları tek tek bulmak zorundadır; `deleted_at` aynı olmadığı için (her kayıt kendi `timezone.now()`'ını alır) toplu bulma da güçtür.
- Kanıt: `soft_delete` her kayıtta ayrı `timezone.now()`; `restore(record, user)` tek kaydı işler; docstring'de açık beyan.
- Öneri: Silme işlemine ortak `deletion_batch` kimliği/zaman damgası ekleyin; restore bu gruptaki kayıtları isteğe bağlı birlikte geri getirsin ve ne getirildiğini kaydetsin.

### F-068 AuditLog'dan "geri al" (değişiklik geri alma) yok; değerler görüntü metni olarak saklanır

Önem: **Orta** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-7`
- Dosyalar: core/audit.py:78-104, core/models.py:105-115
- Açıklama: Güncelleme geçmişi `{etiket: [eski, yeni]}` olarak tutulur ama değerler `str(...)`/yerelleştirilmiş görünüm metni, FK'lar için `str(nesne)`, ondalıklar biçimli metin, özel (private) metinler yalnızca HMAC özeti ("Private text"). Bu yüzden audit log bir kaydı önceki sürüme döndürmek veya veritabanı yedeği olmadan kaybolan bir alanı kurtarmak için kullanılamaz. Düzenleme (UPDATE) hatasında geri almanın tek yolu elle yeniden girmektir.
- Kanıt: `_display()` FK için `str(value)`; `snapshot(..., private=...)` metni asla saklamaz.
- Öneri: Belgeleyin ki audit log kurtarma kaynağı değildir; kritik modeller için sürüm tablosu/ham değer anlık görüntüsü düşünün.

### F-069 Değiştirilemezlik yalnızca satır düzeyi UPDATE/DELETE tetikleyicisine dayanıyor: TRUNCATE, DROP/DISABLE TRIGGER ve sahte INSERT engellenmiyor; uygulama DB sahibiyle bağlanıyor

Önem: **Orta** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-1`
- Dosyalar: core/migrations/0003_audit_log_append_only.py:4-14, core/models.py:154-157, config/settings.py:110-117, docker-compose.yml:7-10, monitoring/tests/test_templates_db.py:121-125
- Açıklama: Tetikleyici `BEFORE UPDATE OR DELETE ... FOR EACH ROW`; `TRUNCATE` (satır tetikleyicisi çalışmaz), `ALTER TABLE audit_log DISABLE TRIGGER` veya `DROP TRIGGER` korunmuyor. Uygulama `DB_USER` (varsayılan `balik`) ile bağlanıyor; docker-compose'ta bu kullanıcı `POSTGRES_USER`, yani veritabanı sahibi ve superuser. Dolayısıyla uygulama kodunda (ör. SQL enjeksiyonu, ele geçirilmiş süreç) veya DB'ye erişimi olan biri log'u sessizce silebilir. `AuditLog` docstring'i "platform yöneticisi bile değiştiremez" diyor; bu iddia DB sahibi için doğru değil. Test kodu TRUNCATE'in tetikleyiciyi atladığını zaten kullanıyor (testlerde serileştirilmiş geri alma).
- Kanıt: `CREATE TRIGGER trg_audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW` (0003:11-13); `TRUNCATE monitor_card_templates CASCADE` "no row trigger" yorumu (test_templates_db.py:121-125); `'USER': os.environ.get('DB_USER', 'balik')` ve `POSTGRES_USER: ${DB_USER:-balik}`.
- Öneri: Üretimde uygulama için ayrı, tablo sahibi olmayan bir rol kullan (audit_log üzerinde yalnızca INSERT/SELECT, `REVOKE TRUNCATE, UPDATE, DELETE`); ek olarak `BEFORE TRUNCATE ... FOR EACH STATEMENT` tetikleyicisi ve olay tetikleyicisi (event trigger) ile DDL'i izle; docstring'i gerçek garantiyle hizala.

### F-070 Kimlik doğrulama olayları loglanmıyor: giriş, hatalı giriş, çıkış, şifre sıfırlama/değiştirme

Önem: **Orta** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-3`
- Dosyalar: config/urls.py:18-31, core/resources.py:61-69, core/forms.py:77-118
- Açıklama: Projede `user_logged_in`, `user_login_failed`, `user_logged_out` sinyallerini dinleyen kod yok; şifre sıfırlama ve değiştirme Django'nun stok görünümleriyle yapılıyor ve log yazmıyor. Kullanıcı oluşturma/değiştirme (alanlar, roller, `is_active`) loglanıyor, ama bir hesabın şifresinin ne zaman sıfırlandığı veya brute-force denemeleri hiçbir yerde kayıtlı değil. Süper kullanıcı oluşturma/yetki değişikliği (shell, `createsuperuser`) de log dışı (`is_superuser` formda yok, "platform admin status is not set here").
- Kanıt: `grep user_logged_in|user_login_failed|user_logged_out` sonucu boş; `path('accounts/', include('django.contrib.auth.urls'))` (urls.py:31); `PasswordResetView.as_view(form_class=PasswordResetForm)` (urls.py:29).
- Öneri: Üç oturum sinyali ve `password_changed`/reset tamamlanması için `audit.record` (kullanıcı, IP olmadan en azından olay) yaz; hatalı girişleri hız sınırı/izleme ile birlikte logla.

### F-071 Hard delete edilen kayıtlar log'a değerleri olmadan düşüyor (rol, kapatılmış rapor, dış görev kaydı, planlı görev)

Önem: **Orta** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-4`
- Dosyalar: core/crud.py:781-785, reports/services.py:132-138, reports/services.py:168-174, tasks/services.py:265-271, core/audit.py:175-176, docs/audit/findings/11-data-modify.md (11-5)
- Açıklama: `record_delete(user, instance)` `changes` vermediği için `{}` yazar. Soft delete olmayan modellerde (Rol/`Group`, `DueClosure`, `OutsideDutyDone`, planlı `Task`) satır gerçekten silindiği için log'da yalnızca tür ve etiket kalır; silinen rolün izinleri, kapatma gerekçesi (`reason`), dış görev tarihi/referansı, görevin içeriği kurtarılamaz. 11 numaralı bulgu notu "silinen rolün izinleri audit'te snapshot ile kayıtlı" diyor, kodda bu doğru değil (crud.py:784 snapshot geçmiyor). Karşıt örnek: `hr/services._write_cell` silmeden önce `before` değerlerini `[value, None]` olarak yazıyor, yani kalıp var ama uygulanmamış.
- Kanıt: `audit.record_delete(request.user, obj, entity_type=r.entity_type()); obj.delete()` (crud.py:784-785); `audit.record(user, AuditLog.Action.DELETE, closure, entity_type=..., label=...)` + `closure.delete()` (reports/services.py:136-138); `audit.record_delete(user, task); task.delete()` (tasks/services.py:270-271).
- Öneri: Hard delete yollarında silmeden önce `r.recorded(obj)` / snapshot'ı `[değer, None]` olarak yaz (jenerik `DeleteView`'da tek yerde çözülür), `DueClosure`/`OutsideDutyDone` için de aynısını yap.

### F-072 Rol/izin oluşturma ve toplu yazma yolları log dışı: `hr_roles` komutu ve `seed_hr_demo`

Önem: **Orta** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-6`
- Dosyalar: hr/roles.py:38-46, hr/management/commands/hr_roles.py:11, hr/management/commands/seed_hr_demo.py:60-77, farm/equipment_types.py:217-225
- Açıklama: `roles.create()` `Group.objects.get_or_create` + `group.permissions.set([...])` ile rol ve izinlerini audit satırı yazmadan oluşturur; uygulamanın en hassas verisi olan izin atamaları bu yolla log'suz verilebilir. `seed_hr_demo` bilinen şifreli hesaplar, roller ve İK kayıtları açar (yalnızca `DEBUG` açıkken çalışıyor, bu iyi bir koruma). `EquipmentType` kataloğu migration'la `update_or_create`/`.update(is_active=False)` yapılır (referans veri, bilinçli). Genel kural: audit yalnızca `crud`/servis yollarında var, model düzeyinde zorlama yok.
- Kanıt: `group.permissions.set([permission(name) for name in preset.permissions])` (roles.py:44) çevresinde `audit` çağrısı yok.
- Öneri: `roles.create()` içinde grup ve izin özeti için `audit.record_create(None/"system", group, ...)` yaz (RoleResource.snapshot yeniden kullanılabilir).

### F-073 `critical` işareti yalnızca handling uyarısı onayında kullanılıyor; kapasite aşımı ve yüksek yemleme onayları normal kalıyor; severity'yi okuyan alarm yok

Önem: **Orta** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-7`
- Dosyalar: farm/stock/services.py:174-177, farm/stock/services.py:493-495, farm/health/services.py:208-214, farm/feeding/services.py:66-77, core/models.py:146-152, core/views.py:50-52
- Açıklama: `AuditSeverity` açıklaması "balık veya gıdayı koruyan uyarının üstünden geçmek" diyor ve "sonraki alarmlar bunu okur" diyor. Kodda tek `critical` üretim yeri handling (açlık/ilaç bekleme) onayı: `critical = assessment is not None and bool(assessment.warnings)` ve tedavi için `checked.warnings`. Aynı türde bilinçli aşımlar, `over_capacity_ack` (stok operasyonu) ve `high_rate_ack` (yüksek yemleme oranı), log'da `normal` kalıyor; `over_capacity_ack` yalnızca değişiklik listesine ekleniyor. Ayrıca `severity` alanını okuyan hiçbir alarm/rapor yok; yalnızca etkinlik logu rozeti ve filtre var (grep: models, views, template). Kritik bir işlemin void'i (VOID satırı) normal yazılıyor, aşılan uyarıyla bağı log'da kopuyor.
- Kanıt: `critical = assessment is not None and bool(assessment.warnings)` (stock/services.py:493); `operation.over_capacity_ack = True; operation.save(update_fields=['over_capacity_ack'])` (stock/services.py:174-176); `record.high_rate_ack = True` (feeding/services.py:72).
- Öneri: Hangi onayların `critical` sayılacağını tek bir tabloda tanımla (kapasite aşımı, yüksek yemleme dahil mi karar ver), void'in aşılan satıra bağlandığını belirt; "sonraki alarmlar" gerçekleşene kadar docstring'i "henüz okunmuyor" şeklinde düzelt.

### F-074 Veri migration'ları canlı uygulama kodunu import ediyor (tekrarlanabilir değil)

Önem: **Orta** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-2`
- Dosyalar: farm/migrations/0007_equipment_types.py:3,15, farm/migrations/0019_water_points.py:27, farm/water/points.py:18-30, farm/equipment_types.py:217
- Açıklama: farm 0007 `farm.equipment_types.sync` içinde GÜNCEL `TYPES` kataloğunu yazar; katalog sonradan değişince taze kurulumda 0007 bugünün kataloğunu yazar (docstring de "sonradan değişiklik aynı sync'i çağıran yeni migration ile gelir" diyor), tarih içindeki şema ile uyumsuz alan eklenirse eski migration kırılır. farm 0019 `farm.water.points.template_for`'u import eder; bu modül canlı `farm.models.water_point` ve `Tank.Kind` import eder, bu modüller yeniden adlandırılırsa/taşınırsa tüm migration yükleyicisi (import anında) kırılır. Ayrıca `sync` her çalışmada `is_active=True` zorlar ve yönetici düzenlemelerini `update_or_create` ile ezer.
- Kanıt: 0007:3 `from farm.equipment_types import sync`; 0019:27 `from farm.water.points import template_for`; points.py:36 docstring "migration farm/0019 reads it ... so keep its shape" (kırılganlık bilinen ama kodla korunmuyor).
- Öneri: Migration içinde veriyi dondurulmuş sabit olarak kopyalamak; en azından import edilen modüllerin kararlı API'sini test ile sabitlemek.

### F-075 reports 0005: kullanıcısı bilinmeyen olaylar migration'ı durduruyor (veri bağımlı başarısızlık) ve geri alma audit kayıtlarını bırakıyor

Önem: **Orta** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-9`
- Dosyalar: reports/migrations/0005_notified_moved_into_notices.py:52-70,97-118,119-122
- Açıklama: Kullanıcısı (AuditLog, updated_by, created_by) çıkarılamayan her `authority_notified_at` olayı `RuntimeError` ile tüm migration'ı durduruyor; prod'da bu veri bir dağıtımı bloklar (kullanıcı silinmişse tüm üç alan NULL olabilir: FK SET NULL). Hata mesajı yönlendirici ama çözüm elle SQL gerektirir (alan düşürülmeden önce). Geri alma `format_version=0` ile ayırt edilen raporları ve snapshot'ları siliyor (trigger'ları geçici devre dışı bırakarak) ama yazılan `AuditLog` kayıtları kalıyor (docstring'te belirtilmiş) — geri-ileri döngüde audit'te çift kayıt oluşur. Ayrıca `run_before` ile farm 0024 sıralanıyor: farm 0024 artık dolaylı olarak reports 0004/0005'e bağımlı, farm'ın reports'a ters bağımlılığı mimari olarak sıkı.
- Kanıt: 0005:52-70 (`unknown` -> `RuntimeError`), 112 `ALTER TABLE ... DISABLE TRIGGER`, 119-122 `run_before`.
- Öneri: Bilinmeyen kullanıcı için sistem kullanıcısı/atlama seçeneği; `DISABLE TRIGGER`'ın try/finally ile sarılması (başarısızlıkta transaction zaten geri alır, yine de açık olsun).

### F-076 audit_log tetikleyicisi TRUNCATE'i engellemiyor

Önem: **Orta** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-1`
- Dosyalar: core/migrations/0003_audit_log_append_only.py:4-14, reports/migrations/0002_filed_reports_frozen.py
- Açıklama: Değişmezlik `BEFORE UPDATE OR DELETE ... FOR EACH ROW` tetikleyicisiyle sağlanıyor; `TRUNCATE audit_log` (ve donmuş rapor tabloları) satır tetikleyicisini çalıştırmaz. Tablo sahibi/süper kullanıcı tüm geçmişi tek komutla silebilir. `reverse_sql=DROP` de tetikleyiciyi kaldırır.
- Kanıt: `CREATE TRIGGER trg_audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW` (0003:11-13); TRUNCATE için ifade düzeyi tetikleyici yok.
- Öneri: `BEFORE TRUNCATE ... FOR EACH STATEMENT` tetikleyicisi ekle; uygulama rolünden TRUNCATE/DROP yetkisini al.

### F-077 `reopen` ve `undo_duty_done`: kilitsiz silme + önce audit yazma; çift tıklamada iki DELETE audit satırı

Önem: **Orta** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-4`
- Dosyalar: reports/services.py:131-139, 168-175
- Açıklama: İkisi de satırı kilitlemeden, mevcut olup olmadığını yeniden doğrulamadan önce DELETE audit kaydı yazıp sonra `delete()` çağırıyor. İki eşzamanlı istek ikisi de audit satırı yazar; ikinci `delete()` 0 satır etkiler ama hata vermez. Audit'te gerçekte olmayan ikinci bir silme görünür.
- Kanıt: `audit.record(..., AuditLog.Action.DELETE, closure ...)` ardından `closure.delete()` (136-138); aynı kalıp 172-174.
- Öneri: `select_for_update` ile satırı yeniden oku, yoksa sessizce dön; `delete()` dönüş sayısı 0 ise audit yazma.

### F-078 Defter satırlarının değişmezliği ve "stok negatif olmaz" kuralı yalnızca uygulama katmanında

Önem: **Orta** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-1`
- Dosyalar: farm/models/stock.py:259-260, 311-312; inventory/models.py:340-343; farm/models/feeding.py:83; core/migrations/0003_audit_log_append_only.py; reports/migrations/0002_filed_reports_frozen.py
- Açıklama: Docstring'ler "satırlar asla düzenlenmez, operasyon void edilir" ve "stok hiçbir günde negatif olmaz" diyor; ancak veritabanında `stock_movements`, `stock_operations`, `inventory_lines`, `inventory_operations`, `feeding_records` için UPDATE/DELETE'i engelleyen tetikleyici yok (tetikleyiciler yalnızca audit_log, regulatory_report*, experiment tasarımı, hr, monitoring'de). Zaman çizgisi kuralı (fold) tamamen Python'da; DB, ardışık satırların toplamının negatif olmasını reddedemez. Elle düzenleme/bug, `check_stock` çalıştırılana dek fark edilmez; void ise `is_deleted` soft-delete olduğundan geçmişi DB düzeyinde de değiştirilebilir.
- Kanıt: Migrasyonlarda `CREATE TRIGGER` yalnızca core/0003, experiments/0002, hr/0001+0005, monitoring/0002, reports/0002+0003 dosyalarında; stock/inventory migrasyonlarında yok. Sabit satır sayısı kuralları (`_operation_problems`, farm/stock/integrity.py:28-70) yalnızca tarayıcıda.
- Öneri: En azından stock_movements/inventory_lines için satır UPDATE'ini (operation_id hariç değişmez alanlar) reddeden trigger; `check_stock`/`check_inventory` zamanlanmış çalıştırma veya CI/izleme kancası.

### F-079 Silme ile geri yükleme asimetrik: kaskadla silinen alt kayıtlar geri gelmiyor

Önem: **Orta** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-4`
- Dosyalar: core/softdelete.py:111-117, 139-143, 189-205; core/crud.py:764-781
- Açıklama: `execute` kaskad (CASCADE) çocukları soft-delete eder (Site -> StorageLocation, ProductionDepartment -> Tank, System, Experiment alt tabloları ...), ama `restore` yalnızca kaydın kendisini geri getirir ("only the record itself returns"). Bir üretim departmanı silinip geri yüklendiğinde üniteleri silinmiş kalır; ünite kodları arada alınmışsa tek tek geri yüklenemeyebilir. Silinmiş üniteye bağlı DO_NOTHING geçmiş (stok satırları, besleme) görünmez kalır; `_follow_status` "unit is deleted and would hold fish again" ile void'i de engelleyebilir. Ayrıca kaskad çocuklar `select_for_update` ile kilitlenmeden (yalnızca ana nesne kilitli, crud.py:770) bayat nesneyle `save()` edilir (tam satır yazımı, softdelete.py:179-181).
- Kanıt: softdelete.py:191 "Only the record itself returns, not what was deleted with it."; `soft_delete` -> `self.save()` (core/models.py:49-55) tüm alanları yazar.
- Öneri: Silme günlüğünden "birlikte silinenler" setini kaydet ve geri yüklemede önerisi sun; çocuklarda `save(update_fields=[...])` veya kilit.

### F-080 Tek sıcaklık sütunlu besleme tablosu fiilen oran üretmiyor (yalnızca tam eşleşen sıcaklıkta)

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-1`
- Dosyalar: farm/feeding/ration.py:74-86, farm/forms/feeding_protocol.py (`parse_temperatures`)
- Açıklama: `parse_temperatures` en az bir sütunu kabul ediyor, ama `sfr_at` tek sütunlu tabloda sıcaklık sütundan farklıysa `None` (OUTSIDE_TABLE) dönüyor. Satır 86'daki "a table of one column" yorumu, tek sütunlu tablonun sabit oran verdiğini ima ediyor; oysa o satıra yalnızca `T == cells[0].temperature_c` iken ulaşılıyor. Sabit SFR'lı basit bir protokol tanımlayan kullanıcı, ölçülen sıcaklık (ör. 12.35) sütunla (12.0) tam eşit olmadıkça her gün "tablo dışı, ration yok" görür; projeksiyonda da üst sınır (cap) uygulanmaz, yem olduğu gibi büyüme sayılır.
- Kanıt: `if not cells or temperature_c < cells[0].temperature_c or temperature_c > cells[-1].temperature_c: return None` (ration.py:76); `for low, high in zip(cells, cells[1:])` tek hücrede boş döner; son satır yalnızca eşitlikte erişilebilir (ration.py:86). Form: "Give at least one temperature column." `farm/tests/test_protocols.py` içinde tek sütun testi yok.
- Öneri: Ya en az iki sütun zorunlu kılın (form + doğrulama mesajı), ya da tek sütunlu tabloyu sabit oran olarak okuyun; yorumu ve testi buna göre düzeltin.

### F-081 "%10 üstü günlük yem" onayı günlük toplamı değil tek kaydı kontrol ediyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-2`
- Dosyalar: farm/feeding/services.py:64-72, config/settings.py:221
- Açıklama: Hata mesajı "more than %(limit)s %% a day is unusual" diyor ve kural günlük oran olarak tanımlı; ama oran yalnızca bu kaydın `amount_kg` değeri / defter biyokütlesi olarak hesaplanıyor, o gün aynı ünitenin önceki kayıtları hesaba katılmıyor. Günde 5 kayıt x %4 = %20 hiçbir onay istemeden girilebilir; öte yandan tek seferde girilen %11 onay ister. Kural bu hâliyle asıl hedefi (gram yerine kilo yazma gibi hatalar) kısmen yakalar, ama gün içinde parçalı fazla yemlemeyi yakalamaz.
- Kanıt: `rate = 100 * amount_kg / book.biomass_kg` / `if rate > settings.FEEDING_ACK_PERCENT:` (services.py:64-65); aynı günün kayıtları sorgulanmıyor.
- Öneri: Oranı `bugünün mevcut kayıtları + yeni kayıt` toplamı üzerinden hesaplayın (kilitli ünite içinde), ya da mesajı "tek kayıt" olarak düzeltin.

### F-082 Deniz biti sayfasında süzgeç "site ortalaması"nı ve limit aşımını bozuyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-1`
- Dosyalar: `farm/health/views.py:257-285`, `farm/health/read.py:422-437`, `templates/farm/lice_list.html:51-56`
- Açıklama: `lice_counts` görünümü, `site/unit/from/to` süzgeçleriyle daraltılmış sayım kümesini doğrudan `read.lice_weeks(counts)` fonksiyonuna verir. `LiceWeek.average` bir sitenin ortalamasını "sayımı olan birimlerin ortalamalarının ortalaması" olarak hesapladığı için, bir birime (veya tarih aralığına) süzülmüş sayfa tek bir kafesin değerini "site ortalaması" ve "Limitin üzerinde" rozeti olarak gösterir. Süzgeç tek kafesi seçtiğinde site limitinin aşıldığı gizlenebilir veya olmayan bir aşım gösterilebilir.
- Kanıt: `views.py:285` `weeks = read.lice_weeks(counts)[:LICE_WEEKS]` ve `_filtered_counts` (257-278) `counts` üzerinde `unit` ve `date` süzgeci uygular; `read.py:425-434` yalnızca verilen sayımlardan hafta kurar.
- Öneri: Haftalık site ortalamasını süzgeçsiz (yalnızca site) sayım kümesinden hesapla; süzgeç yalnızca alttaki sayım listesini daraltsın.

### F-083 İlaç türü ile tedavi nedeni bağlı değil: bit ilacıyla girilen tedavi haftalık bit raporundan düşebilir

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-2`
- Dosyalar: `farm/health/services.py:97-116`, `reports/compute/lice.py:44-49`, `farm/models/health.py:340`
- Açıklama: Haftalık Mattilsynet bit raporu yalnızca `reason=SEA_LICE` olan tedavileri alır. `_check_medicine` ise ilacın `kind` (örn. `LICE`) değerini tedavi `reason` ile eşlemez; yalnızca aşı/aşılama ve uygulama yöntemi kontrol edilir. Bir bit ilacı `reason=PARASITES` veya `OTHER` ile girilirse tedavi raporda yer almaz, yasal bildirim eksik kalır; tersine antibakteriyel ilaç `SEA_LICE` nedeniyle girilirse raporda "etken madde yok" sorunu çıkar. Termal/mekanik/tatlı su yöntemlerinde de neden `SEA_LICE` seçilmezse aynı düşme olur.
- Kanıt: `lice.py:46` `Treatment.objects.filter(reason=TreatmentReason.SEA_LICE, ...)`; `services.py:115` yalnızca `medicine.is_vaccine != (reason == VACCINATION)` kontrolü var.
- Öneri: `Medicine.kind == LICE` ise nedeni `SEA_LICE` zorunlu kıl (veya en azından uyarı ver); rapor tarafında bit ilacı kullanan ama nedeni farklı tedaviler için "rapora girmedi" uyarısı üret.

### F-084 İlaç withdrawal altındaki balığın harvest'i yalnızca uyarı ile geçiliyor, ayrı yetki yok

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-2`
- Dosyalar: farm/handling/check.py:26-29, farm/stock/services.py:35-41, farm/forms/stock.py:92-100, config/access.py:35
- Açıklama: Withdrawal ve açlık (fasting) uyarıları "owner decision: warn, never block" ile engellemiyor; `add_stockoperation` izni olan herkes kutuyu işaretleyerek harvest kaydedebiliyor. Harvest için ayrı bir izin/ikinci onay yok; mortalite kaydı ile aynı yetki (`farm.StockOperation` add). Onay satırı saklanıyor ve audit kaydı critical işaretleniyor (hafifletici).
- Kanıt: check.py:26 "Nothing is blocked (owner decision)"; access.py:35 `Area(_('Production units'), 'farm.StockOperation', actions=('view','add','delete'))`; forms/stock.py:97 "Fish under a medicine withdrawal must not go to food. Going on is stored ...". - Etki: gıda güvenliği/düzenleyici risk; yanlışlıkla veya baskıyla yasaklı dönemde kesim kaydı oluşabilir (kayıt gerçekle birlikte slaughter raporlarını da besler).
- Öneri: withdrawal aşımı için ayrı bir izin (ör. `override_withdrawal`) veya ikinci kişi onayı; en azından uyarıyı veteriner/yönetici rolüne bağlayın.

### F-085 Planlı kesim (slaughter) raporu, planın haftasından/tesisinden farklı gerçekleşen harvest'i çift veya "plansız" sayıyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-3`
- Dosyalar: reports/compute/slaughter.py:37-63
- Açıklama: `items_of` yalnızca `date` değeri haftada olan plan kalemlerini alır; `unplanned_of` ise `planned` kümesini yalnızca o haftanın kalemlerinden kurar. Bir plan kalemi W haftasına tarihli iken harvest W+1'de gerçekleşirse (kalem `operation` ile bağlı), W raporunda plan kalemi, W+1 raporunda aynı operasyon "planlanmamış" olarak (ağırlıklı kg ile ve "late" uyarısıyla) yeniden listelenir. Aynı durum plan tesisi X, gerçek tesis Y olduğunda da olur.
- Kanıt: slaughter.py:48 `planned = {item.operation_id for item in items if item.operation_id}`; :50-52 harvest operasyonları `.exclude(pk__in=planned)`. - Etki: aynı balık iki raporda (planlı + plansız) kg olarak görünür; gerçek harvest kg'ı ile plan kg'ı birbirine karışır.
- Öneri: `unplanned_of` için plan kalemlerinin tarihten bağımsız `operation_id` kümesini (tüm tesis/hafta) dışlayın; kayma durumunda uyarı üretin.

### F-086 Biyokütle raporu "gutted" seçilebiliyor ama sistem yalnızca round (canlı) ağırlık tutuyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-4`
- Dosyalar: reports/compute/biomass.py:88-89, reports/models.py:21-25, farm/forms/stock.py:544-548, docs/regulatory-reports.md (OUR-18)
- Açıklama: HarvestForm `measured_weight_kg` "live weight ... before bleeding and gutting" olarak girilir. Rapor `harvest_condition` için 'gutted' seçildiğinde aynı round kg değerleri "slaughter_weight_kg" olarak 'gutted' etiketiyle yazılır; dönüştürme/uyarı yok.
- Kanıt: biomass.py:88-89 `'slaughter_weight_kg': text(line.kilos, 1), 'condition': condition or None`; models.py:24 `GUTTED = 'gutted'`. - Etki: yanlış etiketli düzenleyici bildirim (gutted ağırlık round'dan ~%10-20 düşük olmalı).
- Öneri: 'gutted' seçimini, kesim sonucu (SlaughterResult) modellenene kadar engelleyin veya açık bir uyarı/dönüşüm katsayısı ekleyin.

### F-087 Sayım düzeltme (count correction) operasyonu yok; ilgili neden değerleri ve rapor eşlemesi ölü kod

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-5`
- Dosyalar: farm/models/stock.py (AdjustmentReason), farm/stock/integrity.py:154-158, farm/stock/services.py:713-725, reports/compute/biomass.py:28-33,
- Açıklama: docs/regulatory-reports.md:321,873 Sayım düzeltmesi yalnızca `record_escape` (neden `escape`) ve harvest'in "unaccounted loss" satırı ile yazılıyor. `COUNT_CORRECTION` ve `OTHER` nedenleri için hiçbir giriş yolu yok; ayrıca integrity.py bir ADJUSTMENT operasyonunu escape kaydı yoksa "problem" sayıyor. Buna rağmen rapor belgesi/kodu "count corrections -> Tellefeil" eşlemesini ve "upward correction" durumunu tarif ediyor. Hatalı sayım (31 günden eski) void penceresi nedeniyle düzeltilemiyor; tek çıkış harvest sonunda "unaccounted loss".
- Kanıt: services.py:713-725 yalnızca `AdjustmentReason.ESCAPE`; integrity.py:155-156 "a count adjustment on its own is an escape"; biomass.py:98 `-(line.kilos or ZERO)` ve :28-33 eşleme. - Etki: stok sayısı gerçeğinden sapınca (sayım hatası, sayım) düzeltme yolu yok; rapordaki "Tellefeil" kategorisi hiç dolmaz.
- Öneri: izin verilen bir sayım düzeltme operasyonu (neden, onay, log) ekleyin veya ölü nedenleri/eşlemeyi koddan ve dokümandan kaldırın.

### F-088 Bar widget'ı: alt sınırları boş limitte çubuk baştan sona "kritik" çiziliyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-1`
- Dosyalar: monitoring/cards/render.py:149-170, monitoring/tests/test_render.py:145-155, templates/monitoring/widgets/_bar.html
- Açıklama: `bar()` bantları `order` listesiyle üretiyor; listede sınır değeri `None` olan öğe "son bant, çubuğun sonuna kadar" olarak yorumlanıyor (`end = 100.0 if edge is None else at(edge)`). Ancak `None`, yalnızca son öğede değil, `critical_low`/`warning_low` boş olduğunda da ilk öğelerde geliyor. NH₃-N, TAN, nitrit, CO₂ gibi yalnızca üst sınırı olan limitlerde (modelde "Any bound may be left open") ilk öğe `('critical', None)` olup 0-100 arası tek bir kritik bant üretiyor, sonraki bantlar `end > start` koşuluyla atlanıyor. Sonuç: değer tamamen güvenli olsa bile çubuk tümüyle kritik renk/desenle çiziliyor; `aria-label` cümlesi ise doğru limitleri söylüyor (görsel ile metin çelişiyor).
- Kanıt: Aynı mantık Python'da çalıştırıldı: sınırlar `{critical_low: None, warning_low: None, warning_high: 5, critical_high: 10}`, değer 3 için çıktı `[('critical', 0.0, 100.0)]`. Mevcut test yalnızca dört sınırın da dolu olduğu O₂ limitini (`critical_low=6, warning_low=7, warning_high=12, critical_high=14`) deniyor.
- Öneri: Açık alt sınırları atlayın (None ise o bandı üretmeyin, sonraki kenara geçin); yalnızca son banda `100` atayın. Testi tek yönlü limit (yalnızca high ya da yalnızca low) için ekleyin.

### F-089 `Site.altitude` sınırsız: aşırı rakım `pressure_atm` içinde `ValueError` ile su okumasını düşürüyor; hesaplayıcı ile okuma katmanı farklı aralık kullanıyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-2`
- Dosyalar: farm/models/site.py:87, farm/forms/site.py (altitude yalnızca TextInput), farm/water/read.py:339-341, farm/water/chemistry.py:365-367, farm/water/calculation.py:36,228-229, farm/forms/water.py:427
- Açıklama: `altitude` DecimalField(max_digits=8, decimal_places=2) olup validator veya DB check yok (tipik yazım hatası: 50000 gibi). Okuma katmanı `_oxygen()` içinde bu değeri doğrudan `chemistry.pressure_atm(float(altitude))`'a veriyor; taban `1 - 2.25577e-5*h` yaklaşık 44 331 m üzerinde negatif olup `math.pow(neg, 5.25588)` `ValueError` fırlatıyor. Oksijeni olan herhangi bir örnek `Context.readings` üzerinden bu yola girdiği için su özet/geçmiş/monitoring okumaları o siteye bağlı tüm ünitelerde patlar. Ayrıca negatif rakım (örn. -500 m) okuma katmanında kabul edilip basınç 1.06 atm hesaplanırken, `offers()` ve hesaplayıcı formu 0-5000 m dışını sessizce yok sayıp deniz seviyesi (1.0 atm) kullanıyor: aynı site için O₂ % ünite sayfasında ve hesaplayıcıda farklı çıkabilir.
- Kanıt: `python3` ile `chemistry.pressure_atm(50000)` -> `ValueError: math domain error`; `pressure_atm(-500)=1.0607`, `pressure_atm(5000)=0.533`. `calculation.py:228`: `0 <= site.altitude <= ALTITUDE_HIGH` (5000). `forms/water.py:427`: `number_field(_('Altitude (m)'), 0, 5000, 0, ...)`.
- Öneri: `Site.altitude` için model validator + DB check (örn. -500..5000 ya da tek sabit) ekleyin; `pressure_atm` girdisini sınırlandırın; okuma, hesaplayıcı ve form aynı sabiti kullansın.

### F-090 Hiç limit tanımlı değilken stoklu ünite kartı sessizce "OK" kalıyor (NO_LIMIT hiçbir uyarı üretmiyor)

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-4`
- Dosyalar: monitoring/read.py:400-450, farm/water/evaluate.py:71-76, farm/models/water.py (WaterLimit docstring: "None is seeded"), farm/water/read.py:362-369
- Açıklama: Limitler tohumlanmıyor (WQ-24 kararı) ve her tür/parametre için elle girilmeli. Limit yoksa `assess()` `NO_LIMIT` döndürüyor; `state_of()` yalnızca `point.alerts` (CRITICAL/WARNING) ve key okumaların tazeliğine bakıyor, `NO_LIMIT` için ne `NOTE` ne `BLIND` üretiyor. Taze sıcaklık+O₂ ölçümü olan fakat o türe hiç limit girilmemiş bir ünite, 2 mg/L oksijenle bile yeşil "OK" kartı gösteriyor. Tek ipucu `_value.html` içindeki küçük "No limit" etiketi ve `_bar.html`'deki "no limit set for this value" yazısı (yalnızca ilgili widget varsa).
- Kanıt: `state_of` içinde yalnızca `for reading in point.alerts` döngüsü ve `_key_readings` tazelik kontrolü var; `NO_LIMIT` için dal yok. `evaluate.py:75`: `return Status.NO_LIMIT, []`.
- Öneri: Stoklu ünitede sıcaklık/O₂ için limit bulunamıyorsa kartı "not" (NOTE) ya da "blind" benzeri bir kademeye alın ve nedeni ("limit tanımlı değil") yazın; ayrıca su limiti olmayan stoklu tür/su tipi için bir kurulum denetimi/uyarısı ekleyin.

### F-091 Alarm eşikleri var ama bildirim yok; yalnızca ekrana bakan kişi görüyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-5`
- Dosyalar: templates/farm/water.html:58, monitoring/read.py:400-456, tasks/models.py:93 (yalnızca WATER_QUALITY görev kategorisi)
- Açıklama: Su sayfasının yardım metni açıkça "Nobody is alerted: critical values are shown here, not sent" diyor; messaging/tasks tarafında su durumuna bağlı hiçbir bildirim/görev üretimi yok (`grep` ile yalnızca görev kategorisi enum'unda "water" geçiyor). Ek olarak kritik bir değer tazelik süresini (O₂/sıcaklık 24 sa) aşınca `STALE` oluyor ve kart kırmızı yerine "blind" oluyor ("never red"). Yani ölçülen kritik oksijenin 25 saat sonra alarmı fiilen kalkıyor. Bu bilinçli bir MVP kararı olarak belgelenmiş olsa da, "alarm eşiği" kavramının bir alarm mekanizması olmadığı kayıt altına alınmalı.
- Kanıt: water.html:58 metni; `evaluate.py:34`'teki `RANK` sırasında STALE, CRITICAL'ın altında; `read.py:367-368` `reading.status = Status.STALE` ile kritik durumu eziyor.
- Öneri: En azından kritik değerler için bildirim (mesaj/görev) tasarımını backlog'a alın; stale-kritik değeri "blind" yerine "son bilinen kritik, X saat önce" olarak göstermeyi değerlendirin.

### F-092 Engelli/askıdaki tedarikçiden teslimat ve iade kabul ediliyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-1`
- Dosyalar: inventory/services.py:187-195, inventory/forms.py:144-154, farm/models/supplier.py:44-49
- Açıklama: `Supplier.status` ACTIVE/INACTIVE/SUSPENDED/BLOCKED. Yazma yolu yalnızca `supplier.is_deleted` ve `supplies` kategorisini kontrol ediyor; durum kontrolü yok. Form sadece etikete durum ekliyor.
- Kanıt: `_check_static` içinde `if supplier.is_deleted` dışında status bakılmıyor; `suppliers()` `Supplier.objects.filter(supplies__overlap=STOCKED)` (durum filtresi yok); `SupplierChoice.label_from_instance` yalnızca `· <status>` ekliyor.
- Öneri: BLOCKED (en az) tedarikçiden yeni teslimatı reddet; INACTIVE/SUSPENDED için uyarı ya da ayarlanabilir kural. İade için kural daha gevşek olabilir.

### F-093 İade (return), lotu getiren tedarikçiye bağlı değil

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-2`
- Dosyalar: inventory/services.py:305-308, inventory/forms.py:296-311, inventory/views.py:338-342
- Açıklama: İade herhangi bir "feed tedarik eden" tedarikçiye yapılabiliyor; lotu o tedarikçi teslim etmiş mi kontrol edilmiyor. Dialog yalnızca ilk teslimatın tedarikçisini `initial` olarak öneriyor. İade edilen miktarın teslim edilenle sınırlanması da yok (yalnız fiziksel stok sınırı).
- Kanıt: `return_to_supplier` -> `_departure(..., supplier=supplier)`; `_check_static` sadece kategori kontrolü; integrity.py:308-311 de yalnız kategori kontrol ediyor.
- Öneri: İade tedarikçisini lotun canlı teslimat tedarikçileriyle sınırla (veya uyar); integrity'e kural ekle.

### F-094 Her sayfa/diyalog yüklemesi tüm lotların tüm geçmişini fold ediyor (ölçeklenme)

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-6`
- Dosyalar: inventory/read.py:69-80, 127-148, 205-260, 338-350, inventory/views.py:221-232, 318, inventory/resources.py:80-83, inventory/fold.py:199-200,219-229
- Açıklama: `folds()` her çağrıda tüm canlı satırlar, tüm sayımlar, tüm yer/FeedingRecord geçmişini yükleyip her (site, gün) için kova sıralaması ve `_drawn_in` toplamlarıyla çözüyor (kabaca gün x kova x çekiş). Sınır yok (`site_earliest` penceresi sadece UI'da). Çağrı noktaları: overview, Stock sekmesi, her departure diyaloğu (GET ve POST), lokasyon listesi (`filter_list`), Counts sekmesi sayfa başına 20 kez `count_variances` -> 20 ayrı fold, `holds_stock` (silme engeli), `book_at`. `_counts()` ayrıca tüm sayım operasyonlarını her item için yeniden okuyor (item başına değil global liste ama her fold'a geçiyor). Overview'da ayrıca site-item başına FeedingRecord sorgusu ve lokasyon başına tüm `rows` taraması (O(L x R)).
- Kanıt: yukarıdaki satırlar; `count_variances` her sayım için `folds(items)` çağırıyor.
- Öneri: Fold sonucunu istek içinde paylaş/önbelleğe al; sayım sekmesinde tek fold; uzun vadede dönemsel kapanış (snapshot) ya da pencere.

### F-095 Unutulan clock-out: pano "yok" der, ama yeni giriş "zaten giriş yaptınız" ile reddedilir

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-2`
- Dosyalar: hr/rules.py:137-159, hr/services.py:365-380, hr/read.py:380-382
- Açıklama: `rules.status` punch penceresi dışındaki (planlanan başlangıçtan `window_minutes` öncesinden eski) punch'ları saymaz; `clock_in` ise yaşına bakmadan her açık kaydı engeller. Dünden açık kalan kayıt varsa kişi panoda NOT_IN/ABSENT görünür fakat giriş yapamaz; çıkış yaparsa kayıt `now()` ile kapanır ve süre gün(ler)ce uzar. Pano ayrıca yalnızca son 2 günlük punch'ı okur.
- Kanıt: services.py:375 `AttendanceRecord.objects.filter(employee=employee, clock_out__isnull=True).exists()`; rules.py:143 `earliest <= punch[0] < end`; read.py:380 `clock_in__gte=moment - timedelta(days=2)`; services.py:396 `clock_out = max(timezone.now(), ...)`. docs/hr-launch-checklist.md 2.4 sadece kısmen belgeler.
- Öneri: Belirli bir süreden eski açık punch'ı "düzeltme gerekli" olarak göster, otomatik kapatma veya lead'e uyarı/rozet ekle; clock_out'ta makul üst sınır uygula.

### F-096 İstihdam tarihleri (joined_on/left_on) vardiya, yoklama ve izin yazımlarında zorlanmıyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-3`
- Dosyalar: hr/services.py:183-219, 365-380, 402-418, hr/forms/roster.py:47-64, hr/forms/leave.py:75-105, hr/checks.py:15-40
- Açıklama: `plan_shifts`, `ShiftAssignmentForm`, `clock_in`, `enter_presence` ve izin formu kişinin işe giriş öncesi/ayrılış sonrası günleri reddetmez (Everyone sahibi için `scope.can_reach` kısıtlamaz). Ayrılış sonrası vardiya `align_placements` ile bir kez silinir ama sonradan yeniden eklenebilir; `checks.problems` ayrılıştan sonra plan/yoklama ve işe girişten önce plan/izin için kural içermez (yalnızca posting ve izin-after-left). Ayrılmış çalışan hesabı aktifse clock_in yapabilir.
- Kanıt: services.py:127 yalnızca ayrılışta tek seferlik silme; checks.py'de ShiftAssignment/AttendanceRecord sorgusu yok; clock_in (365-380) `left_on` kontrolü yok.
- Öneri: Servislerde `joined_on <= day <= left_on` doğrulaması ve checks.py'ye plan/yoklama/izin kontrolleri ekle.

### F-097 Başlamış onaylı izin düzeltilemez, kısaltılamaz veya iptal edilemez

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-4`
- Dosyalar: hr/services.py:278-292, hr/forms/leave.py:80-81
- Açıklama: `can_cancel` onaylı izinde `first_day <= today` ise herkese (HR dahil) False döner; form yalnızca pending düzenler. Hatalı onaylanmış/otomatik onaylı (`needs_approval=False`) bir izin başladıktan sonra silinemez/kısaltılamaz (erken dönüş, yanlış tür). Admin salt okunur olduğundan yalnızca DB müdahalesi kalır.
- Kanıt: services.py:284 `if leave_request.first_day <= today: return False`; forms/leave.py:80 `Only a pending request can be changed.`
- Öneri: Everyone sahibi için başlamış izni sonlandırma/kısaltma (logged) eylemi ekle.

### F-098 `rest_rule` etiketi hafta saati ve ardışık gün kurallarını da kapsıyor görünür ama kod sadece dinlenme için uygular

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-5`
- Dosyalar: hr/models/scheduling.py:320-321, hr/rules.py:93,97,109, hr/forms/scheduling.py:37, README.md (rules)
- Açıklama: Alan etiketi "A short rest, a long week or too many days in a row" (warn/block). `rules.py` WEEK_HOURS ve CONSECUTIVE_DAYS'i sabit `WARN` üretir; yalnızca REST_SHORT `settings.rest_rule` kullanır. Model docstring/README yalnızca dinlenmeyi "warn or block" yapar. Yönetici "Block" seçip haftalık saat ve ardışık gün ihlallerinin de engelleneceğini sanabilir.
- Kanıt: rules.py:97 `Finding(WEEK_HOURS, WARN, ...)`, 109 `Finding(CONSECUTIVE_DAYS, WARN, ...)`, 93 `settings.rest_rule`.
- Öneri: Etiketi düzelt veya kuralları ayarla bağla; hr-launch-checklist 2.1'i netleştir.

### F-099 `clock_in/clock_out` yalnızca `view_attendancerecord` ile yazma yapar

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-7`
- Dosyalar: hr/services.py:365-399, hr/roles.py:34-36
- Açıklama: Kendi punch'ını yazmak "view" yetkisine bağlı: yalnızca okuma rolü verilen (ör. denetçi) ve employee kaydı olan kullanıcı da kendi yoklamasını yazabilir. Rol matrisi okuma/yazma ayrımı bu yolda geçersiz. Kasıtlı olabilir (docstring "Needs Read on Attendance") ama matristeki "Edit/Create" semantiğinden sapar.
- Kanıt: services.py:368 `user.has_perm('hr.view_attendancerecord')`.
- Öneri: Ayrı bir "clock" izni (örn. `hr.clock_attendancerecord`) tanımla veya belgele.

### F-100 Geçmişe dönük izin ve plan değişikliği için tarih sınırı yok

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-8`
- Dosyalar: hr/forms/leave.py:83-105, hr/services.py:183-219
- Açıklama: Form `first_day` geçmişte olabilir ve `needs_approval=False` türde geçmiş tarihli izin anında "approved" olur (kimse karar vermez, `decided_by` boş). Planlar da geçmiş günler için serbestçe değiştirilir/silinir; yalnızca audit log tutar. Geçmiş vardiya, yoklama kıyaslamasının dayanağını sessizce değiştirir.
- Kanıt: forms/leave.py:102-104 `self.instance.status = APPROVED`; clean içinde `first >= today` kontrolü yok; services.plan_shifts'te geçmiş gün kontrolü yok.
- Öneri: Geçmiş tarih için ek yetki/neden alanı veya kilit penceresi.

### F-101 Planlı kesim son tarihi dört yerde dört farklı kuralla hesaplanıyor (due satırı, liste, detay, filing)

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-1`
- Dosyalar: reports/due.py:189-192, reports/services.py:83-84, reports/compute/slaughter.py:131-137, reports/compute/__init__.py:58-63, reports/resources.py:194, farm/handling/fasting.py:282-283, templates/reports/report_list.html:113
- Açıklama: Due satırı son tarihi `slaughter.deadline(...)` (oruç günü varsa daha erken) ve sonra `max(deadline, agreed)` ("sonradan kararlaştırılan kesim") ile hesaplar. Filing anında `services.submit` `compute.deadline(current)` kullanır: `agreed` yok, dolayısıyla due listesinde "gecikmiş değil" görünen bir rapor `filed_late=True` ile kaydedilebilir. Rapor listesi şablonu `report.deadline` (yalnız Perşembe kuralı, oruç ve agreed yok) gösterir; detay sayfası `compute.deadline` (oruç var) gösterir. Ayrıca `fast_of` plan kalemi `is_open` değilse (kesim yapıldı/iptal) `None` döner; kesim gerçekleştikten sonra oruç kısıtı kalkar ve son tarih Perşembe kuralına geri döner, yani aynı rapor için son tarih zamanla değişir.
- Kanıt: due.py:191-192 `deadline = max(deadline, agreed)`; services.py:83 `current.deadline_on = compute.deadline(current)`; fasting.py:282 `if not item.is_open: return None`; report_list.html:113 `report.deadline`.
- Öneri: Tek bir `deadline_for(report)` fonksiyonu (agreed dahil, yapılmış kalemlerin oruç gününü de koruyarak) due, liste, detay ve filing'de kullanılsın; filed raporlarda yalnız `deadline_on` gösterilsin.

### F-102 Rapor listesi her istekte tüm due listesini ve filed raporların kaynak parmak izini yeniden hesaplıyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-2`
- Dosyalar: reports/resources.py:168-169, reports/due.py:399-417, reports/compute/common.py:93-100, reports/views.py:48, 88, 138
- Açıklama: `filter_list` her çağrıda `due.due()` ve `due.no_longer_match()` çalıştırır (sayfalama `?page=2` dahil). `no_longer_match`, son ~1 yıldaki her filed raporun `scope`'unu sorgular; `fingerprint` her sorgunun tüm satırlarını belleğe çekip `sorted(..., key=str)` ile hash'ler (stok işlemleri, tüm geçmiş besleme kayıtları `date__lte=period.end` ile). `due()` her site için Presence, tüm HarvestRecord/EscapeRecord/HandlingPlanItem'ları (zaman sınırı yok) tarar. `overview_upcoming`, `_due_row` (kapatma bağlantısı), `outside_duties` ve `close_due` da `due.due()`'yu ayrı ayrı çağırır. Veri büyüdükçe liste ve şirket genel görünümü doğrusal+ yavaşlar.
- Kanıt: resources.py:169 `rows, changed, lines = owed.rows, due.no_longer_match(), []`; common.py:96-98 `for row in sorted(rows.values_list(*names), key=str)`.
- Öneri: Parmak izini DB tarafında toplulaştır (count + max(version)/hash agregasyonu) veya filing'de/yazmada önbellekle; `no_longer_match` sonucunu kısa süreli önbelleğe al ve yalnız ilgili sekmede çalıştır; due taramalarını `reports_from` sonrası ile sınırla.

### F-103 Deney başına yetkilendirme yok: change izni olan herkes her deneyi değiştirir

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-1`
- Dosyalar: config/access.py:100-103, experiments/models.py:401, experiments/resources.py:130,288, experiments/migrations/0002_design_frozen.py:16-17
- Açıklama: `Member` satırları (lider, öğrenci vb.) hiçbir yetki kararında kullanılmıyor. Genel `experiments.change_experiment` izni olan herkes başkasının deneyini tasarlayabilir/başlatabilir, tank bırakıp değiştirebilir, ekibi (lideri dahil) yeniden yazabilir. Başladıktan sonra ekip tetikleyiciyle korunmuyor.
- Kanıt: models.py:401 "per-experiment rights come with the permissions plan, which reads this"; access.py:100-103 "Who may do what to which experiment (its team) comes with the permissions plan"; 0002 docstring: "The team (`experiment_members`) is not the design and is not guarded."; resources.py:130 `can_start` yalnız `has_perm(change)` ve duruma bakar.
- Öneri: Plan gelene kadar belgelenmiş bilinen risk olarak izlenmeli; en azından başlamış deneyde ekip/lider değişikliği için ek kontrol veya log uyarısı.

### F-104 Başlatmanın yazdığı besleme atamaları çiftlik arayüzünde değiştirilebilir/silinebilir (korumasız, bağlantı kolonu yok)

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-2`
- Dosyalar: experiments/services.py:772-779, experiments/integrity.py:66-86, farm/feeding/assignments.py:31-90
- Açıklama: Deney atamaları yalnızca (unit, protocol, valid_from) üçlüsüyle bulunuyor; satırda deneye ait bağlantı yok, `farm` tarafında deney farkındalığı yok (grep: farm/feeding içinde yalnızca docstring anıyor). Çiftlik kullanıcısı bu satırı sonlandırır/siler veya üstüne parti-kapsamlı protokol atarsa deneyin ön-kayıtlı diyeti sessizce bozulur; yalnızca sonradan `check_experiments` / `ration_off_diet` sapması yakalar. `_end_diet` ise satır değiştirilmişse hiçbir şey sonlandırmadan geçer (boş döngü). Dokümandaki "tank üzerindeki kayıt kilidi" henüz yok.
- Kanıt: services.py:777 `ProtocolAssignment.objects.filter(unit=row.unit, batch__isnull=True, protocol=protocol, valid_from=row.from_on)`; assignments.py:39-40 satırda sadece `notes=f'{code} · {group}'`.
- Öneri: Atama satırına deney referansı/kilit işareti ya da farm tarafında deneydeki tankın atamalarını düzenlemeyi engelleyen/uyaran kontrol; `check_experiments` zamanlanmış çalışsın.

### F-105 Girdinin "reviewed" durumu yalnizca girdinin kendi alanlari degisince draft'a doner.

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-1`
- Dosyalar: knowledge/models/document.py:217-243, knowledge/forms/entry.py:173-178, knowledge/views.py:59-84
- Açıklama: Girdinin "reviewed" durumu yalnizca girdinin kendi alanlari degisince draft'a doner. Atif yaptigi Document degisince (PDF'i degistirme, baslik/yazar/yil/DOI duzenleme) girdi "reviewed" kalir; oysa review'un dayandigi kaynak, sayfa numaralari ve alinti artik gecersiz olabilir. AI ajanlari yalniz reviewed girdilerle calisacagi icin (README 2556) bu sessiz bir guven bosulugudur.
- Kanıt: entry.py:175 yalnizca `self.changed_data` (girdi formu) kontrol eder; Document.save sayfalari silip yeniden yazar (document.py:233-238) ama KnowledgeEntry'ye dokunmaz; testlerde belge degisiminin review'a etkisi yok.
- Öneri: Belge dosyasi/metni degisince bagli reviewed girdileri draft'a cevir veya girdide "reviewed_document_version" tut; en azindan dosya degisiminde uyari goster.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-106 Ajanin alintilayacagi `plain()` ve `short()` ciktisi istek dilinde gettext ile uretilir:

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-10`
- Dosyalar: knowledge/citation.py:17,66,61, locale/tr/LC_MESSAGES/django.po:538,14419
- Açıklama: Ajanin alintilayacagi `plain()` ve `short()` ciktisi istek dilinde gettext ile uretilir: "et al." / "vd." / "u.å." / "t.y." degisir. Ayni belge farkli kullanicilarda farkli atif metni verir; ajan atiflari ve denetim kayitlari dil-bagimli olur, dil sabit degildir.
- Kanıt: citation.py `gettext as _` (satir 17) ve year_of/short_authors icinde kullanim; test_languages.py:67 Turkce "Olsen vd." beklentisini kasten dogrular.
- Öneri: Ajan/log icin dilden bagimsiz (kaynak dil) `plain()` surumu; arayuz icin ceviri ayri.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-107 Tasarlanan AI akisinda eksikler:

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-14`
- Dosyalar: README.md:2543-2553, 2563-2575
- Açıklama: Tasarlanan AI akisinda eksikler: (a) PDF/belge metni ajana girdi olarak verilir ama "guvenilmeyen icerik / prompt injection" modeli ve ajanin tool yetkileri belirtilmemis; (b) ajan "taslak girdi" olarak onerir ama created_by/ajan kimligi (kim onerdi) ve ajan taslaginin insan taslagindan ayirt edilmesi yok; (c) kabul edilen Rule, girdi duzenlenip tekrar onaylandiginda yeniden dogrulanmaz: statement degisip Rule kosullari ayni kalabilir (Rule girdi surumune baglanmiyor).
- Kanıt: README Rule tablosu `entry` PROTECT ile baglanir ama entry.version saklanmaz; evaluator "reviewed girdilerin kabul edilen Rule'lari" ile calisir (satir ~2570).
- Öneri: Rule'a `entry_version` ekle, girdi degisince Rule'u "inceleme gerekli"ye cevir; belge metnini guvenilmez veri olarak isaretle; ajan taslaklarina kaynak (agent) alani ekle.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-108 Girdinin `pages`, `section`, `quote` alanlari serbest metindir;

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-4`
- Dosyalar: knowledge/models/entry.py:372-374, 444-450; knowledge/models/document.py:267-302
- Açıklama: Girdinin `pages`, `section`, `quote` alanlari serbest metindir; DocumentPage ile baglantisi yoktur. Sayfa numarasi PDF sirasi mi (number) yoksa basili etiket mi (label) belirsizdir; sayfa araligi belge page_count'unu asabilir; alinti belgenin sayfa metninde var mi dogrulanmaz. Kaynak etiketi hep "p." der, aralikta ("12-13") "pp." olmaz.
- Kanıt: entry.py:372 `pages` CharField(30) dogrulamasiz; source_label entry.py:447-448 `p. %(page)s`; DocumentPage.shown_number etiket dondurur (document.py:294-296), girdi ise ham metin. README 2593-2596 alinti dogrulamasini ajan icin "tasarim" olarak verir, insan girdisi icin yoktur.
- Öneri: pages icin bicim dogrulamasi + page_count ust siniri; alinti, belge sayfa metninde (NFKC, bosluk-katlamali) araniyorsa "dogrulanmis" isareti; PDF-numara/etiket ayrimini girdi arayuzunde netlestir.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-109 Dort goz ilkesi yok:

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-5`
- Dosyalar: knowledge/views.py:59-84, README.md:2587-2590
- Açıklama: Dort goz ilkesi yok: edit izni olan kisi kendi girdisini onaylayabilir; ayrica herhangi bir editor baskasinin onayini "Back to draft" ile geri alabilir. README bunu acik sahip karari olarak not eder, ama AI ajanlarinin "yalniz reviewed" garantisi su an tek kisiyle saglanabilir. Ayri bir "review" izni de rol matrisinde yok.
- Kanıt: views.py:59 yalniz `change` izni; DB check'i reviewed_by<>created_by icermez (entry.py:425-429).
- Öneri: Sahip karari verilene kadar reviewed_by != created_by uygula veya ayri review izni ekle.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-110 Son üye ayrılınca yetim kanal: ad sonsuza dek kilitli, geçmişe kimse ulaşamaz

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-1`
- Dosyalar: messaging/services.py:176-182, 202-208; messaging/models.py:62-64; messaging/tests/test_services.py:242-243
- Açıklama: `_keep_an_owner` yalnızca başka üye kaldıkça son sahibin ayrılmasını engeller; tek kalan üye ayrılabilir. Kanalın katılımcısı kalmaz, ama kanal `is_deleted=False` kalır; `channel_name_unique` kısmi indeksi adı canlı kanal sayılarak tutmaya devam eder. Geri getirme/silme sayfası yok (screens.py: delete=gap), `add_members` sahip gerektirir, yani kimse kanala dönemez.
- Kanıt: `if owners == [target] and (len(live) > 1 if leaving else True)`; test "the last one may go" sonrası `assertFalse(channel.participants.exists())`.
- Öneri: Son üye ayrılınca kanalı soft-delete edin (adı serbest bırakır) veya son üyenin ayrılmasını engelleyip silme akışı sunun; yönetici için yetim kanal onarımı.

### F-111 Silinen mesaj, açık sayfalarda yeniden yüklenene dek görünür; olay/poll tasarımı silme ve üyelik değişikliğini taşımıyor

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-2`
- Dosyalar: messaging/views.py:108-121; frontend/poll.ts (data-poll-append); messaging/events.py:1-14; messaging/services.py:268-275
- Açıklama: Poll yalnızca `id > after` mesajları ekler; silme ya da başkasının sayfasındaki mevcut satırın değişmesi hiçbir yoldan taşınmıyor. Planlanan push için tek olay `message_posted`; silme/üyelik olayı yok. README bunu kabul ediyor ("stays on an open page"), ancak "text is never shown again" sözüyle çelişir (hassas mesaj yanlışlıkla yazılıp silinse bile diğer üyelerde kalır). Kullanıcı kanaldan çıkarılınca sayfası bir sonraki poll'da 404 ile `gone` olur (iyi), ama mesajların DOM'da kalması sürer.
- Kanıt: `new = read.after(participant, last_id)` yalnızca yeni id; `events.py` yalnızca `message_posted` tanımlar.
- Öneri: `message_deleted`/`membership_changed` olayları ekleyin; o zamana dek poll'a `deleted_since` benzeri bir tazeleme ya da kısa aralıklı liste yenilemesi.

### F-112 Başlık: Balık içeren birim bakıma alınınca tekrar aktife dönemiyor (durum makinesi çıkmazı)

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-1`
- Dosyalar: farm/models/tank.py:488-491, farm/models/tank.py:230-240 (TRANSITIONS), farm/models/tank.py:262-263 (NEEDS_NO_FISH), farm/stock/services.py:85-86
- Açıklama: TRANSITIONS'ta MAINTENANCE yalnızca PREPARING ve INACTIVE'e gidebilir; ikisi de NEEDS_NO_FISH. Yorum "maintenance ve quarantine balıklı da olabilir" diyor. ACTIVE -> MAINTENANCE balıklıyken serbest, ama balık varken oradan çıkış yok (ACTIVE'e geçiş MAINTENANCE'tan tanımlı değil).
- Kanıt: `Status.MAINTENANCE: (Status.PREPARING, Status.INACTIVE)`; `status_blocker` NEEDS_NO_FISH + has_stock() için engeller. _follow_status da yalnızca 'balıksız -> aktif' ve 'boşalınca' kuralını uygular, maintenance'ı değiştirmez.
- Öneri: MAINTENANCE -> ACTIVE geçişini (balıklıysa) ekleyin ya da bakıma balıklı geçişi engelleyin; karar dokümante edilsin.

### F-113 Başlık: System.site değişmezliği yalnızca formda; modelde/DB'de yok, taşınırsa içindeki tank ve alt sistemler tutarsızlaşır

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-2`
- Dosyalar: farm/models/system.py:91-110, farm/forms/system.py:12, farm/models/tank.py:536-552
- Açıklama: SystemForm `fixed_after_creation=('site',)` ile siteyi kilitliyor; System.clean() site değişimini ve alt sistem (children), tank ve ekipman bağlantılarını (EquipmentSystem) kontrol etmiyor. production_department boşsa site serbestçe değiştirilebilir (programatik yol, shell/servis). Tank._check_system yalnızca tank kaydedilirken çalışır.
- Kanıt: System.clean yalnızca production_department/parent site eşleşmesini ve tank-departman uyumunu kontrol eder; hiçbir CHECK/FK site tutarlılığını DB'de tutmaz.
- Öneri: clean()'e "tank/çocuk/ekipman bağlantısı varken site değişemez" kuralı ekleyin (Tank._check_site gibi); tercihen model düzeyinde.

### F-114 Başlık: Site silinince yetim kalan departmanın siteye yeniden bağlanma yolu yok

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-3`
- Dosyalar: farm/models/production_department.py:45-47, farm/forms/production_department.py:7-60, farm/models/production_department.py:84-105, core/crud.py:155-160
- Açıklama: Site silinince departmanlar SET_NULL ile siteyi kaybeder; restore yalnızca siteyi geri getirir, departmanları yeniden bağlamaz (core/softdelete.py restore "yalnızca kayıt kendisi döner"). Form `fixed_after_creation=('site',)` yüzünden düzenlemede site alanı disabled/required=False; kullanıcı "Siteye bağla" yapamaz. Model clean() site taşımayı destekliyor ama UI erişemiyor.
- Kanıt: forms/production_department.py:7 ve crud.py:157-160. Yetim departmanın ekipmanı Equipment.clean'de "not on any site" hatası verir (equipment.py:187), sistemde seçilemez (forms/system.py:43).
- Öneri: Yetim departman için siteyi yalnız boşken atanabilir yapın; ya da site silmeyi departman varken bloklayın (soft delete'te CASCADE/PROTECT tercihi).

### F-115 Başlık: Site.status/Site.is_active hiçbir yerde okunmuyor; "Closed" yalnızca etiket

Önem: **Orta** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-5`
- Dosyalar: farm/models/site.py:29-33, 76, 116-122; farm/forms/site.py:13-24
- Açıklama: Site.delete_blockers mesajı "status'u Closed yap" diyor, ama Closed/Inactive/Maintenance bir site yeni departman, sistem, birim, stok girişi veya rapor görevinden dışlanmıyor. Ayrıca is_active ikinci bir bayrak olarak duruyor (docs SITE-10 "iki durum bayrağı" anti-pattern'i, ProductionDepartment ve System bunu kaldırmış). is_active formda yok, hiçbir yerde okunmuyor.
- Kanıt: grep `Site.Status`/`site.status`/`is_active` (site bağlamında) model dışı sıfır sonuç; reports/due.py yalnızca Site.Type kullanıyor.
- Öneri: is_active kaldırılsın; kapalı site için yeni kayıt/stoklama ve rapor kuralları tanımlansın.

### F-116 farm alt paketleri arasında paket-düzeyi döngüsel bağımlılık

Önem: **Orta** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-1`
- Dosyalar: farm/stock/services.py, farm/stock/integrity.py, farm/feeding/services.py, farm/feeding/read.py, farm/handling/check.py, farm/water/degree_days.py, farm/health
- Açıklama: stock -> feeding/handling/health ve feeding/handling/water/health -> stock yönleri birlikte var; katmanlama yok.
- Kanıt: farm/stock/services.py:59-62 (`from farm.feeding import read`, `farm.handling import check`, `farm.health import read`); farm/feeding/services.py:18 (`from farm.stock.services import ...`); farm/feeding/read.py:42 (`farm.stock.read`); farm/handling/check.py:39 (`farm.feeding.read`); farm/water/degree_days.py:28 (`farm.stock.read`). Betikle çıkarılan grafik: stock->{feeding,handling,health}, feeding->{handling,stock,water}, handling->{feeding,stock,water}, health->{feeding,handling,stock,water}.
- Öneri: stock.read/fold/dates gibi alt katmanı (ledger) ayır; services -> read yönünü tek yönlü tut; import-linter benzeri kontrol ekle.

### F-117 farm fiilen "platform" katmanı: genel yardımcılar farm altında

Önem: **Orta** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-4`
- Dosyalar: farm/stock/dates.py, farm/clocks.py, farm/forms/stock.py, farm/forms/water.py, hr/*.py, tasks/*.py
- Açıklama: Saat/gün hesabı gibi alan-bağımsız işler `farm.stock.dates`/`farm.clocks` içinde; HR ve tasks bu yüzden farm'a bağımlı. `farm.stock.dates` stok alt paketinin içinde, ama hr tarafından 11 yerde kullanılıyor. Formlar (VoidForm, DATE, DECIMAL, NOTES, SiteClockField, AcknowledgeInput) da farm.forms içinde ama inventory/experiments/reports kullanıyor.
- Kanıt: hr/scope.py:19, hr/checks.py:6, hr/services.py:15, hr/views.py:21, hr/read.py:15-18 (`site_today`, `clocks`); inventory/forms.py:16, inventory/views.py:29, inventory/screens.py:5, reports/forms.py:8, experiments/forms.py:15. Sayım: hr -> farm.stock.dates 11, inventory -> farm.stock.dates 5.
- Öneri: Zaman/saat dilimi, ortak form alanlarını `core`'a (veya ayrı `platform`/`common` app'ine) çıkar; farm'ın şişmesini azalt.

### F-118 Farm app'i aşırı büyük (şişme)

Önem: **Orta** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-5`
- Dosyalar: farm/
- Açıklama: farm ~37 bin satır py (migrations/testler dahil), diğer app'lerin her biri 1,7-8 bin satır. Üretim kodu ~21,5 bin satır; stock, feeding, water, health, handling, harvest tek app'te. Tek migration grafiği ve tek AppConfig.
- Kanıt: `wc -l` çıktısı: farm 37123, hr 8101, reports 7657, experiments 7761, core 7722; farm üretim kodu 21575 satır (farm/stock/services.py 760, farm/water/deffeyes.py 749).
- Öneri: Alt alanları (water chemistry/calculator, stock ledger, feeding) ayrı Django app'lerine bölmeyi değerlendir; önce 31-1 döngüleri çözülmeli.

### F-119 monitoring başka app'lerin view modüllerini veri kaynağı olarak import ediyor

Önem: **Orta** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-6`
- Dosyalar: monitoring/read.py, monitoring/views.py, monitoring/cards/render.py
- Açıklama: "composition only" olan monitoring, farm ve tasks'ın `views` modüllerine (sunum katmanı) ve templatetag'ine bağlı; read katmanı view katmanına bağlanıyor, bağımlılık yüzeyi geniş.
- Kanıt: monitoring/read.py:48-56 (`farm.feeding views`, `farm.harvest views`, `farm.health views`, `farm.stock views`, `farm.water views`, `tasks views`); monitoring/views.py:30 (`farm.stock.views VIEW`); monitoring/cards/render.py:13 (`farm.templatetags.water`). Ayrıca monitoring -> tasks yatay bağımlılığı (tek yatay bağ).
- Öneri: Her app'in `views` içindeki ortak sözleşmeyi (VIEW, overview_tiles) ayrı bir `contracts`/`read` yüzeyine çıkar.

### F-120 `_day(value)` tarih ayrıştırıcısı 6 yerde tekrar (ve farklı davranışlı)

Önem: **Orta** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-1`
- Dosyalar: farm/harvest/views.py, farm/health/views.py, farm/feeding/views.py, inventory/views.py, farm/resources/harvest_plan.py, core/views.py, farm/water/views.py
- Açıklama: Aynı 5 satırlık `date.fromisoformat` + `ValueError -> None` fonksiyonu birebir 5 kez kopyalanmış; `core/views.py` `strptime` + aware datetime ve `end` parametresiyle farklı semantik, `farm/water/views.py` ise `parse_date` kullanan, farklı imzalı (request, name, default) bir `_day` tanımlıyor. Aynı ad, üç farklı davranış. Ayrıca `date.fromisoformat(None)` `TypeError` verir (yalnız `ValueError` yakalanıyor), core sürümü `TypeError`'ı da yakalıyor: tutarsız dayanıklılık.
- Kanıt: farm/harvest/views.py:49, farm/health/views.py:63, farm/resources/harvest_plan.py:31, inventory/views.py:69, farm/feeding/views.py:71 (aynı gövde); core/views.py:27-31; farm/water/views.py:214-215.
- Öneri: tek bir `core` yardımcısına (ör. `core/dates.py: parse_day`) topla; aware-datetime varyantını farklı adla ayır.

### F-121 Devasa fonksiyonlar: `core/datamap.py columns` (33), `experiments/services.py _check` (26), `reports/compute/cleaner.py compute` (25)

Önem: **Orta** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-4`
- Dosyalar: core/datamap.py, experiments/services.py, reports/compute/cleaner.py, farm/stock/integrity.py, inventory/integrity.py, inventory/read.py, reports/compute/smolt.py, reports/forms.py, farm/water/deffeyes.py, tasks/resources.py
- Açıklama: ruff C901 eşik 10'a karşı 47 üretim fonksiyonu aşıyor; en kötüleri: `columns` 33 (64 ifade), `_check` 26, `cleaner.compute` 25 (58 ifade, iç içe `row()` kapanışı + 8 kind dalı + doğrulama + biçimleme tek fonksiyonda), `farm/stock/integrity.problems` 23, `inventory/integrity._operation_problems` 19, `inventory/read.overview` 19, `smolt.compute` 19, `reports/forms.__init__` 19. PLR0915 (>50 ifade): `experiments/services._check`, `deffeyes.geometry`, `tasks/resources.filter_list`, `cleaner.compute`, `datamap.columns`.
- Kanıt: core/datamap.py:504; experiments/services.py:119; reports/compute/cleaner.py:30-100 (hesap + problem metni + uyarı aynı gövde); farm/stock/integrity.py:72; inventory/integrity.py:18; reports/forms.py:68; farm/water/deffeyes.py:487; tasks/resources.py:91.
- Öneri: toplama/doğrulama/biçimleme aşamalarını ayır; `cleaner.compute` içindeki kind->alan eşlemesini tabloya çevir.

### F-122 Designer önizlemesi: sunucu hataları sessizce yok sayılıyor, ağ hatası yakalanmayan Promise reddine dönüşüyor

Önem: **Orta** | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-9`
- Dosyalar: frontend/designer.ts, monitoring/views.py
- Açıklama: refresh() içinde '!response.ok' durumunda hiçbir şey yapılmadan return ediliyor (frontend/designer.ts:~457-459): 400/403/413/503 cevaplarında kullanıcıya mesaj yok, önizleme eski haliyle kalıyor ve sunucunun {error:'too large'/'bad request'} gövdesi (monitoring/views.py:188,193) hiç okunmuyor. catch bloğu yalnızca AbortError'ı yutuyor, diğer her hata (çevrimdışı TypeError, response.json() parse hatası) 'throw error' ile yeniden fırlatılıyor; çağıran 'void this.refresh()' olduğundan bu yakalanmayan unhandledrejection olur ve arayüzde durum göstergesi güncellenmez. Oturum süresi dolarsa (redirected/401) de geri bildirim yok.
- Kanıt: frontend/designer.ts:~445-485 (refresh); frontend/designer.ts:~391 'void this.refresh()'; monitoring/views.py:186-193.
- Öneri: Hata durumunda this.status/problems alanına çevrilmiş bir 'önizleme alınamadı' mesajı yazın; ağ hatalarını yakalayın; response.redirected/401/403 için poll.ts'deki gibi oturum uyarısı verin.

### F-123 Envanter okumasi tum defteri ve tum yemleme kayitlarini tarıyor; "fed_week" icin N+1

Önem: **Orta** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-14`
- Dosyalar: inventory/read.py:44-66, inventory/read.py:69-80, inventory/read.py:205-253
- Açıklama: `folds()` her cagrida tum canli InventoryLine'lari (`select_related('operation','lot')`), tum sayimlari ve - yem urunleri icin - tum zamanlardaki FeedingRecord'lari (feed x site x tarih gruplamasi, tarih siniri yok) cekiyor. `overview()` (site, urun) cifti basina ayri bir FeedingRecord agregasyonu calistiriyor (N+1), depo konumu icin `rows` listesini her konumda tekrar tariyor (O(L x R)).
- Kanıt: `FeedingRecord.objects.filter(feed_id__in=feed_ids, ...).values('feed_id', 'unit__production_department__site_id', 'date').annotate(kg=Sum('amount_kg'))` (inventory/read.py:62-64); `for (site_id, _item_id), record in per.items(): ... FeedingRecord.objects.filter(...).aggregate(...)` (read.py:239-244); `sum(... for row in rows if row.location.pk == location.pk ...)` (read.py:256).
- Öneri: Yemleme gruplamasini tarih araligina bagla, fed_week'i tek gruplu sorgu ile al; konum bazli toplamlari sozlukte on-hesapla.

### F-124 check_withdrawal komutunda stock_of birim sayisi kadar tekrar hesaplaniyor (O(n^2))

Önem: **Orta** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-6`
- Dosyalar: farm/management/commands/check_withdrawal.py:16
- Açıklama: List comprehension kosulu icinde `read.stock_of(units)` cagriliyor; her birim icin butun birim listesinin stoku (sorgu + tum defter katlamasi) yeniden hesaplaniyor. Birim sayisi n ise n kez tam farm katlamasi.
- Kanıt: `stocked = [unit for unit in units if unit.pk in read.stock_of(units)]`
- Öneri: `stock = read.stock_of(units)` bir kez hesaplanip `unit.pk in stock` kullanilmali (degisiklik tek satir).

### F-125 Kucuk ihtiyaclar icin tum ciftligin stok defteri katlaniyor (ozet fayanslari, form constructor'lari, birim secici)

Önem: **Orta** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-7`
- Dosyalar: farm/stock/views.py:549-562, farm/stock/views.py:316-319, farm/forms/harvest.py:169, farm/feeding/views.py:293-297, farm/resources/harvest_plan.py:154-157, config/views.py:31-52
- Açıklama: Uretim ana sayfasinin "Stocked units / Fish / Biomass" fayanslari (`overview_tiles`) tum Tank'lari cekip `stock_of` ile tam defteri katliyor; ayni sayfada ayrica su/yemleme/gorev fayanslari ve `System`/`Tank` icin ayri COUNT sorgulari (sistem durumu ve birim turu basina bir sorgu) var. `ProductionPlanForm.__init__` her olusturuldugunda (GET, POST, hatali POST) `stock_of(list(Tank.objects.all()))` calistiriyor; `_unit_choices` ve `choose_unit` de ayni sekilde. Yalnizca "hangi birimde balik var / ne kadar bos yer" gibi bilgiler icin tam gecmis katlaniyor.
- Kanıt: `stock = stock_read.stock_of(list(Tank.objects.all()))` (farm/forms/harvest.py:169); `stock = read.stock_of(units)` (farm/stock/views.py:555); `units_by_kind` ve `systems_by_status` icinde dongu ile `.count()` (config/views.py:43-52).
- Öneri: Mevcut "birim basina anlik stok" bir read-model/materyalize tabloda tutulsun ya da `unit_counts()`/`batches_in_stock()` gibi mevcut ucuz agregasyon fonksiyonlari kullanilsin (yalniz sayi ve biyokutle gerektiren yerlerde); sayimlari tek `values('kind').annotate(Count)` ile al.

### F-126 Repoda CI tanimi yok; `CI=1` korumasi bos

Önem: **Orta** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-1`
- Dosyalar: core/test_catalogs.py:229-238, README.md (Tests bolumu), .github (yok)
- Açıklama: TS birim testi Node yoksa skip, `CI=1` iken fail olacak sekilde tasarlanmis; ancak repoda `.github/workflows` veya baska CI tanimi yok (`ls -a`: .github yok). Testlerin her degisiklikte calistigini garanti eden mekanizma repoda gorunmuyor.
- Kanıt: core/test_catalogs.py:230 "under CI (`CI=1`) a missing Node is a failure"; dizinde CI dosyasi yok.
- Öneri: CI tanimi ekleyip `CI=1`, Postgres+timescaledb, `npm ci` ile `manage.py test` ve `npm test` kosulsun.

### F-127 Tarayici (Playwright) testleri sessizce skip oluyor

Önem: **Orta** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-2`
- Dosyalar: frontend/test/designer.browser.test.ts:105, frontend/test/announce.browser.test.ts:58
- Açıklama: Chrome/Edge yoksa test `skip` ile geciyor; `CI=1` icin fail mekanizmasi yok (TS testindeki gibi degil). Tasarimci ve duyuru (erisilebilirlik/aria-live) davranislari hic calismadan "yesil" gorunebilir.
- Kanıt: `{ skip: BROWSERS.length ? false : 'no Chrome or Edge on this machine' }`
- Öneri: CI'da tarayici zorunlu kil; skip sayisini raporla.

### F-128 CSRF korumasi hicbir testte dogrulanmiyor

Önem: **Orta** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-5`
- Dosyalar: config/settings.py:70, tum test_pages.py dosyalari
- Açıklama: Django test `Client` varsayilan olarak CSRF denetimini atlar; reponun testlerinde `enforce_csrf_checks` / `csrf` gecmiyor (grep: 0 dosya). Yazma uclari (POST/void/delete) token olmadan reddedilir mi testlenmiyor; middleware kaldirilsa/muaf edilse testler yesil kalir.
- Kanıt: `grep -rli csrf --include=test*.py .` sonuc yok.
- Öneri: temsili yazma uclari icin `Client(enforce_csrf_checks=True)` ile 403 testi; tum POST url'leri icin genel bir tarama testi.

### F-129 Veritabanı: compose'ta yedek, healthcheck ve kaynak/ağ sertleştirmesi yok; varsayılan parola

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-10`
- Dosyalar: docker-compose.yml:6-17
- Açıklama: `restart: unless-stopped` ile kalıcı çalışabilecek bir DB; parola `balik` varsayılanı ve port ana makineye tüm arayüzlerde açılıyor (`"${DB_PORT:-5433}:5432"`, 127.0.0.1 bağlı değil). Yedek/pg_dump, WAL arşivi, kaynak limitleri, loglama sürücüsü tanımsız. Port bağlama 0.0.0.0 olduğundan, varsayılan parola ile sunucuda çalıştırılırsa dışarıdan erişilebilir olur.
- Kanıt: docker-compose.yml:8-10, 15.
- Öneri: `127.0.0.1:` ile bağlayın, parolayı zorunlu env yapın, yedek işi ekleyin (bkz. 12-backup-restore.md).

### F-130 Bağımlılık yönetimi: Python için lock/hash ve güvenlik taraması yok

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-12`
- Dosyalar: requirements.txt, package-lock.json, package.json:43-48
- Açıklama: requirements.txt tam sürüm sabitli (iyi) ancak hash'siz, geçişli bağımlılıklar kilitli değil (Babel->..., vb.), pip-audit/Dependabot/Renovate yok. npm tarafında lock var (lockfileVersion 3) ama yalnızca devDependencies; `npm audit`/ci zorunlu kılınmamış (README `npm install` der, `npm ci` değil). Python/Node sürümü sabitlenmemiş (.python-version, engines, .nvmrc yok); Django 6.1 / Python sürüm gereksinimi hiçbir yerde belirtilmemiş.
- Kanıt: package.json'da "engines" yok; `git ls-files` içinde .python-version/.nvmrc yok; README.md:2980 `npm install`.
- Öneri: `pip-compile --generate-hashes`, `npm ci`, sürüm dosyaları ve otomatik bağımlılık güncelleme/tarama.

### F-131 Derleme çıktıları (static/js, .mo) commit edilmiyor ve otomatik üretilmiyor; eksiklik sessiz

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-13`
- Dosyalar: .gitignore:8-13, core/catalogs.py:55-57, README.md:2980-2985
- Açıklama: `static/js/` ve `*.mo` git dışı; elle `npm run build` ve `compile_catalogs` çalıştırılmadan uygulama JS'siz (404) ve çevirisiz (İngilizce'ye düşer) çalışır. Bunları zorlayan bir makefile/entrypoint/check yok. `.mo` güncelliği `is_fresh`-benzeri kontrolü (catalogs.py:55) üretim başlangıcında kullanılmıyor (sadece `core/catalogs.py` içinde, uygulama dışı bir çağrı bulunmadı). Dağıtım sırası (npm build -> compile_catalogs -> migrate -> collectstatic) hiçbir yerde tek komut olarak yok.
- Kanıt: .gitignore:8-13; `grep` ile catalogs fonksiyonlarının yalnızca management komutlarında ve testlerde kullanımı.
- Öneri: Tek build betiği/Dockerfile aşaması; `manage.py check` içine eksik .mo/static/js doğrulaması.

### F-132 Üretim uygulama sunucusu (gunicorn) bağımlılıklarda yok

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-3`
- Dosyalar: requirements.txt:1-14, README.md:2991
- Açıklama: README ve settings gunicorn'u uzun ömürlü worker için öneriyor, ancak requirements.txt'te gunicorn/uvicorn yok; tek belgelenmiş çalıştırma `manage.py runserver`. Başlatma komutu, worker sayısı, timeout (PDF çıkarma, monitoring) rehberi yok.
- Kanıt: requirements.txt'te gunicorn geçmiyor; config/settings.py:118-121 yorumu "gunicorn" der; README.md:2987 `runserver 8047`.
- Öneri: Üretim sunucusunu bağımlılık olarak ekleyip komut/ayarını belgeleyin (ayrı requirements-prod).

### F-133 Healthcheck / liveness-readiness uç noktası ve compose healthcheck yok

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-6`
- Dosyalar: config/urls.py:57-75, docker-compose.yml:6-17
- Açıklama: Yük dengeleyici/orkestratör için `/healthz` benzeri login gerektirmeyen DB-kontrol uç noktası yok (LoginRequiredMiddleware tüm sayfaları kilitler, settings.py:76). db servisinde `healthcheck:` yok, bu yüzden bağımlı servisler hazır olmayı bekleyemez (`pg_isready`).
- Kanıt: urls.py'de health route yok; `grep -rn health` yalnızca `CONN_HEALTH_CHECKS` ve water "fresh" kavramlarını verir; compose db tanımında healthcheck yok.
- Öneri: `@login_not_required` hafif /healthz (SELECT 1) ve compose healthcheck ekleyin.

### F-134 Yapılandırılmış LOGGING ayarı yok; gözlemlenebilirlik (metrik, hata izleme) yok

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-7`
- Dosyalar: config/settings.py (LOGGING yok), monitoring/read.py:277, monitoring/cards/resolve.py:112, farm/placements.py:50
- Açıklama: settings.py'de LOGGING, ADMINS, hata izleme (Sentry vb.), metrik, istek kimliği yok. Kod `logger.exception/error` çağırıyor (ör. monitoring kaynakları, yer sağlayıcı hataları, kart şablonu doğrulaması) ancak Django varsayılanıyla DEBUG=False iken bu kayıtlar yalnızca console'a (WARNING+) gider, merkezi toplama/uyarı yok; "no data" ile sessizce yutulan hatalar kimseye bildirilmez.
- Kanıt: `grep -n "LOGGING" config/settings.py` boş; monitoring/read.py:277 `logger.exception(... widgets say "no data")`.
- Öneri: Üretim LOGGING (JSON, stdout), hata izleme ve ADMINS/e-posta veya uyarı entegrasyonu.

### F-135 Zamanlanmış işler (generate_tasks, check_*) için scheduler/dağıtım tanımı yok

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-8`
- Dosyalar: tasks/management/commands/generate_tasks.py:5-12, README.md:1923, farm/management/commands/check_stock.py
- Açıklama: `generate_tasks` "for a cron job" diye tasarlanmış, ancak cron/CronJob/systemd timer tanımı yok. `check_stock/check_inventory/check_reports/check_hr/check_experiments/check_withdrawal` bütünlük kontrolleri de hiçbir yerde periyodik çalıştırılmıyor ve çıktıları uyarıya bağlı değil. Görev üretimi yalnızca sayfa okumasında yan etki olarak yapılıyor (README:1923), sayfa açılmazsa üretilmez.
- Kanıt: generate_tasks.py help metni; repoda cron/timer dosyası yok.
- Öneri: Zamanlama tanımları ve başarısızlıkta uyarı (non-zero exit kodlarını doğrulayın).

### F-136 "Layout of the code" tablosunda `hr/` ve `monitoring/` uygulamalari hic yok;

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-1`
- Dosyalar: README.md:3347-3394, hr/, monitoring/
- Açıklama: "Layout of the code" tablosunda `hr/` ve `monitoring/` uygulamalari hic yok; `core/` satiri da `core/ranges.py`, `core/checks.py`, `core/resources.py` gibi modulleri anlatmiyor. Tabloda `farm/health/notices.py` (README:2175 baska yerde anar) listelenmemis.
- Kanıt: `grep 'monitoring/' README` sadece bolum metinlerinde cikiyor, tabloda satir yok; `hr/` dizini 20+ dosya ile mevcut; config/settings.py:56-58 hr/experiments/monitoring INSTALLED_APPS'te.
- Öneri: Tabloya hr/ ve monitoring/ satirlari eklensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-137 Ortam degiskenleri `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` README'de hic gecmez (yalniz DB_* ve DJANGO_MEDIA_ROOT).

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-11`
- Dosyalar: README.md:2977-2996, config/settings.py:25-30, 191-196
- Açıklama: Ortam degiskenleri `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` README'de hic gecmez (yalniz DB_* ve DJANGO_MEDIA_ROOT). Varsayilanlar guvensiz (`DEBUG` varsayilan 1, sabit SECRET_KEY); uretim icin gereken ayar belgelenmemis. README gunicorn'dan bahseder ama requirements.txt'te gunicorn yok ve dagitim/deployment bolumu yoktur.
- Kanıt: `grep DJANGO_SECRET_KEY README.md` bos; settings.py:25 `os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-development-only')`, :28 `DEBUG ... '1'`.
- Öneri: "Configuration" tablosu (tum env degiskenleri, uretim zorunluluklari) eklensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-138 Database viewer bolumu tablolarin "`farm`, `inventory`, `knowledge`, `messaging`, `reports`, `tasks`, `core`, `auth`" uy

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-2`
- Dosyalar: README.md:2907-2909, config/database.py:9-20
- Açıklama: Database viewer bolumu tablolarin "`farm`, `inventory`, `knowledge`, `messaging`, `reports`, `tasks`, `core`, `auth`" uygulamalarindan geldigini soyler; gercekte hr, experiments, monitoring de listede.
- Kanıt: config/database.py:`Section(_('People'), ('hr',))`, `Section(_('Research'), ('experiments',))`, `Section(_('Monitoring'), ('monitoring',))`.
- Öneri: README listesi guncellensin veya "config/database.py'ye bakin" denilsin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-139 README maskelenen sutunlari yalnizca `auth_user.password` ve `messages.body` olarak verir;

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-3`
- Dosyalar: README.md:2912-2918, config/database.py:28-31
- Açıklama: README maskelenen sutunlari yalnizca `auth_user.password` ve `messages.body` olarak verir; kodda ayrica `shift_assignments.note`, `leave_requests.reason`, `leave_requests.decision_note`, `attendance_records.note` maskeli. Guvenlik/gizlilik davranisi belgesinde eksik (hr-launch-checklist 4.3 de bunlara dayanir).
- Kanıt: `masked={'auth_user': ('password',), 'messages': ('body',), 'shift_assignments': ('note',), 'leave_requests': ('reason', 'decision_note'), 'attendance_records': ('note',)}`.
- Öneri: README'ye HR sutunlari eklensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-140 Monitoring performans paragrafi "`CONN_MAX_AGE` is left alone ...

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-4`
- Dosyalar: README.md:683-684, config/settings.py:119-122
- Açıklama: Monitoring performans paragrafi "`CONN_MAX_AGE` is left alone ... no evidence for it" der; ayni README'nin Local setup bolumu ve settings.py ise `DB_CONN_MAX_AGE` ayarini (CONN_HEALTH_CHECKS ile) sonradan eklemis. Iki yer celisir gorunur.
- Kanıt: settings.py:121 `'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '0'))`; commit c295bb3 / 0f5bc72.
- Öneri: Paragraf "varsayilan 0 birakildi (DB_CONN_MAX_AGE, bkz. Local setup)" diye netlestirilsin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-141 Dosyanin acilisi "Phase 1 ...

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-5`
- Dosyalar: docs/regulatory-reports.md:3-6, 745, 437
- Açıklama: Dosyanin acilisi "Phase 1 ... No app code is written in this phase" der; oysa `reports/` uygulamasi var ve ayni dosyada "5.13 As built (Phase 2)" ve "Status after Phase 2" bolumleri yer alir. Giris eskimis; okuyucu belgenin tasarim-oncesi plan oldugunu sanir.
- Kanıt: reports/ dizini (models, compute/, services.py...), docs/regulatory-reports.md:745 "### 5.13 As built (Phase 2)".
- Öneri: Girise durum notu ("Phase 1 plani; Phase 2 insa edildi, bkz. 5.13") eklensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-142 "Pages" tablosu eksik:

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-9`
- Dosyalar: README.md:3258-3346, hr/urls.py, monitoring/, reports/urls.py:17-21
- Açıklama: "Pages" tablosu eksik: hicbir `/hr/...` yolu, `/production/team/`, `/monitoring-boards/` ve `/reports/close/`, `/reports/duties/`, `/reports/duties/done/`, `reports/closed/<id>/reopen/` yok. Tablo kapsamli gibi sunulur.
- Kanıt: Tablo icinde `/hr/` ve `/production/team` sayisi 0; `grep -c "reports/duties" README.md` = 0; reports/urls.py:17-21 bu rotalari tanimlar; hr/resources/leave.py:37 `url_prefix = 'hr/leave'`.
- Öneri: Eksik rotalar eklensin veya tablo "secilmis" diye isaretlensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-143 wip/* branch'leri yerel/uzakta yok; geçmiş yalnızca merge mesajlarında

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-1`
- Dosyalar: .git (refs)
- Açıklama: `git for-each-ref` yalnızca `refs/heads/main` ve `refs/remotes/origin/main` gösteriyor. Geçmişte wip/prodteam, wip/cards, wip/hr, wip/experiments, wip/monitoring, wip/reports-gaps, wip/reports-tabs adlı branch'ler kullanılmış; hiçbiri ref olarak kalmamış. HEAD de "detached at refs/heads/main".
- Kanıt: `git branch -a` -> `* (HEAD detached at refs/heads/main)`, `main`, `remotes/origin/main`; fd49eed "Merge branch 'main' into wip/prodteam".
- Öneri: Dal adları artık geri bulunamıyor; büyük özellik dalları (card templates, prodteam) için tag veya merge commit mesajında dal/PR numarası standardı kullan. HEAD'i `git switch main` ile attach et.

### F-144 Aşırı uzun commit konu satırları, gövde neredeyse hiç yok

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-3`
- Dosyalar: .git (commit mesajları), örn. adcda97
- Açıklama: Medyan konu uzunluğu 281, max 1969 karakter; 96 commit'in konusu 400+ karakter. Tüm açıklama konu satırına yazılmış; `%b` (gövde) toplam 71 satır. `git log --oneline`, GitHub arayüzü ve araçlar bu mesajlarda kesiliyor/okunmaz oluyor.
- Kanıt: `git log --format=%s | awk length` -> median 281, max 1969; adcda97 konusu yaklaşık 900 karakter.
- Öneri: 50-72 karakterlik özet + boş satır + gövde biçimi; commit-msg hook veya CI kontrolü.

### F-145 CI yapılandırması, LICENSE, .env.example, pre-commit, CONTRIBUTING yok

Önem: **Orta** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-7`
- Dosyalar: repo kökü
- Açıklama: Kökte `.github/`, LICENSE, `.env.example`, `.pre-commit-config.yaml`, `.editorconfig`, CHANGELOG yok. 2000+ test ve ruff kullanılıyor (.ruff_cache var) ama otomatik çalıştıran CI izi yok; ayrıca ruff/mypy yapılandırması takip edilmiyor. THIRD_PARTY.md lisansları anıyor ama proje lisansı belirsiz.
- Kanıt: `ls -a | grep -iE 'env|github|license|editorconfig|pre-commit|CONTRIBUTING|CHANGELOG'` boş döndü; `git ls-files | grep -E '(^|/)\.[^/]+$'` yalnızca .gitattributes, .gitignore, farm/tests/deffeyes_reference/.gitignore.
- Öneri: Minimal CI (test, ruff, tsc --noEmit, makemigrations --check), LICENSE ve .env.example ekle.

### F-146 `catalogueOf(...)` null dönebiliyor, `designer.ts` `as Catalogue` ile bastırıyor

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-1`
- Dosyalar: `frontend/designer.ts:96`, `frontend/grid/layout.ts:32-49`
- Açıklama: `catalogueOf` geçersiz katalogda `null` döner (tür: `Catalogue | null`). Tasarımcı sonucu `as Catalogue` ile zorla dönüştürüyor; `jsonScript<T>` da JSON'u hiçbir doğrulama yapmadan `T` yapıyor (`designer.ts:49-51`, `'null'` JSON'u dahi `CatalogueData` sayılır).
- Kanıt: `this.cat = catalogueOf(this.data) as Catalogue;` -> sonraki `this.cat.columns` (satır 146) `TypeError` ile tasarımcıyı tamamen çökertir; hata mesajı kullanıcıya gösterilmez. Kütüphanenin "garbage in is a typed answer, never a throw" sözü burada bozuluyor.
- Öneri: `null` ise açık bir hata durumu göster (`data-designer-broken`) ve sınıfı kurma; `as` dönüşümünü kaldır; `jsonScript` sonucunu çalışma anında doğrula.

### F-147 `Modal.load` ağ hatasını yakalamıyor, istekler yarışabilir

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-11`
- Dosyalar: `frontend/components.ts:333-366`, `:304-310`, `:321`, `:204`
- Açıklama: `fetch` etrafında try/catch yok; çağrılar `void this.load(...)` olduğundan ağ kesintisinde işlenmemiş reddedilme olur, diyalog açılmaz/değişmez, kullanıcıya geri bildirim yok. 5xx yanıtları da düz `innerHTML` olarak diyaloğa basılır (yalnızca 403 özel işleniyor). Eşzamanlılık denetimi yok: art arda tıklamada iki yanıt sırası belirsiz yarışır; `AbortController` yok. `X-Modal-Load` zinciri sınırsız özyinelemelidir.
- Kanıt: `const response = await fetch(url, {...options, credentials: 'same-origin', headers: { 'X-Modal': '1' }});` (headers `options.headers`'ı ezer). Giriş yönlendirmesi `pathname.startsWith('/accounts/login')` ile sabit kodlu.
- Öneri: try/catch + çevrilmiş hata metni (`label()`), `AbortController`, özyineleme sınırı, `response.ok` kontrolü.

### F-148 Ctrl+Shift+Z ile yinele hiç çalışmıyor; Ctrl+Z tasarımcı içindeki metin alanlarının yerel geri almasını engelliyor

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-2`
- Dosyalar: `frontend/designer.ts:365-370`
- Açıklama: Koşul `event.key === 'z' || event.key === 'y'`. Shift basılıyken `event.key` `'Z'` (büyük harf) olur, dolayısıyla Ctrl+Shift+Z/Cmd+Shift+Z koşula hiç girmez; `event.key === 'z' && !event.shiftKey` içindeki shift dalı ölü koddur. Ayrıca dinleyici `root` üzerinde olduğundan, ızgara düzeni `textarea`'sı ve denetçi `input`'larında yazarken Ctrl+Z `preventDefault` ile tarayıcının kendi geri alma işlemi yerine tasarım geçmişini geri alır.
- Kanıt: `if ((event.ctrlKey || event.metaKey) && (event.key === 'z' || event.key === 'y')) { event.preventDefault(); this.step(event.key === 'z' && !event.shiftKey ? undo : redo); }`. Tarayıcı testi yalnızca ok tuşu ve düğme geri almasını sınıyor (`frontend/test/designer.browser.test.ts:117-123`).
- Öneri: `event.key.toLowerCase()` kullan; hedef `input/textarea/select` ise dokunma; Ctrl+Shift+Z ve Ctrl+Y için test ekle.

### F-149 Kaldırma duyurusu "undefined" etiketiyle okunuyor

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-3`
- Dosyalar: `frontend/designer.ts:339-349`, `frontend/grid/layout.ts:266-276`, `frontend/grid/types.ts:377-384`
- Açıklama: Silinen widget artık `history.present` içinde yoktur; `announce` `?? change` ile `Change` nesnesine düşer, `as Item` ile türü susturur. `Change` içinde `type` alanı yok, `labelOf` -> `spec?.label ?? item.type` -> `undefined`; `fill` `String(undefined)` yazar.
- Kanıt: `const item = this.history.present.find((each) => each.id === change.id) ?? change;` ... `label: this.labelOf(item as Item)`. Test şablonu `data-announce-removed="{label} removed"` kullanıyor (`designer.browser.test.ts:50`) ama silme duyurusunu sınayan bir test yok. (Çalıştırılarak doğrulanmadı; mantıksal çıkarım.)
- Öneri: `announce` için silinen öğeyi `before` düzeninden bul (ya da `Change`'e `type/bind` ekle); `as Item` dönüşümünü kaldır; "removed" için test yaz.

### F-150 Bozuk kayıtlı yerleşim, ilk düzenlemede sessizce ezilir; `designerBroken` bayrağı hiç temizlenmez / metin değişikliğinde sessiz kalır

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-4`
- Dosyalar: `frontend/designer.ts:105-114`, `:280-288`, `:371-381`
- Açıklama: Başlangıç ayrıştırması başarısızsa `parsed = []` olur ve yorum "metin gerçek kalır" der. Ancak kullanıcı bir widget eklediği/geri aldığı anda `record()` `textarea.value`'yu boş/yeni düzenle üzerine yazar (satır 284); bozuk özgün metin kaybolur. `record()` `designerBroken` bayrağını temizlemez (yalnızca textarea `change` dalı siler). `textarea` `change` olayında `parse` `ok:false` dönerse (örn. şema/id hatası) hiçbir şey yapılmaz ve bayrak da set edilmez; yalnızca JSON istisnası `'shape'` yazar (bayrak sadece 'shape'e sıfırlanır, gerçek hata kodu kaybolur). "Başa dön" (`[data-designer-revert]`) da `this.initial` = `[]` olduğundan bozuk metni geri getirmez.
- Kanıt: `designer.ts:109-111`, `:284`, `:371-381` (`if (parsed.ok) {...}` else dalı yok).
- Öneri: bozuk durumda tasarımcı düzenlemelerini devre dışı bırak ya da önce özgün metni sakla; `ok:false` için `designerBroken = result.error` set et; `record()` sonrası bayrağı yönet.

### F-151 Önizleme isteğinde hata yönetimi: yanıt hataları sessiz, ağ hataları işlenmemiş promise reddine dönüşüyor

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-5`
- Dosyalar: `frontend/designer.ts:452-487`
- Açıklama: `!response.ok` durumunda (403 CSRF, 400, 500) sessizce dönülür; önizleme ve sorun listesi eski haliyle kalır, kullanıcı bilgilendirilmez. `AbortError` dışındaki her hata `throw error` ile yeniden fırlatılır ve çağıran `void this.refresh()` (satır 454) bunu yakalamaz -> `unhandledrejection`. `answer.problems` için çalışma anı doğrulaması yok (`as` dönüşümü).
- Kanıt: `if (!response.ok) { return; }` ... `if (!(error instanceof DOMException && error.name === 'AbortError')) { throw error; }`. `csrfToken` form yoksa `''` döner (satır 69-72) ve bu da sessiz 403'e yol açar.
- Öneri: hata durumunda `status`/`problems` alanında çevrilmiş bir uyarı göster; `refresh` çağrısına `.catch` ekle; yanıt şeklini doğrula.

### F-152 Void diyalogları üç şablonda kopya, `water_void` `stock_void` formunu kopyalıyor

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-2`
- Dosyalar: templates/farm/water_void.html:13-25, templates/farm/stock_void.html:17-29
- Açıklama: stock_void.html "entry" bloğu ile türetilebilir bir iskelet (feeding/lice/treatment/health_event bunu `extends` ediyor) iken water_void.html aynı form/reason/Cancel/Void gövdesini baştan yazıyor. Birinde yapılan düzeltme (ör. buton, hata alanı) diğerine gitmez.
- Kanıt: iki dosyada aynı `<form method="post" action="{{ request.get_full_path }}" novalidate>…{% with field=form.reason %}…button-danger`.
- Öneri: water_void `farm/stock_void.html`'i extend etsin (entry bloğunu doldursun) veya ortak `_void_form.html` include edilsin.

### F-153 Liste satırı eylem ikonları (Düzenle/Sil) ~35 liste şablonunda kopya

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-5`
- Dosyalar: templates/farm/site_list.html:30-31, farm/supplier_list.html:54-55, hr/holiday_list.html:19-20, hr/shift_list.html:24-25, farm/tank_list.html, farm/equipment_list.html vb.
- Açıklama: `icon-button` + `blocktrans Edit/Delete {{ name }}` + `sr-only` üçlüsü her listede elle yazılı; ayrıca `can_change/can_delete` ve başlık bağlantısı aynı. crud/list.html başlık/boş durum/ekle'yi ortaklaştırmış ama satır eylemleri ortaklaşmamış. Metin ve ARIA değişikliği 38 dosya gerektirir.
- Kanıt: aynı `{% if can_change %}<a class="icon-button" href="{% url '…_edit' x.pk %}" data-modal title="{% blocktrans with name=… %}Edit {{ name }}…` desenleri.
- Öneri: `crud/_row_actions.html` include (`edit_url`, `delete_url`, `name`) ya da simple_tag.

### F-154 Giriş sonrası herkes Company özetine düşüyor; üretim çalışanı neredeyse boş sayfa görür

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-1`
- Dosyalar: config/settings.py:200, templates/home.html, config/views.py:25-30, core/middleware.py
- Açıklama: `LOGIN_REDIRECT_URL='home'` ve `home` Company özeti; WorkspaceMiddleware paneli oturumda hatırlıyor ama girişten sonra `/` yolu company'ye ait olduğundan hatırlanan panel hemen company ile ezilir. Yalnız üretim izni olan kullanıcı, tek kutucuğu (Sites, izne bağlı) olan ve "The company’s figures will appear here" yer tutucusu gösteren sayfaya iner; Production'a panel menüsünden kendisi geçmeli.
- Kanıt: `LOGIN_REDIRECT_URL = 'home'`; home.html `<section class="placeholder">...figures will appear here`; `workspace_of('/')` company döner.
- Öneri: Girişte oturumdaki son paneli veya kullanıcının sunulan ilk anlamlı panelini aç (ör. yalnız Production sunuluyorsa `production_home`).

### F-155 Onaysız tek tıkla yıkıcı/geri alınamaz eylemler: izin talebini iptal, kanaldan üye çıkarma

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-12`
- Dosyalar: templates/hr/leave_list.html:39, templates/hr/leave_detail.html:25, templates/messaging/members.html:22-25
- Açıklama: "Cancel the request" liste satırında yalnız kırmızı ikon düğmesi (onay yok, geri alma yok; izin talebi silinemiyor, iptal son hal), detayda da tek tık. Mesajlaşmada kanaldan ayrılma (`leave`) ve mesaj silme onaylı iken (confirm.html) "Remove" (üye çıkarma) ve "Make owner" onaysız doğrudan POST; "Make owner" ile yetki devri tek tık. Aynı alan içinde onay politikası tutarsız. (Görev için `reopen` var; izin için yok.)
- Kanıt: leave_list.html:39 `<form ... leaverequest_cancel ...><button type="submit" class="icon-button icon-button-danger"`; members.html:22-25 `remove_member` formu, onay şablonu yok; messaging/confirm.html yalnız leave/delete_message için kullanılıyor.
- Öneri: remove_member, set_role(owner) ve leave cancel için `confirm.html`/modal onayı; mümkünse izin talebi için "Reopen".

### F-156 "Leave types" sayfasına hiçbir bağlantı yok (yetim sayfa)

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-3`
- Dosyalar: config/navigation.py:72, hr/resources/leave.py:16, templates/hr/settings_list.html:31,38
- Açıklama: Giriş `hidden=True` ve "Scheduling settings'ten erişilir" deniyor; fakat settings_list.html yalnız "Manage shifts" ve "Manage holidays" bağlantılarını içeriyor. `hr:leavetype_list` şablonlarda hiçbir yerde `{% url %}` ile geçmiyor. İzin türleri (tohumsuz, "none seeded") eklenemeden izin talebi akışı kullanılamaz; yönetici yolu bulamaz.
- Kanıt: grep `leavetype_list` templates/ → yalnız leave_type_list içi `leavetype_edit/delete`; settings_list'te leave types bölümü yok.
- Öneri: settings_list.html'e "Leave types" bölümü + "Manage leave types" bağlantısı ekle; izin talep formunda tür yoksa buraya yönlendir.

### F-157 Diyalog kirli form uyarısı vermiyor: backdrop tıklaması/Esc girilen veriyi sessizce atar

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-6`
- Dosyalar: frontend/components.ts:312-314, 323-325
- Açıklama: Uzun kayıt formları (sekmeli, stok/su kaydı) diyalogda açılıyor. Backdrop'a yanlış tıklama, Esc veya "Cancel" değişiklik kontrolü olmadan `dialog.close()` yapar ve içerik `replaceChildren()` ile silinir. Dirty-state/onay yok.
- Kanıt: `if (event.target === dialog) dialog.close();` ve close olayında `this.content.replaceChildren()`.
- Öneri: Form değiştiyse (input olayı ile dirty bayrak) kapatmadan önce onay iste; en azından backdrop kapatmayı kirli formda iptal et.

### F-158 Mobil off-canvas menü kapalıyken odaklanabilir ve ekran okuyucuya açık; odak tuzağı/`inert` yok

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-1`
- Dosyalar: `static/css/app.css:370-385`, `frontend/shell.ts:39-48,91-98`, `templates/app_base.html:21,63`
- Açıklama: 767px altında `.rail` yalnızca `transform: translateX(-100%)` ile ekran dışına itiliyor; `display:none`, `visibility:hidden`, `inert` veya `aria-hidden` yok. Kapalı menünün bağlantıları Tab sırasında görünmez şekilde odak alır, ekran okuyucu da okur. Menü açıkken ise ne odak tuzağı ne `inert` ile arka plan kilidi var; Tab menüden çıkıp arkadaki sayfaya gider. `scrim` tıklanabilir ama menü `role="dialog"`/modal olarak işaretlenmemiş. Menü kapanınca odak yalnızca Esc yolunda `openButton`'a döner; scrim tıklamasıyla kapanışta odak geri verilmez.
- Kanıt: `app.css` `.rail, [data-nav="collapsed"] .rail { ... transform: translateX(-100%); }`; depoda `inert`/`visibility` araması yalnızca `poll.ts`'te `visibilityState` buluyor; `shell.ts:46-47` scrim ve açma tıklamaları odak yönetmiyor.
- Öneri: Mobilde kapalı durumda `inert` (veya `visibility:hidden` geçişli) uygula; açıkken arka plana `inert`, odak tuzağı ve kapanışta odağı `openButton`'a geri ver.

### F-159 Roster'da bilgi yalnızca `title` ile veriliyor ("!" uyarıları, vardiya adı)

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-10`
- Dosyalar: `templates/hr/roster.html` (`roster-finding`, `shift-chip title`), `static/css/hr.css:28-29`
- Açıklama: Hücrelerdeki uyarı işareti `<span class="roster-finding" title="{{ cell.finding_text }}">!</span>`: uyarı metni yalnızca tooltip'te; klavye/dokunmatik/çoğu ekran okuyucu bunu okumaz, görünen içerik yalnızca "!" (imleç `cursor:help`). Vardiya çipleri yalnızca kodu (ör. "N") gösterir, ad ve saat `title`'da; bağlantı erişilebilir adı yalnızca kod kalır. Vardiya boyama düğmelerinde de aynı: `title="{{ shift.name }}"` açıklama niteliğinde. Hata/blok durumu (`has-block` kırmızı alt kenar, `has-warning` sarı) `box-shadow` ile; forced-colors'ta kaybolur. Haftalık toplam sütunundaki "!" için de aynı.
- Kanıt: `hr.css:28-29` `.roster-finding {... cursor: help; }`; `roster.html` `title="{% trans 'More than the standard week' %}"`.
- Öneri: Uyarı metnini `sr-only` kardeş metin olarak ekle, `aria-label`/`aria-describedby` kullan; vardiya adını sr-only olarak çipin içine koy; durum için `box-shadow` yanında metin/ikon.

### F-160 Türkçe `.lower()` çevrilmiş etiketlerde birleşik noktalı "i̇" üretir

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-1`
- Dosyalar: `templates/inventory/void.html:6`, `templates/farm/stock_void.html:12`, `templates/farm/_unit_drawer.html:106`, `tasks/services.py:126,142,178`, `farm/models/tank.py:510,528,536`, `inventory/services.py:97,195,226`, `farm/feeding/services.py:53`, `farm/health/withdrawal.py:341`, `farm/templatetags/water.py:48`, `monitoring/cards/render.py:175`
- Açıklama: Çevrilmiş etiketler cümle ortasına girmek için `str.lower()` / `|lower` ile küçültülüyor. Türkçede `İ` Python'da `i` + U+0307 (birleşik nokta) olur, `I` ise `ı` değil `i` olur.
- Kanıt: `'İptal edildi'.lower()` -> `'i̇ptal edildi'` (13 karakter; doğrulandı). Katalogda `Voided`=`İptal edildi`, `Cull`=`İtlaf`, `Culled`=`İtlaf edildi`, `Cancelled`=`İptal edildi` ve `İ` ile başlayan onlarca etiket var; `void.html` `operation.get_kind_display|lower` ile "İtlaf" etiketini küçültüyor. (Etkinlik günlüğü yolları `source_language()` içinde İngilizce çalıştığı için etkilenmez; kullanıcıya görünen yollar etkilenir.)
- Öneri: Küçültmeyi dile göre yapan bir yardımcı (tr için `İ->i`, `I->ı` ön eşlemesi) kullanın ya da cümleyi küçültme gerektirmeyecek biçimde (etiketi başlık hâliyle koyan) kurun.

### F-161 `a:hover` kurali `<a class="button">` hover rengini bozuyor (kontrast 2.1:1)

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-1`
- Dosyalar: `static/css/base.css:143-144`, `static/css/base.css:110-129`, `static/css/components.css:30-31`
- Açıklama: `a:hover { color: var(--speck) }` ozgullugu (0,1,1); `.button { color: var(--white) }` ozgullugu (0,1,0). `.button:hover` yalniz `background` degistirdigi icin, `<a class="button ...">` uzerine gelinince metin koyu (`#232920`) olur. `.button-ghost`, `.menu-item`, `.rail-link` icin bu elle yamanmis (`color: var(--speck)` hover'da), birincil ve tehlike dugmeleri icin yamanmamis.
- Kanıt: `<a class="button` ile baslayan, ghost olmayan 26 sablon kullanimi (ornegin `templates/tasks/task_list.html:27`, `templates/hr/today.html:16`, `templates/registration/password_reset_done.html:7`). Hesap: `#232920` uzerinde `#9A3650` = 2.14:1; `.button-danger:hover` `#7E1D24` uzerinde = 1.48:1.
- Öneri: `.button:hover { color: var(--white) }` ekle (ve `.button-ghost` icin ayri kalsin) veya `a:not(.button):hover` kullan.

### F-162 `hidden` oznitelgi `display` veren siniflarca eziliyor (JS'siz progressive enhancement bozuk)

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-2`
- Dosyalar: `static/css/components.css:5-19`, `static/css/hr.css:46`, `templates/hr/roster.html:12,16`, `templates/hr/overview.html:14`, `templates/hr/orgchart.html:9`, `templates/reports/report_print.html:19`, `templates/farm/water_calculator_report.html:23`
- Açıklama: Sablonlar `data-print hidden` ve `data-roster-paint hidden` ile "JS yoksa gizli" niyetini yaziyor (`frontend/components.ts:13`, `frontend/roster.ts:5` yorumlari). Ancak `.button-inline`/`.button-ghost` `display:inline-flex`, `.roster-paint` `display:flex` veriyor; yazar CSS'i tarayicinin `[hidden]{display:none}` kuralini ezer. Global `[hidden]` kurali yok; yalniz `.tabs`, `.tab-panel`, `.link-row`, `.menu-panel` icin tek tek var (`components.css:186,222,294`, `app.css:309`).
- Kanıt: `grep "\[hidden\]" static/css/*.css` yalniz bu 4 sonuc. `roster.html:16` `<form class="roster-paint" ... hidden>` JS'siz gorunur ve calismaz.
- Öneri: `base.css`'e `[hidden] { display: none !important; }` ekle; tek tek `[hidden]` kurallari kaldirilabilir.

### F-163 Google Fonts harici CDN'den yukleniyor; `THIRD_PARTY.md` ile celisiyor

Önem: **Orta** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-4`
- Dosyalar: `templates/app_base.html:8-10`, `templates/auth_base.html:7-9`, `THIRD_PARTY.md:3`, `static/css/base.css:15`
- Açıklama: `THIRD_PARTY.md` "Nothing from a package registry is shipped to the browser" diyor; fakat her sayfa `fonts.googleapis.com` ve `fonts.gstatic.com`'a baglaniyor (Bricolage Grotesque). Sonuclari: kullanici IP'si ucuncu tarafa gider (AB/Norvec veri koruma acisindan beyan gerektirir), cevrimdisi/kapali aginda font yuklenmez (system-ui yedegi kullanilir), render-engelleyici harici stil, ucuncu taraf listesinde font (OFL) lisansi yok. `water_calculator_report.html` fontu hic yuklemiyor (tutarsiz).
- Kanıt: yukaridaki `<link>` satirlari; `THIRD_PARTY.md` fontu anmiyor.
- Öneri: Fontu `static/fonts/` altinda barindir (woff2 + `@font-face`), `THIRD_PARTY.md`'ye ekle; ya da en azindan belgele.

### F-164 Tedavi -> hasat arınması yalnızca onaylanabilir uyarı; ikinci kişi/rol ayrımı yok

Önem: **Orta** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-2`
- Dosyalar: `farm/handling/check.py:50`, `farm/handling/check.py:318-330` (`require_acknowledged`), `farm/stock/services.py:200-210` (`_handling`), `README.md:1796`
- Açıklama: Arınma sürerken hasat, formdaki kutu işaretlenerek kaydedilebiliyor; engel yok ("owner decision"). Onay kaydı (`HandlingAcknowledgement`) ve kritik log tutuluyor, ancak hasat yetkisi olan her kullanıcı kendi başına onaylayabiliyor; "veteriner/yönetici onayı" gibi ikinci kontrol yok. Bilinmeyen sonlu arınma (`until=None`) da yalnız uyarı. Gıdaya giden balık için düzenleyici risk taşıyan akış.
- Kanıt: `_handling` -> `check.require_acknowledged(assessment, seen)`; uyarı varsa kutu parmak izi eşleşmesi yeterli. Başka bir kapı (rol, ikinci onay) kodda yok.
- Öneri: Owner kararı korunacaksa, arınma uyarısını aşmak için ayrı bir izin (örn. `farm.override_withdrawal`) ve/veya bilinmeyen-bitişli arınmada ikinci onay düşünülsün; aşılan hasatlar `check_withdrawal`/rapor ekranında listelensin.

### F-165 Depo (inventory) ile tedavi/ilaç arasında bağ yok; `issue(reason=treatment)` serbest kalan kayıt

Önem: **Orta** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-3`
- Dosyalar: `inventory/models.py:150-170`, `inventory/models.py:246-251`, `inventory/services.py:45-47`, `inventory/services.py:313-317`, `farm/health/services.py` (`record_treatment`)
- Açıklama: `InventoryItem` yalnız yem bağlayabiliyor (`CheckConstraint(feed__isnull=False)`); ilaç (`Medicine`) depoda yok. `IssueReason.TREATMENT` ile yapılan çıkış hiçbir `Treatment` kaydına referans vermiyor, `record_treatment` de depodan düşmüyor. Yani tedavi kaydı ile ilaç stoğu, lot/SKT izlenebilirliği ve arınma zinciri tamamen ayrı; "hangi ilaç lotu hangi tedavide" sorusu cevapsız. `LOT_REQUIRED = {MEDICINES}` ile ilaç lot kuralları ölü kod (23-9 ile ilişkili; burada akış boyutu).
- Kanıt: `chk_inventory_items_one_link` `Q(feed__isnull=False)`; `issue()` imzasında treatment alanı yok; README:1857 "medicine stock" taşınmamış olarak geçiyor.
- Öneri: README'de bu kopukluk "bilinen eksik" olarak işaretlensin; ilaç öğesi eklendiğinde `Treatment` <-> `InventoryLine` bağı (lot) tasarlansın.

### F-166 Tank `maintenance` durumunda balık varken çıkış yolu yok

Önem: **Orta** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-3`
- Dosyalar: farm/models/tank.py:175-184, 516-541
- Açıklama: `MAINTENANCE` yalnızca `PREPARING` ve `INACTIVE`'e gidebilir; ikisi de `NEEDS_NO_FISH`. `ACTIVE`'ten `MAINTENANCE`'a balıklı geçilebiliyor (`NEEDS_FISH`/`NEEDS_NO_FISH` dışında), ama bakımdaki balıklı tank `ACTIVE`'e (veya `QUARANTINE`'e) dönemez; ancak balık boşaltılırsa `preparing` mümkün olur. Ayrıca `QUARANTINE`'den balıksız `ACTIVE` yasak, `CLEANING`'e gidiş balıklıyken `NEEDS_NO_FISH` nedeniyle engellenir: karantinadaki balıklı tank da yalnızca `ACTIVE`'e dönebilir.
- Kanıt: TRANSITIONS[MAINTENANCE] = (PREPARING, INACTIVE); status_blocker satır 504-509.
- Öneri: MAINTENANCE -> ACTIVE (balıklıysa) geçişi eklenmeli ya da kasıtlıysa belgelenmeli.

### F-167 Stok servisinin otomatik durum değişikliği TRANSITIONS tablosunu atlıyor

Önem: **Orta** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-4`
- Dosyalar: farm/stock/services.py:407-431, farm/models/tank.py:175-184
- Açıklama: `_follow_status` doğrudan `unit.status = ...; unit.save()` yapar, `_check_status`/`TRANSITIONS` çalışmaz (clean çağrılmıyor). Örn. `cleaning -> active` ve `inactive -> active` (void ile balık geri gelirse) tablo dışıdır. Kodun yorumu bunu kasıtlı gösteriyor ama makine tek yerde tanımlı değil; model.save() de geçişi doğrulamıyor.
- Öneri: Geçerli "sistem geçişleri" ayrı bir tablo olarak açıkça tanımlanmalı; `save()` içinde invariant testi.

### F-168 Deney okuma sayfaları, farm okuma izni olmadan beslenme/stok/ölüm rakamlarını gösterir

Önem: **Orta** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-4`
- Dosyalar: experiments/resources.py:118-146; experiments/read.py:129-164 (yalnız satır 478'de has_perm); experiments/resources.py:33-47 (data_links ise has_perm ile süzülüyor)
- Açıklama: `experiments.view_experiment` sahibi `/research/experiments/<pk>/view/` Overview/Data sekmesinde parti kodları, tanktaki balık/biyokütle, sağkalım, dönüşüm oranı (FCR) gibi rakamları `farm.view_stockoperation`/`view_feedingrecord` olmadan görür. Bağlantılar izne göre süzülürken veriler süzülmüyor: tutarsız. (README: "It reads the farm and nothing reads it", ama matris bu çapraz okumayı göstermiyor.) 02-6 raporlar için benzer bulgu.
- Kanıt: `overview()` içinde `stock_read.Presence.of_units`, `Batch.all_objects`, `feeding_read.Conversion` doğrudan çağrılıyor; izin kontrolü yok.
- Öneri: Rakamları ilgili farm izinlerine göre gizle ya da matriste "Experiments Read çiftlik rakamlarını içerir" diye belgele.

### F-169 Varsayılan "açık" (fail-open) tasarım ve URL x rol matrisini süpüren otomatik test yok

Önem: **Orta** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-6`
- Dosyalar: config/settings.py:75-76; hr/views.py:60-130,197-212 (punch/plan/approve/leave_request fonksiyon içi kontrol); config/views.py:22-53; core/tests.py:436; core/test_database.py:93; monitoring/tests/test_templates_db.py (resolver kullanımı yalnız şablonlar için)
- Açıklama: Dekoratörsüz bir görünüm her oturumlu kullanıcıya açıktır. Birçok görünüm izni dekoratörle değil, gövdede (`has_perm`/servis) kontrol eder (`hr.views.punch`, `plan`, `approve`, `reject`, `cancel`, knowledge `_allowed`, `today*`). Tüm `get_resolver()` rotalarını dolaşıp "ya login_not_required ya izin bildirimi" doğrulayan ya da rol başına 200/403/404 matrisini test eden bir test bulunamadı; yalnız seçili URL'ler için 403 testi var. Yeni bir rotada dekoratör unutulursa sessizce tüm oturumlu kullanıcılara açılır.
- Kanıt: grep (`get_resolver|urlpatterns`) testlerde yalnızca core/tests_crud_mount.py, hr/tests/test_scope.py, monitoring testlerinde çıkıyor; core/tests.py:436 yalnız roles/users için.
- Öneri: Rota başına izin bildirimi (ör. `PERM` özniteliği) + tüm rotaları kapsayan sözleşme testi; ya da `LoginRequiredMiddleware`'e ek bir "izin bildirilmemiş görünüm" denetimi.

### F-170 DB bağlantı/ifade/kilit zaman aşımı tanımlı değil

Önem: **Orta** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-3`
- Dosyalar: config/settings.py
- Açıklama: DATABASES'te `OPTIONS` yok: `connect_timeout`, `statement_timeout`, `lock_timeout` yok. Servislerdeki `select_for_update()` kilidi süresiz bekler; takılan bir işlem arkasındaki tüm istekleri bloklar. DB erişilemezse bağlantı denemesi işletim sistemi zaman aşımına kadar asılı kalabilir.
- Kanıt: config/settings.py:110-125 (yalnızca CONN_MAX_AGE ve CONN_HEALTH_CHECKS); `select_for_update` kullanımı örn. farm/stock/services.py:125, core/crud.py:724.
- Öneri: OPTIONS içinde connect_timeout ve `-c lock_timeout/statement_timeout` ayarla; lock timeout hatasını kullanıcıya anlaşılır göster.

### F-171 Kimlik/yapılandırma bulguları PII etkisi açısından birleşiyor: sabit SECRET_KEY + DEBUG + console e-posta

Önem: **Orta** | özgün: Yüksek | Güven: belirtilmedi | Alan: Gizlilik/KVKK | Doğrulama: doğrulandı

- Kaynaklar: `08-X1`  (yalnız çapraz görüş)
- Dosyalar: config/settings.py:25, config/settings.py:28, core/audit.py
- Açıklama: Kimlik/yapılandırma bulguları PII etkisi açısından birleşiyor: sabit SECRET_KEY + DEBUG + console e-posta
- Doğrulama `08-X1`: doğrulandı; doğrulayıcı önemleri Orta/Orta -> nihai Orta. config/settings.py:25, :28, :190-194 üç varsayılan doğrulandı; PII etkisi dolaylı.

### F-172 restore() cascade çocuklarını geri getirmez

Önem: **Orta** | özgün: Orta/Düşük | Güven: belirtilmedi | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `11-X1`, `18-X1`  (yalnız çapraz görüş)
- Dosyalar: core/softdelete.py, tasks/services.py
- Açıklama: Restore ebeveyni geri getirir, kaskadla silinen çocuklar silinmiş kalır; çocuğu ayırt edecek silme grubu yok
- Birleştirilen kayıtlar:
  - `11-X1` (Düşük): restore() yalnızca kaydı geri getirir; cascade çocukları aynı deleted_at ile işaretli olduğu halde toplu geri alma yok

### F-173 Raporlar (`reports.view_report`) başka alanların verisini o alanların izni olmadan gösterir ve dışa aktarır

Önem: **Orta** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-6`
- Dosyalar: reports/views.py:202-241, 33-38, 41-52
- Açıklama: `export` ve `print_page` yalnızca `view_report` ister; içerik `compute.compute(report).content` ile stok, yem, ilaç, bit sayımı vb. kayıtlardan canlı hesaplanır (taslakta). İzleme modülü bölüm başına izin uygular (monitoring/read.py:107-110) fakat raporlar uygulamaz; Reports Read izni, Production units/Treatments/Lice Read izninin yerini tutar. Tasarım gereği olabilir (rapor sahibi yasal rapor çıkarır) ama matris bunu belirtmiyor.
- Kanıt: reports/views.py:33-37 `_content`: `return compute.compute(report).content, False`.
- Öneri: Bu sızıntı belgelenmeli veya Reports Read için ön koşul izinleri tanımlanmalı.

### F-174 ALLOWED_HOSTS boş varsayılan; DEBUG kapalıyken tüm istekler reddedilir, belgesi yok

Önem: **Orta** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-7`
- Dosyalar: config/settings.py:30
- Açıklama: Boşsa DEBUG açıkken yalnız localhost kabul edilir; kapalıyken her istek 400 alır. Güvenli yönde ama hata mesajı sezgisel değil ve README'de DJANGO_ALLOWED_HOSTS biçimi (virgüllü liste, boşluk kırpılmıyor) yok. `split(',')` sonrası `strip()` yapılmadığından `a.com, b.com` yazımında ikinci host eşleşmez.
- Kanıt: `[h for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h]`
- Öneri: `h.strip()` ekle, belgele.

### F-175 Docker imajı yalnızca etiketle sabit (digest yok) ve eski bir TimescaleDB sürümü

Önem: **Orta** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-8`
- Dosyalar: docker-compose.yml:4
- Açıklama: `timescale/timescaledb:2.17.2-pg17` değişebilir bir etikettir; imaj içeriği digest ile sabitlenmemiş. 2.17.x serisi güncel TimescaleDB sürümlerinin gerisinde (2024 sonu çıkışlı; bugünün tarihine göre yama/güvenlik düzeltmelerini almıyor olabilir; sürüm geçmişi ağ olmadığından doğrulanmadı). README PostgreSQL 17 + TimescaleDB 2.17 olarak belgeliyor, bu yüzden güncelleme hem compose hem README'yi etkiler.
- Kanıt: `image: timescale/timescaledb:2.17.2-pg17`; README.md:4 "PostgreSQL 17 with TimescaleDB 2.17".
- Öneri: Güncel yama sürümüne geç, `@sha256:` digest ile sabitle, güncelleme politikasını belgele.

### F-176 `?from=`/`?to=` geçerli biçimde ama var olmayan tarihte (`2026-13-45`) `parse_date` `ValueError` fırlatır: 500

Önem: **Orta** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-13`
- Dosyalar: farm/water/views.py:214-216
- Açıklama: `django.utils.dateparse.parse_date` biçimi doğru ama geçersiz tarihte `ValueError` fırlatır (yalnızca biçim uymazsa None döner). `_day` bunu yakalamaz. Aynı klasördeki diğer sayfalar (`farm/feeding/views.py:73-77`, `core/views.py:_day`, envanter `_day`) `ValueError`'u yakalıyor; bu kullanım tutarsız. Django bu ortamda kurulu olmadığından çalıştırılarak doğrulanmadı, Django belgelerine/uygulamasına dayanır.
- Kanıt: `return parse_date(request.GET.get(name, '')) or default` (views.py:215).
- Öneri: `try/except ValueError` ile `default` döndür; test ekle.

### F-177 Menü `rail` context processor'ı her sayfa render'ında tüm çalışma alanlarının rozetlerini ve `show_when` kurallarını sorgular

Önem: **Orta** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-15`
- Dosyalar: core/navigation.py:165-196; config/navigation.py:173, 186; messaging/read.py:25-37; hr/read.py:539-547; hr/scope.py:187-203
- Açıklama: `rail` her istekte (fragment olmayan her render, modal dahil) kullanıcının görebildiği tüm çalışma alanlarının tüm girdileri için `badge_for(user)` çağırır, yalnızca geçerli panelin değil. Bu: mesaj okunmamış sayımı (`Message` üzerinde `Exists` alt sorgulu `COUNT`, tüm konuşmalar) ve izin bekleyen sayısı (`scope.by_day` + `Exists`) ile `LEADS`/`production_only` (`ProductionDepartment...exists()`, `Employee...exists()`) sorgularını her sayfaya ekler. `monitoring.cards` yorumu "no request goes to the template, so the menu is never worked out for a poll" ile sorunun farkında olunduğunu gösteriyor; normal sayfalar için ise rozetler her seferinde hesaplanıyor. Ayrıca `entries()`/`place()` her çağrıda menüyü doğrusal tarar.
- Kanıt: `'badge': entry.badge_for(user)` (navigation.py:182); `Message.objects.filter(is_deleted=False).filter(Exists(mine)).count()` (messaging/read.py:31).
- Öneri: Rozetleri yalnızca geçerli panelde/yalnızca gösterilirken hesapla ya da kullanıcı başına kısa önbellekle; `entries()` sonucunu sabitle.

### F-178 Görüntüleyicinin "her sütunda ara" ve sütun filtreleri indekssiz `ICONTAINS(CAST(... AS text))` üretir; sorgu zaman aşımı yok

Önem: **Orta** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-2`
- Dosyalar: core/dbgrid.py:59-72, 163-165, 171-172; config/settings.py:107-122
- Açıklama: Arama terimi, okunabilir her sütun için `Cast(attname, TextField()) ILIKE '%terim%'` koşuluna çevrilip OR'lanır; büyük tablolarda (audit_log JSON `changes`, stock_movements, water_measurements) tam tarama olur ve Paginator'ın `COUNT(*)` sorgusu aynı koşulla yeniden çalışır. `DATABASES` altında `statement_timeout` veya `OPTIONS` yok; tek bir platform yöneticisi isteği veritabanı bağlantısını uzun süre meşgul edebilir (gunicorn worker'ı da).
- Kanıt: `Q(IContains(Cast(field.attname, models.TextField()), term))` (dbgrid.py:72); `rows.filter(reduce(or_, conditions))` (dbgrid.py:165); settings.py:107-122'de zaman aşımı ayarı yok.
- Öneri: Görüntüleyici sorguları için `SET LOCAL statement_timeout` (ör. 5-10 sn) uygula; arama için sütun sayısını/kapsamı sınırla veya büyük tablolarda aramayı kapat.

### F-179 Maskeleme politikası tutarsız: kişilerin yazdığı diğer serbest metinler (görev notları, iptal/tamamlama notları, deney gerekçeleri) maskesiz; README "ne yazdıkları kişilerin kendi arasındadır" ilkesine yalnızca `messages.body` uyar

Önem: **Orta** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-4`
- Dosyalar: config/database.py:17-24; tasks/models.py:357,361,493; tasks/services.py:188-198; experiments/models.py:93,98,366; reports/models.py:86-87; README.md (Database viewer, "Sensitive data")
- Açıklama: `masked` yalnızca `auth_user.password`, `messages.body`, `shift_assignments.note`, `leave_requests.reason/decision_note`, `attendance_records.note` içerir. `task_notes.body` (4000 karakterlik kişi yazısı), `tasks.completion_note/cancel_reason`, `experiments` notları/`left_reason` ile `reports.contact_email/contact_phone` görüntüleyicide ve CSV'de açık okunur. Üstelik `tasks.services.add_note` not metnini `audit_log.changes` içine düz yazar (tasks/services.py:198) ve `audit_log` tablosu da görüntüleyicide maskesiz. Test yalnızca `password|secret|token|session` adlı sütunları zorunlu kılıyor (core/test_database.py:180); "kişi yazısı" sınıfı için kontrol yok. Politika bilinçli olabilir (görev notu "iş kaydının parçası") ama config'te gerekçesi yazılı değil.
- Kanıt: `masked={'auth_user': ('password',), 'messages': ('body',), 'shift_assignments': ('note',), 'leave_requests': (...), 'attendance_records': ('note',)}` (config/database.py:20-24); `audit.record(user, AuditLog.Action.UPDATE, task, {str(NOTE): [None, body]})` (tasks/services.py:198).
- Öneri: Hangi serbest metin sütunlarının kasıtlı açık olduğunu config'te yorumla belgele; `task_notes.body` ve `audit_log.changes` için karar ver; testle "TextField/uzun CharField adayları" için liste uyarısı ekle.

### F-180 İzin kotası kontrolü kilitsiz: eşzamanlı talepler yıllık hakkı aşabilir

Önem: **Orta** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-3`
- Dosyalar: `hr/forms/leave.py:90-100`, `hr/leave.py:60-67`
- Açıklama: `LeaveRequestForm.clean` kalan günleri `leave.used(...)` ile okuyup `used + days > kind.annual_days` ile karşılaştırıyor; bu form doğrulama aşamasında, çalışan satırı kilitlenmeden yapılıyor. Aynı çalışan için iki farklı talep aynı anda gönderilirse (tarihleri çakışmasa da, örn. iki ayrı hafta) ikisi de eski toplamı görür ve ikisi de geçer; toplam `annual_days` aşılabilir. Çakışma için DB exclusion constraint var, kota için yok; kota yalnızca form katmanında.
- Kanıt: `used = leave.used(employee, kind, year, site, exclude=None if adding else self.instance)` / `if used + days > kind.annual_days:` formda; `CreateView` içinde `employee` satırı kilitlenmiyor (`hr/services.py` içindeki servisler `Employee.select_for_update` kullanırken talep oluşturma CRUD yolundan geçiyor).
- Öneri: `LeaveRequestResource.after_save` veya form kaydı içinde çalışan satırını kilitleyip kotayı yeniden kontrol edin (sistemin diğer yerlerindeki "kilit altında yeniden doğrula" deseni).

### F-181 Görev kontrol listesi "başlamış mı" kontrolü kilit öncesinde: tik ile eşzamanlı kayıt işaretli satırları siler

Önem: **Orta** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-4`
- Dosyalar: `tasks/forms.py:224-232`, `core/crud.py:801-833`, `core/crud.py:362-367`, `tasks/services.py:170-186`
- Açıklama: `TaskChecklistFormSet.clean` "satırlardan biri işaretlendiyse liste değiştirilemez" kuralını formset doğrulamasında (kilit öncesi) kontrol ediyor. `RowListView` formset'i doğruladıktan sonra görevi kilitler ve `RowList.save` tüm satırları `delete()` + `bulk_create` ile değiştirir. Doğrulama ile kilit arasında biri `tasks.services.tick` ile bir satırı işaretlerse (tick de aynı görevi kilitler, ama sırada beklemez) görev sürümü `tick` tarafından arttırılmadığı için (`item.save(update_fields=['done_at','done_by'])`, task.version değişmiyor) `RowListView`'in sürüm kontrolü de bunu yakalamaz; işaretleyen kişi ve zaman bilgisi silinir. Bu, kodun kendi yorumunda anlatılan TSK-11 hatasının geri dönüşü.
- Kanıt: `tick` yalnızca `item.save(update_fields=['done_at', 'done_by'])` yapar ve `Task.version` arttırmaz; `TaskChecklistFormSet.clean` kontrolü kilit dışındadır; `RowList.save` satır 364 `cls.rows(obj).delete()`.
- Öneri: "başlamış mı" kontrolünü `RowList.save` içinde (kilit altında) tekrarlayın veya `tick`'te görev sürümünü arttırın.

### F-182 TimescaleDB hypertable (water_measurements) için yedek/geri yükleme özel adımları belgelenmemiş

Önem: **Orta** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-12`
- Dosyalar: farm/migrations/0014_water.py:91-103, core/migrations/0001_timescaledb.py, docker-compose.yml:6
- Açıklama: Hypertable'lı veritabanı pg_dump ile geri yüklenirken `timescaledb_pre_restore()`/`timescaledb_post_restore()` gerekir; imaj sürümü (`2.17.2-pg17`) sabitlenmiş ama yedek/geri yükleme aynı veya uyumlu TimescaleDB sürümü gerektirir; bu hiçbir yerde yazılı değil. Ayrıca birincil anahtar (id, measured_at) olarak elle değiştirildi (Django durumu `id` der), yedekten geri yüklenen şema ile `makemigrations` uyumu test edilmeli. Veri saklama (retention) ve sıkıştırma politikası yoktur; 90 günlük chunk'lar süresiz büyür (miktar düşük, sadece bilgi).
- Kanıt: `create_hypertable('water_measurements', by_range('measured_at', INTERVAL '90 days'))`; `reverse_sql=migrations.RunSQL.noop` (geri alma sırasında hypertable ayrıca dönüştürülmez, CreateModel tersi tabloyu siler); 'timescaledb_pre_restore' için repo araması boş.
- Öneri: Runbook'a pre/post_restore adımlarını, sürüm eşleşmesi gereksinimini ve bir geri yükleme testini ekleyin.

### F-183 İzleme duvarının `change_token`/`audit.revision()` mekanizması audit log'un eksiksizliğine ve uygulama saatine bağlı

Önem: **Orta** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-14`
- Dosyalar: core/audit.py:127-141, monitoring/read.py:459-470, core/tests.py:198-200
- Açıklama: Duvar sayfası "bir şey değişti mi?" sorusunu yalnızca `audit_log` üzerinden (en yeni `created_at` + son 5 dakikadaki satır sayısı) yanıtlıyor. Bu, audit log'u bir değişiklik veriyolu yapıyor: log'lanmayan bir yazma (13-9) veya log satırı üretmeyen değişiklik (`record_update` fark yoksa `None` döner) duvarı güncellemez; `created_at` uygulama saatinden ve satır oluşturulurken verildiği için, 5 dakikadan (`LATE_COMMIT`) uzun süren bir transaction'ın geç commit olan satırı belirteci hiç değiştirmez (kod yalnızca "5 dakika içindeki geç commit"i yakalıyor); birden çok sunucu arasında saat kayması da sıralamayı bozar. Test dosyası bu sınırı kabul ediyor.
- Kanıt: `LATE_COMMIT = timedelta(minutes=5)` ve `recent = AuditLog.objects.filter(created_at__gte=newest - LATE_COMMIT, ...)` (audit.py:127, 140); test: "a write that is not logged is not seen" (tests.py:198).
- Öneri: Değişiklik belirteci için `audit_log` yerine ayrı bir sayaç/sequence (ör. `pg_current_xact_id`/versiyon tablosu) kullan; en azından zaman damgasını DB'den ata ve sınırı belgele.

### F-184 BtreeGistExtension geri alma ve hr 0002'nin uzantıya sahipliği tutarsız

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-1`
- Dosyalar: farm/migrations/0015_feeding_protocols.py:25, hr/migrations/0002_people.py:21, hr/migrations/0005_leave.py:139, experiments/migrations/0001_initial.py:2
- Açıklama: `btree_gist` uzantısını farm 0015 `BtreeGistExtension()` ile (geri alınca `DROP EXTENSION`) oluşturuyor; hr 0002 ise aynı uzantıyı `CREATE EXTENSION IF NOT EXISTS` ile, `reverse_sql=noop` olarak ayrıca oluşturuyor ve hr 0002/0005/0006 exclusion constraint'leri uzantıya bağlı. hr, farm 0015'e bağımlı değil (yalnızca farm 0004). farm 0015 geri alınırsa `DROP EXTENSION` hr'nin exclusion constraint'lerine bağımlılık nedeniyle hata verir (hr geri alınmadıkça). Uzantının "sahibi" belirsiz; sıra bağımsız olduğundan taze kurulumda hangisinin oluşturduğu rastgele.
- Kanıt: farm 0015:25 `BtreeGistExtension()`; hr 0002:21 `RunSQL('CREATE EXTENSION IF NOT EXISTS btree_gist', reverse_sql=migrations.RunSQL.noop)`; experiments 0001:2 yorumu "farm 0015 creates the extension ... reversing that would drop it".
- Öneri: Uzantıyı tek yerde (örn. core, timescaledb gibi) oluşturup farm 0015 ve hr 0002'yi ona bağımlı yapmak; farm 0015'in reverse'ünü noop yapmak.

### F-185 CI / dağıtım yönergesi yok: migrate tek satır, yedek/kilit/geri alma planı belirtilmemiş

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-12`
- Dosyalar: README.md:2984, docker-compose.yml, (yok) .github/workflows
- Açıklama: Depoda CI iş akışı dizini (.github/workflows) yok; README yalnızca `manage.py migrate` ve "timescaledb extension'ı etkinleştirir" diyor. `CREATE EXTENSION timescaledb`/`btree_gist` süper kullanıcı veya trusted yetkisi gerektirir (core 0001:9, hr 0002:21, farm 0015:25); uygulama kullanıcısı kısıtlıysa migrate yarım kalır. Prod için migrate öncesi yedek, `sqlmigrate` incelemesi, `lock_timeout`, `makemigrations --check` ve `migrate --check` adımları dokümante edilmemiş. 12-backup-restore bulgularıyla ilişkili.
- Kanıt: README.md:2984 `manage.py migrate # also enables the timescaledb extension`; `ls .github/workflows` yok.
- Öneri: Dağıtım kılavuzu + CI'da (taze DB'ye migrate, geri alma döngüsü, `makemigrations --check`).

### F-186 audit_log üzerinde tam-tablo taramalı DDL ve append-only trigger kilitleme/engel riski

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-6`
- Dosyalar: core/migrations/0007_audit_severity.py:18-27, core/migrations/0003_audit_log_append_only.py:4-24
- Açıklama: `audit_log` en hızlı büyüyen, silinemez tablodur. 0007 `AddIndex` (CONCURRENTLY değil: yazmaları bloklar) ve `AddConstraint(CheckConstraint)` (tüm tabloyu tarayıp ACCESS EXCLUSIVE tutar) çalıştırıyor. Ayrıca 0003 tetikleyicisi her UPDATE/DELETE'i reddettiği için audit_log üzerinde herhangi bir gelecek veri migration'ı (backfill, `severity` düzeltme) trigger'ı geçici devre dışı bırakmadan başarısız olur; bunun için standart bir yardımcı/yönerge yok (yalnızca monitoring 0002 ve reports 0005 elle çözüyor).
- Kanıt: 0007:20-27 AddIndex+AddConstraint; 0003:10-12 `BEFORE UPDATE OR DELETE ... RAISE EXCEPTION`.
- Öneri: Büyük tabloda `NOT VALID` + ayrı `VALIDATE CONSTRAINT`, `AddIndexConcurrently` (atomic=False) kullanmak; trigger'lı tablolar için veri migration kılavuzu yazmak.

### F-187 büyüyen defter/log tabloları için saklama/bölümleme stratejisi yok

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-6`
- Dosyalar: core/models.py:162, farm/models/stock.py:341, messaging/models.py:112, farm/migrations/0014_water.py
- Açıklama: Tek hypertable `water_measurements` (90 günlük chunk). Retention/compression politikası yok; `audit_log` UUIDv4 PK'lı sade tablo ve silinemez olduğu için budanamaz; `stock_movements`, `messages` sınırsız büyür. UUIDv4 PK rastgele B-tree ekleme maliyeti getirir. Ölçek MVP için küçük olabilir (güven orta).
- Kanıt: `create_hypertable('water_measurements', by_range(...))` tek çağrı; `add_retention_policy`/`add_compression_policy` aramasında sonuç yok; audit_log için hypertable/partition yok.
- Öneri: Gereksinime göre compression/retention kararını belgele; audit_log için zaman bölümleme (partition) düşün.

### F-188 Tedavi son günü değişikliği tank kilidi almıyor: hasat çekilme (withdrawal) kontrolüyle yarışır

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-1`
- Dosyalar: farm/health/services.py:218-242, farm/stock/services.py:143-146, 200-210
- Açıklama: Hasat (`_commit`) tankları kilitleyip ilaç çekilme süresini bu kilit altında değerlendiriyor; `record_treatment` de tankları kilitliyor. Fakat `change_last_day` yalnızca `Treatment` satırını kilitliyor, tankları değil. Eşzamanlı bir hasat, çekilme süresi uzatılmadan önceki durumu görüp kaydedilebilir; sonuç yasal/gıda güvenliği açısından yanlış onaylı hasat.
- Kanıt: `Treatment.all_objects.select_for_update(of=('self',)).get(...)` (health/services.py:220-221); `locked(Tank, ...)` hasatta (stock/services.py:144-145), `check.assess(...)` kilit sonrası (stock/services.py:208).
- Öneri: `change_last_day` ve `void_treatment` içinde de aynı sırayla (`locked(Tank, ...)`) tankları kilitle.

### F-189 Rapor dondurma (`submit`) READ COMMITTED altında yalnızca rapor satırını kilitliyor; çok sorgulu hesap tutarsız okuyabilir

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-3`
- Dosyalar: reports/services.py:41-100, config/settings.py:121
- Açıklama: `compute.compute(current)` birçok tabloyu ayrı sorgularla okur; izolasyon seviyesi varsayılan (READ COMMITTED), kaynak kayıtlar kilitli değil. İçerik özeti (`content_sha256`) kullanıcının gördüğüyle karşılaştırılıyor, ama hesap sırasında araya giren geriye dönük bir kayıt aynı hesabın iki parçasını farklı durumlarda okutabilir; dondurulan snapshot hiçbir tekil zamanı temsil etmeyebilir.
- Kanıt: `current = Report.objects.select_for_update().get(...)` (50-51), `result = compute.compute(current)` (61), izolasyon ayarı yok (settings.py:121 civarı yalnızca `CONN_MAX_AGE`).
- Öneri: `submit` içinde `REPEATABLE READ` kullan (ya da hesabı tek anlık görüntüde çalıştır) ve `compute`'un iki kez çalıştırılmasını (satır 70) tek hesapla birleştir.

### F-190 Yumuşak silme planı alt kayıtları kilitlemiyor; bayat nesneler `save()` ile tüm alanları geri yazıyor

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-6`
- Dosyalar: core/softdelete.py:171-186, core/models.py:52-58, core/crud.py:769-790
- Açıklama: `DeleteView.post` yalnızca üst kaydı kilitler; `plan_delete` çocuk kayıtları kilitsiz okur, `execute` bunlara `soft_delete` (tam `save()`, `version += 1`) uygular. Eşzamanlı çocuk düzenlemesi sessizce ezilebilir (son yazan kazanır, sürüm kontrolü yok) ve plan sonrası eklenen çocuk üstte silinmiş ebeveyne bağlı kalır (10-6 ve 11-7 ile ilgili).
- Kanıt: `plan = plan_delete(obj)` / `softdelete.execute(plan, request.user)` (crud.py:779-784); `self.save()` (models.py:58).
- Öneri: Plandaki kayıtları `select_for_update` ile yeniden oku ve `soft_delete`'i `update_fields` ile sınırla; `restore` içinde de kilit + `is_deleted` yeniden doğrulama ekle.

### F-191 Envanter feeding çekimi, sitesi olmayan departmandaki ünitelerin yemini sessizce yok sayar

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-2`
- Dosyalar: inventory/read.py:59-66; farm/models/production_department.py:45-47
- Açıklama: `_feeding` yalnızca `unit__production_department__site__isnull=False` olan beslemeleri toplar. `ProductionDepartment.site` null olabilir (site silinince SET_NULL, "orphaned"). Böyle bir departmanın ünitelerindeki besleme kayıtları ne siloya yansır ne de "karşılanmayan besleme" (uncovered) olarak raporlanır; envanter "stokta" göründüğünden fazla yem sayar. Site silme engeli (`Site.delete_blockers`, farm/models/site.py:116-122) yalnızca canlı StockMovement'a bakar, yani sitesiz departmanlar yalnızca stoksuz ünitelerle ulaşılabilir; yine de kod yolu savunmasız ve diğer okuyucular (`site_today`, farm/stock/dates.py:17-19) sitesiz durumu açıkça ele alırken bu filtre ele almıyor.
- Kanıt: `FeedingRecord.objects.filter(feed_id__in=feed_ids, unit__production_department__site__isnull=False)` (inventory/read.py:62).
- Öneri: Sitesiz besleme sayısını ayrı raporla (uyarı) ya da `check_inventory`'ye "sitesi olmayan departmanda besleme" kuralı ekle.

### F-192 Gerçek (tartılmış) kg ile defter kg'ı iki ayrı doğruluk kaynağı; sapma hiçbir yerde kontrol edilmiyor

Önem: **Orta** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-3`
- Dosyalar: farm/models/stock.py:341-344, 352-357; farm/stock/read.py:396-401; farm/feeding/fold.py:240; reports/compute/biomass.py:104-112
- Açıklama: Ölü/hasat/teslimat satırı hem defter gramı (fold: ortalama ağırlıkla çıkış) hem `measured_weight_kg` taşır. Raporlar (`Movement.kilos`) ölçülen kg'ı, stok bakiyesi/biyokütle ise defter gramını kullanır; beslemeyi izleyen yürüyüş (feeding fold) "çıkan biyokütle" için ölçülenı kullanır. Aynı hasat için üç tüketici iki farklı kg görebilir. Ölçülen kg ile `count × defter ortalaması` arasında makullük/sapma eşiği veya uyarı yok (yalnızca `measured_weight_kg > 0`). Biyokütle raporunda "harvested.slaughter_weight_kg" ile kapanış `stock.biomass_kg` bu yüzden tutarlı toplanmayabilir.
- Kanıt: `measured = ... if line.measured_weight_kg is None else line.measured_weight_kg * 1000` (feeding/fold.py:240); `Movement.kilos` (stock/read.py:397-401); CHECK `_check('measured', ...)` yalnızca işaret/tür.
- Öneri: Ölçülen/defter oranı için kayıt anında uyarı (örn. ±%25) ve raporda sapmayı gösteren satır; ya da ölçülenı defterin tek gerçeği yapan tasarım kararı belgele.

### F-193 Gün sonunda unit'te olmayan batch'in o günkü yemi tahmini ağırlığa ve hesaplanan rasyona yansımıyor

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-4`
- Dosyalar: farm/feeding/projection.py:341-350 (`Projector.day`), farm/feeding/fold.py:210-220 (`_allocate`), farm/feeding/projection.py:191 (`UnitDay.fed_kg`)
- Açıklama: Yem payı gün başındaki batch'lere dağıtılır (`_allocate`, `start`), ama `Projector.day` yalnızca gün SONUNDA ünitede sayısı > 0 olan paylar için döner (`if unit != unit_id or not share.count: continue`). Gün içinde tamamen başka üniteye transfer edilen (veya hasat edilen) batch gün başında yemlenmiş olsa bile bu yem o batch'in `Track`'ine büyüme olarak eklenmez; transfer edilen balıkların `moved` track'i yemden önce kopyalandığı için yem hiç kredilendirilmez. Sonuç: tahmini ağırlık düşük kalır, `UnitDay.fed_kg` (kayıt toplamı) o batch'in payını içerirken `calculated_kg` (yalnızca gün sonu share'leri) içermez; by-day sapma yüzdesi (deviation) şişer.
- Kanıt: `if unit != unit_id or not share.count: continue` (projection.py:341); `fed_kg` tüm üretim kayıtlarını toplar (projection.py:191-193); `_allocate` start-of-day biyokütle ile böler (fold.py:210-220).
- Öneri: Gün başı payı olan ama gün sonu sayısı 0 olan batch için de yemi kredilendirin (veya payı gün sonu mevcut balıklara/kaybolan track'e taşıyın) ve `fed_kg` ile `calculated_kg` aynı batch kümesini kullansın. Davranışı kapsayan bir test ekleyin.

### F-194 Geçmiş günlerin oran/tahmin değerleri sonradan girilen veriyle değişiyor; düzenleyici biyokütle raporuna sızıyor

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-6`
- Dosyalar: farm/feeding/read.py:108-129 (`policy`), farm/forms/feeding_protocol.py:250-256 (`within_window`), reports/compute/biomass.py:130-155 ve 144-175
- Açıklama: Oranlar ve tahmini ağırlık saklanmıyor, her okumada mevcut atamalar + su örneklerinden yeniden hesaplanıyor. Atama `valid_from` geçmişe STOCK_BACKDATE_DAYS (31) gün kadar girilebiliyor; geçmiş gün sıcaklığı da sonradan girilen/iptal edilen örneklerle değişiyor. README "geçmiş günlerin oranı değişmez" diyor, ama yalnızca tablonun değişmediği doğru; atama ve sıcaklık değişebiliyor. Aylık biyokütle raporunda PROJECTED yöntemi bu hesaba dayanıyor; `scope()` parmak izi atamaları, kayıtları ve yemleri kapsıyor ama sıcaklıkları kapsamıyor (kod yorumu bunu kabul ediyor), yani sonradan girilen bir geçmiş sıcaklık raporun biyokütle rakamını parmak izi değişmeden değiştirebilir.
- Kanıt: `book.at(unit, now if day >= today[unit_id] else end_of(day, unit))` (read.py:123); `within_window` 31 gün geriye izin verir; `scope` docstring: "the temperatures it also reads are the water module's, and a past sample voided later is shown by the page's own comparison, not by this fingerprint" (biomass.py:130-134).
- Öneri: Gönderilmiş rapor için kullanılan projeksiyon girdilerini (günlük sıcaklık, atama) raporla birlikte dondurun veya parmak izine ekleyin; ya da PROJECTED yöntemini onaylı rapora koymadan önce kullanıcıdan açık onay isteyin.

### F-195 Geriye dönük girilen tedavi, zaten yapılmış hasatla çakışmayı yakalamıyor

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-3`
- Dosyalar: `farm/health/services.py:182-196`, `farm/health/withdrawal.py:277-304`, `farm/handling/check.py:236-245`
- Açıklama: Arınma denetimi yalnızca hasat kaydı sırasında çalışır (`WITHDRAWAL_KIND = HARVEST`). Tedavi kaydı geriye dönük (31 güne kadar) girilebilir ve yalnızca başlangıç gününde balık olması aranır. Aynı partinin tedavi gününden sonra ama kayıttan önce hasat edilmiş olması (yani ilaçlı balığın yiyeceğe gitmiş olması) bildirilmez; tedavi kaydı sessizce başarılı olur ve gıda güvenliği ihlali hiçbir ekranda işaretlenmez. Stok servisi ters yönü (tedaviyi boşta bırakacak stok işlemi) reddediyor, bu yönün karşılığı yok.
- Kanıt: `services.py:192-194` yalnızca `_has_fish(unit, start_date, 'treatment')`; `withdrawal.py:155` `holds_on(day)` yalnızca sorulan gün için çalışır; hasat sonrası tarama yok.
- Öneri: Tedavi kaydında, tedavi penceresi ile arınma süresi içinde parti için kayıtlı hasat olup olmadığını denetle ve kritik uyarı/onay iste; ya da `check_withdrawal` benzeri bir rapor ekle.

### F-196 Arınma süresi değişebilen referans verilerden anlık hesaplanıyor; tedaviye anlık görüntü yok

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-4`
- Dosyalar: `farm/models/health.py:202-215`, `farm/health/withdrawal.py:68-85,218-238`, `farm/models/species.py:118-121`,
- Açıklama: `farm/forms/health.py:96-152` Tasarım gereği hiçbir şey saklanmıyor (`HLT-02` düzeltmesi); ancak bir tedavi kaydı, o günkü ilaç `MedicineWithdrawal` satırı, `safety_margin_pct` veya türün `withdrawal_temperature_c` değerinin kopyasını tutmaz. İlacın arınma satırı düzenlenir/silinirse (satır listesi toptan değiştirilir, `MedicineWithdrawal` modelinde güncelleme ve soft-delete sütunu yok) devam eden ve geçmiş tüm tedavilerin arınma bitişi geriye dönük değişir; satır silinirse süre "bilinmiyor"a döner, marj/gün 0 yapılırsa süre kısalır. Hasat onay kaydı (`HandlingAcknowledgement`) yalnızca hasat anında gösterileni saklar; tedavi anındaki kural saklanmaz. Denetimde "o gün hangi arınma kuralı geçerliydi" sorusu cevaplanamaz. Değişikliklerin denetim günlüğüne `RowList` üzerinden yazıldığı bu incelemede doğrulanmadı.
- Kanıt: `models/health.py:208-211` ("no update or soft-delete columns"), `withdrawal.py:218-238` kuralı her okumada `MedicineWithdrawal.objects` üzerinden çözer.
- Öneri: Tedavi kaydında kullanılan kuralın (gün, derece-gün, marj, tür, varsayılan sıcaklık) özetini saklamayı veya kural değişikliklerini versiyonlamayı değerlendir; ilaç arınma satırı değişiklikleri için ayrı yetki ve kritik günlük.

### F-197 Eldeki (31 günden eski) balık stoğu sisteme doğru tarihle girilemiyor

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-1`
- Dosyalar: farm/stock/dates.py:61-73, farm/stock/services.py:249 (check_date), config/settings.py:215-217, farm/management/commands/
- Açıklama: Her operasyon (stocking dahil) `STOCK_BACKDATE_DAYS = 31` günden geriye tarihlenemiyor; bir `input` yeni Batch yarattığı için `Batch.input_date` de aynı pencereye hapsoluyor. Repoda toplu içe aktarma/açılış bakiyesi komutu yok (yalnızca check_stock ve check_withdrawal). Sisteme geçişte mevcut balık, gerçekte 31 günden eski olsa bile yakın bir tarihle girilmek zorunda.
- Kanıt: dates.py:66-73 `if day < site_earliest(site): raise ValidationError(...)`; settings.py:217 `STOCK_BACKDATE_DAYS = 31`; commands/ altında yalnızca check_stock.py ve check_withdrawal.py. - Etki: yanlış stocking tarihi, "days stocked", survival, year_class/rapor dönemi ve beslenme/projeksiyon başlangıcı bozulur; Batch kodu (B-YYYY-) yanlış yıla düşer.
- Öneri: açılış bakiyesi için ayrı, loglanan ve yetkisi sınırlı bir "devir/import" operasyonu veya yönetim komutu tanımlayın; pencereyi yalnızca günlük operasyonlara uygulayın.

### F-198 Survival/mortality yalnızca "birim içi kalış" bazında; transfer sonrası batch yaşam boyu mortalitesi ve transfer çıkışı yansımıyor

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-7`
- Dosyalar: farm/stock/fold.py:80-85,135-143,171-174, farm/stock/read.py:213-215,308-313
- Açıklama: `Share.fish_in` yalnızca varışlarla (input, transfer_in, up-adjustment) artar; transfer_out/harvest `fish_in`'i düşürmez. Kısmi transferden sonra kaynak birimde `mortality = deaths / fish_in` payda olarak ayrılan balığı da içerir (risk altındaki gerçek stok daha az). Hedef birimde ise `fish_in` yalnızca gelenler; kaynakta transferden önceki ölümler batch'in yaşam boyu oranına yansımaz. Birim boşalıp yeniden dolunca sayaçlar sıfırlanır. Bu, owner decision Q2'nin kapsamı içindedir ama "survival" etiketiyle yaşam boyu üretim performansı gibi okunabilir.
- Kanıt: fold.py:174 `share.fish_in += k` (yalnızca arrival dalı); :171 sıfırlama; read.py:309 `HUNDRED * (1 - Decimal(self.deaths) / self.fish_in)`. - Etki: bölünmüş/transfer edilmiş batch'ler için mortalite/survival yanıltıcı; karşılaştırmalı performans raporlaması hatalı olabilir.
- Öneri: batch bazında (birimlerden bağımsız) kümülatif survival ekleyin ve birim metriğini "bu kalıştaki" olarak etiketleyin; payda için ortalama/başlangıç stoğu tanımını netleştirin.

### F-199 Sayım, formdaki liste dışında kalan lotları sessizce 0 yapıyor (yarış / eski form)

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-3`
- Dosyalar: inventory/fold.py:156-167, inventory/services.py:321-329, inventory/views.py:349-388
- Açıklama: Sayım "tüm lokasyon" semantiğinde: listelenmeyen her kova 0'lanıyor. Form, sayım ekranı açıldığındaki kitap ile doldurulur; ekran açıkken (veya geriye dönük günde) aynı lokasyona yapılan başka bir teslimat/transfer sayım satırlarında olmadığı için kayıt anında 0'a düşer. Sunucu, formun gördüğü kitap ile kayıt anındaki kitabı karşılaştırmıyor; uyarı/ret yok. Değişiklik, aynı gün/gün-sonu sayımı ile fark (variance) olarak görünür ama yeniden hesaplanabilir veri kaybı yerine fiziksel stokta gerçek bir sıfırlama yaratır (void ile geri alınabilir).
- Kanıt: `found.get(bucket, ZERO)` ile listede olmayan kova ZERO; `services.count` satırları yalnız POST'tan; `_items_at(location)` kilitleri formdan sonra alınan kitapla ilişkisiz.
- Öneri: Forma kitap-hash/son hareket zamanı koyup uyuşmazlıkta reddet veya "listede olmayan N kova 0 olacak" onayı iste.

### F-200 Kitap (feeding tahmini) 0 gösterirken fiziksel stok var: issue/write-off/iade/transfer diyaloğu o lotu hiç sunmuyor

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-5`
- Dosyalar: inventory/views.py:318, inventory/forms.py:231-247, inventory/read.py:127-148, inventory/fold.py:222-229
- Açıklama: Departure diyaloğundaki kova listesi `read.buckets()` (kitap = fiziksel - feeding'in çektiği) ve `quantity > 0` ile sınırlı. Yem tüketimi tahmini (hangi lota denk geldiği bilinmiyor) süresi geçmiş/yanlış lotu "tüketilmiş" gösterirse, fiziksel olarak rafta duran bu lot için imha (write-off, expired) kaydı girilemez; tek çıkış sayım + "bulunan lot". Servis fiziksel kontrol yaptığı için asıl tutarsızlık UI seçim katmanında. Ayrıca departure miktarı fiziksel stoğa kadar kabul edilirken ekranda kitap miktarı gösteriliyor (büyük kayıt kabul edilebilir).
- Kanıt: `buckets = [row for row in read.buckets() if row.quantity > 0]`; servis `physical()` ile doğruluyor (services.py:198-205).
- Öneri: Fiziksel > 0 olan kovaları da listele (kitap farkını göstererek) ya da bu durumda sayım yoluna açık yönlendirme yaz.

### F-201 Tek bir bozuk seri tüm Görevler sayfalarını ve overview'ı düşürebilir

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-2`
- Dosyalar: `tasks/services.py:257-262`, `tasks/resources.py:92,226`, `tasks/views.py:142`
- Açıklama: `materialise_due` her seri için `materialise` çağırır, istisna yakalanmaz. Bir serideki hata (ör. IntegrityError, veri bozukluğu) liste sayfalarında ve üretim overview'ında 500'e yol açar; TSK-14 "bir şablon koşuyu zehirlemesin" hedefi yalnızca transaction düzeyinde karşılanmış, hata izolasyonu yok.
- Kanıt: `return [task for series in behind for task in materialise(series)]` try/except yok.
- Öneri: Seri başına try/except + log; hatalı seri sayfaları engellemesin.

### F-202 `withdraw` kilitsiz aday listesiyle sert silme yapar (yarış)

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-5`
- Dosyalar: `tasks/services.py:265-271`, `tasks/models.py:424-437`
- Açıklama: `Task.planned` adayları (`version=1`, dokunulmamış) kilitsiz okur; sonra her biri `task.delete()` (sert silme, checklist/atamalar CASCADE) ile silinir. Aradaki sürede biri görevi başlatır/tamamlarsa (`start`/`complete` task'ı kilitler ve version artırır) görev yine silinir, kaydı yalnızca audit'te kalır.
- Kanıt: `for task in Task.planned(...)`: `audit.record_delete`; `task.delete()` yeniden `version`/status doğrulamadan.
- Öneri: Silmeden önce görevi `select_for_update` ile kilitleyip planned koşulunu tekrar doğrula.

### F-203 Production manager preset'inde vardiya temizleme ve yoklama giriş/düzeltme yetkisi yok

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-6`
- Dosyalar: hr/roles.py:24-34, hr/services.py:177-180, hr/services.py:402-418, hr/resources/attendance.py:25-28
- Açıklama: Preset `view/add/change_shiftassignment` verir ama `delete_shiftassignment` yok; CLEAR `hr.delete_shiftassignment` ister, yani yönetici hücreyi temizleyemez, sadece "off" yapabilir (plan kaydı "planlanmadı"ya dönmez). `add_attendancerecord`/`change`/`delete` de yok: docstring "Today & attendance" der, fakat `enter_presence` ve yoklama düzeltme/geçersiz kılma (resource docstring) yönetici için kapalıdır; unutulan clock-out'u (25-2) lead düzeltemez.
- Kanıt: roles.py:24-27 izin listesi; services.py:179 `'hr.delete_shiftassignment'`; services.py:405 `hr.add_attendancerecord`.
- Öneri: Hedeflenen davranış belgelenmeli ya da preset'e ilgili izinler eklenmeli (tasarım kararı olabilir, confidence orta).

### F-204 Yıllık izin kotası denetimi eşzamanlılığa karşı korumasız

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-9`
- Dosyalar: hr/forms/leave.py:95-101, hr/leave.py:57-64
- Açıklama: Kota yalnızca form `clean` içinde okunup kontrol edilir; çalışan satırı kilitlenmez (plan/yoklama servislerinin aksine). Çakışmayı exclusion constraint önler ama iki ayrı tarih aralığındaki eşzamanlı talepler toplamda `annual_days`'i aşabilir. Ayrıca `needs_approval=False` ve `annual_days=None` türü sınırsız kendi kendine onay verir (tasarım gereği ama kayda değer).
- Kanıt: forms/leave.py:97 `used = leave.used(...)` kilitsiz; services.py'de izin oluşturma servisi yok (form kaydı doğrudan).
- Öneri: Kayıt anında `select_for_update` + yeniden doğrulama veya servis katmanına taşı.

### F-205 `no_longer_match` eski dönemleri "değişemez" varsayarak atlıyor; ana veri değişiklikleri ve stok-dışı kayıtlar kaçar

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-3`
- Dosyalar: reports/due.py:402-415, config/settings.py:217, reports/compute/lice.py:100-110, reports/compute/stock.py:62-77
- Açıklama: Dönemi `STOCK_BACKDATE_DAYS` (31 gün) penceresinden eski filed raporlar hiç okunmaz ve `period_start` ~1 yıldan eski raporlar listeden tamamen düşer. Ancak parmak izine giren satırlar yalnız stok işlemleri değil; `sites` (organisation_number, lokalitetsnummer), `species` (official_code), `batches` (year_class), `units`, `medicines` gibi ana veriler de var (`scope_rows`, `lice.scope`) ve bunlar geriye dönük pencereye bağlı değil. Yani türün resmî kodu veya site numarası düzeltilirse, eski filed raporlar "kayıtlar artık eşleşmiyor" uyarısı vermez. Kimlik değişikliği (`IDENTITY_LEAVES`) tespiti yalnızca raporun detay sayfasında (`differences`) çalışır, listede değil.
- Kanıt: due.py:413 `if report.is_superseded or report.period and report.period.end < recent: continue`.
- Öneri: Pencere optimizasyonunu yalnız stok/ledger kaynakları için uygula; ana veri tablolarını (site, species, medicine, batch) pencereye bakmadan karşılaştır, ya da ana veri değişince ilgili raporları işaretle.

### F-206 Parmak izi kapsamı raporun okuduğu bazı satırları içermiyor

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-4`
- Dosyalar: reports/compute/lice.py:100-110 (scope) ile lice.py:176-179, 209-227; reports/compute/biomass.py:117-130
- Açıklama: Lice hesabı `_coverage` içinde haftadan önceki son sayımları (`LiceCount ... date__lt=period.start`) ve `_all_to_be_slaughtered` içinde `HandlingPlanItem` kayıtlarını okur; `lice.scope` yalnızca hafta içi sayımları, hafta işlemlerini, ilaçları ve su örneklerini içerir. Önceki bir sayımın iptali/değişmesi ya da bir kesim planının değişmesi sayım "gerekli" kararını (`problems`) değiştirir ama filed raporun "eşleşmiyor" durumu tetiklenmez. Biomass için sıcaklıkların kapsam dışı olduğu kod yorumunda kabul edilmiş (biomass.py:116-119).
- Kanıt: lice.py:177 `LiceCount.objects.filter(unit__in=held, date__lt=period.start)`; lice.scope listesinde bu sorgu yok.
- Öneri: `lice.scope`a önceki sayımlar ve ilgili `HandlingPlanItem`'lar eklensin; biomass için sıcaklık kaynağı (water) eklensin veya sınırlama belgelensin.

### F-207 Sağkalım: yabancı parti ve sonradan eklenen (yerine koyma olmayan) tanklarda pay/payda tutarsız

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-3`
- Dosyalar: experiments/read.py:201-212
- Açıklama: `start` yalnızca ilk günün (`began`) hücrelerindeki `count_at_end` ile toplanıyor; `lost` ise `row.batches`'teki tüm partilerin kayıplarını topluyor. `row.batches` sonradan giren (foreign_batch) partileri de içerir; bu partinin başlangıçta payda katkısı 0 iken ölümleri paya yazılır, sağkalım olduğundan düşük (hatta negatif) çıkabilir. Aynı şekilde bir replikata yeni bir tank farklı bir `from_on` ile (yerine koyma değil, ek tank) eklenirse başlangıç sayısına girmez ama kayıpları sayılır. Dokümandaki varsayım yalnızca "yerine koyma".
- Kanıt: `initial = cell.first == began`; `if initial: start += ...`; `lost += sum(... )` koşulsuz partiler üzerinden (read.py:205-210); `row.survival = 100*(start-lost)/start` (211-212).
- Öneri: Kayıpları yalnızca başlangıçta bulunan (start>0) parti/tank çiftleriyle sınırla veya sapma olduğunda değeri "güvenilmez" işaretle; negatif sonuca karşı sınır.

### F-208 Tahsis tekrarlanabilirliği: havuz saklanmıyor, tank kodu değiştirilebilir

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-5`
- Dosyalar: experiments/models.py (allocation_* alanları), experiments/services.py:518-568, experiments/allocation.py:5-26, farm/models/tank.py:333, farm/forms/tank.py:99
- Açıklama: Doküman "aynı havuz ve tohum sonsuza dek aynı yerleşimi verir; hakem tekrarlayabilir" diyor. Yalnızca yöntem+tohum saklanıyor; havuz (özellikle sistem öğeleri, kodu sistem kodu) saklanmıyor, yalnızca sonuç tank yerleşimleri duruyor. Anahtar `sha256("<tohum>:<kod>")` ve tank kodu düzenlenebilir (`fixed_after_creation` yalnızca `kind`) olduğundan kod sonradan değişirse doğrulama bozulur. Havuz yalnızca denetim günlüğündeki "Places" metninden yeniden kurulabilir.
- Kanıt: models.py `allocation_method/seed/note` dışında havuz alanı yok; services.py:534-568 havuz kodları yalnız hesapta kullanılır; allocation.py:17-19 anahtar koddan türer.
- Öneri: Havuz kod listesini (kod anlık görüntüsüyle) deneyde sakla veya tahsis sırasında loga yaz; kodu bir deneyde olan tankta kod değişikliğini engelle.

### F-209 Sorgu NFKC'e normalize edilir ve docstring "saklanan metinler gibi" der;

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-2`
- Dosyalar: knowledge/search.py:92-94, knowledge/extraction.py:50-53, knowledge/models/entry.py:386-390
- Açıklama: Sorgu NFKC'e normalize edilir ve docstring "saklanan metinler gibi" der; ama yalnizca PDF sayfa metni NFKC'lenir. Baslik, ozet, statement, quote, citation elle yazilan metinler normalize edilmez. Yardim metninin kendisi "CO₂" kullanir (forms/entry.py:128): statement'ta "CO₂" yazilirsa vektorde `co₂`, aramada "CO₂" ve "CO2" ikisi de `CO2`'ye indirgenir; eslesme olmaz.
- Kanıt: search.py:94 NFKC; document.py/entry.py'de save/clean icinde normalize yok (yalniz normalise_doi/authors, document.py:38-49). Dokuman "CO2 ile CO₂ bulunur" iddiasi (extraction.py:16) sadece PDF icin gecerli.
- Öneri: Document ve KnowledgeEntry metin alanlarini kaydederken NFKC'le (veya arama vektorunde normalize et); test ekle.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-210 AI asistan katılımı: yazma yolunda asistan yetki/etkinlik denetimi yok

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-13`
- Dosyalar: messaging/services.py:232-248; messaging/models.py:27-43, 82-103; README "AI assistants"
- Açıklama: `post(author, body)` herhangi bir Participant'ı kabul eder; asistanın silinmiş olup olmadığına, sahibinin hâlâ aktif/`USE` iznine sahip olup olmadığına bakmaz (README: "worker checks the owner's permissions" - kural kodda değil, ileride dışarıda). Asistan katılımcısı eklemek için hizmet fonksiyonu yok; `_reachable` yalnız kullanıcıları denetler. Asistan kanala eklendiğinde kanalın tüm geçmişini okuyacak mı (add_members `last_read` ayarlıyor ama okuma sınırı yok) belirsiz; platform yöneticisinin okuyamadığı mesajları asistanın okuyabilmesi gizlilik modelini zayıflatır. `message_posted` yükü yazarın türünü/asistan olduğunu taşımıyor (dinleyicinin yeniden sorgulaması gerekir; asistan-asistan döngüsü koruması tasarlanmamış).
- Kanıt: `post` yalnızca `Participant.objects.filter(pk=author.pk).first()` kontrolü; `Assistant` için `is_deleted`/`owner.is_active` denetimi yok.
- Öneri: `post`ta yazar türüne göre yetki kuralı (asistan etkin + sahip izni), katılma/okuma kapsamı (`visible_from`), olay yüküne `author_kind`, döngü/hız sınırı tasarımı.

### F-211 `message_posted.send` dinleyici hatasında istek 500 olur, ileti kaydedilmiş kalır

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-6`
- Dosyalar: messaging/services.py:246-247; messaging/events.py:10-11
- Açıklama: `on_commit` içinde `Signal.send` (robust değil) kullanılıyor; bir dinleyici (planlanan push/AI dağıtıcı) istisna atarsa istisna, commit'ten sonra istek yoluna çıkar: mesaj yazılı ama kullanıcı 500 görür ve yeniden gönderince tekrar mesaj oluşur. events.py "must not fail the request" der ama kod bunu zorlamaz. Şu an dinleyici yok, bu yüzden gizli.
- Kanıt: `transaction.on_commit(lambda: events.message_posted.send(...))`.
- Öneri: `send_robust` + loglama ya da on_commit(robust=True).

### F-212 Başlık: Yetim departmandaki birimler site bazlı raporlardan ve deniz sitesi kurallarından düşer

Önem: **Orta** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-4`
- Dosyalar: farm/models/site.py:116-122, farm/stock/read.py:75-77, reports/compute/stock.py:24
- Açıklama: Site.delete_blockers yalnızca StockMovement'a bakar. Hareketi olmayan site silinirse birimler canlı kalır, siteleri yoktur; sonra stoklanabilirler (ARRIVAL_STATUSES). Rapor/derleme kodları `production_department__site=site` ile filtrelediği için bu balık hiçbir lokaliteye raporlanmaz; sea_units() de yetim birimi deniz sayamaz (temizleyici balık kuralı değişir). Stok servisinde birimin sitesinin var olduğuna dair kontrol bulamadım.
- Kanıt: services.py'de site kontrolü yok (grep: yalnızca sağlık olayı eşleşmesi, :279); Tank.clean yetim departmanı reddetmez.
- Öneri: Siteyi olmayan departmanın birimlerine stoklamayı reddedin ve/veya Tank/Stock kontrolü ekleyin.

### F-213 IntegrityError yakalayıcıları kısıt adını ayırt etmeden tek bir 'başkası aynı anda yaptı' mesajı veriyor

Önem: **Orta** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-11`
- Dosyalar: hr/views.py, experiments/services.py, farm/resources/feeding_protocol.py, messaging/services.py, farm/feeding/assignments.py
- Açıklama: Bazı yerler doğru yapıyor: hr/services.py:355 ve messaging/services.py:142 kısıt adını (constraint_name) kontrol edip diğerlerini yeniden fırlatıyor, core/crud.py constraint_error ile yalnız bilinen kısıtları eşliyor. Ancak şu yerler her IntegrityError'ı tek bir yarış mesajına çeviriyor ve kaydetmiyor: hr/views.py:86-88 ('Someone planned one of these days at the same time'), experiments/services.py:451, 666, 883 ('A tank was booked to another experiment meanwhile'), farm/resources/feeding_protocol.py:150 ve farm/feeding/assignments.py çağıran view ('Another protocol was assigned...'). NOT NULL/FK/CHECK ihlalleri gibi gerçek hatalar da bu mesajla maskelenir ve günlüğe düşmez. messaging/services.py:112 ise IntegrityError sonrası doğrudan Conversation.all_objects.get(direct_key=key) çağırıyor: ihlal başka bir sebepten ise DoesNotExist (yakalanmamış 500) oluşur.
- Kanıt: hr/views.py:78-88; experiments/services.py:451,666,883; farm/resources/feeding_protocol.py:150; messaging/services.py:105-114.
- Öneri: Ortak bir yardımcıyla constraint_name'e göre ayıklayın, tanınmayanı yeniden fırlatın veya en azından logger.exception ile kaydedin; messaging'de get() sonucunu da koruyun.

### F-214 knowledge: PDF okuma hatasının ham istisna metni veritabanına yazılıp kullanıcıya gösteriliyor; hata kaydı yok

Önem: **Orta** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-8`
- Dosyalar: knowledge/extraction.py, knowledge/models/document.py
- Açıklama: read_pdf geniş 'except Exception' ile f'{type(error).__name__}: {error}'[:500] biçimindeki ham metni text_error alanına yazıyor (knowledge/extraction.py:69-70). Document.text_status mesajı bunu gettext('The text could not be read: %(reason)s') içinde olduğu gibi kullanıcıya gösteriyor (knowledge/models/document.py:254). Sonuçlar: (a) Python sınıf adları ve kütüphane (pypdf) iç mesajları son kullanıcıya sızıyor, çevrilmiyor; (b) hiçbir logger çağrısı yok, bozuk dosya/kütüphane regresyonu operatöre görünmez; (c) 'The PDF is protected by a password.' (satır 62) sabit İngilizce, çeviri sarmalı yok ve veritabanında İngilizce saklanıyor (diğer alanlar için 'English at rest' kuralı var ama burada kullanıcıya olduğu gibi gidiyor). Doğrulanmadı: şablonda başka yerde farklı biçimde kullanılıyor olabilir.
- Kanıt: knowledge/extraction.py:62, 69-70; knowledge/models/document.py:227, 254.
- Öneri: Kullanıcıya sabit, çevrilebilir bir kod/mesaj gösterin; ham metni logger.warning ile kaydedin; _labels içindeki sessiz except (satır 84) için de en azından debug log ekleyin.

### F-215 `withdraw` kilitsiz, bayat "planlı" listeyle görevleri kalıcı siler (cascade ile not/checklist kaybı)

Önem: **Orta** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-1`
- Dosyalar: tasks/services.py:267-273, tasks/services.py:276-287, tasks/models.py:426-435, tasks/models.py:463,491
- Açıklama: `replan` yalnızca seri satırını kilitler. `withdraw`, `Task.planned()` ile (kilitsiz, `list()`) aday listesini okur, sonra her birini `task.delete()` ile SERT siler (AuditedModel soft-delete değil; `Task`'ta `delete` override'ı yok). Bu arada başka bir istek `start/complete/tick/add_note` ile (`_locked(task)` satır kilidi) aynı görevi değiştirmiş olabilir; `delete()` kilidi bekler ve sonra bayat listedeki görevi yine siler. TaskNote ve TaskChecklistItem `CASCADE` olduğu için "kalıcı tutulur" denen notlar (tasks/services.py:~125) ve işaretli checklist silinir; denetim kaydı da ancak silmeden önce yazılmış olur.
- Kanıt: `withdraw` döngüsü `for task in Task.planned(...): audit.record_delete(...); task.delete()`; `planned` koşulu `version=1, status=OPEN`, notsuz/işaretsiz sadece sorgu anında değerlendirilir. Silme sırasında görev kilidi alınmaz veya koşullar yeniden doğrulanmaz.
- Öneri: Silmeden önce görevi `select_for_update` ile kilitleyip `planned` koşullarını yeniden doğrulamak (ya da `planned` sorgusunu `select_for_update(skip_locked=True)` ile yapmak).

### F-216 Etkinlik gunlugu: indekssiz filtreler, her sayfada DISTINCT acilirlar, sinirsiz buyuyen tablo

Önem: **Orta** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-10`
- Dosyalar: core/views.py:36-71, core/models.py:154-200, core/audit.py:130-141
- Açıklama: `user_name` filtresinin indeksi yok; `q` aramasi `entity_label__icontains` (indeks kullanamaz). Her sayfa yuklemesi `users` ve `types` acilirlari icin tum audit_log uzerinde `DISTINCT` sorgusu calistiriyor (`readable.order_by('user_name').values_list(...).distinct()`), `Paginator` ayrica COUNT(*) yapiyor. Tablo yalniz ekleniyor (tetikleyici UPDATE/DELETE'i yasakliyor), saklama/bolumleme politikasi yok; her kayit degisikligi, JSON `changes` ile satir ekliyor. `revision()` iki indeksli sorgu ile iyi tasarlanmis (created_at indeksli), ancak tum izleme ekranlari tarafindan poll ediliyor.
- Kanıt: `'users': readable.order_by('user_name').values_list('user_name', flat=True).distinct()` (core/views.py:66); `entity_type`'a ve `created_at`'e indeks var, `user_name`'e yok (core/models.py:171-196).
- Öneri: Acilir listeleri kucuk bir referans tablosundan/onbellekten besle; `(user_name, created_at)` indeksi ekle; log icin `created_at` bolumleme veya arsivleme stratejisi dusun.

### F-217 Soft-delete plani silinecek kaydin tum su orneklerinin pk kumesini bellekte topluyor

Önem: **Orta** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-11`
- Dosyalar: core/softdelete.py:105-160, core/softdelete.py:177-190
- Açıklama: `_collect` DO_NOTHING iliskilerde `set(model.objects.filter(link=obj)....values_list('pk'))` ve `_keep` icinde `child.objects.filter(<fk>__in=new).values_list('pk')` ile bir birimin/noktanin TUM iliskili kayitlarinin (ornegin binlerce su olcumu) pk'lerini Python kumesine cekiyor; plan onay sayfasi (GET) icin de calistirildigi icin yalnizca "kac kayit korunacak" sayisi icin tum pk'ler tasiniyor. Cascade'de her cocuk icin ayri sorgu (`_collect` ozyinelemeli, N x iliski). `execute` her kayit icin ayri `soft_delete` + `audit.record_delete` (satir basina INSERT).
- Kanıt: `found = child.objects.filter({f'{relation.field.name}__in': new}).values_list('pk', flat=True)` / `_keep(child, set(found), plan)` (softdelete.py:155-156); `plan.kept_records` yalniz `len(pks)` olarak kullaniliyor (`kept` property).
- Öneri: Korunan kayitlar icin yalniz `COUNT` kullan (pk kumesi gerektiren yerde sayfalanmis/sinirli); cascade'i iliski basina tek sorgu ile topla.

### F-218 Poll yogun mimari: DB baglantisi her istekte yeniden aciliyor, oturum DB'de, onbellek yok

Önem: **Orta** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-15`
- Dosyalar: config/settings.py:110-125, config/settings.py:64-78, messaging/views.py:30, config/settings.py:239, monitoring/views.py:128-146, core/audit.py:130-141, frontend/poll.ts
- Açıklama: `CONN_MAX_AGE` varsayilani 0 (istek basina yeni PostgreSQL baglantisi). Istemci poll sikligi: acik konusma 5 sn, konusma listesi 15 sn, menu rozeti 30 sn, izleme ekrani 15 sn. Her poll istegi: oturum sorgusu (DB oturumlari, `CACHES` tanimsiz), kullanici + izin sorgulari (ilk `has_perm`'de 2 sorgu), `audit.revision()` (2 sorgu), kullaniciya ozgu bolum izinleri. Yani bos 204 yaniti bile yaklasik 5-6 sorgu ve yeni bir baglanti. Baglanti havuzu/pgbouncer yapilandirmasi repoda yok; `CONN_MAX_AGE` yorumu yalnizca runserver uyarisi veriyor. (Olumlu: istemci gorunmeyen sekmede poll etmiyor, jitter ve geri cekilme var - frontend/poll.ts:118,152,187.)
- Kanıt: `'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '0'))` (settings.py:121); `CACHES`/`SESSION_ENGINE` ayari yok (settings.py arandi).
- Öneri: Uretimde `DB_CONN_MAX_AGE` veya psycopg pool (`OPTIONS: {'pool': True}`) ac; oturum icin cache/signed-cookie dusun; `revision()` sonucunu process icinde 1-2 sn onbellekle.

### F-219 Stok ve yemleme yazma yolu her islemde ilgili tum gecmisi katliyor (kilit altinda)

Önem: **Orta** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-8`
- Dosyalar: farm/stock/services.py:285-335, farm/stock/services.py:125, farm/stock/services.py:747, farm/feeding/services.py:54-58, farm/feeding/read.py:163-168
- Açıklama: `_validate` her stok operasyonunda birimlerin hic gordugu tum batch'lerin butun defterini, `since=day` sonrasi yemlemeleri ve saglik kayitlarini yukleyip katliyor; bu `select_for_update` kilitleri alindiktan sonra (islem acikken) yapiliyor, dolayisiyla kilit tutma suresi gecmisle buyur ve es zamanli yazmalari bekletir. Yemleme kaydi `book_on(unit, day)` ile birimin tum soyunu katliyor; hata yolunda `book_on` iki kez cagriliyor (`read.book_on(unit, day).has_fish` satir 58).
- Kanıt: `batch_ids = batch_ids | read.batches_ever_in(unit_ids)` / `lines = read.ledger(batch_ids)` (stock/services.py:299-300); `walked = walk(lines, feeding_read.feedings(unit_ids, since=day), ...)` (satir 322-324).
- Öneri: Kilit suresini kisaltmak icin katlama hazirligini kilitten once yap ya da birim basina anlik goruntu tut; `book_on` sonucunu degiskene ata.

### F-220 Yeni yazilan her URL icin yetki taramasi sadece bazi uygulamalarda otomatik

Önem: **Orta** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-7`
- Dosyalar: hr/tests/test_scope.py:144-145, experiments/tests/test_pages.py:403, core/tests_crud_mount.py
- Açıklama: hr, experiments ve core'da URL sayimi/rol matrisi var; farm (1009 test), reports, monitoring, tasks icin "tum URL adlari icin anonim=302, rolsuz=403" tarzi genel bir tarama testi gormedim, yetki testleri elle yazilmis. Yeni eklenen bir view icin yetki testi unutulabilir. (Oranlar: inventory 2/50, knowledge 6/60 yetki-ilgili eslesme; yine de 403 testleri mevcut.)
- Öneri: `get_resolver()` ile tum rotalari dolasip anonim/yetkisiz erisimi dogrulayan tek bir test ve muaf listesi.

### F-221 Modal, `FormData(form)` kullandığı için gönderen düğmenin `name/value` değeri ve `formaction` kaybolur

Önem: **Orta** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-10`
- Dosyalar: `frontend/components.ts:317-322`, `templates/experiments/_places.html:30,50`, `templates/experiments/_design.html:42`, `experiments/resources.py:247`
- Açıklama: Submit dinleyicisi `new FormData(form)` ile POST yapar; `event.submitter` FormData'ya eklenmez. Şablonlarda `name="action" value="randomise|save"` ve `name="_draft"` düğmeleri var; sunucu `request.POST.get('action') == RANDOMISE` ile karar veriyor. Modal içinde açılan formda "Randomise" ile "Save places" ayırt edilemez. Ayrıca `form.action` ve `form.method` okunuyor; `formaction/formmethod` ve `<form method="dialog">` ele alınmıyor. Formun `action` adında bir alanı varsa `form.action` bir elemana dönüşür (DOM clobbering).
- Kanıt: `void this.load(form.action, { method: 'POST', body: new FormData(form) });`. Hangi formların fiilen modalda açıldığı (data-modal bağlantısı) kodda tam doğrulanmadı.
- Öneri: `new FormData(form, event.submitter)` (modern tarayıcılar destekler); `getAttribute('action')` kullan.

### F-222 Duvarda "stale/gone" ve kritik kart bildirimi: yalnızca CSS, canlı bölge yok

Önem: **Orta** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-17`
- Dosyalar: `frontend/poll.ts:143-147`, `static/css/monitor.css:4-8`, `frontend/announce.ts:11-13,289-304`
- Açıklama: Sunucuya ulaşılamadığında (`stale`) ve erişim kaybında (`gone`) uyarı `::before` sözde öğesiyle yazdırılıyor; bu içerik canlı bölge değildir, ekran okuyucuya duyurulmaz ve veri eskirken kullanıcı bunu bilemez. `announce.ts` ise yalnızca "kötüleşen" kartlar için konuşur; ilk yüklemede kritik olan, yeni eklenen (`inserted`) ya da tüm içeriği yeniden yazan yedek yolda (poll.ts:173, `poll:merged` olayı yok) kritik kartlar sessizdir. Kod yorumu bunu bilinçli tasarım olarak belirtiyor, ama çiftlik izleme (su kalitesi alarmı) bağlamında risklidir.
- Öneri: `stale/gone` için `role="status"` canlı bölgesinde çevrilmiş metin; eklenen kritik kartlar için de duyuru düşün.

### F-223 Derleme/test/CI: repo içinde CI tanımı yok, testler Node yoksa atlanıyor, lint yok

Önem: **Orta** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-23`
- Dosyalar: `package.json`, `tsconfig.json`, `tsconfig.test.json`, `README.md:3403-3406`
- Açıklama: Repo kökünde `.github/` ve başka bir CI tanımı yok (`ls -a`). README, Node yokken testin atlandığını, `CI=1` iken başarısız olduğunu söylüyor; yani yerel/Django test çalıştırmasında TypeScript doğrulaması sessizce atlanabilir. `npm run check` ve `npm test` ayrı; ESLint/Prettier yok, `engines` alanı yok (Node sürümü belirsiz; `node --test` glob'u Node 21+ gerektirir). `tsconfig.json` `moduleResolution` belirtmiyor (`module: ES2022` ile varsayılan eski "classic" çözümleme; testte `bundler` kullanılıyor) -> iki yapılandırma farklı çözümleme kullanıyor. `.build/test` içindeki `package.json` `mark-esm.mjs` ile yazılıyor; Windows'ta `node --test ".build/test//*.test.js"` glob'u kabuğa bağlı. `npm test` önizleme/`static/js` çıktısını üretmiyor. (Bu ortamda `npm test` çalıştırılamadı.)
- Öneri: CI iş akışı (`npm ci && npm run check && npm test`), `engines`, `moduleResolution: "bundler"` veya `"node16"`, eslint-typescript.

### F-224 Void (iptal) diyalogları geri alınamazlığı söylemiyor

Önem: **Orta** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-11`
- Dosyalar: templates/farm/stock_void.html:14, farm/health_event_void.html:7, farm/water_void.html:10-12, farm/feeding_void.html
- Açıklama: Metinler "stops counting, stays in the history with its reason" der; geri alma (un-void) olmadığı, düzeltmenin "void edip yeniden girme" olduğu yalnız stok metninde geçer. Water/health/feeding void'de yok. Kod tabanında un-void eylemi yok (grep: unvoid/reinstate yok), admin restore da dışarıda. Stocking void "takes its batch with it" ama etkilenen sonraki operasyonların listesi yalnız "refused" durumunda görünür.
- Kanıt: grep `unvoid|reinstate` sonuçsuz; stock_void.html:14 yalnız stok için "void it and enter it again".
- Öneri: Tüm void diyaloglarında "Bu geri alınamaz; yeniden girmek için ... sayfasını kullanın" cümlesi ortak partial'da; onay butonunda etkilenen kayıt sayısını göster.

### F-225 Form hata mesajları alanlara bağlanmamış; zorunlu alan görsel göstergesi yok

Önem: **Orta** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-2`
- Dosyalar: `templates/registration/_field.html:155-175`, `templates/crud/form.html:24`, `static/css/base.css:67-69,100-106`
- Açıklama: `{{ field.errors }}` alanın yanına düz `<ul class="errorlist">` olarak basılıyor; hata listesine `id` verilip alanın `aria-describedby` değerine eklenmiyor. Yardım metnine `{{ field.auto_id }}_helptext` id'si verilmiş (Django'nun üreteceği describedby ile eşleşir) fakat hatalar için eşdeğeri yok; hata yalnızca kenarlık rengiyle (`.has-error`) ve listeyle işaretleniyor. Ayrıca 32 şablondaki `novalidate` formlarda ve CSS'te zorunlu alan işareti (yıldız/"zorunlu" metni) yok (`required` araması CSS'te boş). Ekran okuyucu kullanıcı hatayı alana odaklanınca duymayabilir; görme engelsiz kullanıcı da hangi alanın zorunlu olduğunu önceden göremez (WCAG 3.3.1, 3.3.2). Django sürümü kurulu olmadığı için `aria-invalid` davranışı çalıştırılarak doğrulanamadı (`poll.ts:288` yalnızca canlı formda elle `aria-invalid` ekliyor).
- Kanıt: `_field.html:172-173` (`help` id'li, `{{ field.errors }}` id'siz); `grep describedby` yalnızca test/ts dışında hiçbir şablonda yok.
- Öneri: Hata listesine `id="{{ field.auto_id }}_errors"` ver, alan widget'ına `aria-describedby` ile ekle (veya form `__init__`'te widget attrs); zorunlu alanlara görünür işaret ve `aria-required` ekle.

### F-226 Yazdirma stili yalniz `hr.css` icinde; regulatory rapor sayfasi menu ve ust cubukla yazdiriliyor

Önem: **Orta** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-3`
- Dosyalar: `static/css/hr.css:41-45`, `static/css/components.css:1296-1298`, `templates/reports/report_print.html:1-19`, `core/crud.py:92`
- Açıklama: `.rail, .topbar, .scrim` gizleme yalniz `hr.css` `@media print` blogunda; `hr.css` sadece HR sayfalarinda yukleniyor. `report_print.html` `app_base.html`'i genisletiyor, bir "Print" dugmesi var, ama `components.css` print blogu yalniz `.regulatory-print .form-actions` gizliyor; sticky `.rail` (100vh) ve `.topbar` ciktida kalir. Yazdirma stili ayrica sayfa-ozel dosyaya gomulu oldugundan tutarsiz.
- Kanıt: `grep "@media print"` -> `components.css:803,1296`, `hr.css:41`; `report_print.html` yalniz `base.css/app.css/components.css` (app_base) yukler.
- Öneri: Kabuk gizleme kuralini `app.css` icine tasi (tum sayfalar icin), `hr.css`'te yalniz HR'a ozgu olanlar kalsin.

### F-227 Planlı hasat gerçekleşince tarih/kesimhane/taşıyıcı tutarlılığı denetlenmiyor; iki ayrı bildirim doğabilir

Önem: **Orta** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-5`
- Dosyalar: `farm/stock/services.py:213-239` (`_fulfil`), `reports/due.py:320-348` (`_slaughter`), `farm/models/harvest.py:248-300`
- Açıklama: `_fulfil` yalnız silinmiş/iptal/tamamlanmış, işlem türü ve (birim, parti) eşleşmesini kontrol ediyor. Planın `date`, `facility`, `transport`, `vessel` değerleri gerçekleşen hasat (`HarvestRecord`) ile karşılaştırılmıyor. `reports/due._slaughter` ise plan haftasını plan kesimhanesine, gerçek hasat haftasını `record.facility`ye yazıyor; ikisi farklıysa aynı hasat için iki ayrı "planlı kesim" bildirimi borçlanabilir ve plan "done" göründüğü halde plan kesimhanesi için hafta açık kalır.
- Kanıt: `_slaughter` plans döngüsü (`item.facility_id`, `item.date`) ve ayrı `HarvestRecord` döngüsü (`record.facility_id`, `record.operation.date`) `weeks` sözlüğünde farklı anahtarlar üretir; `_fulfil` içinde tarih/tesis karşılaştırması yok.
- Öneri: Gerçekleşen farklıysa kullanıcıya uyarı göster ve planı güncelle/yeniden bağla; ya da `_slaughter`'da planı yerine getirilmiş sayıp yalnız gerçek kayda dayan. Davranış kasıtlıysa belgelensin.

### F-228 Site/ProductionDepartment/System durumları (closed/inactive/maintenance) operasyonlarda uygulanmıyor

Önem: **Orta** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-10`
- Dosyalar: farm/models/site.py:26-30, farm/models/production_department.py:40-52, farm/models/system.py:35-56
- Açıklama: `Site.Status` (active/maintenance/inactive/closed) için grep ile yalnızca silme engeli mesajı ("set its status to Closed instead", site.py:121) bulundu; kapalı sitedeki tanklara stok girişi, görev oluşturma veya rapor üretimi engellenmiyor, alt birimler (tank) kapanışta otomatik pasifleşmiyor. Durum yalnızca bilgi amaçlı. (Kapsamlı doğrulama sınırlı: tüm view'lar taranmadı.)
- Öneri: kapalı/pasif site için alt birim ve operasyon kuralları tanımlanmalı veya alanın yalnızca etiket olduğu belgelenmeli.

### F-229 Employees "Create" sütunu Everyone dışı roller için ölü izin: form görünür, kayıt her zaman 403

Önem: **Orta** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-1`
- Dosyalar: hr/services.py:25-27,50-55; hr/resources/employee.py:90-99; hr/forms/employee.py:78-81; config/access.py (Employees alanı); README.md (Team list bölümü)
- Açıklama: Matris Employees için `add` sütununu her role sunuyor ve `can_add` yalnızca `has_perm` ile hesaplanıyor (core/crud.py:~585). Ancak yeni kişinin yerleşimi `services.move` -> `_allowed` -> `scope.can_reach` ile denetleniyor; yeni kişi henüz kimsenin ekibinde olmadığı için Everyone (`hr.all_employee`) olmayan biri için PermissionDenied oluşur. CreateView kaydı `transaction.atomic` içinde yapıp `after_save` içinde 403 fırlattığından kayıt geri alınır; kullanıcı doğrulama hatası yerine düz 403 görür. README "yalnızca Everyone sahibi yeni kişi oluşturabilir" diyor, ama matris/UI bunu yansıtmıyor.
- Kanıt: `_allowed`: `if not any(user.has_perm(perm) ...) or not scope.can_reach(user, employee): raise PermissionDenied`; `after_save` -> `services.move(request.user, employee, ...)`.
- Öneri: `add_employee` iznini Everyone'a bağla (örn. create_view içinde erken kontrol / matriste yalnız Everyone satırında göster) ya da formda anlaşılır hata ver; test ekle.

### F-230 Employees Edit sahibi lider, ekip üyesini (ve kendini) yönetmediği herhangi bir bölüme taşıyabilir; kendi satırında self_plan benzeri koruma yok

Önem: **Orta** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-2`
- Dosyalar: hr/forms/employee.py:81-84; hr/units.py:47-59; hr/services.py:50-55; hr/resources/employee.py (allowed override yok); karşılaştırma: hr/resources/attendance.py:55, roster.py:46
- Açıklama: Düzenleme formunda bölüm seçenekleri `kinds=None` ile TÜM aktif üretim ve ofis bölümlerini listeler (`kinds` yalnız `adding` iken daraltılır). `services.move` yalnızca kişinin ekipte olmasını ister (hedef bölümün yöneticisi olmayı değil). Yani `change_employee` sahibi lider: (i) ekibindeki birini başka yöneticinin bölümüne ya da ofis/üretim arasında taşıyabilir (realm değişir), (ii) kendi `Employee` satırını (kapsamda olduğu için) düzenleyip kendi yerleşimini/ünvanını/`left_on`'unu değiştirebilir. Katılım ve vardiya için kendi kaydını yazma yasağı (`self_plan`) var, çalışan kaydında yok.
- Kanıt: `units.choices(include=..., kinds=[realm] if realm and adding else None)`; `EmployeeResource` içinde `allowed` tanımı yok (core/crud.py:463 varsayılan True).
- Öneri: Hedef bölüm için de `can_reach`/yönetici koşulu uygula veya Everyone iste; kendi satırında yerleşim/left_on değişimini engelle.

### F-231 Yedekleme/felaket kurtarma planı ve prosedürü yok; DB tek tomlu

Önem: **Orta** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-13`
- Dosyalar: docker-compose.yml, README.md, config/settings.py
- Açıklama: Repoda pg_dump/WAL arşivi/PITR veya medya (MEDIA_ROOT) yedeği betiği ya da dokümanı yok; DB tek `pgdata` volume'ünde. PDF'ler dosya sisteminde, DB'de yalnız yol var: DB ve medya ayrı yedeklenmezse tutarsız geri yükleme olur. README'deki "restore" geçişleri yalnız uygulama içi soft-delete restore'u anlatır. Olay/ölçüm (hypertable) verisi için chunk bazlı yedek stratejisi yok.
- Kanıt: docker-compose.yml:1-17 (tek volume, replika yok); README.md grep: "backup" geçmiyor; config/settings.py:177-185 (MEDIA_ROOT dosya sistemi).
- Öneri: DB+medya birlikte yedek/geri yükleme runbook'u ve test edilmiş prosedür.

### F-232 Token'sız modellerde çift tıklama/yeniden gönderim kopya kayıt üretir

Önem: **Orta** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-2`
- Dosyalar: core/crud.py, farm/models/health.py, knowledge/models/entry.py, frontend/components.ts
- Açıklama: Genel CRUD create idempotency'si yalnızca modelde `entry_key` alanı varsa çalışır. `HealthEvent` ve `KnowledgeEntry` gibi, doğal benzersiz anahtarı olmayan AuditedModel'lerde `entry_key` yok; çift tıklama iki kayıt yaratır. İstemci tarafında gönderim sırasında buton devre dışı bırakılmıyor. Kodu olan modellerde (site, tank) ikinci istek ilkinin kodu yüzünden "kod kullanılıyor" hatası gösterir; kullanıcı kaydın aslında oluştuğunu anlamaz.
- Kanıt: core/crud.py:165-166 (`ENTRY_KEY` yalnızca alan varsa), core/crud.py:193-196; farm/models/health.py:460 (HealthEvent'te entry_key/benzersiz kısıt yok); knowledge/models/entry.py:46-130; frontend/components.ts:317-321 (submit'te buton kilidi yok).
- Öneri: Tüm genel create formlarına entry_key ekle veya modal/form submit'te butonu kilitle.

### F-233 Davet akışı: hesap oluşur, e-posta yitebilir, yeniden davet yolu belirsiz

Önem: **Orta** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-X2`  (yalnız çapraz görüş)
- Dosyalar: core/resources.py, core/crud.py, config/settings.py, core/forms.py
- Açıklama: Davet akışı: hesap oluşur, e-posta yitebilir, yeniden davet yolu belirsiz

### F-234 Envanter: tüm hareket türleri tek izne bağlı (görev ayrılığı yok)

Önem: **Orta** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-X1`  (yalnız çapraz görüş)
- Dosyalar: inventory/views.py:43, inventory/views.py:275, inventory/views.py:310, inventory/views.py:348
- Açıklama: Envanter: tüm hareket türleri tek izne bağlı (görev ayrılığı yok)

### F-235 Python/Node sürüm bildirimi yok; minimum sürüm belirsiz

Önem: **Orta** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-X1`  (yalnız çapraz görüş)
- Dosyalar: requirements.txt, package.json
- Açıklama: Python/Node sürüm bildirimi yok; minimum sürüm belirsiz

### F-236 Migrate oncesi yedek/geri donus adimi belgelenmemis

Önem: **Orta** | Güven: belirtilmedi | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-X1`  (yalnız çapraz görüş)
- Dosyalar: docker-compose.yml, README.md
- Açıklama: Migrate oncesi yedek/geri donus adimi belgelenmemis

### F-237 Hard delete audit kayıtları değer taşımıyor: record_delete snapshot almıyor, withdraw/closure silmeleri yalnız etiket bırakıyor

Önem: **Orta** | Güven: belirtilmedi | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-X1`  (yalnız çapraz görüş)
- Dosyalar: core/audit.py:175-176, tasks/services.py:265-271, reports/services.py:135-138, reports/services.py:169-174
- Açıklama: Hard delete audit kayıtları değer taşımıyor: record_delete snapshot almıyor, withdraw/closure silmeleri yalnız etiket bırakıyor

### F-238 Plan kalemi ile harvest farklı haftaya düşünce planlı kesim raporunda çift sayım

Önem: **Orta** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-X1`  (yalnız çapraz görüş)
- Dosyalar: reports/compute/slaughter.py
- Açıklama: Plan kalemi ile harvest farklı haftaya düşünce planlı kesim raporunda çift sayım

### F-239 Bit raporunun tedavi seçimi neden alanına bağlı, sağlık servisi ilaç-neden ilişkisini zorlamıyor

Önem: **Orta** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-X2`  (yalnız çapraz görüş)
- Dosyalar: reports/compute/lice.py, farm/health/services.py
- Açıklama: Bit raporunun tedavi seçimi neden alanına bağlı, sağlık servisi ilaç-neden ilişkisini zorlamıyor

### F-240 Onbellek/okuma-modeli katmaninin yoklugu mimari bir karar olarak belgelenmemis; performans bulgularinin ortak kok nedeni

Önem: **Orta** | Güven: belirtilmedi | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-X3`  (yalnız çapraz görüş)
- Dosyalar: config/settings.py, monitoring/read.py:315-336, farm/harvest/read.py, inventory/read.py
- Açıklama: Onbellek/okuma-modeli katmaninin yoklugu mimari bir karar olarak belgelenmemis; performans bulgularinin ortak kok nedeni

### F-241 README uretim/dagitim, yedekleme ve DEBUG varsayilani konusunda sessiz

Önem: **Orta** | Güven: belirtilmedi | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-X1`  (yalnız çapraz görüş)
- Dosyalar: README.md, config/settings.py, docker-compose.yml
- Açıklama: README uretim/dagitim, yedekleme ve DEBUG varsayilani konusunda sessiz

### F-242 _field.html hata ve yardım metinlerini alana bağlamıyor

Önem: **Orta** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-X1`  (yalnız çapraz görüş)
- Dosyalar: templates/registration/_field.html
- Açıklama: _field.html hata ve yardım metinlerini alana bağlamıyor

### F-243 Geri alma/düzeltme penceresi dolunca eski kayıtlar kilitli kalıyor, yönetici düzeltme yolu yok

Önem: **Orta** | Güven: belirtilmedi | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-X1`  (yalnız çapraz görüş)
- Dosyalar: farm/stock/services.py, farm/health/services.py, farm/stock/dates.py
- Açıklama: Geri alma/düzeltme penceresi dolunca eski kayıtlar kilitli kalıyor, yönetici düzeltme yolu yok

### F-244 Sensör kesintisi senaryosu: bayat veri alarmı kaldırıyor ve limit yokken kart OK kalıyor (fail-open)

Önem: **Orta** | Güven: belirtilmedi | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-X4`  (yalnız çapraz görüş)
- Dosyalar: monitoring/read.py, farm/water/evaluate.py
- Açıklama: Sensör kesintisi senaryosu: bayat veri alarmı kaldırıyor ve limit yokken kart OK kalıyor (fail-open)

## Düşük önem (421)

### F-245 next yönlendirme doğrulayıcısı çoklu kopya, tutarsız

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-10`, `04-11`, `01-X4`, `04-X2`
- Dosyalar: hr/views.py:35-41, inventory/views.py:58-62
- Açıklama: Açık yönlendirme koruması her ikisinde var, fakat inventory ek `startswith('/')` ile, hr `require_https` ile farklı uyguluyor; paylaşılan tek yardımcı yok (03-xss raporundaki öneriyle aynı). `//evil.com` yolu inventory'de `startswith('/')`'i geçer ama `url_has_allowed_host_and_scheme` tarafından reddedilir (doğru).
- Kanıt: inventory/views.py:60.
- Öneri: Tek `safe_next` yardımcısı.
- Birleştirilen kayıtlar:
  - `03-10` (Bilgi): `next` yönlendirmeleri tutarlı biçimde doğrulanıyor ama beş farklı uygulamayla
  - `01-X4` (Düşük): Üç bağımsız 'next' doğrulayıcısı: authn dışındaki akışlarda require_https tutarsız
  - `04-X2` (Bilgi): next yönlendirme doğrulaması 7 kopya; sertleştirme eşitsiz

### F-246 PDF aynı kökenden inline sunum, ek başlık yok

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-14`, `06-9`, `28-15`, `03-X2`
- Dosyalar: knowledge/views.py:37-40, config/settings.py:64-78
- Açıklama: Varsayılan olarak yüklenen PDF aynı kökende `inline` gösterilir (`as_attachment` yalnızca `?download` ile). Kullanıcı kontrollü, doğrulaması yalnızca imza düzeyinde olan içerik uygulama kökeninde sunulur. `X-Content-Type-Options: nosniff` SecurityMiddleware ile geliyor (testte doğrulanmış), `X-Frame-Options` (DENY) de var; ancak `Content-Security-Policy: sandbox` gibi bir ek önlem yok. Polyglot (bkz. 06-4) bir dosya PDF dışı olarak yorumlanırsa nosniff + application/pdf bunu büyük oranda engeller; kalan risk tarayıcının PDF görüntüleyicisindeki betik/açık bağlantı davranışıdır.
- Kanıt: `FileResponse(stream, as_attachment='download' in request.GET, ..., content_type='application/pdf')`; test_the_file_is_sent... nosniff'i doğrular, CSP yok.
- Öneri: Yanıta `Content-Security-Policy: sandbox` (veya `default-src 'none'`) ekle; mümkünse medya için ayrı köken.
- Birleştirilen kayıtlar:
  - `03-14` (Düşük): Kullanıcı yüklü PDF aynı kökenden satır içi (inline) sunuluyor, `Content-Security-Policy: sandbox` yok
  - `28-15` (Düşük): Dosya `inline` PDF olarak ayni origin'den sunulur;
  - `03-X2` (Düşük): PDF yanıtı X-Frame-Options SAMEORIGIN ile aynı kökenli sayfalarda gömülebilir; CSP sandbox başlığı yok

### F-247 İzleme sayfası liste/filtre adları okuma izni olmadan

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `02-7`, `09-22`, `49-8`
- Dosyalar: monitoring/views.py:99-120; config/navigation.py:124; config/access.py (Monitoring boards yorumu)
- Açıklama: Menü girişi ve görünüm `farm.view_stockoperation` ister (tasarım: "anyone who may read Monitoring may choose a board"), fakat bağlamda `MonitorBoard.objects`, `Site`, `ProductionDepartment`, `System`, `Tank` listeleri izin süzmeden gelir. 02-7 ile örtüşür (orada yalnız filtre listeleri); pano listesi de ekleniyor.
- Kanıt: `boards=MonitorBoard.objects.order_by('name')`, `sites=Site.objects.order_by('name')`.
- Öneri: Seçenekleri `has_perm` ile süz veya matrise not düş.
- Birleştirilen kayıtlar:
  - `02-7` (Düşük): İzleme sayfası Site/Departman/Sistem/Tank listelerini ilgili Read izni olmadan filtre seçeneği olarak sunar
  - `09-22` (Bilgi): İzleme sayfası filtre seçenekleri (site/departman/sistem/tank adları) ilgili okuma izni olmadan bağlama verilir (02-7 ile aynı)

### F-248 view_task sahibi her göreve not ekleyebilir (Read=yazma)

Önem: **Düşük** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `02-13`, `49-9`, `49-X1`
- Dosyalar: tasks/views.py:67-76; tasks/services.py:190-205; config/access.py (Tasks yorumu: "Read ... and adding a note")
- Açıklama: `add_note` yalnız `tasks.view_task` ister; `start/tick/complete` ise atanan veya `change_task` ister (`may_work_on`). Notlar silinemez/düzenlenemez ve tam metniyle denetim günlüğüne yazılır (02-5). Salt-okur rolün kalıcı yazma yetkisi var; belgelenmiş ama "Read" sütununun anlamını genişletir.
- Kanıt: `@permission_required(VIEW...) def add_note` -> `services.add_note(request.user, task, body)`; services'te `may_work_on` kontrolü yok.
- Öneri: Notu atanan/`change_task` ile sınırla veya ayrı sütun ver.
- Birleştirilen kayıtlar:
  - `02-13` (Düşük): Herhangi bir `tasks.view_task` sahibi her göreve not ekleyebilir; atanan/Edit şartı yok
  - `49-X1` (Düşük): Okuma izni sayfaları ile yazma uçları aynı izne bağlı: matris 'Read' sütunu tutarsız

### F-249 Tek adlandırılmış Docker volume, redundancy ve yedek yok

Önem: **Düşük** | özgün: Yüksek | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulandı

- Kaynaklar: `12-2`
- Dosyalar: docker-compose.yml:15-19
- Açıklama: Veri `pgdata` adlı tek yerel volume'de. `docker compose down -v`, `docker volume prune` veya disk arızası tüm veriyi kaybettirir. Komutlar arasında koruma/uyarı yok. Dosya "Local development database" diye başlıyor, ama README aynı yapıyı kurulum yolu olarak sunuyor; üretim için ayrı bir tanım yok.
- Kanıt: `volumes: [pgdata:/var/lib/postgresql/data]`, `volumes: pgdata: {}`; varsayılan parola `balik` (docker-compose.yml:10-11).
- Öneri: Üretim için ayrı compose/yönergede volume'ü hostta bilinen bir yola bağlayın veya yönetilen veritabanı kullanın; yedek servisi ve volume snapshot ekleyin; dev/prod ayrımını belgeleyin.
- Doğrulama `12-2`: doğrulandı; doğrulayıcı önemleri Düşük/Bilgi -> nihai Düşük. docker-compose.yml:15-19 tek pgdata volume doğru; ancak dosya yerel geliştirme içindir, şiddet abartılı.

### F-250 Mesaj gönderme (`messaging:post`) idempotent değil

Önem: **Düşük** | özgün: Orta | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulandı

- Kaynaklar: `38-2`
- Dosyalar: messaging/views.py:91, messaging/services.py:232, templates/messaging/inbox.html:37
- Açıklama: Stok, besleme, envanter, tedavi vb. `entry_key` ile aynı form iki kez gönderilince tek kayıt yaratır; mesaj formunda anahtar yok. Çift tıklama/yeniden gönderme/ağ tekrarı aynı mesajı iki kez ekler. `Message` modelinde `entry_key` yok (grep sonucu yalnızca hr, tasks, inventory, farm, experiments modellerinde).
- Kanıt: `post()` doğrudan `services.post_as(...)`; `MessageForm` içinde istemci anahtarı yok.
- Öneri: formda gizli UUID, `Message(conversation, author, client_key)` benzersiz kısıtı.
- Doğrulama `38-2`: doğrulandı; doğrulayıcı önemleri Düşük/Düşük -> nihai Düşük. messaging/views.py:98 -> services.py:232-248 post() her çağrıda Message.objects.create; tekrar gönderim tanınmıyor.
- Çapraz görüş itirazı `38-2`: db-schema: Kısmen. Görev ve görev notunda entry_key unique alanı şemada var (tasks/models.py:193,363); mesajlar için ayrıca doğrulanmadı, eksik uygulama katmanında olabilir.

### F-251 start_direct silinmiş konuşmayı döndürüyor

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-14`, `10-14`, `29-12`
- Dosyalar: messaging/services.py:95-110, 47-52
- Açıklama: `Conversation.all_objects.filter(direct_key=key).first()` silinmiş bir konuşmayı döndürebilir; sonrasında `member()` `is_deleted=False` filtresiyle 404 verir (kullanıcı konuşmaya giremez). Ayrıca `contacts()` tüm aktif kullanıcıları (ad/soyad) Messages izni olan her role listeler.
- Kanıt: `found = Conversation.all_objects.filter(direct_key=key).first(); if found is not None: return found`.
- Öneri: Silinmiş doğrudan konuşmayı canlandır veya yeni oluştur; kişi dizinini belgele.
- Birleştirilen kayıtlar:
  - `10-14` (Bilgi): Mesajlaşma: `start_direct` silinmiş sohbeti de döndürüyor; küçük tutarsızlıklar
  - `29-12` (Düşük): `start_direct` silinmiş konuşmayı döndürür

### F-252 close_due/record_duty_done/copy_template ön koşul işlem dışında

Önem: **Düşük** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-13`, `16-5`, `50-10`
- Dosyalar: `monitoring/views.py:149-170`, `reports/services.py:114-124`, `reports/services.py:144-166`
- Açıklama: Kopya adı `_copy_name` ile bir sorguda hesaplanıp ayrı `create` ile yazılıyor; iki kişi aynı anda kopyalarsa aynı ad üretilir ve unique ihlali yakalanmadan 500 olur. `close_due` "bu rapor hâlâ borç mu" kontrolünü (`due.due()`) transaction ve kilit dışında yapıyor; `record_duty_done` salmonid kontrolünü de dışarıda yapıyor. `full_clean()` yarışı kapatmaz, IntegrityError sarılmamış. Etkisi küçük (nadir, sonuç 500, veri bozulmaz).
- Kanıt: `copy_template` içinde yalnızca `transaction.atomic()` var, `IntegrityError` yakalanmıyor; `close_due` satır 117'de kontrol, satır 119'da atomic.
- Öneri: Ad çakışmasında yeniden deneme/`IntegrityError` yakalama; borç kontrolünü transaction içine alın.
- Birleştirilen kayıtlar:
  - `16-5` (Düşük): `close_due`/`record_duty_done`: ön koşul kontrolü işlem ve kilit dışında (10-13 ile örtüşür)
  - `50-10` (Düşük): Raporlar: close_due/record_duty_done kontrolü işlem dışında, yarışta 500; reopen çift log

### F-253 messaging.post silinmiş konuşmada DoesNotExist

Önem: **Düşük** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `16-9`, `34-10`, `33-X1`
- Dosyalar: messaging/services.py:231-246
- Açıklama: `Conversation.objects.select_for_update().get(pk=...)` (yalnızca canlı yöneticisi) konuşma eşzamanlı silinmişse `DoesNotExist` fırlatır; `author` yeniden okunması için `PermissionDenied` hazırlanmış ama bu ilk istisna önce çıkar. Olumlu: gönderi ve üyelik değişiklikleri aynı konuşma kilidini kullanıyor (`_locked`, `owner(lock=True)`), mesaj kimlikleri commit sırasına uyuyor; `mark_read` tek UPDATE ile atomik ve geriye gitmez (286).
- Kanıt: messaging/services.py:236.
- Öneri: `get_object_or_404`/`Http404`/`PermissionDenied` eşlemesi yapın.
- Birleştirilen kayıtlar:
  - `16-9` (Düşük): `messaging.post`: kilit sorgusu `get()` ile; konuşma aradan silinirse `DoesNotExist` (500), diğer yollar 404
  - `33-X1` (Düşük): messaging.post hata sözleşmesi tutarsız: silinmiş konuşmada DoesNotExist (500), silinmiş katılımcıda PermissionDenied (403)

### F-254 Flash mesajları role=status (hata dahil)

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-14`, `44-16`, `41-X3`
- Dosyalar: `templates/app_base.html:99-101`, `templates/modal_base.html:13`, `static/css/app.css:458-461`
- Açıklama: Başarı ve hata (`flash-error`) mesajları aynı `role="status"` (polite) kapsayıcıda. Hata için `role="alert"` kullanılmıyor (form `non_field_errors` için doğru kullanılmış). Kapsayıcı sayfa yüklenirken zaten dolu olduğu için çoğu ekran okuyucu içeriği duyurmaz (canlı bölgeler yalnızca sonradan eklenen içeriği duyurur). Modal içinde form POST sonrası içerik `innerHTML` ile değiştirilip odak ilk girdiye taşındığında hata özeti okunmuyor; odak `.has-error input`'a gidiyor ama hata metni alana bağlı değil (bkz. 44-2).
- Kanıt: `app_base.html:99` `<div class="flash-list" role="status">`; `components.ts:363-365`.
- Öneri: Hata mesajlarını `role="alert"` ile ver, odağı hata özetine veya ilk geçersiz alana + describedby ile taşı.
- Birleştirilen kayıtlar:
  - `43-14` (Düşük): Flash hata mesajları `role="status"` ile duyuruluyor
  - `41-X3` (Düşük): Flash role=status sorunu sunucu sablonunda, TS duyuru katmani yalniz izleme duvari icin

### F-255 Parola politikası varsayılan asgari

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-10`, `05-12`
- Dosyalar: config/settings.py:132-145
- Açıklama: Yalnızca 4 standart doğrulayıcı, minimum 8 karakter. Çiftlik konsolu (veri değiştirme yetkisi) için zayıf; yönetici hesapları için daha güçlü politika/MFA yok. /admin/ de aynı parola ile tek faktör (config/urls.py:42).
- Kanıt: `MinimumLengthValidator` seçeneksiz.
- Öneri: min_length 12; superuser için MFA.
- Birleştirilen kayıtlar:
  - `05-12` (Düşük): Parola doğrulayıcı minimum uzunluğu varsayılan (8), parola politikası yapılandırılmamış

### F-256 innerHTML sink + CSP yok

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-8`, `41-29`
- Dosyalar: frontend/poll.ts:72,169,173,176,319; frontend/components.ts:111,359; frontend/designer.ts:477
- Açıklama: Poll, modal ve tasarım önizlemesi sunucu fragmanlarını doğrudan DOM'a yazıyor. Fragmanlar aynı kökenden, Django şablonlarıyla (autoescape) üretiliyor ve `credentials: 'same-origin'` ile çekiliyor; `<script>` `innerHTML` ile çalışmaz, ama `<img onerror>` gibi içerik çalışır. Güvenlik tamamen sunucu tarafı kaçışına bağlı; DOMPurify/Trusted Types yok. `components.ts:111` ise `template.innerHTML.replace(/__prefix__/g, ...)` ile şablon klonluyor (sunucu şablonu, güvenli). CSP olmaması (03-1) bu sink'lerin etkisini büyütür.
- Kanıt: `this.content.innerHTML = await response.text();` (components.ts:359), `this.preview.innerHTML = answer.html;` (designer.ts:477), `element.innerHTML = html.trim();` (poll.ts:173/176).
- Öneri: CSP + Trusted Types (report-only) ile sink'leri tek yardımcıya topla; fragman uç noktalarının yalnızca şablonla ürettiğini testle sabitle.
- Birleştirilen kayıtlar:
  - `41-29` (Bilgi): HTML parçaları `innerHTML` ile ekleniyor; CSP tanımı yok

### F-257 Kod benzersizliği kapsamı tutarsız

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-10`, `30-12`
- Dosyalar: farm/models/tank.py:389-393, inventory/models.py:97-100
- Açıklama: `Tank.code` ve `StorageLocation.code` yalnızca `is_deleted=False` koşuluyla global benzersiz; çok lokasyonlu çiftlikte iki site aynı birim kodunu kullanamaz. Kod yorumları (tank.py:394-396) regulatory_unit_id'nin site kapsamlı olması gerektiğini söylüyor ama DB yalnızca production_department kapsamında tutuyor (site kapsamı clean()'de).
- Kanıt: `UniqueConstraint(fields=['code'], condition=Q(is_deleted=False), name='uq_tanks_code_live')`; `uq_tanks_regulatory_unit_id_live` `production_department` ile.
- Öneri: İş kararını belgele; site düzeyi benzersizlik DB'de tutulamıyorsa (join gerekir) tetikleyici/denormalize site_id düşün.
- Birleştirilen kayıtlar:
  - `30-12` (Düşük): Başlık: Kod benzersizliği kapsamı tutarsız (Tank/Equipment/Departman şirket genelinde, System site bazında, Site genelinde)

### F-258 entry_key idempotensi (su ölçümü)

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-8`, `17-5`
- Dosyalar: farm/models/water.py:121-124, farm/water/services.py:135,170
- Açıklama: Diğer tablolarda `entry_key` tek başına `unique=True` iken burada hypertable gereği `measured_at` ile birleşik. Aynı form farklı `measured_at` ile gönderilirse DB iki kayda izin verir; korumanın tamamı uygulama kontrolüne (`filter(entry_key=token, measured_at=...)`) bağlı. NULL `entry_key` için de benzersizlik yok.
- Kanıt: `UniqueConstraint(fields=['entry_key', 'measured_at'])`; services.py:135 `filter(entry_key=token, measured_at=measured_at)`.
- Öneri: Bilinen sınırlama olarak belgele; formun zamanı sabit gönderdiğini testle doğrula.
- Birleştirilen kayıtlar:
  - `17-5` (Düşük): İdempotensi anahtarı `(entry_key, measured_at)`.

### F-259 Mesaj silme izi ve moderasyon yok

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-4`, `13-X4`
- Dosyalar: messaging/services.py:256-275; messaging/models.py:127
- Açıklama: Mesaj `AuditedModel` değil; silme `version`/`updated_by` yazmaz, `audit.record_*` çağrısı yok (tasarım gereği, ama silen = yazar zaten). Yalnızca yazar silebilir (`own_message`: başkasınınsa PermissionDenied); kanal sahibi ya da yönetici uygunsuz mesajı kaldıramaz, ayrılan üye de kendi eski mesajını silemez (`member` canlı üyelik ister).
- Kanıt: `if message.author_id != actor.pk: raise PermissionDenied`.
- Öneri: Kanal sahibine moderatör silmesi (deleted_by ayrımıyla) düşünün; ürün kararı olarak belgeleyin.
- Birleştirilen kayıtlar:
  - `13-X4` (Düşük): Mesaj silme ve okundu işaretçisi: metin DB'de kalırken log'da iz yok, silme yetkisi/kim bilgisi yalnız satırda

### F-260 Hata mesajı dili tutarsız

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-12`, `45-16`
- Dosyalar: monitoring/views.py, hr/views.py, knowledge/views.py
- Açıklama: JsonResponse({'error': 'too large'}) ve ({'error': 'bad request'}) (monitoring/views.py:188,193) çevrilmemiş ve ham; HttpResponseBadRequest() gövdesiz (hr/views.py:63,73; knowledge/views.py:62) olduğundan kullanıcı Django'nun boş 400 sayfasını görür (özel 400 şablonu da yok, bkz. 33-3). Oysa uygulamanın geri kalanı messages.error ve gettext kullanıyor.
- Kanıt: monitoring/views.py:188,193; hr/views.py:63,73; knowledge/views.py:62.
- Öneri: Form tabanlı view'larda 400 yerine messages.error + yönlendirme; JSON hata kodlarını sabit anahtar yapıp istemcide çevirin.
- Birleştirilen kayıtlar:
  - `45-16` (Bilgi): Geliştirici/JSON hata metinleri İngilizce

### F-261 Besleme çekişi silo/besleyici bağını kullanmıyor

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `23-15`, `47-9`
- Dosyalar: `inventory/fold.py:198-236` (`_feed`), `inventory/forms.py:44-82`, `farm/feeding/services.py:44-80`
- Açıklama: Depo lokasyonunun `feeder` alanı var (silo -> besleyici), yemleme kaydı da `feeder` taşıyabiliyor; ancak çekiş site genelindeki tüm kovalardan "ilk SKT'si dolan ilk çıkar" sırasıyla yapılıyor, `feeder` hiç kullanılmıyor. Yani yemleme -> stok zincirinde lokasyon düzeyinde doğruluk yok; birden çok silolu sitelerde "kitap" ile gerçek silo içeriği ayrışır. (23-15 ile aynı kök; burada uçtan uca etki: sayım farkları hep varyans olarak çıkar.)
- Kanıt: `_feed` yalnız `self.places[bucket[0]].site == site` filtresi kullanıyor.
- Öneri: Yemlemenin besleyicisi bir silo ile eşleşiyorsa o silodan önce çek; kararı README'de belgele.
- Birleştirilen kayıtlar:
  - `23-15` (Bilgi): Besleme çekişi lokasyon/silo-besleyici bağını kullanmıyor (site genelinde havuz)

### F-262 Hareketli pencerelerde ok tuşları gövde kaydırmasını engelliyor; klavye kısayolları belgelenmemiş

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulandı

- Kaynaklar: `44-11`
- Dosyalar: `frontend/windows.ts:185-203`, `templates/monitoring/_windows.html:9-16`
- Açıklama: Pencere `keydown` işleyicisi pencere içinde herhangi bir yerde ok tuşuna `preventDefault` çağırıyor (yalnızca `input,select,textarea` hariç). Gövde (`.monitor-window-body`, `overflow:auto`) kaydırılabilir; bir bağlantı/düğmeye odaklıyken veya gövde odaklıyken ok tuşuyla kaydırma yerine pencere kayıyor. Taşıma (ok) ve yeniden boyutlandırma (Shift+ok) klavye kısayolları ekranda ya da `aria-describedby` ile duyurulmuyor; pencere başlığındaki sürükleme tutamacı yalnızca fareyle. `role="dialog"` ile modal olmayan pencere odak tuzağı yapmıyor (bu kasıtlı), ancak `aria-modal` yok, kabul edilebilir. Poll gövdeyi `innerHTML` ile değiştirirken (`poll.ts:176`) içindeki odak kaybolabilir (yalnızca `merge` yolunda id ile geri yükleniyor).
- Kanıt: `windows.ts:191-193` `if (!arrow || (event.target as Element).closest('input, select, textarea') || PHONE.matches) return; event.preventDefault();`.
- Öneri: Taşıma için yalnızca pencere elemanının kendisi odaklıyken (`event.target === element`) tetikle; kısayolları sr-only metinle belgele.
- Doğrulama `44-11`: doğrulandı; doğrulayıcı önemleri Düşük/Düşük -> nihai Düşük. frontend/windows.ts:185-203 keydown dinleyicisi ok tuşlarında preventDefault; kapsam pencere odağıyla sınırlı.
- Çapraz görüş itirazı `44-11`: frontend-ts: windows.ts:185-203 dinleyici pencere elemanına bağlı; yalnız pencere içi odakta, input/select/textarea ve PHONE dışında preventDefault ediyor; etki dar.

### F-263 is_deleted tek sütunlu indeks

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `15-4`, `35-18`
- Dosyalar: core/models.py:35
- Açıklama: `is_deleted` `db_index=True` ile tum AuditedModel tablolarinda ayri bir boolean indeks olusturuyor. Cogu satir `False` oldugundan planlayici bu indeksi nadiren secer; yazma maliyeti ve disk kullanimi artar. Canli kayit kisitlari icin kismi indeks (`WHERE NOT is_deleted`) daha uygun olurdu.
- Kanıt: `is_deleted = models.BooleanField(_('Deleted'), default=False, db_index=True)`
- Öneri: `db_index` kaldirilip gerekli yerlerde kosullu (partial) indeks kullan; once `pg_stat_user_indexes` ile kullanim dogrulansin.
- Birleştirilen kayıtlar:
  - `15-4` (Düşük): `AuditedModel.is_deleted` her tabloda tek sütunlu indeks

### F-264 get_users, kullanılamaz parolalı hesapları da sıfırlamaya açıyor

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-7`
- Dosyalar: core/forms.py:162-165
- Açıklama: Django'nun `has_usable_password` filtresi bilerek kaldırıldı (davet için). Sonuç: yönetici bir hesabı `set_unusable_password` ile kilitlemiş olsa (ör. dış kimlik) e-posta sahibi yine parola belirleyebilir; superuser hesapları da dahil. Ayırt edici bir "davet bekliyor" durumu yok.
- Kanıt: `User._default_manager.filter(email__iexact=email, is_active=True)`.
- Öneri: Davet durumunu ayrı işaretle veya yalnızca henüz parola atanmamış + davet edilmiş hesaplara izin ver.

### F-265 Toplu vardiya planı (`plan`) mount'un realm'ini uygulamıyor

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-12`
- Dosyalar: hr/views.py:56-80 (`scope.team(request.user)` realm'siz), hr/views.py:72
- Açıklama: Üretim > Takım adresi ile ofis kişisi (ulaşılabiliyorsa) planlanabilir, diğer sayfalar realm ile daralıyor. Yetki yükseltmesi değil, tutarsızlık; yazma kapsamı okuma kapsamından geniş. Vardiya (`Shift`) de site/realm'e bağlanmıyor.
- Kanıt: `reachable = {... scope.team(request.user).filter(pk__in=...)}`.
- Öneri: `scope.team(request.user, realm=scope.realm_for(request))`.

### F-266 Rapor "sunuldu" kaydı geri alınamaz işlem olduğu halde sıradan `change_report` izniyle yapılıyor (görev ayrılığı yok)

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-8`
- Dosyalar: reports/views.py:55-57, 94, 123, 147, 178; config/access.py (Regulatory reports yorumu)
- Açıklama: Taslağı dolduran kişi aynı izinle raporu "filed" yapıp dondurabilir; kapatma/yeniden açma ve "dış görev yapıldı" da aynı izin. Ayrı "gönder/onayla" hakkı yok.
- Kanıt: `@permission_required('reports.change_report', ...)` `def submit`.
- Öneri: Ayrı bir `submit` izni ya da matriste ayrı sütun düşün.

### F-267 Bilgi girişinin kendi kaydını inceleme (dört göz) kontrolü yok

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-9`
- Dosyalar: knowledge/views.py:54-85; knowledge/models/entry.py:175-177; README.md ("Owner decision open")
- Açıklama: `change_knowledgeentry` sahibi kendi oluşturduğu girişi `reviewed` yapabilir; sadece belgelenmiş açık karar.
- Kanıt: `review_entry` yalnızca `_allowed(request, KnowledgeEntryResource, 'change')` kontrol eder, `reviewed_by != created_by` yok.
- Öneri: Karar verilene dek bu risk kabul listesinde izlensin; DB CHECK + ayrı Review sütunu.

### F-268 Importmap `mark_safe` ile ve `</script>`'e karşı kaçışsız `json.dumps` ile üretiliyor

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-3`
- Dosyalar: core/templatetags/assets.py:41
- Açıklama: `mark_safe('<script type="importmap">' + json.dumps(...) + '</script>')`. `json.dumps` `<`, `>`, `&` karakterlerini kaçışlamaz; girdiler `static/js/*.js` dosya adları ve mtime sürümü olduğundan bugün geliştirici kontrolünde, fakat desen güvenli değil (dosya adında `</script>` bulunması betik bloğunu kırar).
- Kanıt: `imports = {static(path): versioned(path) ...}` -> `json.dumps({'imports': imports})`.
- Öneri: `django.utils.html.json_script` benzeri kaçış (`<`) uygula; CSP nonce eklerken aynı yerde düzelt.

### F-269 CSV formül koruması yalnız Char/Text alanlarda ve sınırlı önek listesiyle

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-2`
- Dosyalar: core/dbgrid.py:32,38,268-272, reports/exports.py:196
- Açıklama: `FORMULA_STARTS = ('=','+','-','@','\t','\r')`; `\n` ve baştaki boşluk+`=` gibi biçimler kapsanmıyor. `export_text` yalnızca `CharField/TextField` için koruma uyguluyor; JSON/dizi/seçim/FK etiketi gibi metin üreten başka sütun türleri korumasız (JSON `[`/`{`/`"` ile başladığından bugün zararsız). reports/exports.py yalnızca `str` değerleri koruyor; sayı olarak gelen ama aslında metin olan değerler atlanır.
- Kanıt: dbgrid.py:268-272 `if isinstance(column.field, (models.CharField, models.TextField)): return formula_safe(text)`.
- Öneri: Tüm metin çıktısına uygula (tür yerine çıktı string'ine göre), önek listesine `\n` ekle; sayıları ayrı biçimle yaz.

### F-270 Önizleme (`preview`) JSON'u şablona veri olarak gider, kısıtlı ama doğrulama validate.validate'e bağlı

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-3`
- Dosyalar: monitoring/views.py:186-211
- Açıklama: `json.loads(request.body)` 64 KB sınırıyla alınıyor, `validate.validate` hata verirse çizim yapılmıyor; `render_to_string` ile standart şablon (otomatik kaçışlı) kullanılıyor, şablon kaynağı kullanıcıdan gelmiyor. Güvenlik tamamen `validate`/`render` modüllerindeki kaçışlamaya dayanıyor (bu denetimde `monitoring/cards/*` derinlemesine incelenmedi).
- Kanıt: views.py:190 `asked = json.loads(request.body)`; :211 `render_to_string('monitoring/_card.html', ...)`.
- Öneri: Kart şablonunda `|safe` yokluğunu test ile sabitleyin. (güven: orta bakımından kapsam sınırlı)

### F-271 PDF doğrulaması yalnız ilk 1 KB içinde `%PDF-` alt dizesine bakıyor

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-4`
- Dosyalar: knowledge/models/document.py:58-72, knowledge/views.py:36-39
- Açıklama: `b'%PDF-' in head` imzanın dosya başında olmasını şart koşmuyor; polyglot (ör. HTML+PDF) dosya kabul edilir. Yanıt `content_type='application/pdf'` ile geldiği ve Django `nosniff` varsayılanı açık olduğu için bugün kullanılabilir bir saldırı yok, fakat savunma derinliği zayıf. Ayrıca `Content-Disposition` dosya adını kullanıcıdan alıyor (`file_name`); `FileResponse` bunu güvenli kodluyor.
- Kanıt: document.py:71 `if b'%PDF-' not in head`.
- Öneri: `head.startswith(b'%PDF-')` (en fazla birkaç baytlık BOM/boşluk toleransı) kullanın.

### F-272 Compose: parolasız-yan etkili ve sürüme/kaynağa kısıt yok, restart: unless-stopped geliştirme DB'si için

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-9`
- Dosyalar: docker-compose.yml:5-15
- Açıklama: Görüntü sürümü sabitlenmiş (iyi) ama digest yok; kaynak limiti, healthcheck, ağ izolasyonu yok. Başlık "Local development" diyor; üretim DB'si olarak kullanılırsa varsayılan parola geçerli kalır.
- Kanıt: docker-compose.yml:1-15 (healthcheck/deploy anahtarı yok).
- Öneri: Healthcheck ekle; dosyanın yalnızca geliştirme için olduğunu README'de vurgula.

### F-273 Aynı dosyanın tekrar yüklenmesi/yinelenen içerik denetimi yok; kötü amaçlı yazılım taraması yok

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-12`
- Dosyalar: knowledge/models/document.py:115-124, knowledge/forms/document.py
- Açıklama: İçerik özeti (hash) saklanmıyor; aynı PDF birden çok belge olarak yüklenebilir (yalnızca DOI benzersizliği var, DOI boşsa hiçbir kontrol yok). Yüklemeler virüs/zararlı içerik taramasından geçmiyor; PDF'ler diğer kullanıcılara sunuluyor (06-9 ile ilişkili).
- Kanıt: Modelde hash/checksum alanı yok; yükleme yolunda tarayıcı entegrasyonu yok.
- Öneri: SHA-256 alanı ve uyarı; dağıtımda ClamAV gibi bir tarama adımı değerlendirilmeli.

### F-274 Magic-byte kontrolü "başlangıçta" değil "ilk 1024 baytın herhangi bir yerinde" `%PDF-` arıyor; doküman ile çelişiyor

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-4`
- Dosyalar: knowledge/models/document.py:58-72, README.md (The file paragrafı)
- Açıklama: Kod `b'%PDF-' in head` ile 1024 baytın içinde arar. PDF spesifikasyonu başlığın ilk 1024 bayt içinde olmasına izin verdiği için bu bilinçli olabilir, ama docstring ve README "first bytes say %PDF-" diyor. Sonuç: HTML/ZIP/başka biçimlerle polyglot dosyalar (başında başka içerik, ilk KB'de `%PDF-`) doğrulamayı geçer. Etki, `Content-Type: application/pdf` + nosniff sunumu ve inline görüntüleme nedeniyle sınırlı. Ayrıca doğrulama yapısal değil: `%PDF-1.4\nnot really a PDF` kabul edilir (test bunu FAILED olarak saklıyor).
- Kanıt: `if b'%PDF-' not in head: raise ValidationError(_('This file is not a PDF.'))`; testte `upload(b'%PDF-1.4\nnot really a PDF')` kabul ediliyor (test_a_damaged_pdf_is_kept...).
- Öneri: Ya ofset 0'ı zorunlu kıl ya da docstring/README'yi "ilk 1024 bayt" olarak düzelt; isteğe bağlı olarak pypdf ile başarılı açılışı yükleme kabulüne koşul yap.

### F-275 Silinmiş belgelerin dosyaları süresiz tutuluyor, kalıcı silme/saklama politikası yok

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-6`
- Dosyalar: knowledge/models/document.py:89-91, knowledge/admin.py:8-15, core/softdelete.py:189-205
- Açıklama: Soft-delete'te dosya ve sayfalar bilinçli olarak saklanır; kalıcı silme (purge) yolu yok. Admin üzerinden hard delete yapılırsa (AuditedModelAdmin'in delete izni kontrol edilmedi) `on_delete` hiçbir dosya silme tetiği yok, dosya yetim kalır. KVKK/GDPR veya telif nedeniyle bir PDF'in gerçekten kaldırılması gerekirse yöntem yok ("Remove the file" yalnızca canlı kayıtta, geri dönülmez şekilde dosyayı siler ama silinmiş belge için çalışmaz).
- Kanıt: kodda `Document` için delete/post_delete sinyali veya purge komutu yok (`grep storage.delete` yalnızca models/document.py:241).
- Öneri: Saklama süresi + purge komutu; model `delete()`/post_delete'te dosyayı silme; admin'de hard delete kapatma.

### F-276 Önbellek başlığı `private, no-cache` ama ETag/Last-Modified/Range yok; her açılışta tam indirme

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-8`
- Dosyalar: knowledge/views.py:37-39
- Açıklama: `FileResponse` Django'da Range isteklerini desteklemez; ETag/Last-Modified de verilmez, `no-cache` her seferinde tam 20 MB'a kadar dosyayı yeniden akıtır. Büyük PDF'te tarayıcı görüntüleyici ilerleyici (range) yükleme kullanamaz. İşlevsel hata değil, verimlilik.
- Kanıt: `response['Cache-Control'] = 'private, no-cache'`; başka başlık yok.
- Öneri: Dosya UUID adı değişmez olduğundan `ETag`'i (örn. depo adı + boyut) ver; koşullu GET desteği ekle; gerekirse X-Accel-Redirect ile sunumu ön sunucuya devret.

### F-277 Geliştirme/üretim bağımlılıkları ayrılmamış

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-11`
- Dosyalar: requirements.txt:1-13
- Açıklama: Tek dosya var; `Babel` yalnızca çeviri katalog komutunda (core/catalogs.py:15-18) kullanılıyor ve `cryptography` yalnızca PDF AES için; çalışma zamanı vs geliştirme ayrımı yok. Üretim imajına gereksiz paketler girer.
- Kanıt: `from babel.messages...` core/catalogs.py:15-18; requirements.txt tek dosya.
- Öneri: requirements-dev ayrımı (Babel'in çalışma zamanı mı yoksa derleme aracı mı olduğuna karar ver).

### F-278 Projenin kendi lisansı yok; package.json'da license alanı yok

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-6`
- Dosyalar: package.json:14-29, (yok) LICENSE
- Açıklama: Repoda LICENSE/COPYING dosyası yok; package.json `private: true` ama `license` alanı yok. Dışarıya dağıtım/müşteriye teslim durumunda hak belirsizliği olur.
- Kanıt: `git ls-files` listesinde LICENSE yok; package.json'da "license" anahtarı yok.
- Öneri: Kasıtlı olarak tescilli ise `"license": "UNLICENSED"` ve LICENSE/telif notu ekle.

### F-279 THIRD_PARTY.md geçişli npm bağımlılığını (undici-types) ve axe-core MPL-2.0 koşulunu belirtmiyor

Önem: **Düşük** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-7`
- Dosyalar: THIRD_PARTY.md:7-16, package-lock.json:21-25, package-lock.json:51-55
- Açıklama: package-lock'ta `undici-types@6.20.0` (`@types/node` bağımlılığı) var ama tabloda yok. axe-core MPL-2.0 dosya düzeyinde copyleft'tir; yalnızca dev kullanımı olduğu doğru, ancak "asla gömülmez" güvencesi bir CI kontrolüyle doğrulanmıyor.
- Kanıt: package-lock.json: `"node_modules/undici-types": {"version": "6.20.0"...}`; THIRD_PARTY.md tablosunda 4 paket.
- Öneri: Geçişli paketleri tabloya ekle veya "geçişli bağımlılıklar için package-lock'a bakın" notu yaz.

### F-280 Konuşma sayfasını GET ile açmak okundu işaretçisini yazar (okuma yolunda yazma)

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-17`
- Dosyalar: messaging/views.py:66-77; messaging/services.py:278
- Açıklama: `conversation` bir GET görünümüdür ve `services.mark_read(participant, shown[-1].pk)` çağırır; ön yükleme/prefetch, bağlantı önizleyici veya yeniden yükleme okundu durumunu değiştirir. Yanıt `no-store` ile işaretlenmiş poll fragmanının aksine bu sayfa için önbellek başlığı da yok. Tasarım amaçlı ("Opening it marks what it shows as read") ama GET'in yan etkisi ve rozet sayımıyla (09-15) etkileşir.
- Kanıt: `if reading_latest and shown: services.mark_read(participant, shown[-1].pk)`.
- Öneri: Bilinçli kabul olarak belgele veya işaretçiyi ayrı POST/beacon ile ilerlet.

### F-281 Sayfalaması olmayan listeler ve her istekte yüklenen tam açılır liste verileri

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-19`
- Dosyalar: farm/stock/views.py:124-133; monitoring/read.py:208-222 ve monitoring/views.py:112-120; farm/resources/harvest_plan.py:138-156 (`ProductionPlanResource`, `page_size` yok); farm/water/views.py:233-246 (`_owner_groups`); farm/feeding/views.py:84-89 (`'batch': Batch.objects.order_by(...)`)
- Açıklama: Üretim birimleri sayfası tüm birimleri ve stok/yem/su okumalarını Python'da süzer, izleme duvarı tüm eşleşen birimler için kart üretir, `ProductionPlanResource` tüm (parti, birim) satırlarını sayfalamadan listeler, su geçmişi sayfası tüm birim/sistem/ekipmanı seçici için, yem kayıtları sayfası tüm partileri açılır liste için yükler. Küçük çiftlik için kabul edilebilir; çok siteli büyümede sınırsız. `Tank.objects.count()` her izleme poll'unda tekrarlanır (monitoring/views.py:78).
- Kanıt: `units = list(Tank.objects.select_related('production_department__site', 'system'))` (farm/stock/views.py:125).
- Öneri: Ölçek hedefini README'de yaz; seçiciler için arama tabanlı (autocomplete) yükleme.

### F-282 CSV dışa aktarma 50.000 satırda sessizce keser; dosyanın içinde kesildiği belli değil

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-3`
- Dosyalar: core/dbgrid.py:26, 258-262; core/dbview.py:58-64; templates/core/database/_grid.html:24
- Açıklama: `export()` `queryset()[:EXPORT_LIMIT]` ile keser. Sınır yalnızca düğmenin `title` metninde yazıyor; üretilen dosyada bir uyarı satırı/üst bilgi yok, kullanıcı eksik dışa aktarmayı tam sanabilir ("veriyi denetlemek" amacıyla indirilen dosya için yanıltıcı). Ayrıca akış başladıktan sonra oluşan bir DB hatası HTTP 200 ile yarım dosya bırakır.
- Kanıt: `for values in self.queryset()[:EXPORT_LIMIT].iterator():` (dbgrid.py:261).
- Öneri: Kesildiğinde son satıra/ayrı bir başlığa "kesildi" işareti ekle ya da `X-Export-Truncated` başlığı ve sayfada sayı uyarısı göster.

### F-283 Görüntüleyici `audit.restrict` kısıtlarını atlar: `audit_log` tablosu HR kayıt türlerinin geçmişini de gösterir

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-5`
- Dosyalar: core/audit.py:25-43, hr/apps.py:14-17, core/dbgrid.py:157, config/database.py:11
- Açıklama: Etkinlik günlüğü sayfası HR geçmişini `hr.all_employee` sahibi olmayanlardan gizler; veritabanı görüntüleyicisi `audit_log`'u `_base_manager.all()` ile ham gösterir. Görüntüleyici yalnızca platform yöneticisine açık olduğundan bu bir yetkisiz erişim değil, ama iki yüzeyin kuralı farklıdır ve README bunu söylemez (platform yöneticisi `hr.all_employee` sahibi sayılsa da `has_perm` superuser için hep True olduğundan etkisiz).
- Kanıt: `rows = self.table.model._base_manager.all() # soft-deleted rows included: this is the database` (dbgrid.py:157).
- Öneri: Bilinçli kabulü README'ye yaz.

### F-284 `?page=` değeri `isdecimal()` ile doğrulanıp `int()`'e verilir; çok uzun rakam dizisi (4300+ hane) `ValueError` (500) üretir

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-8`
- Dosyalar: core/dbgrid.py:146
- Açıklama: Python'un `int()` rakam sınırı (varsayılan 4300) aşılırsa `ValueError` fırlar ve bu yakalanmaz. Gunicorn'un 4094 baytlık istek satırı sınırı arkasında ulaşılamaz; daha gevşek bir ters vekilde (8 KB) erişilebilir. Etkisi yalnızca oturum açmış platform yöneticisinin kendi isteğidir.
- Kanıt: `max(int(params['page']), 1) if params.get('page', '').isdecimal() else 1`.
- Öneri: `try/except ValueError` veya `len` sınırı.

### F-285 İzin talebi formu: "tür oluşturulurken seçilir" belgesi ile kod uyuşmuyor

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-10`
- Dosyalar: `hr/forms/leave.py:39-42`
- Açıklama: Sınıf açıklaması "the person and the type are chosen once" diyor, ama `fixed_after_creation = ('employee',)` yalnızca çalışanı sabitliyor. Bekleyen talebin türü sonradan değiştirilebiliyor; bu durumda kota yeni türe göre yeniden hesaplanıyor (iyi) ama `needs_approval=False` olan bir türe geçmek talebi otomatik onaylamaz (yalnızca `adding` iken `APPROVED` yapılıyor). Ayrıca `leave_type` kümesi yalnızca `status='active'`: türü sonradan pasifleşen bekleyen bir talep düzenlenirken mevcut tür seçeneklerde bulunmadığı için form hata verir ve talep düzenlenemez.
- Kanıt: `self.fields['leave_type'].queryset = LeaveType.objects.filter(status='active')` (satır 66), `if adding and not kind.needs_approval:` (satır 102).
- Öneri: Ya türü de `fixed_after_creation`'a ekleyin ya da mevcut türü kümeye dahil edip belgeyi düzeltin.

### F-286 RowList her kayıtta satırları silip yeniden yaratıyor: kimlik, oluşturan ve oluşma zamanı kaybolur

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-7`
- Dosyalar: `core/crud.py:360-372`
- Açıklama: `RowList.save` eski satırları `delete()` edip `bulk_create` ile `created_by=user` olarak yeniden yazar. Değişmeyen satırlar bile yeni kimlik, yeni `created_by` ve yeni `created_at` alır; bir satıra dışarıdan verilen referans (varsa) kopar, satırların kim tarafından ne zaman eklendiği bilgisi her kaydedende kaydedene devredilir. `bulk_create` model `save()` ve `full_clean()` çağırmaz; doğrulama yalnızca formset'e güveniyor. Denetim kaydı satır bazında değil metin özeti olarak tutuluyor. Monitoring board kartlarında silinmiş birimlere ait satırlar da sessizce düşer (`monitoring/forms.py` docstring: "saving the list drops it"), oysa soft-delete belgesi "geri yüklenince kart döner" diyor.
- Kanıt: `cls.rows(obj).delete()` ve `model({link: obj, 'created_by': user}, ...)` (satır 364-366).
- Öneri: Değişmeyen satırları koruyup yalnızca farkı yazın (id ile eşleştirme); en azından `created_by/created_at` değerlerini koruyun.

### F-287 Yeni kullanıcı daveti transaction içinde e-posta gönderiyor ve sonucunu kontrol etmiyor

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-9`
- Dosyalar: `core/resources.py:62-69`, `core/crud.py:690-700`
- Açıklama: `UserResource.after_save` kayıt transaction'ı içinde çalışır; `invitation.is_valid()` sonucu yok sayılıyor, `invitation.save(...)` SMTP hatasında istisna fırlatırsa tüm kullanıcı oluşturma geri alınır ve kullanıcı 500 görür; tersine commit sonrası başarısız olursa e-posta zaten gitmiş olur (`on_commit` yok). `is_active` işaretsiz yeni kullanıcı için `get_users` hiç kullanıcı bulmaz ve davet sessizce gönderilmez; kullanıcıya uyarı çıkmaz. E-posta tekliği `clean_email` ile uygulanıyor, DB unique yok (yarış mümkün).
- Kanıt: `invitation.is_valid()` dönüş değeri kullanılmıyor; `core/forms.py:120-124` `clean_email` yalnızca form düzeyinde.
- Öneri: Gönderimi `transaction.on_commit` ile yapın, hatayı yakalayıp mesajla bildirin, pasif kullanıcı için uyarı verin.

### F-288 Ekipman kaydedilince silinmiş sistemlere olan bağlar hard delete edilir; modelin ve onay ekranının "restore bağı geri getirir" vaadiyle çelişir

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-10`
- Dosyalar: farm/forms/equipment.py:104-117, 181-190, farm/models/equipment.py:216-222, templates/crud/confirm_delete.html:41-43, core/softdelete.py:19-21
- Açıklama: `EquipmentSystem` düz satırdır; `EquipmentForm._save_m2m` `system_links.all().delete()` ile silinmiş sistemlere olan bağları da siler (form bunu yardım metninde açıklıyor). Ama `core/softdelete` ve onay ekranı "bağ satırı kalır, restore bağı geri getirir" der. Sistem silinip ekipman düzenlendikten sonra sistem restore edilirse bağ kayıptır. Davranış bilinçli ama iki belgeyle tutarsız; ayrıca kayıp bağlar audit'te yer almıyor.
- Kanıt: `self.instance.system_links.all().delete()` (equipment.py:186); `"restoring the system brings the link back"` (equipment.py:221).
- Öneri: Silinmiş sistem bağlarını silme (yalnızca formda görünenleri değiştir) ya da dokümanı güncelle.

### F-289 Mesaj silme audit log'a yazılmaz ve metin DB'de kalır

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-12`
- Dosyalar: messaging/services.py:267-275, messaging/models.py:127-158
- Açıklama: `delete_message` yalnızca `is_deleted/deleted_at/deleted_by` yazar (`update_fields`), `audit.record_*` çağrısı ve `version` yok; oysa üyelik/rol değişiklikleri loglanıyor. `body` silinmiş mesajda da durur ("metin gösterilmez" yalnızca sunum katmanı). Silme talebi (ör. KVKK/GDPR) fiilen yerine getirilmez; ayrıca silinmiş mesajın geri alınması için yol da yok (ama DB'den okunabilir).
- Kanıt: `message.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])` (services.py:274); `body` temizlenmez.
- Öneri: Silmede `body`'yi boşalt/anonimleştir (kontrol kısıtı `chk` ile uyumlu) ve gerekiyorsa log yaz.

### F-290 Rol silme hard delete'tir; onay ekranı üyeleri ve kaybedilecek izinleri göstermez, geri alma yolu yok

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-5`
- Dosyalar: core/crud.py:781-785, templates/crud/confirm_delete.html:51-52, core/resources.py:14-31
- Açıklama: `RoleResource` `AuditedModel` olmadığı için `DeleteView` doğrudan `obj.delete()` çağırır (kalıcı). Onay ekranı `plan=None` iken yalnızca genel "kalıcı silinir" metni gösterir; role bağlı kullanıcı sayısı/adı ve bunların kaybedeceği izinler gösterilmez (liste şablonu sayıyı gösteriyor ama silme diyaloğu göstermiyor). Silinen rolün izinleri audit'te `snapshot` ile kayıtlıdır ama restore mekanizması yok; son izinli rol silinirse kullanıcılar yetkisiz kalır.
- Kanıt: `audit.record_delete(...); obj.delete()` (crud.py:784-785); şablonda `{% else %}<p>This removes it permanently...` (confirm_delete.html:51).
- Öneri: Rol silme için bloklayıcı/uyarı (üyesi olan rol silinemez veya üye listesi gösterilir) ekle.

### F-291 `RowList.save` "hepsini sil, yeniden oluştur" yapar: satır kimlikleri, `created_at/created_by` her kayıtta sıfırlanır

Önem: **Düşük** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-9`
- Dosyalar: core/crud.py:357-371, farm/models/equipment.py:259-270, farm/models/site.py:198
- Açıklama: Site iletişimleri, besleyici kalibrasyonları vb. her kayıtta `rows(obj).delete()` + `bulk_create` ile komple yenilenir. Değişmemiş satırlar da yeni pk alır ve `created_by` o anki kullanıcı, `created_at` şimdi olur; asıl oluşturan ve ilk giriş zamanı kaybolur. Bu satırlara dışarıdan pk ile bağlanan bir şey (şu an yok) kırılırdı. Log yalnızca özet önce/sonra karşılaştırması tutar. İyimser kilit kayıt düzeyinde var (iyi).
- Kanıt: `cls.rows(obj).delete(); model.objects.bulk_create([... 'created_by': user ...])` (crud.py:364-367).
- Öneri: Satırları pk ile eşleştirip yalnızca değişeni güncelle/ekle/sil.

### F-292 Yönetici arayüzünde geri getirme yok ("void" sınıfı) ve bazı kayıt türleri için hiç geri alma yok

Önem: **Düşük** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-9`
- Dosyalar: README.md:568, 1004, 1276, 1497, 1844; core/admin.py:39-53
- Açıklama: Void'lanmış operasyonlar, besleme, su örnekleri, tedaviler, olaylar ve sayımlar için yönetici geri getirme "bilerek" yok (kontrolleri atlayacağı için). Bu tutarlı bir tasarım, ancak yanlış void yapıldığında bunun tek çaresi "yeniden girmek"tir; su örneklerinde `entry_key` aynı olduğundan aynı form yeniden gönderilirse unique constraint nedeniyle de engellenebilir (kontrol edilmedi; confidence düşük).
- Kanıt: README satırları yukarıda; `uq_water_measurements_entry` (entry_key, measured_at) farm/models/water.py:125.
- Öneri: Void'u geri alan, kontrolleri çalıştıran bir "unvoid" servisi düşünün veya düzeltme yolunu (yeni giriş) belgeleyin.

### F-293 Log satırının bütünlüğü/özgünlüğü doğrulanamıyor: zincir/imza yok, `created_at` uygulama saatinden, INSERT serbest

Önem: **Düşük** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-2`
- Dosyalar: core/models.py:170-189, core/audit.py:144-158, core/test_languages.py:169, core/tests_scope.py:190
- Açıklama: `created_at` `auto_now_add` (uygulama sunucusunun saati); veritabanı `now()` değil. `user_name`, `action`, `entity_type` üzerinde veritabanı kısıtı yok (yalnızca `severity` için CHECK var), `action` seçimleri yalnızca Django düzeyinde. `AuditLog.objects.create(...)` ile herhangi bir kod yolu serbestçe sahte satır ekleyebilir (testler bunu yapıyor); hash zinciri veya imza olmadığından eklenen/silinen satır sonradan fark edilemez (13-1 ile birleşince).
- Kanıt: `created_at = models.DateTimeField(auto_now_add=True, db_index=True)` (models.py:171); `constraints = [CheckConstraint(... name='chk_audit_log_severity')]` tek kısıt (models.py:198-201).
- Öneri: Zaman damgasını DB varsayılanıyla (`clock_timestamp()`) ata, `action` için CHECK ekle, isteğe bağlı olarak önceki satırın hash'ini içeren zincir veya periyodik dış arşiv/imza.

### F-294 Soft delete ve RESTORE satırlarında değişiklik içeriği yok

Önem: **Düşük** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-5`
- Dosyalar: core/softdelete.py:177-203, core/audit.py:175-176
- Açıklama: `execute` her kayıt için `audit.record_delete(user, record)` çağırır, `changes` boş; `restore` da `audit.record(user, RESTORE, record)` ile boş yazar. Hangi alanların (ör. `version`, `is_deleted`, `deleted_at`) değiştiği ve restore edilen kaydın o anki değerleri log'dan okunamaz; restore'un `full_clean()` ile kod değişikliği gibi yan etkileri de belirtilmez. Silinen kaydın son hali yalnızca soft delete edilmiş satırdan okunabilir (o da sonradan değişebilir).
- Kanıt: `audit.record_delete(user, record)` (softdelete.py:184-185); `audit.record(user, AuditLog.Action.RESTORE, record)` (softdelete.py:203).
- Öneri: Silme/restore satırlarına kaydın snapshot'ını (ve restore'da varsa değişen alanları) ekle.

### F-295 "Aynı transaction'da yaz" kuralı yalnızca konvansiyon: `audit.record` bir transaction içinde olup olmadığını denetlemiyor

Önem: **Düşük** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-8`
- Dosyalar: core/audit.py:1-3, core/audit.py:144-158, config/settings.py (ATOMIC_REQUESTS yok), core/softdelete.py:177-186
- Açıklama: Modül başlığı "Call these inside the same transaction as the change"; ancak `record()` `connection.in_atomic_block` kontrolü yapmıyor, `ATOMIC_REQUESTS` tanımlı değil, `softdelete.execute` da "çağıranın transaction'ında" diyor. Bugün incelenen tüm yazma yolları (`crud`, hr, tasks, stock, inventory, experiments, reports, messaging) atomic blok içinde; ama yeni bir çağıran bloğu unutursa değişiklik logsuz kalır veya log satırı değişiklik olmadan yazılır (autocommit). Bunu yakalayan test de yok.
- Kanıt: `return AuditLog.objects.create(...)` koruma olmadan (audit.py:147); `grep ATOMIC_REQUESTS config/settings.py` boş.
- Öneri: `record()` başında `assert connection.in_atomic_block` (veya `transaction.get_connection().in_atomic_block` ile `RuntimeError`) ekle; testlerde `TestCase` zaten atomic olduğundan `TransactionTestCase` ile bir kontrol testi yaz.

### F-296 Log kapsamı model düzeyinde zorlanmıyor; bazı yazmalar bilinçli veya istemsiz log dışı

Önem: **Düşük** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-9`
- Dosyalar: messaging/services.py:101-112, messaging/services.py:268-276, tasks/services.py:253, tasks/services.py:286, core/language.py:22-23, core/tests.py:198-200
- Açıklama: Doğrulanan log'suz yazmalar: mesaj silme (`delete_message`: `is_deleted/deleted_by` yazılıyor, audit yok; mesaj gönderme de yok), doğrudan konuşma ve katılımcı oluşturma (`start_direct`), `TaskSeries.generated_until` güncellemesi (üretim cursor'ı, `materialise` GET sayfa okumasında bile çalışıyor), `Profile` dil kaydı (`update_or_create`). Bunlar kısmen bilinçli (mesaj içeriği, işlemsel durum), ama hiçbiri "log dışı" olarak belgelenmemiş; `core/tests.py` açıkça "a write that is not logged is not seen: the token test of the writers is what guards that" diyor, yani her yazıcı için ayrı test var ama genel güvence yok. `delete_message` özellikle bir "silme" işlemi olup kimin sildiğini yalnızca satırın kendisi tutuyor.
- Kanıt: `message.is_deleted, message.deleted_at, message.deleted_by = True, timezone.now(), user; message.save(...)` ve audit çağrısı yok (messaging/services.py:271-275).
- Öneri: Log dışı bırakılan yazmaları `docs/data-map` içinde "log yok, nedeni" olarak belgele; mesaj silme için en azından silme eylemi log'lansın (içerik olmadan).

### F-297 Frozen/append-only trigger'ları için veri migration'ı kılavuzu yok; trigger'ı devre dışı bırakma deseni kopyalanmış

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-10`
- Dosyalar: reports/migrations/0002_filed_reports_frozen.py, experiments/migrations/0002_design_frozen.py, monitoring/migrations/0002_card_templates.py:3-8,82-85, reports/migrations/0005_notified_moved_into_notices.py:97-118
- Açıklama: Beş farklı veritabanı katmanı koruması var (audit_log, filed reports/snapshots/cevaplar, experiments, built-in card templates). Gelecekte bu tablolarda veri düzeltmesi gerektiğinde her migration `ALTER TABLE ... DISABLE TRIGGER` adımını yeniden yazmak zorunda; yalnızca monitoring docstring'i bunu ("A later change to a built-in is a migration that disables the trigger around its own update") söylüyor, ortak bir yardımcı yok. Reports 0005 yetkisiz devre dışı bırakma deseninin tek örneği.
- Kanıt: monitoring 0002:7-8; reports 0005:114-118.
- Öneri: `core` içinde `without_trigger(schema_editor, table, trigger)` yardımcı bağlam yöneticisi ve docs/ altında kılavuz.

### F-298 Migration'lar farm.models.feeding_protocol ve hr.models.scheduling gibi canlı model modüllerini import ediyor

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-3`
- Dosyalar: experiments/migrations/0001_initial.py:9,362, farm/migrations/0015_feeding_protocols.py:8, hr/migrations/0003_scheduling.py:5
- Açıklama: experiments 0001 `farm.models.feeding_protocol.DateRange` kullanıyor; bu isim orada yalnızca `from core.ranges import DateRange` yeniden-export'u (feeding_protocol.py:29). farm 0015 ise doğrudan `core.ranges.DateRange` kullanıyor. Aynı fonksiyonun iki farklı yoldan referansı; yeniden-export kaldırılırsa experiments 0001 import hatası verir. hr 0003 `hr.models.scheduling` import eder (bases/validators için).
- Kanıt: feeding_protocol.py:29; experiments 0001:362 `farm.models.feeding_protocol.DateRange(...)`; farm 0015:133 `core.ranges.DateRange`.
- Öneri: experiments 0001 deconstruct yolunu `core.ranges.DateRange`'e çevirmek (ifade ayni).

### F-299 Geri alma sessizce no-op: veri dönüşümü kayıpsız geri dönmüyor

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-4`
- Dosyalar: farm/migrations/0023_reports_fields.py:45,91, farm/migrations/0004_production_departments.py:43, hr/migrations/0003_scheduling.py:120, monitoring/migrations/0002_card_templates.py:243
- Açıklama: farm 0023 `organisation_numbers` serbest metni dokuz haneye çevirip anlamsız olanı `notes`'a taşıyor; reverse noop (kolon adı geri döner, ama değer artık 9 haneli ve notlara eklenen metin kalır, `provenance` kolonu düşer). farm 0004 `administration` -> `other` dönüşümü geri alınmaz (bilgi kaybı: eski değer yok). Bu kayıplar dokümante edilmemiş (0023 docstring'i geri alma davranışını söylemiyor).
- Kanıt: 0023:45 `RunPython(organisation_numbers, noop)`; 0004:43 `RunPython(administration_becomes_other, noop)`.
- Öneri: Geri alma kısıtlarını docstring'e yazmak veya `IrreversibleError` ile açıkça belirtmek.

### F-300 Site.facilities/settings/metadata JSONField null=True (iki boş durum)

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-11`
- Dosyalar: farm/models/site.py:111-114
- Açıklama: `null=True, blank=True` ile NULL ve `{}`/`null` JSON değerleri ayrı boş durumlar; JSON `null` ile SQL NULL karıştırılabilir. Şema/tip denetimi (CHECK jsonb_typeof) yok, oysa monitoring.CardTemplate bunu yapıyor. Ayrıca `settings` alan adı Django `settings` ile karışmaya açık.
- Kanıt: `facilities = models.JSONField(_('Facilities'), null=True, blank=True)` x3.
- Öneri: `default=dict`, null=False ve jsonb_typeof CHECK.

### F-301 Uzun metinler için CharField(max_length=10000/5000)

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-12`
- Dosyalar: knowledge/models/document.py:99-100, reports/models.py:~89-94
- Açıklama: `Document.abstract` max_length=10000, `authors` 5000 gibi uzun varchar'lar; PostgreSQL'de TextField+CHECK ile eşdeğer ama migrasyon maliyeti (limit değişimi ALTER) fazla. Aynı projede başka yerlerde `TextField` kullanımı var (tutarsızlık).
- Kanıt: `abstract = models.CharField(_('Abstract'), max_length=10000, blank=True)`.
- Öneri: TextField + CHECK(char_length) tutarlı yaklaşım.

### F-302 audit_log'da gereksiz (tekrarlayan) indeks

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-2`
- Dosyalar: core/models.py:180,193
- Açıklama: `entity_type` için tek sütunlu `db_index=True` var; ayrıca `(entity_type, entity_id)` bileşik indeksi var. Bileşik indeksin öndeki sütunu aynı sorguları karşılar; tek sütunlu indeks yazma maliyeti ve disk ekler (append-only büyüyen tablo).
- Kanıt: `entity_type = models.CharField(max_length=50, db_index=True)` ve `models.Index(fields=['entity_type', 'entity_id'])`.
- Öneri: `db_index=True`'yu kaldır.

### F-303 audit_log.action için CHECK yok (severity için var)

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-3`
- Dosyalar: core/models.py:172-199
- Açıklama: `severity` `chk_audit_log_severity` ile kısıtlı ama `action` (create/update/delete/restore/void) serbest 10 karakter; migrasyon 0002'de `void` seçeneği yok (seçenek sonradan eklendi), yani seçim listesi ile veri bütünlüğü tutarsız ele alınmış.
- Kanıt: `constraints = [CheckConstraint(severity__in=...)]` tek kısıt; `action = CharField(max_length=10, choices=...)`.
- Öneri: `chk_audit_log_action` ekle. (Değişmez tabloda ihlal eden eski satır olmadığını doğrula.)

### F-304 Meta indeksleri FK'nin otomatik indeksiyle çakışıyor

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-5`
- Dosyalar: farm/models/stock.py:399, inventory/models.py:125,390
- Açıklama: Django her ForeignKey'e otomatik indeks açar. `StockMovement` `Index(fields=['batch'])` (batch FK db_index varsayılan True), `StorageLocation` `Index(fields=['site'])`, `InventoryLine` `Index(fields=['location'])` aynı sütunu ikinci kez indeksler. (Karşıt örnek: water.py:104 `db_index=False` ile bu hatadan kaçınmış.) Migrasyonda ayrıca `AddIndex` olarak oluşuyor (inventory/migrations/0001_storage.py:189-191,257-259).
- Kanıt: `indexes = [models.Index(fields=['unit', 'batch']), models.Index(fields=['batch'])]`; `batch = ForeignKey(Batch, ...)` db_index=False verilmemiş.
- Öneri: FK'ye `db_index=False` ver veya fazladan Meta indeksini sil. Not: `(unit, batch)` bileşik indeksi `unit` FK indeksini kısmen gereksiz kılar.

### F-305 unique kuralı büyük/küçük harf duyarlılığı tutarsız

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-9`
- Dosyalar: farm/models/site.py:134-137, farm/models/species.py:135, farm/models/supplier.py:168, farm/models/feed.py:181
- Açıklama: Supplier/Feed/Board/Template adları `Lower('name')` ile benzersiz; `Site.name` ise `fields=['name']` (büyük/küçük harf duyarlı): "Tromso" ve "tromso" iki ayrı site olabilir. Kodlar (`code`) büyük harfe zorlanıyor ama `uq_*_code_live` doğrudan eşitlik.
- Kanıt: `models.UniqueConstraint(fields=['name'], condition=Q(is_deleted=False), name='uq_sites_name_live')`.
- Öneri: `Lower('name')` kullan.

### F-306 `receive`/`count`: `item_for` ana işlemden ayrı işleme yazıyor; reddedilen işlemde yetim `InventoryItem` + audit kalır

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-7`
- Dosyalar: inventory/services.py:71-81, 274-276, 326-328
- Açıklama: `item_for` kendi `atomic` bloğunda öğe ve audit CREATE satırı oluşturur. `receive` ve `count` bunu `_commit` çağrısından önce, dışarıda çalıştırır; `_commit` doğrulamada reddederse (görünüm `atomic` sarmıyor) yeni öğe ve audit satırı kalıcı olur. Zararı sınırlı, ama "başarısız işlem iz bırakmaz" beklentisini bozar. Ayrıca her `item_for` çağrısı tüm kiracı için tek global advisory lock (`hashtext('inventory_items')`) alır.
- Kanıt: `entries = [Entry(NewLot(item_for(feed, user), ...` (276, 327), `_commit` ayrı `atomic` (138).
- Öneri: `receive`/`count` gövdesini tek `transaction.atomic()` altında çalıştır.

### F-307 `messaging.post`: `on_commit` içinde `Signal.send`; alıcı istisnası commit sonrası çağırana sızar (mesaj yazılmış, istek 500)

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-8`
- Dosyalar: messaging/services.py:246-247, messaging/events.py:14, messaging/views.py:96-100
- Açıklama: `events.message_posted.send` alıcı hatasını yutmaz; commit tamamlandıktan sonra yükselen istisna kullanıcıya hata gösterir, kullanıcı yeniden gönderince çift mesaj oluşur. Şu an alıcı yok (yalnızca testte), yani gizli bir tuzak.
- Kanıt: `transaction.on_commit(lambda: events.message_posted.send(...))`.
- Öneri: `send_robust` kullan ve hataları logla.

### F-308 Retention, compression ve continuous aggregate yok.

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-2`
- Dosyalar: farm/migrations/0014_water.py:91-103, README.md:1068
- Açıklama: README "compression is left for later" der; retention politikası ve CAGG hiç yok. Mevcut hacimde sorun değil, ancak sensör gelirse tablo sınırsız büyür.
- Kanıt: migration'da yalnızca `create_hypertable`.
- Öneri: Hacim eşiği ve gelecekteki politika (compress_after, retention) belgelenmeli.

### F-309 Hypertable'da `id` tek başına DB düzeyinde benzersiz değildir.

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-4`
- Dosyalar: farm/models/water.py:84-90, farm/migrations/0014_water.py:92-102
- Açıklama: PK `(id, measured_at)` ile Timescale yalnızca (id, measured_at) çiftini garanti eder; Django state'i `id`'yi PK sanır (`get(pk=)`, void). UUID4 çakışması pratikte imkansız, ama DB garantisi yok; ayrıca `void` ve `in_bulk` id ile tüm chunk'lara bakar.
- Öneri: Kabul edilen risk olarak belgelenmiş (docstring); id'ye güvenen kodlarda (audit log object_id) ek `measured_at` taşımak değerlendirilebilir.

### F-310 Duyarlılık uyuşmazlıkları: ağırlık/fiyat birimleri farklı ondalıklarla iki yerde

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-12`
- Dosyalar: farm/models/stock.py:314-318 (avg_weight_g 4 ondalık), farm/models/feed.py:277-281 ve farm/models/feeding_protocol.py:151-154 (bant sınırları 2 ondalık), farm/models/feed.py:160 (`price_per_kg` 2 ondalık, >= 0.01) ve inventory/models.py:355 (`unit_cost` 4 ondalık)
- Açıklama: Balık ortalama ağırlığı 0,0001 g, besleme bandı sınırları 0,01 g; sınırdaki bir ortalama (örn. 5,0049 g) bandın "altında" kalır, davranış tutarlı ama belgelenmemiş. Aynı yemin fiyatı Feed.`price_per_kg` (kg başına) ve InventoryLine.`unit_cost` (birim başına) olarak iki kaynakta ve farklı duyarlılıkla; maliyet raporları hangisini kullanacağı belirsiz. `feed_suitability` CHECK'leri `max_weight_g` için `>=0.01` yazılmış ama alan null olabilir (NULL CHECK'i geçer): niyet ile kısıt uyumsuz.
- Kanıt: bkz. satırlar; `chk_feed_suitability_max_weight` (feed.py ~305).
- Öneri: Sözleşmeyi belgele; fiyat için tek kaynak; `max_weight_g` null ise açık kısıt.

### F-311 `check_stock` içindeki "fold sayısı = satır toplamı" kontrolü totolojik

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-5`
- Dosyalar: farm/stock/integrity.py:115-121
- Açıklama: Aynı canlı satır kümesi hem fold'a hem `Sum('count_delta')`'ya giriyor; fold'un sayısı zaten `count_delta` toplamı. Kontrol fold'da sapma olmadıkça hiçbir şey yakalamaz ve `shares.update(fold(...))` bir batch'in hata vermesi durumunda (`broken`) atlanır. Gerçek riskleri (yetim satır: silinmiş birim/parti, void edilmiş operasyonun satırı) yakalamıyor.
- Kanıt: `share.count != row['fish']` (integrity.py:119); `ledger` filtresi `operation__is_deleted=False` (stock/read.py:33-35) ile aynı.
- Öneri: Bağımsız doğrulama ekle: `Tank` başına `unit_counts` ile `fold` birim toplamı; silinmiş Batch'e/Tank'a bağlı canlı satır; operasyonsuz satır (FK cascade zaten) için.

### F-312 Site ve System kapasite alanları elle giriliyor, hiçbir yerde türetilmiş Tank toplamıyla karşılaştırılmıyor; Site alanlarında negatif değer CHECK'i yok

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-8`
- Dosyalar: farm/models/site.py:100-104, 129-190; farm/models/system.py:58-66, 77-84; farm/models/tank.py:370-384; templates/farm/system_list.html:45-46
- Açıklama: `System.total_volume_m3`/`max_biomass_kg` ve `Site.water_capacity_m3`/`max_biomass_kg` girilen değerler; Tank'ın hacmi/max biyokütlesi ise DB'de türetiliyor. Hiçbir okuyucu bunları karşılaştırmıyor (grep: yalnızca liste şablonu gösteriyor) - çift kaynaklı doğruluk, zamanla çelişir. Üstelik System'de `>= 0` CHECK'i varken Site'ta `area_m2`, `water_capacity_m3`, `max_biomass_kg` için hiçbir sınır (model validator veya CHECK) yok; negatif girilebilir.
- Kanıt: sites constraint listesinde bu alanlar için `chk_*` yok (site.py:129-190); `chk_systems_total_volume` yalnızca System'de.
- Öneri: Alanları kaldır/türet (Tank toplamı) veya "tavan vs kullanım" kontrolü ekle; Site alanlarına `>= 0` CHECK.

### F-313 İzin günleri okuma anında hesaplanıyor: çalışma günü ayarı/tatil sonradan değişince onaylı izinlerin maliyeti ve bakiyeler geriye dönük değişir

Önem: **Düşük** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-9`
- Dosyalar: hr/leave.py:41-71; hr/forms/leave.py:94-102; hr/models/leave.py (LeaveRequest docstring)
- Açıklama: `leave_days` hiçbir yerde saklanmıyor; `SchedulingSettings.working_weekdays` veya `Holiday` eklenip silinince geçmiş/onaylı taleplerin "kullanılan gün"ü ve kalan hak değişir (örn. cumartesi çalışma günü yapılınca 2025 izinleri de yeniden fiyatlanır). Ayrıca `used()` mevcut taleplerin hepsini yeni talebin `site`'ı ile fiyatlandırıyor (hr/leave.py:56-64, forms/leave.py:92-97): çalışan site değiştirmişse önceki talepler yanlış site tatilleriyle hesaplanır.
- Kanıt: `charged_by_year(request.first_day, request.last_day, site)` içinde `SchedulingSettings.get().working_weekdays` anlık okunuyor (leave.py:43).
- Öneri: Onay anında `charged_days` ve kullanılan takvimin anlık kaydı (snapshot) ya da ayar değişiminde geriye dönük etki uyarısı.

### F-314 Yemleme kaydı; açlık günü, bant yemi, pellet uygunluğu ve tıbbi yem için yalnızca uyarı veriyor, hiçbirini engellemiyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-12`
- Dosyalar: farm/feeding/services.py:25-80, farm/feeding/views.py:337-364, farm/forms/feeding.py:81-103
- Açıklama: `record_feeding` servisi aktif yem, balık varlığı ve %10 onayı dışında hiçbir iş kuralı uygulamıyor: planlı hasat/nakil öncesi açlık günü (`fasting_on` yalnızca sayfada bilgi), kaydedilen yemin atanmış protokol bandının yemiyle aynı olması, türe/ağırlığa uygunluk (yalnızca `messages.warning`), ve ilaçlı yem için kapsayıcı tedavi yoksa yalnızca uyarı. Servisi çağıran başka yollar (ör. ileride API/toplu içe aktarma) bu uyarıları hiç görmez; çünkü bunlar view katmanında. Bant yemi ile verilen yem arasındaki fark by-day sapmasında görünmez (yalnızca kg).
- Kanıt: services.py'de `fasting`, `suits`, `Feed.Type.MEDICATED` hiç geçmez; uyarılar views.py:340-350'de; açlık yalnızca bağlam (`'fasting': fasting_on(unit, day)`, views.py:354).
- Öneri: Uyarı üreten kuralları servis katmanına taşıyıp sonuç olarak döndürün (veya audit log'a yazın), böylece her giriş yolu aynı sonucu görür.

### F-315 Protokol SFR üst sınırı (15 %) ile yemleme onay eşiği (10 %) çelişiyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-3`
- Dosyalar: farm/models/feeding_protocol.py:44, config/settings.py:221, farm/feeding/services.py:64-72, farm/feeding/views.py (`next_meal`)
- Açıklama: Tablo hücreleri 15 %/gün'e kadar tanımlanabiliyor ("covers first-feeding fry"), ancak herhangi bir kayıt biyokütlenin %10'unu aşarsa kullanıcıdan onay kutusu isteniyor. %10 üstü SFR'li bir bantta (yavru) tüm gün tek öğün (`meals_per_day=1`) olduğunda board'daki "Record meal" önerilen miktarı doğrudan onay uyarısına çarpar; sistem kendi hesapladığı oranı "alışılmadık" diye reddeder. Eşik bant/tür bazlı değil, global.
- Kanıt: `MAX_SFR = 15` (feeding_protocol.py:44) ve `FEEDING_ACK_PERCENT = 10` (settings.py:221); `next_meal()` ration/meals miktarını formu doldurmak için kullanır, `ack` set etmez.
- Öneri: Eşiği protokolün o gün için hesaplanmış oranına (veya bant SFR'sine) göre ayarlayın ya da onay eşiğini en az `MAX_SFR`'a eşitleyin.

### F-316 Sıcaklık yoksa ya da açlık gününde yem sınırsız büyüme olarak kredilendiriyor (üst sınır tam da veri eksik olduğunda devre dışı)

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-5`
- Dosyalar: farm/feeding/projection.py:246-248, README.md (Estimated weight bölümü), farm/feeding/ration.py:223-234
- Açıklama: Üst sınır (Q4) yalnızca `basis.has_ration` iken uygulanıyor. Sıcaklık yoksa, tablo dışıysa veya açlık (fasting) günüyse `credit = part` olur ve yem tamamı büyümeye çevrilir. README bunu bilinçli ("its feed is credited as given") yazıyor, ama sonuç, ölçümü en güvenilmez günlerde tahmini ağırlığın en şişkin hesaplanmasıdır; bu tahmin düzenleyici biyokütle raporunda (19-6) ve hasat tahmininde kullanılıyor.
- Kanıt: `credit = part` / `if basis.has_ration:` (projection.py:247-248); açlık dalı `Basis(... missing=FASTING)` `sfr=None` (ration.py:226-228).
- Öneri: Bu günlerde büyümeyi kredilendirmeyin veya band için "son bilinen oran" ile sınırlayın; en azından bu günleri raporda "kör gün" gibi işaretleyip projeksiyonu PROJECTED olarak kullanmayın.

### F-317 Başlamış atama satırının son günü formda uzatılabiliyor/silinebiliyor, servis ise "yalnızca kısaltılır" diyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-7`
- Dosyalar: farm/forms/feeding_protocol.py:374-381, farm/feeding/assignments.py:76-82
- Açıklama: `assignments.end()` başlamış satırın son gününü yalnızca kısaltmaya izin verir ("The row ends on %(day)s already: it is only ever shortened"). `AssignmentForm.clean_valid_until` ise yalnızca "dünden önce" kontrolü yapar; `until` boş bırakılarak (None) veya ileri bir tarihe alınarak başlamış bir satır uzatılabilir. İki yazma yolu aynı kuralı uygulamıyor; deney (experiments) yolu `end()` kullandığından davranış yola göre değişiyor. Uzatma yalnızca gelecek günleri etkiler ama "satır geçmiştir, sona erdirilir" kuralıyla ve denetim izi beklentisiyle tutarsız.
- Kanıt: `if self.started and until != stored and until is not None and until < self.today - timedelta(days=1)` (forms/feeding_protocol.py:376-378) vs `if row.valid_until is not None and last_day > row.valid_until: raise` (assignments.py:79-82).
- Öneri: Formu da `assignments.end()` kuralına bağlayın (uzatmayı reddedin ya da iki yolda da izin verin ve belgeleyin).

### F-318 Bit sayımı girişinde asgari örneklem ve makullük kontrolü yok

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-10`
- Dosyalar: `farm/health/services.py:256-276`, `farm/models/health.py:578-582,597-602`, `farm/forms/health.py:341`
- Açıklama: Vedlegg 1 gereği kafes başına en az 10 (bahar haftalarında 20) balık sayılmalıdır; bu yalnızca form yardım metninde geçer ve `LiceWeek.small_samples`/rapor uyarısında kullanılır. Kayıt anında hiçbir uyarı yoktur; `fish_counted` alt sınırı 1'dir. Bit sayıları için üst sınır 1.000.000'dir (1000 balıkta fiziksel olarak makul değil) ve bir aşama sayısının örneklem büyüklüğüne oranı doğrulanmaz; bir sıfır fazlası yazım hatası bir siteyi limit aşımına sokabilir.
- Kanıt: `models/health.py:578-582` (`MinValueValidator(1)`, `MAX_LICE`), servis içinde minimum örneklem kontrolü yok.
- Öneri: Kayıt anında `lice.minimum_fish(area, week)` altı için uyarı ver; kafes başına ortalama olağandışı yüksekse onay iste.

### F-319 Bit sayfasında ve tedavi listesinde tüm kayıtlar bellekte işleniyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-11`
- Dosyalar: `farm/health/read.py:422-437`, `farm/health/views.py:143-150`, `farm/health/views.py:285`
- Açıklama: `lice_weeks` sorgu kümesinin tamamını döngüyle okur, sonra `[:12]` ile keser; yıllar içinde sayım sayısı arttıkça her sayfa açılışı O(tüm sayımlar) olur. `show=withdrawal` veya parti süzgeci, tüm aday tedavileri belleğe `list(treatments)` ile alıp `Reader` kurar.
- Kanıt: `read.py:425-428` `for count in counts.filter(is_deleted=False)...order_by(...)`; `views.py:143`.
- Öneri: Hafta sayısını veritabanında sınırla (tarih alt sınırı) ve `LICE_WEEKS` kadar haftayı sorgula.

### F-320 Çok birimli tedavide handling onayı birim bilgisi taşımıyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-8`
- Dosyalar: `farm/models/handling.py:305-353`, `farm/handling/check.py:395-413`, `farm/health/services.py:204-207`
- Açıklama: Çok birimli bir tedavide her birim için ayrı oruç uyarısı üretilir ve her biri ayrı `HandlingAcknowledgement` olarak yazılır; ancak satırda birim (unit) sütunu yoktur. Hangi birimin yetersiz oruç uyarısının onaylandığı sonradan ayırt edilemez (yalnızca `rule`, saatler). `uq_handling_acknowledgements_one_fast` yalnızca `operation` için tanımlı olduğundan tedavide birden fazla "fasting" satırı mümkündür (bilinçli), ama yinelenen veya eksik satır kontrolü yoktur.
- Kanıt: `models/handling.py:314-331` alan listesi (unit yok); `services.py:205-207` her uyarılı değerlendirme için `check.acknowledge`.
- Öneri: Onay satırına `unit` FK'si ekle ve tedavi için (treatment, unit, warning) tekilliği tanımla.

### F-321 Servis katmanında girdi doğrulaması tutarsız; yalnızca formlar koruyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-10`
- Dosyalar: farm/stock/services.py:581-587,596-604,607-621,634-647,677-704,707-710,726-739
- Açıklama: Modül başlığı servisi "tek yazma yolu" ilan eder, ancak sayı/ağırlık doğrulaması yalnızca `record_escape`/`record_delivery` içinde (`_positive`) yapılır. `record_mortality(count=0)` `count_delta=0` üretir ve `chk_stock_movements_sign` ihlaliyle IntegrityError (500) olur; `record_weighing(sample_count=0)` Decimal bölme hatası verir; `record_harvest(count<=0)`, `record_transfer`/`record_grading`/`record_input` için de aynı. Şu an yalnızca formlar çağırıyor (başka çağıran yok), dolayısıyla etki dolaylı.
- Kanıt: services.py:586 `Entry(unit, batch, MovementKind.MORTALITY, -count, ...)` doğrulamasız; :615 `sample_weight_kg * 1000 / sample_count`; :707-710 yalnızca escape/delivery için `_positive`. - Etki: yeni bir çağıran (API, import, experiments) doğrulamayı atlarsa kullanıcı dostu hata yerine 500.
- Öneri: servis girişinde ortak `count >= 1`, `weight > 0` doğrulaması (ValidationError).

### F-322 Plan kalemi (HandlingPlanItem) ile gerçekleşen operasyon arasında planlanan adet/hedef birim doğrulanmıyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-11`
- Dosyalar: farm/stock/services.py:213-239, farm/models/harvest.py:335-359
- Açıklama: `_fulfil` yalnızca tür, kaynak birim/batch, iptal/silinme ve "zaten yapıldı" durumlarını kontrol eder. Transport planında `destination_unit` gerçek transferin hedefleriyle karşılaştırılmaz; planlanan adet/kg ile gerçek arasında eşik yok; plan kalemi `clean()` `planned_count`'ı birimdeki balıkla sınırlamaz. Plan "done" olduğunda tarihi veya miktarı ne olursa olsun kapanır; DB'de "done iken iptal edilemez" kuralı yalnızca `clean()`'de (CHECK yok).
- Kanıt: services.py:230-231 yalnızca `(item.unit_id, item.batch_id) != (source.unit.pk, source.batch.pk)`; harvest.py:346-347 iptal+done kontrolü yalnızca model clean. - Etki: planlanan ile gerçek sapma sessizce "Done" olarak görünür; planlı kesim raporu plan kg'ını kullanır (bkz. 21-3).
- Öneri: plan sapmasını (adet/kg/hedef) uyarı olarak gösterin ve `_add_actuals` çıktısını raporda karşılaştırın.

### F-323 Escape kaydı: recaptured doğrulanmıyor, geri yakalanan balık stoğa dönmüyor ve kayıt güncellenemiyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-12`
- Dosyalar: farm/forms/stock.py:602-603, farm/models/stock.py (EscapeRecord), farm/stock/services.py:713-725
- Açıklama: `recaptured` yalnızca `min_value=0`; `count`'tan büyük olabilir. Kayıt "never edited"; sonradan geri yakalanan balık için güncelleme yok, ancak void + yeniden kayıt (31 gün penceresi içinde). Geri yakalanan balığı stoğa geri alacak operasyon yok (ör. sayım artışı `chk escape_removes` ve 21-5 nedeniyle mümkün değil).
- Kanıt: forms/stock.py:602 `recaptured = forms.IntegerField(..., min_value=0, required=False)`; models/stock.py EscapeRecord "never edited". - Etki: Fiskeridirektoratet bildirimi için recaptured bilgisi eskir; stok gerçekten ayrılmış sayılır.
- Öneri: `recaptured <= count` doğrulaması ve ayrı bir güncelleme/geri alım operasyonu.

### F-324 Void sırasında kapasite (max biyokütle) yeniden kontrol edilmiyor ve onay istenmiyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-6`
- Dosyalar: farm/stock/services.py:742-760 (özellikle :753), :294-340
- Açıklama: `void` `_validate(set(batches), set(units), operation.date)` çağırır; `new_op_id`/`arriving` verilmediği için `grams_after` boş kalır ve `_over_capacity` `[]` döner; zaten dönen değer lambda tarafından yok sayılır. Bir çıkış (mortality/harvest/transfer_out) void edilince balık birime geri döner ve birim max biyokütleyi aşabilir, onay kaydı oluşmaz. Tür karışımı ise sonraki girişlerde yeniden doğrulanıyor (bu kısım güvenli).
- Kanıt: services.py:753 `check=lambda: _validate(...)`; :340 `return _over_capacity(grams_after, new_op_id)`; :343-345 `if not grams_after: return []`. - Etki: kapasite aşımı sessizce oluşur; kapasite kuralı (owner decision Q4) yalnızca yeni varış için işler.
- Öneri: void'de geri dönen balık için aşımı uyarı/onay ile ele alın veya bunun bilinçli olduğunu belgeleyin.

### F-325 Tuzlu/acı su ünitesinde tuzluluk girilmemişse NH₃-N hiç hesaplanmıyor (en toksik parametre yargılanmıyor)

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-13`
- Dosyalar: farm/water/read.py:75-78,291-301,319-328, farm/models/tank.py (WaterType), farm/water/calculation.py:313-320
- Açıklama: `assumed_salinity` yalnızca tüm üniteler tatlı su ise 0 varsayıyor; `saltwater`/`brackish` ünitede son 30 günde tuzluluk ölçümü yoksa NH₃-N ve eksik olan O₂ (mg/L ↔ %) hesaplanmıyor, yalnızca "Needs the salinity" notu çıkıyor (durum NOT_MEASURED). NH₃ limiti olan bir deniz ünitesi, TAN ölçülse bile NH₃ üzerinden hiç alarm üretmiyor ve unit chart reddediliyor. Ayrıca `Tank.water_type` ile ölçülen tuzluluk arasında çapraz kontrol yok (tatlı su ünitesinde 30 ‰ ölçüm sessizce kabul edilir; o zaman tuzluluk ölçümü varsayımın yerine geçer).
- Kanıt: `return Decimal(0) if set(water_types) == {Tank.WaterType.FRESHWATER} else None`; `_ammonia()`: `if salinity is None: return {NH3_N.code: Reading(NH3_N, None, ...)}`.
- Öneri: Su tipine göre tuzluluk için makul bir uyarı/varsayılan (ör. tanım alanı olarak tank/sistem tuzluluğu) veya örnek formunda TAN girilip tuzluluk yoksa uyarı verin; su tipi ile ölçülen tuzluluk aralığı uyuşmazlığı için plausibility uyarısı ekleyin.

### F-326 Negatif günlük sıcaklık derece-gün toplamından düşüyor (projeksiyon ise ≤0'ı reddediyor)

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-3`
- Dosyalar: farm/water/degree_days.py:125-133,171, farm/health/withdrawal.py:196-215, farm/water/parameters.py (temperature_c low=-3)
- Açıklama: Sıcaklık plausibility aralığı -3 °C'den başlıyor; ölçülen günlük ortalama negatif olabilir (Tromsø'de kışın buz altı/şok durumları, yazım hatası). `Counted(value, MEASURED)` bu negatif değeri olduğu gibi döndürüyor ve hem `accrue()` hem `degree_days()` `total += counted.value` ile toplamı azaltıyor; yani bekleme (withdrawal) ve açlık (fasting) hedefi o gün için ilerlemek yerine geriliyor. Bu güvenli yönde (daha uzun bekleme) bir hata, ama derece-gün tanımına aykırı ve bekleme/açlık tarihini keyfî uzatıyor. Aynı dosyada projeksiyon ortalaması `mean <= 0` ise "bilinmiyor" sayıyor (withdrawal.py:212): iki yol arasında negatif/sıfır sıcaklık için tutarsız kural var. Ayrıca tatlı suda -3 °C ölçüm fiziksel olarak mümkün değil, yani plausibility alt sınırı kaba.
- Kanıt: `accrual.total += counted.value` (degree_days.py:171), `total += counted.value` (withdrawal.py:207), `if mean is None or mean <= 0: return None, True, ...` (withdrawal.py:212); `_parameter('temperature_c', ..., 1, -3, 40, 24, 'oxygen')`.
- Öneri: Günlük katkıyı `max(value, 0)` ile sınırlandırın (ya da kuralı açıkça belgeleyin) ve hem toplam hem projeksiyon aynı kuralı kullansın; tatlı su ünitelerinde alt sınırı 0 yapmayı düşünün.

### F-327 Su tipine özel limit satırı, "any" satırını bütünüyle gölgeliyor (sınır bazında birleştirme yok)

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-6`
- Dosyalar: farm/water/evaluate.py:58-64, farm/models/water.py (WaterLimit docstring), farm/forms/water.py (limit formu help_text)
- Açıklama: `applying()` `rows.get((species, parameter, water_type)) or rows.get((species, parameter, ANY))` ile tek satır seçiyor. Kullanıcı "any" satırında dört sınırı, "saltwater" satırında yalnızca `warning_high` girdiyse, tuzlu sudaki ünite için `critical_*` ve düşük sınırlar tamamen kaybolur (yalnızca `warning_high` yargılanır); satırların alan bazlı mirası yok. Form yardımı yalnızca "wins over" diyor, bunu anlatmıyor.
- Kanıt: `return self.rows.get((species_id, parameter, water_type)) or self.rows.get((species_id, parameter, ANY_WATER))`.
- Öneri: Ya sınırları alan bazında birleştirin (spesifik satır yoksa any'den alın), ya da form/yardım metninde satırın tam yerine geçtiğini ve eksik sınırın "yok" sayıldığını açıkça yazın; boş sınırlı spesifik satır için uyarı verin.

### F-328 Hesaplayıcı/Deffeyes NH₃ ve CO₂ için farklı "uyarı" tanımı kullanıyor (pH payı 0.2) ve türün warning sınırını yok sayıyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-8`
- Dosyalar: farm/water/calculation.py:11-14,230-233, farm/water/deffeyes.py:51,129-137, farm/water/evaluate.py:45-55
- Açıklama: Ünite okuma yolunda NH₃-N ve CO₂ dört sınırla (warning/critical) yargılanırken, hesaplayıcı ve ünitenin Deffeyes grafiği yalnızca `critical_high`'ı limit olarak alıp "uyarı"yı sınırdan 0.2 pH uzaklık (`ALERT_PH`) olarak üretiyor. Aynı ünite için üretim ekranında NH₃ "OK" iken grafikte "warning" (veya tersi) görünebilir. Bu kod yorumunda belgelenmiş bir tasarım kararı, ancak iki ayrı "durum" tanımının kullanıcıya açıklandığına dair UI ipucu yok.
- Kanıt: `_strictest(limits.get(code, []), 'critical_high', min)` (calculation.py:232); `status = ... WARNING if margin <= ALERT_PH` (deffeyes.py:137).
- Öneri: Uyarı metnine "grafikteki uyarı pH payıdır, tür limitindeki warning sınırı değil" notu ekleyin ya da warning_high'ı da hesaba katın.

### F-329 Pozitif/negatif işaret ve süre doğrulamaları: geçmiş SKT'li lot teslimatı ve SKT < teslimat tarihi kontrol edilmiyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-10`
- Dosyalar: inventory/services.py:94-119, inventory/forms.py:191-218, 359-366
- Açıklama: Teslimat/sayım "bulunan lot" için `expiry_date` herhangi bir tarih olabilir (örn. teslimat tarihinden önce biten, zaten süresi geçmiş lot). Fold bunu "expired lot" olarak sona sıralar ve overview'da raporlar, ama giriş anında uyarı yok. Bilinen lot yeniden teslim edilirken SKT verilmezse mevcut SKT sessizce kullanılır (reddedilmez).
- Kanıt: `_resolve` yalnız `lot.expiry_date != wanted.expiry` ve `wanted.expiry is not None` iken kıyaslıyor.
- Öneri: SKT < işlem günü için uyarı/ret (write-off istisnası ayrı).

### F-330 `item_days`: aynı site içindeki transferler "geldi" ve "çıktı" olarak şişiriyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-12`
- Dosyalar: inventory/read.py:287-293
- Açıklama: Site lokasyonlarındaki `transfer_in` ve `transfer_out` satırları arrived/left sütunlarına yazılıyor; aynı site içi transferde net 0 olsa da gün satırında hem giriş hem çıkış görünür. Kapanış (`closing`) doğru ama arrived - left - fed != closing farkı kullanıcıyı yanıltabilir. Sitelerarası transfer doğru yansır.
- Kanıt: `if line.kind in ('in', 'transfer_in')` / `('out','transfer_out')` ayrım yok.
- Öneri: Site içi transfer çiftlerini netle veya ayrı "moved" sütunu kullan.

### F-331 Sayım pasif lokasyona yeni stok sokabiliyor ("pasif lokasyon yeni stok almaz" kuralını deliyor)

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-4`
- Dosyalar: inventory/services.py:48,183-186, inventory/forms.py:342, inventory/models.py (LocationStatus)
- Açıklama: `ARRIVING = (IN, TRANSFER_IN)`; COUNT satırı kontrol dışı. `CountForm` lokasyon seçiminde pasif olanları da sunuyor, "bulunan lot" ile pasif lokasyona stok girilebilir ve kitap artar. Belgelenen kural (README: "An inactive location takes no new stock") yalnızca teslimat/transferi kapsıyor.
- Kanıt: `_check_static` sadece `entry.kind in ARRIVING` iken status kontrolü yapıyor.
- Öneri: Pasif lokasyonda sayım sonucu artış (counted > book / found) için ret veya açık uyarı; ya da kuralı belgede "sayım hariç" olarak yaz.

### F-332 `costs()`: karışık para birimli teslimatlarda diğer para birimleri değer hesabından sessizce düşüyor; kısmi maliyetli lot tamamına yayılıyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-7`
- Dosyalar: inventory/read.py:111-124, 144, 225-227
- Açıklama: Lot için en son teslimatın para birimi seçiliyor, farklı para birimli teslimatlar `same` filtresiyle atılıyor; maliyet bilgisi olmayan teslimatlar (unit_cost NULL) ortalamaya girmiyor, ama ortalama maliyet lotun tüm kalan miktarına uygulanıyor. Ağırlıklı ortalama, tüketilen/çıkan miktarı hesaba katmıyor (FIFO/lot izleme yok), dolayısıyla "değer" yalnızca bir yaklaşım. Hiçbir uyarı yok.
- Kanıt: `same = [... if money == currency]`; `Bucket.value = quantity * cost[0]`.
- Öneri: Karışık para birimi veya kısmi maliyette değeri "eksik" işaretle; belgede yaklaşımı belirt.

### F-333 Birim modeli (`Unit.UNITS`) ve kapasite birimi pratikte ölü; "units" kapasiteli lokasyon asla uyarmaz

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-8`
- Dosyalar: inventory/models.py:53-58,163-165,182, inventory/read.py:254-258, inventory/resources.py:83
- Açıklama: Item birimi DB check ile feed -> kg, ve tek item tipi feed. Dolayısıyla `capacity_unit='units'` seçilen lokasyonda `row.item.unit == location.capacity_unit` hiçbir kovada doğru olmaz; "over capacity" asla tetiklenmez, form ise bu seçeneği sunuyor. `capacity = 0` kabul ediliyor (`MinValueValidator(0)`): 0 kapasiteli lokasyon stok girer girmez "over".
- Kanıt: `chk_inventory_items_feed_kg`; `over` döngüsü yalnız eşleşen birimleri topluyor.
- Öneri: Ilaç modülü gelene kadar `units` kapasitesini formda gizle/uyar; kapasite > 0 yap.

### F-334 `add_note` servisinde yetki kontrolü yok; yalnız view'a bağlı

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-13`
- Dosyalar: `tasks/services.py:190-203`, `tasks/views.py:62-72`
- Açıklama: Diğer servislerin aksine `add_note` kullanıcı yetkisine bakmaz ("view checks it"); gelecekteki API/asistan çağrıları (modül başlığı bunları öngörüyor) kontrolü atlayabilir. Ayrıca silinmiş göreve yarış durumunda `_locked` DoesNotExist (500) verir.
- Kanıt: `add_note` içinde `has_perm` çağrısı yok; `_locked` `Task.objects` (silinmişleri gizler).
- Öneri: Yetkiyi serviste zorunlu kıl.

### F-335 Okuma (GET) sırasında yazma: yalnızca görüntüleme yetkisi olan kullanıcı görev üretir

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-3`
- Dosyalar: `tasks/resources.py:92,226`, `tasks/views.py:142`, `tasks/services.py:228-255`
- Açıklama: Her liste/overview GET isteği kilit alıp görev, checklist ve audit satırı yazabilir; salt okuma yetkili kullanıcı da tetikler. Cron (`generate_tasks`) varken istek yolunda üretim gecikme/kilit çekişmesi yaratır.
- Kanıt: `filter_list` içinde `services.materialise_due()`; `overview_tiles` içinde aynısı.
- Öneri: Üretimi cron/arka plana al; sayfada yalnızca gerekirse (yaşlanmış `generated_until`) tetikle.

### F-336 Planlı görevlerin serisi değişince sert silinip yeniden oluşturulması: kimlik ve geri alınabilirlik kaybı

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-6`
- Dosyalar: `tasks/services.py:265-285`, `tasks/resources.py:36-38,258-260`
- Açıklama: Seride yalnızca başlık gibi bir alan değişse (veya yalnız checklist kaydedilse) tüm gelecekteki planlı görevler sert silinip yeni UUID ile tekrar yaratılır. `?task=<pk>` bağlantıları kırılır; kişi silmeleri soft-delete/restore edilebilirken bunlar geri getirilemez.
- Kanıt: `withdraw` -> `task.delete()`; `replan` her kayıtta çağrılır (`after_save`, `SeriesChecklist.save`).
- Öneri: Yerinde güncelle (diff) ya da sert yerine soft-delete uygula.

### F-337 Atanan kişiler yetkisini kaybedince yeni görevler sessizce atamasız üretilir

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-7`
- Dosyalar: `tasks/services.py:236,242`
- Açıklama: `people` yalnızca `read.readers()` ile kesişen atananlardır; hepsi pasif/yetkisiz ise görevler atamasız oluşur, uyarı/log yok. Formda en az bir atanan zorunlu olduğu halde otomatik üretilen görevlerde bu değişmez bozulur.
- Kanıt: `task.assignees.set(people)` boş listeyle çalışabilir; testi `test_people_who_can_no_longer_read_tasks_get_no_new_tasks` davranışı belgeler ama bildirim yok.
- Öneri: Atamasız kalan görevi işaretle/seri listesinde uyar.

### F-338 Onay/ay-sonu: `leave.used` her talebi YENİ talebin site'ına göre hesaplar ve N+1 sorgu üretir

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-10`
- Dosyalar: hr/leave.py:57-64
- Açıklama: `used()` eski taleplerin gün sayısını talep sahibinin o talepteki yerleşiminden değil, çağrıya verilen `site`'tan (yeni talebin ilk günündeki site) hesaplar; çalışan yıl içinde siteler arası geçtiyse tatil günleri yanlış olabilir. Her talep için ayrı Holiday sorgusu (tablo geçirilmiyor). Ayrıca günler hep tam gün (`Decimal(1)`), yarım gün desteği yok, ayarlar/tatiller sonradan değişince bakiye geçmişe dönük değişir (saklanmaz).
- Kanıt: leave.py:62-63 `charged_by_year(request.first_day, request.last_day, site)`; holidays tablosu verilmez (leave.py:35 yolu).
- Öneri: Talebin kendi sitesini kullan, holiday_table'ı bir kez oku.

### F-339 Çalışan ayrılışında onaylı gelecek izinler ve sınır aşan talepler temizlenmez

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-11`
- Dosyalar: hr/services.py:112-137, hr/checks.py:22-24
- Açıklama: `align_placements` yalnızca `first_day > left_on` olan PENDING talepleri iptal eder. Onaylı gelecek izin ile ayrılış gününü aşan talepler kalır; `away_on`/`approved_days` bunları gösterir (rapor ve pano). Sadece `check_hr` komutu bunu bildirir, otomatik uyarı yok. `leave_company` içinde `before` snapshot'ı silinen posting için hesaplanıp kullanılmaz (küçük).
- Kanıt: services.py:130-131 `status=LeaveStatus.PENDING, first_day__gt=left_on`; checks.py:22.
- Öneri: Onaylı gelecek izinleri iptal et veya uyarı rozeti göster.

### F-340 Yoklama düzeltmesi "self" kayıtlarda neden istemez, `via` değişmez

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-12`
- Dosyalar: hr/forms/attendance.py:394-397, hr/models/attendance.py:170
- Açıklama: Neden zorunluluğu yalnızca `entered` kayıtlara uygulanır; lead çalışanın kendi (`self`) punch'ının saatini nedensiz değiştirebilir ve kayıt `via='self'` kalır (artık çalışanın kendi beyanı gibi görünür). Form yardım metni "Why the time was entered or corrected" der ama düzeltme için zorunlu değildir; DB check da yalnızca `via != self` için.
- Kanıt: forms/attendance.py:394 `entered = adding or self.instance.via == ENTERED`.
- Öneri: Düzeltmede neden zorunlu kıl ve `via`/düzeltme izini kaydet.

### F-341 İzin ile giriş yapan kişi panoda "izinde" kalır; docstring çelişir

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-13`
- Dosyalar: hr/rules.py:125-139
- Açıklama: Docstring "Bir kayıt gerçektir... punch atan kişi present/late" der; ancak kodda `if on_leave: return ON_LEAVE` punch kontrolünden önce gelir. İzinli günde işe çağrılan/çalışan kişi panoda "izinde" kalır, yoklaması görünmez. Ayrıca gece vardiyası devam ederken `on_leave` yalnızca site'ın "bugün"ü için bakılır (read.py:402).
- Kanıt: rules.py:137-138; read.py:402.
- Öneri: Punch'ı olanı izin üzerinde değerlendir veya docstring'i düzelt.

### F-342 Tekrarlanan mantık ve ölü kod

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-16`
- Dosyalar: hr/leave.py:67-72, hr/services.py:142-147, hr/read.py:90-95, hr/rules.py:61, hr/models/scheduling.py:204-209,256-263
- Açıklama: `leave.balance` hiçbir yerde çağrılmaz (form kotayı kendi yeniden uygular); `services.holiday_days` yalnızca `leave.holidays_for` sarmalayıcısı; `monday` hem rules hem read'de, `MARGIN`/`WEEK_MARGIN` iki kez 15; `Shift.paid_minutes` duvar saati farkına dayanır ve `clock.net_minutes` ile (DST) farklı sonuç verebilir; `span_minutes`'ın `or 24*60` kolu DB check ile erişilemez.
- Kanıt: grep `balance(` sadece leave.py:67; services.py:144.
- Öneri: Birleştir/sil; ortak sabitler.

### F-343 Hazır olmayan (problems dolu) taslak da API-JSON/CSV olarak dışa aktarılabiliyor; dosyada uyarı yok

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-5`
- Dosyalar: reports/views.py:202-226, reports/exports.py:384-428
- Açıklama: `export`, `compute.compute(report)` içeriğinin `problems` değerine bakmaz. Eksik organisation_number/lokalitetsnummer/species code ile üretilen JSON'da bu alanlar `null` ya da `''` olarak çıkar; taslak olduğunu yalnızca dosya adı eki `-not-filed` ve sayfa gösterir. Dosyanın kendi içinde (API gövdesi) bir "hazır değil" işareti yok; `X-Content-SHA256` başlığı da taslak içeriğin hash'idir.
- Kanıt: views.py:206 `content, filed = _content(report)`; views.py:212 `shaped = exports.api_json(report, content)` (problems kontrolü yok).
- Öneri: `problems` doluyken JSON dışa aktarmayı reddet (veya açık onay iste); CSV'ye "NOT READY" satırı ekle.

### F-344 API'si olmayan türlerin CSV'sinde iletişim bilgisi iki kez yazılıyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-7`
- Dosyalar: reports/exports.py:442-450, reports/compute/__init__.py:56-62
- Açıklama: `compute.compute` içeriğe `contact` ekler; `rows()` API-dışı türlerde `{'kontaktperson': contact(report), content}` üretir. Sonuçta CSV'de hem `kontaktperson` hem `contact` bölümü bulunur (aynı ad/e-posta/telefon). Yazdırma sayfası da aynı `rows`'u kullanır.
- Kanıt: exports.py:446 `source = shaped if shaped is not None else {'kontaktperson': contact(report), content}`.
- Öneri: `content['contact']` varken `kontaktperson` ekleme (veya tersine) ve tek anahtar kullan.

### F-345 Tank durumu/tür/balık doğrulaması zayıf: day-0 kontrolü yalnız taslakta ve yalnız gün gelince

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-7`
- Dosyalar: experiments/design.py:303-331, experiments/services.py:384-421, 822-886
- Açıklama: `_wanted` yalnız silinmiş ve site kontrolü yapar; tank `status`'una (preparing/fallow vb.) bakılmaz. `check_day_zero` yalnız `status == DRAFT` ve `starts_on <= bugün` iken çalışır: day 0 gelecekteyken başlatılan deney bu kontrolü hiç görmez, sonrasında da (status != DRAFT) bir daha çalışmaz. `replace_unit` yeni tankta balık/tür/tartı olup olmadığını denetlemez (yalnız besleme çakışması).
- Kanıt: design.py:306-309; services.py:405-411; 838-871.
- Öneri: Çalışan deneyde day-0 ve yeni tank için balık/tür uyarıları `deviations`'a eklensin.

### F-346 validate_pdf `%PDF-` imzasini dosyanin ilk 1024 baytinin herhangi bir yerinde arar (`b'%PDF-' in head`);

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-6`
- Dosyalar: knowledge/models/document.py:58-72, README.md:2492-2493
- Açıklama: validate_pdf `%PDF-` imzasini dosyanin ilk 1024 baytinin herhangi bir yerinde arar (`b'%PDF-' in head`); README ve docstring "ilk baytlar %PDF-" der. Basina baska icerik eklenmis polyglot dosya kabul edilir (pypdf'in toleransi ile). Sunulurken content_type PDF zorlandigi icin risk dusuk.
- Kanıt: document.py:71.
- Öneri: `head.startswith(b'%PDF-')` kullan veya dokumani duzelt.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-347 `direct_key` asistanı desteklemiyor, docstring ile uyumsuz

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-10`
- Dosyalar: messaging/services.py:63-67; messaging/models.py:48-51
- Açıklama: Docstring "An assistant's part will read 'assistant:<id>'" der, ama kod her tarafı `user:{pk}` yazar; asistan geçirilirse yanlış anahtar (`user:<uuid>`) oluşur ve kullanıcıyla çakışma/yanlış eşleşme riski. `start_direct`/`contacts` yalnız kullanıcıyı kabul eder, yani asistanla doğrudan konuşma yolu henüz yok.
- Kanıt: `' '.join(sorted(f'user:{party.pk}' for party in parties))`.
- Öneri: Parti türüne göre önek; asistan için ayrı `start_direct` yolunu tasarlayın.

### F-348 GET ile okundu işaretleme; 50'den fazla okunmamış varsa görünmeyenler de okunmuş olur

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-7`
- Dosyalar: messaging/views.py:70-76; messaging/read.py:19-21, 98-105
- Açıklama: Konuşmayı açan GET, gösterilen son mesaja işaretçiyi ilerletir. Okunmamış sayısı PAGE=50'yi aşarsa daha eski okunmamışlar sayfada yok ama "okundu" olur; "New" çizgisi de (`first_unread` yalnızca gösterilenlerde arar) çıkmaz. Ayrıca ön-getirme/ikinci sekme GET'i de okundu yapar.
- Kanıt: `services.mark_read(participant, shown[-1].pk)` ve `shown` en fazla 50 mesaj.
- Öneri: Okunmamış sayısı PAGE'i aşarsa işaretçiyi ilk okunmamışın hemen öncesine veya gösterilen sayfanın sonuna göre ayarlayın; işaretlemeyi POST/poll'a taşıyın.

### F-349 Başlık: Site.Type / System.Type / Tank.Kind / WaterType arasında tutarlılık kuralı yok

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-10`
- Dosyalar: farm/models/site.py:25-27, 45-51, farm/models/system.py:22-29, farm/models/tank.py:19-22, 98-105
- Açıklama: sea_cage sitesinde pond kind birim, land_based sitede cage, saltwater tank + tatlı su sitesi, RAS sistemine cage vb. engellenmiyor. Site.type değişimi (sea_cage <-> başka) mevcut stoktaki karışım kuralını (mixed(), sea_units) ve rapor yükümlülüklerini sessizce değiştirir; clean() bunu denetlemez.
- Kanıt: Tank.clean ve System.clean'de type/kind karşılaştırması yok; stock/read.py:75 site.type'a bağlı kural.
- Öneri: İzin matrisi (site tipi -> birim kind) veya en azından uyarı ve "stoklu sitede type değişmez" kuralı.

### F-350 Başlık: System/Equipment/ProductionDepartment/Site durumlarının hiçbir davranışı yok; yalnız Tank'ın durum makinesi var

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-11`
- Dosyalar: farm/models/system.py:101-110, farm/models/tank.py:536-552
- Açıklama: System.Status (maintenance/offline/construction), Equipment.Status (decommissioned vb.), ProductionDepartment.Status ve Site.Status serbest alan; çevrimdışı sistemdeki birime stoklama, hizmet dışı ekipmanın yemleyici seçilmesi veya inactive departmana birim eklenmesi engellenmiyor (yalnız hr/units.py:57 departman statüsünü picker'da okuyor, config/views.py:46 sistem sayımı).
- Kanıt: grep `System.Status|Equipment.Status|ProductionDepartment.Status` model dışı: yalnız filtre/sayım.
- Öneri: Durumların iş anlamını tanımlayın (örn. decommissioned ekipman yeni silo/su noktasına bağlanamaz).

### F-351 Başlık: Site'ta formdan hiç yazılamayan ölü kolonlar

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-6`
- Dosyalar: farm/models/site.py:92-95, 101-107, 113; farm/forms/site.py:13-24
- Açıklama: water_capacity_m3, max_biomass_kg, established_date, facilities, settings, notes, metadata ve is_active forma konmamış; kodda başka yerde okunmuyor (grep). docs SITE-05 "kolon ya düşürülsün ya forma eklensin" der. Özellikle Site.max_biomass_kg (izin verilen azami biyokütle, MTB) düzenlenemez ve hiçbir kontrolde kullanılmaz.
- Kanıt: SITE_FORM_TABS alan listesi; `grep facilities|metadata|site.settings` sonuç yok.
- Öneri: Kolonları kaldırın ya da forma ekleyin; MTB için biyokütle toplamı doğrulaması düşünün.

### F-352 Başlık: Elle girilen kapasite alanları gerçek birimlerle ilişkisiz ve uygulanmıyor

Önem: **Düşük** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-7`
- Dosyalar: farm/models/system.py:62-69, farm/models/production_department.py:54-56, farm/models/site.py:90-91
- Açıklama: System.total_volume_m3/max_biomass_kg yalnızca sistem listesinde gösteriliyor; sistemdeki Tank'ların toplam hacmi/biyokütlesiyle karşılaştırılmıyor ve stok kontrolünde kullanılmıyor (services.py:350 yalnızca birim bazlı). ProductionDepartment.capacity'nin birimi tanımsız. Zamanla gerçek birimlerden sapar (bkz. docs "hand-typed tank count would drift" mantığı).
- Kanıt: grep max_biomass/total_volume_m3: yalnız şablon ve form; tank.py üretilmiş kolonları ayrı.
- Öneri: Türetilmiş toplam gösterin ya da elle girilen değeri toplamla doğrulayın; capacity için birim ekleyin.

### F-353 reports -> farm bağımlılığı çok geniş (50 import, iç modüllere)

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-12`
- Dosyalar: reports/ (compute/, health.py, forms.py)
- Açıklama: reports farm'ın modellerine, fold/read/handling.fasting/forms.water gibi iç modüllerine doğrudan uzanıyor; farm'ın iç yeniden düzenlemesi reports'u kırar. Docstring "farm raporları okur, farm okumaz" söylüyor ve bu doğrulandı (farm -> reports importu yok), ama genel API yok.
- Kanıt: reports/apps.py:8-9 (docstring); import sayımı reports->farm 50; reports farm.stock.fold, farm.handling.fasting, farm.forms.water:8 kullanımı.
- Öneri: farm için dışa açık `farm.api`/read sözleşmesi tanımla.

### F-354 Model katmanı üst katmana (read) lazy import ile bağımlı

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-2`
- Dosyalar: farm/models/harvest.py
- Açıklama: `clean()` içinde fonksiyon-içi import, model -> stock.read bağımlılığını ve döngüyü gizliyor.
- Kanıt: farm/models/harvest.py:339-340 (`from farm.stock.dates import earliest`, `from farm.stock.read import fish_of_batch`).
- Öneri: İş kuralını services katmanına taşı ya da saf yardımcıyı models'ın altına çıkar.

### F-355 Servis katmanı sunum katmanına (templatetags) bağımlı

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-3`
- Dosyalar: farm/stock/services.py, inventory/services.py, inventory/templatetags/inventory.py
- Açıklama: Biçimleme fonksiyonları (`number`, `amount`) templatetags içinde durduğu için servis ve başka app'ler onları import ediyor.
- Kanıt: farm/stock/services.py:74 (`from farm.templatetags.stock import number`); inventory/services.py:34, inventory/views.py:34, inventory/forms.py:20 (`farm.templatetags.feeding import amount`).
- Öneri: Biçimleme yardımcılarını `core` altında nötr bir modüle taşı.

### F-356 Dashboard (config/views.py) birçok app'in views modülüne doğrudan bağlı

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-7`
- Dosyalar: config/views.py
- Açıklama: Genel bakış, farm/reports/tasks'ın view fonksiyonlarını elle import ediyor; yeni app eklemek config'i değiştirmeyi gerektiriyor (kayıt/registry yok).
- Kanıt: config/views.py:5-10 (`farm.feeding.views overview_tiles`, `farm.stock.views`, `reports.views overview_upcoming`, `farm.water.views`, `tasks.views overview_tiles`).
- Öneri: placements/notices'taki kayıt desenini overview için de kullan.

### F-357 core testleri farm'a bağımlı (alt katman test olarak üst katmanı biliyor)

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-9`
- Dosyalar: core/tests.py, core/tests_crud_mount.py, core/tests_scope.py, core/tests_workspaces.py, core/test_languages.py, core/test_database.py, core/test_codes.py, core/tests_schema.py
- Açıklama: `core` üretim kodunda farm importu yok (iyi), ama testleri farm modellerini ve `farm.tests.helpers`'ı import ediyor; core bağımsız test edilemiyor ve dağılım/ayırma zorlaşıyor. `core` içinde test dosyaları üretim modülleriyle aynı dizinde.
- Kanıt: core/tests.py:19-20; core/tests_crud_mount.py:13-16; core/tests_scope.py:11-13; core/test_database.py:14; core/test_languages.py:16-19.
- Öneri: Entegrasyon testlerini üst düzey bir `tests/` altına ya da config'e taşı; core için bağımsız fixture modelleri kullan.

### F-358 Mutable/çağrı içeren varsayılan argümanlar (B008) ve `zip` strict eksik

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-11`
- Dosyalar: farm/water/calculation.py, farm/water/deffeyes.py
- Açıklama: `judge_step(..., ph_bounds=PhBounds())` ve `Limits()` import zamanında bir kez oluşturuluyor; nesneler değişmez (dataclass/namedtuple) ise sorun yok ama doğrulanmadı. Ayrıca 37 `zip()` çağrısı `strict=` belirtmeden kullanılıyor (B905); uzunluk uyuşmazlığı sessizce kırpılır.
- Kanıt: farm/water/calculation.py:75,159; farm/water/deffeyes.py:177; B905: 37 adet (ruff).
- Öneri: değişmezliği doğrula; `strict=True` ekle.

### F-359 `raise ... from` eksik (B904) ve `except Exception` kalıpları

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-12`
- Dosyalar: experiments/services.py, farm/models/equipment.py, monitoring/read.py, farm/placements.py, knowledge/extraction.py
- Açıklama: Dört `except` içinde `raise` yeni istisna `from` olmadan atılıyor (zincir kaybı). Geniş `except Exception` "fail open" olarak bilinçli, yorumlu ve loglanıyor (monitoring/read.py:272, placements.py:49, extraction.py:69,84), ancak aynı niyet için üç farklı yorum ifadesi ve üç farklı log stratejisi (rate-limit/`logger.exception`/belge kaydı) var: tutarsız.
- Kanıt: experiments/services.py:452,667,884; farm/models/equipment.py:77; monitoring/read.py:272; farm/placements.py:49-51; knowledge/extraction.py:69,84.
- Öneri: `from error`; ortak bir "fail-open" yardımcısı düşün.

### F-360 `_is_uuid` 3 kez kopya, `_back`/`_refused` aileleri benzer kopyalar

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-2`
- Dosyalar: knowledge/resources/entry.py, reports/resources.py, farm/stock/views.py, hr/views.py, inventory/views.py, farm/stock/views.py, farm/feeding/views.py, tasks/views.py, messaging/views.py, farm/water/views.py
- Açıklama: `_is_uuid` üç dosyada aynı (biri `str()` sarmalayıp biri sarmalamıyor). `_back` en az 4 app'te "next parametresini `url_has_allowed_host_and_scheme` ile doğrula, yoksa varsayılan" mantığını tekrarlıyor; `farm/feeding/views.py` bunu `stock_views._back`'e devrederek doğru yapmış, inventory ve stock ise kendi kopyasını tutuyor. `_refused` 5 modülde farklı imzalarla (request,template,context / error / *messages) tanımlı.
- Kanıt: knowledge/resources/entry.py:94-99, reports/resources.py:278-283, farm/stock/views.py:308-313; farm/stock/views.py:257-265 ile inventory/views.py:57-62 aynı `next` doğrulaması; farm/feeding/views.py:60-64 delegasyon; `_refused`: tasks/views.py:37, messaging/views.py:42, farm/water/views.py:123, farm/stock/views.py:267, experiments/services.py:76.
- Öneri: `core`'da `safe_next(request, default)` ve `is_uuid` yardımcısı; `_refused` isimleri anlamlı ayrışsın (`render_refused` vs `refusal_error`).

### F-361 `_number` aynı adla 3 farklı anlam

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-3`
- Dosyalar: reports/exports.py, farm/equipment_types.py, farm/feeding/protocols.py
- Açıklama: Üç modülde `_number` birbiriyle ilgisiz işler yapıyor: JSON sayıya çevirme, alan tanımı üretme (`_number(name,label,unit)`), Decimal'i metne normalize etme. İsimlendirme belirsiz ve arama/yeniden düzenlemeyi zorlaştırıyor.
- Kanıt: reports/exports.py:31-36, farm/equipment_types.py:21, farm/feeding/protocols.py:21-22.
- Öneri: ad ver: `json_number`, `number_field`, `decimal_text`.

### F-362 `reports/integrity.py` döngü içinde sorgu (N+1)

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-6`
- Dosyalar: reports/integrity.py
- Açıklama: Her rapor için döngüde `EscapeRecord.all_objects.get(...)` ve ilişkili `movements` sorgusu yapılıyor; ayrıca `report.corrects`/`health_event` select_related ile iyi ama escape için değil.
- Kanıt: reports/integrity.py:41-46.
- Öneri: kaçış kayıtlarını önceden `in_bulk` ile al.

### F-363 Kullanılmayan importlar (üretim kodunda 12, toplam 60)

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-7`
- Dosyalar: farm/feeding/temperature.py, farm/health/views.py, farm/water/points.py, hr/management/commands/seed_hr_demo.py, hr/resources/employee.py, hr/services.py, monitoring/cards/validate.py, monitoring/read.py
- Açıklama: ruff F401, test ve `__init__` dışında 12 kullanılmayan import: `farm.water.read.SYSTEM`/`UNIT`, `timedelta` (iki yerde), `AuditLog`, `scope.covering`, `read`, `Q`, `Holiday`, `farm.water.parameters`. Hiçbiri otomatik lint ile yakalanmıyor (repo'da ruff yapılandırması bulunmadı).
- Kanıt: farm/feeding/temperature.py:23; farm/health/views.py:10; farm/water/points.py:16; hr/services.py:8,18; hr/resources/employee.py:9; monitoring/cards/validate.py:23; monitoring/read.py:38; hr/management/commands/seed_hr_demo.py:14.
- Öneri: `ruff --fix` ve CI'da F401/F841 zorunluluğu. (Bazıları yan etki/yeniden dışa aktarma amaçlı olabilir; silmeden önce kontrol et.)

### F-364 Kimya sabitleri satır içi ve tekrar ediyor

Önem: **Düşük** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-9`
- Dosyalar: farm/water/chemistry.py, farm/water/deffeyes.py, farm/water/dosing.py
- Açıklama: Klorinite çevirimi `1.80655` 3 kez ve `0.001005` (yoğunluk) 3 kez ham sayı olarak geçiyor; ayrıca `0.1400/96.062`, `0.000067/18.998`, `0.000232/10.811` gibi kaynak sabitleri adlandırılmamış. Yorumlar kaynağı açıklıyor ama sabit adı yok; yanlış yerde değişiklik riski. `deffeyes.py` içinde `* 1000`, çizim sabitleri `arm = 7`.
- Kanıt: farm/water/chemistry.py:69,73,78 (1.80655); :94,101,130 (0.001005); farm/water/deffeyes.py:474,667.
- Öneri: `CHLORINITY_PER_SALINITY = 1.80655`, `SEAWATER_DENSITY_SLOPE = 0.001005` gibi modül sabitleri.

### F-365 poll.ts form 'live' yenilemesi: sunucu hatası ve ağ hatası tamamen sessiz

Önem: **Düşük** | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-10`
- Dosyalar: frontend/poll.ts
- Açıklama: live() içinde '!response.ok' ise 'return' (frontend/poll.ts:~311-316 'a passing server error: the next change asks again') ve catch bloğu boş (satır ~324-326); yalnızca aria-busy kaldırılıyor. Kullanıcı filtre/arama sonucunun yenilenmediğini fark edemez ve ekran okuyucuya da bildirim yok. poll() tarafında ise 'stale' durumu var; iki mekanizma arasında tutarsızlık.
- Kanıt: frontend/poll.ts:~311-330 (live), kıyas ~193-210 (failed()/state('stale')).
- Öneri: Hata durumunda forma 'sonuçlar güncel olmayabilir' uyarısı (aria-live) ekleyin; ya da sayfayı ?query ile yeniden yükleyin.

### F-366 Monitor sayfası 503 durumunda düz metin dönüyor (HTML sayfa değil)

Önem: **Düşük** | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-5`
- Dosyalar: monitoring/views.py
- Açıklama: _unavailable() hem poll parçası hem tam sayfa (monitor, satır 108-111) için content_type='text/plain' cevap veriyor. Poll için uygun ama tam sayfa isteğinde kullanıcı menüsüz, stilsiz, çevrilmiş tek satır metin görür ve yeniden denemek için sayfa yenilemesi gerekir. Docstring 'a page says so' diyor; gerçekte sayfa şablonu kullanılmıyor.
- Kanıt: monitoring/views.py:66-71 ve :108-111.
- Öneri: Tam sayfa isteğinde render_page ile 503 durumlu bir hata şablonu (yenile bağlantısı ile) döndürün; poll yolunda düz metin kalabilir.

### F-367 Izleme sayfasi: tum Tank'lar Python'da filtreleniyor, her tam sayfada ve poll'de ekstra COUNT/listeler

Önem: **Düşük** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-16`
- Dosyalar: monitoring/read.py:170-196, monitoring/views.py:74-92, monitoring/views.py:113-125
- Açıklama: `units_for` metin aramasini (`q`) veritabaninda degil Python'da (`params.q.lower() in word.lower()`) tum filtrelenmis Tank'lar uzerinde yapiyor, `select_related` ile tum birimleri yukledikten sonra siralama da Python'da. `_grid` her poll yanitinda `Tank.objects.count()` calistiriyor; tam sayfada ayrica `all_units=Tank.objects.order_by('code')` (secici icin tum birimler), `sites`, `departments`, `systems` tam listeleri cekiliyor. Kart sayisi icin sayfalama yok (duvar tum birimleri cizer).
- Kanıt: `units = [unit for unit in found if not params.q or any(params.q.lower() in word.lower() ...)]` (read.py:188-189); `farm = Tank.objects.count()` (views.py:79).
- Öneri: Metin aramasini `Q(code__icontains)|Q(name__icontains)` ile sorguya tasi; sayiyi `len` veya onbellek ile ver.

### F-368 Bazi listeler butun gecmisi hesaplayip kesiyor (lice_weeks, records_of_batch)

Önem: **Düşük** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-19`
- Dosyalar: farm/health/read.py:121-138, farm/health/views.py:283-286, farm/feeding/read.py:192-199, farm/feeding/views.py:105-117, farm/health/views.py:146-155
- Açıklama: `lice_weeks(counts)` filtreye uyan TUM bit sayimlarini `select_related` ile cekip Python'da haftalara grupluyor, ardindan `[:LICE_WEEKS]` ile kesiyor. Yemleme kayitlarinda batch filtresi `records_of_batch` ile adaylarin hepsini (`list(records.filter(...))`) cekip `split_of` ile defteri katliyor, yalnizca sonra sayfaliyor. Saglik tedavilerinde `UNDER_WITHDRAWAL` veya batch filtresi tum aday tedavileri `treated_batches` ile degerlendiriyor.
- Kanıt: `weeks = read.lice_weeks(counts)[:LICE_WEEKS]` (health/views.py:283); `candidates = list(records.filter(unit_id__in=unit_ids, date__gte=batch.input_date))` (feeding/read.py:197).
- Öneri: Haftalik gruplamayi SQL'de (`TruncWeek`/`DISTINCT ON`) yap, tarih alt sinirini sorguya koy; batch filtresini sayfa sonrasi uygula veya sonucu sinirla.

### F-369 Frontend modullerinin cogunun birim testi yok

Önem: **Düşük** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-14`
- Dosyalar: frontend/auth.ts, components.ts, dom.ts, nav-boot.ts, poll.ts, roster.ts, shell.ts, windows.ts, designer.ts
- Açıklama: ~3150 satir TS'in yalniz announce.ts ve grid/{history,keyboard,layout}.ts icin birim testi var; designer yalniz (skip olabilen) tarayici testinde. `poll.ts` (veri guncelleme/birlestirme) ve `windows.ts` (dialog) gibi durumlu modullerin birim testi yok. Python tarafi `test_frontend_contract.py` yalniz sozlesme/nitelik varligini dogruluyor.
- Öneri: poll/windows/roster icin node:test birim testleri.

### F-370 Yuk/performans testi varsayilan olarak kapali ve sure-bazli

Önem: **Düşük** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-3`
- Dosyalar: monitoring/tests/test_load.py:39, :43-45
- Açıklama: `MONITOR_LOAD=1` olmadan calismaz, dolayisiyla 200 kartlik duvar icin sorgu/sure regresyonu rutin kosuda yakalanmaz. Calistiginda `time.perf_counter` ile mutlak sure esigi kullaniyor, yavas makinede flaky olabilir.
- Kanıt: `@skipUnless(os.environ.get('MONITOR_LOAD') == '1', ...)`
- Öneri: sorgu sayisi esigini (deterministik) her kosuda, sure esigini ayri etiketli kosuda tut.

### F-371 N+1 / sorgu sayisi korumasi cok az

Önem: **Düşük** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-4`
- Dosyalar: monitoring/tests/test_render.py:90, test_read.py:168, test_resolve.py:115, core/tests.py:214
- Açıklama: ~2500 testte `assertNumQueries` yalniz 4 yerde; liste/sayfa goruntuleri (farm, hr, reports) icin sorgu sabitligi testi yok. Veri buyudukce sessiz N+1 regresyonu olabilir.
- Kanıt: grep `assertNumQueries` toplam 4 sonuc.
- Öneri: ana liste ve izgara gorunumlerine sorgu butcesi testi ekle.

### F-372 Rastgele (fuzz) stok testinde tum ValidationError'lar yutuluyor

Önem: **Düşük** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-9`
- Dosyalar: farm/tests/test_stock.py:451-478
- Açıklama: Tohumlu RNG (20261102) iyi, tekrarlanabilir; ancak `except ValidationError: pass` her reddi sessizce gecer. Hizmetin cok sayida islemi yanlis nedenle reddetmesi (ornegin tarih penceresi) testi anlamsizlastirir, kac islemin kabul edildigi sayilmiyor/dogrulanmiyor.
- Kanıt: satir 474 `pass`; son assert yalniz "stok >= 0" ve toplam esitligi.
- Öneri: kabul edilen islem sayisi icin alt sinir assert'i ekle.

### F-373 Kod kalitesi/stil araçları yapılandırılmamış (ruff cache var, config yok)

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-15`
- Dosyalar: .ruff_cache/ (git dışı), (pyproject.toml / ruff.toml yok)
- Açıklama: Çalışma dizininde `.ruff_cache` var, yani ruff yerelde çalıştırılmış, fakat ruff/flake8/mypy yapılandırması, pre-commit, .editorconfig yok; kurallar repoda tanımlı değil, CI'da uygulanamaz. `.ruff_cache` .gitignore'da listelenmiyor (yalnızca .gitignore sözlüğünde yok; `git status`/izlenme durumu doğrulanmadı).
- Kanıt: `ls -a` -> .ruff_cache; `git ls-files | grep -i "ruff\|pyproject\|pre-commit\|editorconfig"` boş; .gitignore:1-19 .ruff_cache içermez.
- Öneri: pyproject.toml ile lint yapılandırması, .ruff_cache'i .gitignore'a ekleyin.

### F-374 Çakışan `next` doğrulama kodu 6+ yerde kopyalanmış, davranışları farklı

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-1`
- Dosyalar: farm/stock/views.py:257, farm/health/views.py:49, farm/water/views.py:114, inventory/views.py:57, hr/views.py:34, tasks/views.py:30
- Açıklama: satırlar; hr/views.py `_return` `require_https` içerir, diğerleri içermez. "geri dönülecek adres" kuralı her modülde ayrı yazılmış. farm/health/inventory/water yalnızca `GET['next']` okur ve `require_https` vermez; hr yalnızca `POST['next']` okur ve `require_https=request.is_secure()` kullanır; tasks hem POST hem GET okur ama kendi `startswith('/operations/tasks/')` kuralını kullanır.
- Kanıt: bkz.
- Öneri: tek bir `core.crud.safe_next(request, default)` yardımcısı; https zorunluluğu tek yerde.

### F-375 `components.ts` modal `load()` ağ/sunucu hatalarında sessiz bozuk davranış

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-11`
- Dosyalar: frontend/components.ts:333-362
- Açıklama: `fetch` try/catch dışında (ağ hatasında yakalanmamış promise rejection, diyalog açılmaz); yalnızca 403 özel işlenir; 404/405/500 yanıtlarının gövdesi (boş veya hata sayfası HTML'i) doğrudan `innerHTML` ile diyaloğa basılır. Ayrıca 403 mesajı CSRF hatalarında da "yetkiniz yok" anlamına gelir.
- Kanıt: `this.content.innerHTML = await response.text();`
- Öneri: `!response.ok` (422 hariç) için genel hata görünümü ve try/catch.

### F-376 Tasarımcı önizlemesi (`cardtemplate_preview`) hataları istemcide yutulur; hata yanıt biçimi tutarsız

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-12`
- Dosyalar: frontend/designer.ts:467-474, monitoring/views.py:186-194, monitoring/views.py:66-72
- Açıklama: Sunucu 413/400 için `{"error": ...}` JSON, 503 için `text/plain` döner; istemci `!response.ok` ise sessizce `return` eder (kullanıcıya hiçbir ileti yok, `error` alanı hiç okunmuyor). Başarılı/başarısız yanıt zarfı: 200 + `{html, problems}`, hatalarda farklı. Tek JSON ucu için sözleşme yazılı bir şemaya bağlı değil.
- Kanıt: `if (!response.ok) { return; }`
- Öneri: tek hata zarfı (`{error, code}`), istemcide durum bildirimi (`status` alanı zaten var).

### F-377 URL adlandırma kuralları tutarsız (fiil yeri, kök yolları, tekil/çoğul)

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-14`
- Dosyalar: farm/urls.py:25-47, reports/urls.py:12-20, messaging/urls.py:13, hr/urls.py, core/urls.py, çeşitli resources `url_prefix`
- Açıklama: "void" eylemi bir yerde `.../void/<pk>/` (units, feeding, water, storage) başka yerde `.../<pk>/void/` (treatments, lice, events). Rapor: `reports/close/` (sorgu dizgesiyle kimlik) ve `reports/closed/<pk>/reopen/`. Mesajlaşma: yeni mesajları poll eden uç `<pk>/new/` (`new/` ise yeni konuşma). Referans veri uçları kökte (`sites`, `tanks`, `roles`, `users`) ama işlemler `operations/...`, İK `hr/...`, deneyler `research/experiments`. `hr/` ve `production/team/` aynı sayfaları iki adreste sunar.
- Kanıt: urlpatterns listeleri.
- Öneri: tek kural (`<kaynak>/<pk>/<fiil>/`), poll için `.../poll/`.

### F-378 `close` ve `duty_done` diyaloglarının kimliği sorgu dizgesinde taşınıyor, POST'ta da

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-15`
- Dosyalar: reports/views.py:93-101, reports/views.py:146-155, templates/reports/duty_done.html:12
- Açıklama: Kaynağın kimliği path yerine `?kind=&site=&period=` ve form `action=request.get_full_path`; URL yolu bir kaynağı tanımlamıyor, böylece kaynak-tabanlı yetkilendirme/log/önbellek için anlamlı bir path yok, ayrıca eksik/hatalı parametreler 404 olur. Kayıt oluşturan POST'lar için `entry_key` yok (close/duty_done), çift gönderim 38-8 yolunu izler.
- Kanıt: `_due_row(request)` `request.GET`'ten okur.
- Öneri: `reports/due/<kind>/<site>/<period>/close/` gibi path parametreleri.

### F-379 Görev notu ekleme (`task_note`) idempotent değil

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-3`
- Dosyalar: tasks/views.py:79, tasks/services.py:190, templates/tasks/_task_drawer.html:71
- Açıklama: Notlar "kalıcı, düzenlenmez, silinmez" olduğundan çift gönderim kalıcı yinelenen not üretir. `tick` ise mutlak küme (idempotent) olarak tasarlanmış; `add_note` ile tutarsız.
- Kanıt: `add_note` view -> `services.add_note`, anahtar yok.
- Öneri: `entry_key` benzeri istemci anahtarı.

### F-380 CRUD view'ları HEAD isteğine 405 döner; `Allow` başlığı yok

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-5`
- Dosyalar: core/crud.py:559-561
- Açıklama: `ResourceView.as_view` `getattr(self, request.method.lower())` ile gönderir; `head` tanımlı olmadığından tüm CRUD liste/form/detay sayfalarında HEAD 405 döner, oysa düz fonksiyon view'ları (monitor, storage vb.) HEAD'i kabul eder. 405 yanıtında `Allow` başlığı da yok (RFC 9110 zorunlu kılar). Ayrıca keyfi metod adı (`CONTEXT`, `URL`, `PAGE`) sınıfın kendi metodlarına eşleşir ve `TypeError` -> 500 verir (`handler(request, *args)`).
- Kanıt: `handler = getattr(self, request.method.lower(), None)`.
- Öneri: izinli metod beyaz listesi (`get/post`, `head=get`), 405'te `Allow` başlığı; Django `View.http_method_names` kullanın.

### F-381 Doğrulama hatası durum kodları tutarsız (200 vs 422)

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-6`
- Dosyalar: core/crud.py:648-662, farm/stock/views.py:267-271, messaging/views.py:44, reports/views.py:118,172, inventory/views.py
- Açıklama: Özel diyaloglar (stok, envanter, mesajlaşma, raporlar) geçersiz formda 422 döner (`_refused`), Resource tabanlı CRUD formları (CreateView/UpdateView `self.page(form)`) ise 200 döner. tasks `_action` ve messaging `start` da farklı davranır. İstemci (components.ts `load`) durum koduna bakmadığı için çalışıyor ama sözleşme belirsiz; proxy/izleme/test araçları hata oranını yanlış ölçer.
- Kanıt: `return self.page(form)` (200) vs `response.status_code = 422`.
- Öneri: `render_page` sonrası geçersiz form için tek yerde 422.

### F-382 Local setup yalnizca Windows yollarini (`C:\Python312\python.exe`, `.venv\Scripts\...`) verir;

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-12`
- Dosyalar: README.md:2977-2988
- Açıklama: Local setup yalnizca Windows yollarini (`C:\Python312\python.exe`, `.venv\Scripts\...`) verir; Linux/macOS karsiligi yok. Ayrica README "Tests" bolumu ayni sekilde `.venv\Scripts\python.exe`.
- Kanıt: README.md:2983-2988, 3399.
- Öneri: POSIX komutlari da eklensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-383 Layout tablosu `manage.py check_stock`, `check_inventory`, `check_experiments`, `generate_tasks`, `data_map`'i listeler

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-14`
- Dosyalar: README.md:3347-3394, farm/management/commands/check_withdrawal.py, reports/management/commands/check_reports.py
- Açıklama: Layout tablosu `manage.py check_stock`, `check_inventory`, `check_experiments`, `generate_tasks`, `data_map`'i listeler ama `check_withdrawal`, `check_reports`, `check_hr`, `hr_roles`, `seed_hr_demo` yok; bunlar yalniz ilgili bolumlerde gecer. Hicbir yerde tum yonetim komutlarinin ozeti yok.
- Kanıt: komut dosyalari mevcut; README:1844, 2306, 2814-2827 ilgili bolumlerde.
- Öneri: Komut ozet tablosu eklensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-384 Belge README'ye satir/yer atfi yapar:

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-6`
- Dosyalar: docs/regulatory-reports.md:366, 697, 722, 725-727
- Açıklama: Belge README'ye satir/yer atfi yapar: `README.md:43-44, :1722-1723` ve "README already says the cleaner-fish track comes 'later, as batches of a cleaner-fish species' (Operations > Production units, 'Not ported')". README:43-44 su an "Ported farm tabs" giris metni; alinti ifade README'de bulunamadi.
- Kanıt: `grep "later, as batches" README.md` bos; README.md:41-45 baska icerik.
- Öneri: Satir numarasi yerine bolum adi kullanilsin; alinti guncellensin/silinsin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-385 Kod satir atiflari kaymis.

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-7`
- Dosyalar: docs/regulatory-reports.md (farm/feeding/fold.py:184-191, farm/models/health.py:367-371, farm/forms/site.py:42-43, farm/handling/check.py:166 ...), docs/regulatory-reports.md:727-883
- Açıklama: Kod satir atiflari kaymis. `farm/models/health.py:367-371` EventKind diye gosterilir ama EventKind health.py:434'te, 367-371 Treatment Meta'sidir; `farm/models/harvest.py:148-149` dogru gorunse de fold.py/site.py/check.py atiflari ilgisiz satirlari gosterir.
- Kanıt: health.py:365-372 `class Meta: db_table = 'treatments'`; health.py:434 `class EventKind`; fold.py:184-186 while dongusu, belgedeki aciklamayla uyusmaz.
- Öneri: Sembol adi ile at (dosya::fonksiyon) veya belge "satirlar commit X'e gore" diye isaretlensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-386 Repoda bulunmayan dosyalara atif:

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-8`
- Dosyalar: docs/regulatory-reports.md:727, 883, docs/experiments.md:131
- Açıklama: Repoda bulunmayan dosyalara atif: `coverage/COVERAGE.md` ("planning material ile saklanir"), `plan/area1/PLAN.md`, `utils/thresholds.ts` (dis kaynak). Okuyucu bunlari bulamaz; experiments.md "plan ile kod ayrilirsa kod kazanir" der ama plan repoda yok.
- Kanıt: `find` ile COVERAGE.md ve PLAN.md yok.
- Öneri: Dis/depo-disi oldugu acikca yazilsin veya ozet repoya alinsin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-387 README.md tek dosyada 316 KB; her özellik commit'i onu değiştiriyor

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-11`
- Dosyalar: README.md
- Açıklama: Commit mesajları sürekli "README says ..." diyor; README dev bir spesifikasyon/karar günlüğüne dönüşmüş, merge çakışmalarının ana kaynağı (merge mesajlarında "both sides kept in the README"). Git diff/blame için verimsiz.
- Kanıt: `ls -la` -> README.md 320208 bayt; 502075a "both sides kept in the menu, the access areas, the menu tests and the README".
- Öneri: README'yi docs/ altına bölümlere ayır.

### F-388 Üretilen dosyalar takipte (data-map, .po) ve her merge'de yeniden üretiliyor

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-12`
- Dosyalar: docs/data-map.json, docs/data-map.md, locale/*/LC_MESSAGES/django.po
- Açıklama: data-map.json (852 KB) ve data-map.md koddan üretiliyor ("the data map regenerated" en az onlarca commit); .po dosyaları da "rebuilt from the merged code". Bunlar merge çakışması ve büyük diff üretir. core/test_datamap.py'nin bunu zorladığı commit 9ad5c26'da belirtiliyor, yani tutarlılık testle korunuyor; ama tek kaynak ve yeniden üretim komutu merge sürecinde elle uygulanıyor.
- Kanıt: 502075a, a4d5729, 6980141 mesajları; 9ad5c26 "Data map enforced: core/test_datamap.py fails for a t...".
- Öneri: Yeniden üretim komutunu Makefile/pre-commit adımı yap.

### F-389 "main'i wip dalına merge et" deseni: main'e ters yönde merge'ler ve tekrarlı merge gürültüsü

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-2`
- Dosyalar: .git
- Açıklama: 53 merge commit'in büyük kısmı `Merge main (...) into wip/X` biçiminde; yani main sürekli dallara çekilmiş, sonra dal main'e fast-forward olmuş (first-parent geçmişi 107 commit, toplam 299). Merge conflict çözümleri (katalog .po yeniden üretimi, data map yeniden üretimi) tekrar tekrar elle yapılmış.
- Kanıt: 0f5bc72'nin ebeveyni fd49eed `Merge branch 'main' into wip/prodteam`; 502075a, a4d5729, 6980141, afca8e6, 42e894f, 5508e92 aynı desen. `git log --first-parent --oneline | wc -l` = 107.
- Öneri: Üretilen dosyalar (data-map, .po) için merge driver veya "regenerate" adımı belgelenmeli; mümkünse rebase/squash ile geçmişi sadeleştir.

### F-390 Konu satırına gömülü elle yazılmış zaman damgası, tutarsız ve author date ile uyuşmuyor

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-4`
- Dosyalar: .git
- Açıklama: 252 commit konusu `[2026-11-05 16:00 +0100]` önekiyle başlıyor, diğerleri başlamıyor (örn. 0f5bc72, 156cfd9, 0fd548f yok). "Test:" commit'lerinde önek `Test: [ts]` sırasıyla, diğerlerinde `[ts] ...` biçiminde. Gömülü zaman ile git author date 1-2 dakika farklı: bd1e53b (00:59 vs 01:00), 000321d (21:43 vs 21:45), 563ebb7 (14:25 vs 14:24). Ayrıca öneksiz son commit'ler (11-05 18:27 sonrası) biçim değiştiğini gösteriyor. Git zaten tarih tutuyor; önek mesajı uzatıyor ve güvenilir değil.
- Kanıt: awk karşılaştırması: `bd1e53b 2026-11-04 00:59 2026-11-04 01:00`, `000321d ... 21:43 21:45`.
- Öneri: Öneki kaldır; zaman gerekiyorsa git'in kendi tarihine güven.

### F-391 .gitignore kapsamı dar

Önem: **Düşük** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-8`
- Dosyalar: .gitignore
- Açıklama: Yalnızca .venv/, __pycache__/, *.pyc, db.sqlite3, .env, staticfiles/, static/js/, node_modules/, *.mo, /media/, .build/ var. Eksik: `.env.*`, `.idea/`, `.vscode/`, `*.log`, `.pytest_cache/`, `.coverage`, `htmlcov/`, `.mypy_cache/`, `*.sqlite3`, `*.dump`/`*.sql`, `.DS_Store`, `*.swp`. `.ruff_cache` ruff'ın kendi içindeki .gitignore ile korunuyor, repo kuralı değil. `.env` ignore'u var ama `.env.local` vb. değil.
- Kanıt: .gitignore tam içeriği (satır 1-17); `git status` .ruff_cache göstermiyor ama `git check-ignore -v .ruff_cache` çıktısız.
- Öneri: Standart Python/Node/editör kalıplarını ekle, `.env.*` ve `!.env.example`.

### F-392 `init()` zincirinde tek `required` hatası kalan tüm başlatmaları durduruyor

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-12`
- Dosyalar: `frontend/components.ts:125-131`, `:283-294`, `:361`
- Açıklama: `initRequires` `required(...)` ile eksik hedefte `throw` eder. `init()` tüm alt başlatıcıları sırayla çağırdığı için sonraki `initAutosubmit`, `initDependents`, `initRefresh`, `initLinkLists`, `initOmitEmpty`, `initPrint` çalışmaz. Modal içinde `init(this.content)` istisna fırlatırsa `showModal()` hiç çağrılmaz (satır 361-362) ve kullanıcı sessizce takılır. "Eksik öğe şablon hatasıdır, yüksek sesle başarısız ol" kararı bilinçli ama etkisi tüm sayfa davranışına yayılıyor.
- Öneri: her başlatıcıyı try/catch ile yalıtıp `console.error` yap; modal için `showModal` önce çağrılsın.

### F-393 `data-autosubmit` iki dosyada farklı yorumlanıyor

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-16`
- Dosyalar: `frontend/poll.ts:345`, `frontend/components.ts:135-137`
- Açıklama: `poll.ts` `live` formunda `[data-autosubmit]` taşıyan HER öğeyi "formu kendisi gönderir" diye atlar; `components.ts` yalnızca `select[data-autosubmit]` ile bunu gerçekleştirir. Bir onay kutusu/metin alanında `data-autosubmit` kullanılırsa ne canlı yenileme ne gönderim olur.
- Öneri: seçiciyi tek yerde tanımla (`select[data-autosubmit]`).

### F-394 `localStorage` içeriği doğrulanmadan `Places` türüne dönüştürülüyor

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-19`
- Dosyalar: `frontend/windows.ts:57-64`, `:95-102`
- Açıklama: `parsed as Places` yalnızca "nesne mi" kontrol eder; değerler `Box` olmayabilir. `box.w * window.innerWidth` `NaN` üretir, `Math.max(MIN_WIDTH, NaN)` `NaN` döndürür ve `style.width = 'NaNpx'` yok sayılır; pencere boyutsuz kalır. Eski/başka sürüm verisinde olası.
- Öneri: sayı alanlarını `Number.isFinite` ile doğrula.

### F-395 Sürükleme iptalinde `pointercancel` dinleyicisi sızıyor

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-8`
- Dosyalar: `frontend/designer.ts:434-448`
- Açıklama: `onUp` üç dinleyiciyi kaldırır; `onCancel` yalnızca `pointermove` ve `pointerup`'ı kaldırır, kendisini (`pointercancel`) kaldırmaz. Her iptal edilen jestte düğümde bir bayat `onCancel` kalır; sonraki bir `pointercancel` hepsini çağırır ve `shown`'u sıfırlayıp `render` eder. Zararı küçük ama birikimli. `lostpointercapture` de ele alınmıyor.
- Kanıt: satır 440-445.
- Öneri: `{ once: true }` ya da ortak bir `cleanup()` kullan.

### F-396 monitoring/_card.html tek satırda mantık: bölüm adı eşlemesi ve iç içe if zinciri

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-10`
- Dosyalar: templates/monitoring/_card.html:23, :31
- Açıklama: `view.hidden` -> "Feeding/Water/Health/Tasks" eşlemesi ve `state.basis` -> etiket eşlemesi (satır 31, `else` her şeyi "Health" yapar) şablonda. Yeni bir kaynak eklenirse `else` dalı yanlış etiket basar ("Tasks" ya da "Health" olarak). Aynı eşleme iki yerde farklı kodla (satır 23 `else`=Tasks, 31 `else`=Health).
- Kanıt: `{% if view.hidden == "feeding" %}…{% else %}…section=_("Tasks")` ve `{% elif name == "water" %}…{% else %}{% trans "Health" %}`.
- Öneri: görünüm modelinde `view.hidden_label` / `state.basis_labels` üret.

### F-397 Şablonlar için otomatik denetim yalnızca "çok satırlı {# #}" kuralı

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-15`
- Dosyalar: core/tests_templates.py:1-24
- Açıklama: Şablon kuralı testi tek: çok satırlı yorum. csrf eksikliği, `|safe`, `target=_blank` rel, ham (çevrilmemiş) metin, kırık `{% url %}`/`include` yolu ve eksik ikon (`icons/<name>.svg` dinamik include; `entry.icon`, `empty_icon`) için statik denetim yok. (Betikle şu an csrf eksiği ve eksik sabit ikon bulunmadı.)
- Kanıt: dosya içeriği; `icons/_icon.html:1` `{% include "icons/"|add:name|add:".svg" %}` - prod'da eksik dosya sessiz boş SVG.
- Öneri: tüm şablonları derleyen + csrf/`|safe` allowlist testi ekle.

### F-398 POST form `action` tutarsızlığı: `request.path` ve `request.get_full_path`

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-3`
- Dosyalar: templates/crud/form.html:22, crud/confirm_delete.html:52 (request.path); farm/stock_void.html:18, farm/water_record.html, inventory/dialog.html, tasks/task_action.html vb. (get_full_path)
- Açıklama: CRUD formları sorgu dizgisini düşürür (ör. roster'dan `?employee=` ile açılan create formu geçersiz yanıtta/yeniden gönderimde sorguyu kaybeder), diğer ~15 şablon korur. Aynı kavram için iki davranış.
- Kanıt: `action="{{ request.path }}"` vs `action="{{ request.get_full_path }}"` (grep).
- Öneri: tek kural seç (tercihen boş `action` veya get_full_path) ve ortak include kullan.

### F-399 Sekme çubuğu (`view-tabs`) 10+ şablonda ayrı yazılmış, üç farklı "aktif" işareti

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-6`
- Dosyalar: hr/leave_list.html:9 (class `is-current`), tasks/task_list.html:15, inventory/storage.html:11, experiments/experiment_detail.html:24, reports/report_list.html:10, farm/_harvest_tabs.html:4, farm/_water_tabs.html:3-5, farm/production_units.html:14-15
- Açıklama: Çoğu `aria-current="page"` kullanırken hr/leave_list.html `is-current` sınıfı kullanıyor (erişilebilirlik/stil tutarsız). Sayı rozeti koşulu `item.count is not None` (task_list:15) vs `tab.count` (report_list:10): 0 sayısı biri gösterir, diğeri gizler. `_harvest_tabs` tek sekmede gizler, `_water_tabs` gizlemez.
- Kanıt: ilgili satırlar.
- Öneri: `_view_tabs.html` ortak include; aktif işareti tek biçim.

### F-400 Sayfalayıcı: knowledge/document_text.html kendi kopyasını taşıyor ve davranışı farklı

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-7`
- Dosyalar: templates/knowledge/document_text.html:17-25, templates/crud/_pager.html
- Açıklama: Kopya `pager_query` desteklemez, "Page n of m" göstermez. Metinler aynı `msgid` ("{{ first }}–{{ last }} of {{ total }}") kullanıyor ama biçim farklı.
- Kanıt: document_text.html:19-22 `href="?page=…"`; _pager.html:5-7 `?{{ pager_query }}&page=`.
- Öneri: `crud/_pager.html` include et (page ve pager_query ver).

### F-401 `<head>` iskeleti üç yerde kopya; Google Fonts dış bağımlılığı

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-8`
- Dosyalar: templates/app_base.html:6-17, auth_base.html:6-17, farm/water_calculator_report.html:7-16
- Açıklama: meta/font/favicon/module_map/CSS blokları kopya (rapor sayfası fontu hiç yüklemiyor, nav-boot.js yok - tutarsız). Fontlar `fonts.googleapis.com`'dan: gizlilik/CSP ve çevrimdışı (çiftlik ağı) bağımlılığı; çiftlik panelinde internet kopması durumunda render gecikmesi.
- Kanıt: app_base.html:9-11, auth_base.html:9-11.
- Öneri: ortak `_head.html`/`base.html`; fontu self-host et.

### F-402 Onay ekranlarında düğme/dil tutarsızlığı: Cancel / Back, danger stili

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-13`
- Dosyalar: templates/tasks/task_action.html:15-16, templates/hr/leave_reject.html:20, templates/hr/leave_approve.html:28, templates/crud/confirm_delete.html:53-55
- Açıklama: İptal düğmesi bazı diyaloglarda "Cancel", görev eyleminde "Back". Reddetme ("Reject") ve "Approve" düğmeleri `button-danger` değil, oysa void/delete danger; reject'in yıkıcılığı görsel olarak ayırt edilmiyor. Leave approve/reject, crud şablonlarından farklı `class="form"` + elle yazılmış `.confirm` olmayan iskelet kullanıyor.
- Kanıt: ilgili satırlar (`{% trans "Back" %}`, `<button type="submit" class="button">{% trans "Reject" %}`).
- Öneri: Ortak onay partial'ı (confirm kapsayıcı, Cancel, danger bayrağı).

### F-403 Production özeti izinsiz erişilebilir ve boş yer tutucu; Company özeti yalnız tek kutucuk

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-16`
- Dosyalar: config/urls.py:27, config/views.py:30-55, templates/production_home.html:35-37, templates/home.html:9-11
- Açıklama: `production_home` görünümünde panel izni kontrolü yok (menü gizleme "courtesy"); izni olmayan biri `/production/` açınca yalnız boş bölümler ve "The production figures will appear here." görür (403 yerine). Her iki özet sayfası da sabit "will appear here" yer tutucusu taşıyor; tüm kutucuklar izin yoksa sayfa tamamen boş kalıyor ve boş durum/yönlendirme yok.
- Kanıt: `path('production/', views.production_home...)` login dışında dekoratör yok; `<section class="placeholder">`.
- Öneri: Panel sunulmuyorsa 403/yönlendirme; hiç kutucuk yoksa "Henüz görüntüleyecek bir şey yok, yöneticinize başvurun" metni.

### F-404 Gizli (hidden) menü girişleri sayfadayken rail'de hiçbir satır aktif değil

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-2`
- Dosyalar: core/navigation.py:170, config/navigation.py:70-72
- Açıklama: `current_url` hidden girişler dahil hesaplanır, fakat rail yalnızca `shown_to` olanları çizer; Shifts/Holidays/Leave types sayfalarında hiçbir satır `aria-current` almaz ve üst sayfa ("Scheduling settings") işaretlenmez. Yorum "it is current there" diyor ama işaret kullanıcıya yansımıyor.
- Kanıt: `current_url = max(... entry.matches(request.path) ...)`; satırlar `for entry in group.entries if entry.shown_to(...)` içinde `'current': entry.url() == current_url`.
- Öneri: Hidden giriş current ise ebeveyn girişi (Scheduling settings) işaretle veya hidden girişe `parent` alanı ekle.

### F-405 Liste boş durumu filtre sonucunu "No X yet / Add the first" diye gösterir

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-4`
- Dosyalar: templates/crud/list.html:33-38, core/crud.py:620-645
- Açıklama: Boş durum yalnız `q` aramasını ayırt ediyor. `filter_list` ile (ör. `?kind=`, `?status=`) uygulanan filtre sıfır sonuç verince "No tanks yet - Add the first tank" yazar ve filtreyi temizleme bağlantısı yoktur; kayıt var olduğu halde yoktur izlenimi doğar. (production_units.html:56-66 bu ayrımı doğru yapıyor; tutarsız.)
- Kanıt: `{% if query %}... {% else %}<h2>No {{ plural }} yet`.
- Öneri: Filtre parametresi aktifse "No match / Clear filters" dalını göster (ListView bağlama `filtered` bayrağı versin).

### F-406 Sürüm çakışmasında diyalog tam sayfaya atıyor ve kullanıcının girdisi kayboluyor

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-8`
- Dosyalar: core/crud.py:726-731, core/crud.py:102-108, frontend/components.ts:342-346
- Açıklama: Çakışmada `done(request, edit_url)` stay=False olduğundan modal için `X-Modal-Redirect` döner; istemci `window.location.assign` ile düzenleme formunu tam sayfa olarak açar (diyalog bağlamı kaybolur). Mesaj "make your changes again" der ama kullanıcının yazdığı değerler gösterilmez/geri verilmez.
- Kanıt: `return done(request, self.url('edit', pk))` (stay yok) ve `done()` içinde `'X-Modal-Load' if stay else 'X-Modal-Redirect'`.
- Öneri: Çakışmada `stay=True` kullan ve kullanıcının girdisini yan yana göster/kopyalanabilir bırak.

### F-407 Dil değiştirici düğmelerinde görünen metin erişilebilir adın içinde değil (EN/TR/NB vs. English/Türkçe/Norsk bokmål)

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-14`
- Dosyalar: `templates/_language_switcher.html:6`, `config/settings.py:153`, `static/css/base.css:170-175`
- Açıklama: Düğmenin görünen etiketi `{{ code|upper }}` ("TR", "NB"), `aria-label` ise dilin adı ("Türkçe", "Norsk bokmål"). "TR" ifadesi "Türkçe" içinde düz metin olarak geçmiyor, "NB" de "Norsk bokmål" içinde yok (WCAG 2.5.3 Label in Name; sesle kontrol "TR'ye tıkla" komutu çalışmaz). Düğme yüksekliği `min-height:2rem` (32px) dokunmatik hedef için 44px önerisinin altında (WCAG 2.5.5 AAA/2.5.8 AA 24px'i geçer, bilgi amaçlı). Seçili dil `aria-current="true"` ile iyi işaretlenmiş.
- Kanıt: `_language_switcher.html:6` `lang="{{ code }}" aria-label="{{ name }}" title="{{ name }}"` ve görünen `{{ code|upper }}`.
- Öneri: Görünen metni dil adının kısaltması olarak tut ve adı "TR Türkçe" gibi görünen metni içerecek biçimde ver; veya görünür metni dil adına çevir.

### F-408 İç sekmeler (tabs): `aria-controls`/`aria-labelledby` yok, Home/End yok

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-5`
- Dosyalar: `templates/crud/form.html:13-19,27,49`, `frontend/components.ts:21-49`
- Açıklama: `role="tab"` düğmelerinde `id`/`aria-controls`, `role="tabpanel"` bölümlerinde `id`/`aria-labelledby` yok; ekran okuyucu sekme-panel ilişkisini kuramaz. Klavye yalnızca ArrowLeft/Right işliyor; Home/End yok. Tüm `extra_tabs` şablonları (board_form, task_form, report_form, experiment_form...) aynı yapıyı kopyalıyor.
- Kanıt: `components.ts:43` `event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0`; panel/sekme eşleşmesi yalnızca `data-tab`/`data-panel`.
- Öneri: Sekme ve panellere üretilen `id`, `aria-controls`, `aria-labelledby` ekle; Home/End destekle.

### F-409 Modal 403 yanıtında `aria-labelledby` geçersiz referans, kapatma düğmesi yok; hata yüklemesinde geri bildirim yok

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-6`
- Dosyalar: `frontend/components.ts:333-366`, `templates/app_base.html:107`, `templates/modal_base.html`
- Açıklama: `<dialog aria-labelledby="modal-title">` yalnızca `modal_base.html` içeriği yüklenince geçerli. 403 yolunda `components.ts:350-357` yalnızca `<p class="form-error">` koyuyor: `#modal-title` yok (dialog adsız kalır), `data-modal-close` düğmesi yok (yalnızca Esc/arka plan tıklaması kapatır; dokunmatik kullanıcı için zor). `fetch` ağ hatasında `load()` yakalanmamış reddedilir, kullanıcı hiçbir şey görmez; `void this.load(...)` ile bırakıldığı için sessiz hata. Yükleme sırasında `aria-busy`/duyuru da yok. Başarılı yüklemede odak ilk girdiye gider, başlık/duyuru verilmez (kabul edilebilir).
- Kanıt: `components.ts:304-311` `void this.load(opener.href)`; `:350-357`.
- Öneri: 403 içeriğine başlık + kapat düğmesi ekle; fetch hatasında dialog içinde `role="alert"` mesajı göster.

### F-410 Mobil menüdeki `aside aria-label="Main navigation"` ve etiketsiz iç `nav` landmark karmaşası

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-8`
- Dosyalar: `templates/app_base.html:21,46`
- Açıklama: Ana gezinme etiketi `<aside>` (complementary landmark) üzerinde; asıl `<nav class="rail-nav">` etiketsiz. Ekran okuyucu "Main navigation, complementary" ve ayrıca adsız "navigation" bildirir; sayfada `production_units.html:13`, `task_list.html:13` gibi başka `nav aria-label` var ama ana nav ayırt edilemiyor. Ayrıca çalışma alanı menüsü ve kullanıcı menüsü `aria-haspopup="true"` (menu rolü) ile işaretli ama panel içeriği `role="menu"`/`menuitem` değil, normal bağlantı/düğme; `aria-haspopup="true"` `menu` anlamına gelir ve beklenen ok tuşu davranışı yok (`shell.ts:78-98` yalnızca tıklama ve Esc; açılışta odak panele taşınmıyor).
- Kanıt: `app_base.html:21` ve `:46`; `:27,76`.
- Öneri: `aria-label`'ı `<nav>`'a taşı; `aside`'ı kaldır/ayrı etiketle; menü düğmelerinde `aria-haspopup` kaldır (disclosure deseni) veya tam menu klavye desenini uygula.

### F-411 Geçersiz/uygunsuz ARIA: `td`'de `aria-selected`, `<a>`'da `aria-pressed`, `tr`'de `aria-current`

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-9`
- Dosyalar: `frontend/roster.ts:61`, `templates/farm/production_units.html:32,37,41`, `templates/hr/roster.html` (hücreler), `templates/farm/production_units.html:87`, `templates/tasks/task_list.html:81`
- Açıklama: (a) `roster.ts` seçili `td`'ye `aria-selected` yazıyor; tablo `grid` rolünde değil, `td` rolü `cell` bu özniteliği desteklemez. (b) Filtre "düğmeleri" `<a class="filter-button" aria-pressed=...>`: bağlantı rolünde `aria-pressed` geçersiz, bağlantı seçili durumunu `aria-current` ile bildirmeli. (c) `tr.unit-row` üzerinde `aria-current="true"`; bu rol için anlamı belirsiz. Ekran okuyucu bu durumları yok sayar: seçili hücre/filtre bilgisi işitsel kullanıcıya iletilmez.
- Kanıt: `roster.ts:61` `cell.setAttribute('aria-selected', String(on))`; `production_units.html:32` `<a class="filter-button" ... aria-pressed="...">`.
- Öneri: Roster seçimi için gerçek bir kontrol (ör. gizli onay kutusu) veya `role="grid"`/`gridcell` desenini kullan; filtre bağlantılarında `aria-current="true"`; satır işaretini bir görünür/sr-only metne çevir.

### F-412 Çevrilmiş kullanıcı mesajlarında tarihler ISO (`isoformat()`), diğer yerlerde yerel `DATE_FORMAT`

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-4`
- Dosyalar: `experiments/design.py:256-257`, `experiments/services.py:805,808,852,855`, `experiments/read.py:245,400,463`, `reports/compute/lice.py:214,256,263,300`, `farm/models/stock.py:313`, `hr/models/roster.py:42`
- Açıklama: `docs/i18n.md` tarihlerin dilin biçiminde gösterildiğini söylüyor ve `farm/handling/check.py:54`, `farm/stock/dates.py:58` vb. `formats.date_format(..., 'DATE_FORMAT')` kullanıyor. Aynı türden `_()` mesajlarında ise `2026-11-02` biçimi `%(date)s` olarak veriliyor; aynı ekranda iki farklı tarih görünümü ortaya çıkar. `isoformat()` çağrısı test dışı Python'da ~81 yerde.
- Kanıt: `experiments/design.py:257` `_('%(first)s to %(last)s') % {'first': first.isoformat(), ...}`; `reports/compute/lice.py:214` `'date': due[unit_id].isoformat()`.
- Öneri: Kullanıcıya giden mesajlarda ortak bir `formats.date_format` yardımcısı kullanın (şu an `farm/templatetags/feeding.py:48`, `health.py:45`, `farm/handling/check.py:54`, `farm/stock/dates.py:58` içinde dört kopya var, bkz. 45-12).

### F-413 Türkçe sözlük kayması: `site` = `saha` (139) ve `lokasyon` (32)

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-5`
- Dosyalar: `locale/tr/LC_MESSAGES/django.po`, `docs/i18n.md` (sözlük: site -> saha)
- Açıklama: Sözlük `site` için tek terim (`saha`) belirliyor ve "bir terim, bir çeviri" kuralı koyuyor. `tr` katalogunda 32 msgstr `lokasyon` kullanıyor: `%(site)s bir deniz lokasyonu değil`, `%(site)s bir yavru balık (settefisk) lokasyonu değil`, `lokasyonun diğer birimlerine taşındı`, `lokasyonunkidir`. Aynı kavram menüde `Sahalar`.
- Kanıt: Babel ile msgstr taraması: `lokasyon` 32, `saha` 139. NB tarafı tutarlı (`lokalitet` 165).
- Öneri: 32 msgstr'yi `saha` yapın; `core/test_catalogs.py`'ye sözlük yasaklı-terim kontrolü ekleyin.

### F-414 Şablonlarda sabit tarih biçimleri (`j M`, `D j`, `D j M`, `l`)

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-6`
- Dosyalar: `templates/hr/_crew.html:11`, `templates/hr/overview.html:55`, `templates/hr/leave_approve.html:15`, `templates/hr/holiday_list.html:15`
- Açıklama: `docs/i18n.md` "şablonlar format yazmak yerine `DATE_FORMAT` ister" diyor; bu dört yer gün/ay sırasını sabitliyor. Norveççede gün sırasının noktası (`3. nov`) kaybolur; Türkçe/İngilizce ile aynı çıktı verir. Ekranda yerel biçim (`DATE_FORMAT`) ile yan yana durduğunda tutarsız.
- Kanıt: grep sayımı: `date:"j M"` 2, `date:"D j"` 1, `date:"D j M"` 1, `date:"l"` 1.
- Öneri: `MONTH_DAY_FORMAT`/`SHORT_DATE_FORMAT` gibi dil biçimlerini veya `config/formats` içinde kısa gün-ay tanımı kullanın.

### F-415 Sayfa-ozel CSS yuklenmeyen sablon: `experiment_detail.html` `plain-list` kullaniyor

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-10`
- Dosyalar: `templates/experiments/experiment_detail.html:31`, `static/css/hr.css:15`
- Açıklama: `.plain-list` yalniz `hr.css`'te tanimli, ama deneyler sayfasi `hr.css` yuklemiyor; liste isaretli/bosluksuz stil almaz. Genel yardimci sinif ozel dosyaya konmus.
- Öneri: `.plain-list`'i `components.css`'e tasi.

### F-416 Renk token'lari eksik: ayni degerler yuzlerce kez sabit yaziliyor; tanimsiz degisken ve yanlis fallback

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-13`
- Dosyalar: `static/css/components.css` (121 hex), `static/css/hr.css:37,48,49`, `static/css/base.css:5-17`
- Açıklama: `#7A5410` 19, `#F7E6E6` 13, `#ECECEA` 11, `#FBF0D9` 10 kez sabit; amber/kirmizi tint token'i yok. `hr.css:37` `var(--paper, #fff)` ve `:48-49` `var(--stripe-dark, #2B5F43)` tanimsiz/eski degiskenler: `--paper` hicbir yerde tanimli degil, `--stripe-dark` tanimli (`#9A3650`) oldugu icin yesil `#2B5F43` fallback'i hic calismaz ama paletle de ilgisiz (eski temadan kalma). Grafik renkleri (`#2563EB`, `#EF4444` vb.) Tailwind paletinden ayri ikinci bir palet; yorumlar "source's tokens" diyor.
- Öneri: `--warn-bg/--warn-fg/--error-bg` token'lari tanimla; olu fallback'leri temizle.

### F-417 `.links` sinifi iki dosyada farkli amacla tanimli (marj sizintisi)

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-6`
- Dosyalar: `static/css/base.css:136-139`, `static/css/components.css:290`, `templates/core/widgets/link_list.html:2`, `templates/registration/login.html:13`
- Açıklama: `base.css` `.links { margin:1.5rem 0 0; font-size:.9375rem }` giris sayfasi baglantilari icin; `components.css` ayni isimle `LinkList` widget'ini (`display:grid; gap`) tanimliyor. Widget `margin-top:1.5rem` ve kucuk font devralir (istenmeyen bosluk). `auth_base` components.css yuklemedigi icin giris sayfasinda catisma yok, uygulama kabugunda var.
- Öneri: Biri yeniden adlandirilsin (`.auth-links`).

### F-418 `.card-grid` iki farkli yerlestirme icin kullaniliyor

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-7`
- Dosyalar: `static/css/components.css:73-80`, `static/css/monitor.css:152` (`.card-grid { --row; grid-template-columns: repeat(12...) }`), `templates/farm/site_list.html:6`, `templates/monitoring/_card.html:22`
- Açıklama: Ayni sinif adi hem site kartlari (auto-fill) hem izleme kartinin 12 sutunlu widget izgarasi. Calisma, `monitor.css`'in `components.css`'ten sonra yuklenmesine ve her ozelligin yeniden yazilmasina bagli (kirilgan). `components.css`'teki `list-style/padding/margin` monitor `div`'ine de uygulanir.
- Öneri: Izleme tarafini `.monitor-widgets` gibi ayri adlandir.

### F-419 Dinamik rozet siniflari (`badge-leave-*`, `badge-state-*`) icin CSS yok; flash varyantlari eksik

Önem: **Düşük** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-9`
- Dosyalar: `templates/hr/leave_list.html:31`, `templates/hr/_board.html:21`, `templates/app_base.html:100`, `templates/modal_base.html:14`, `static/css/app.css:448` (`.flash-error` tek varyant)
- Açıklama: Izin durumu (`pending/approved/rejected/cancelled`) ve bugunku pano durumu (`upcoming/present/late/not_in/absent/on_leave/done`) rozetleri icin hic kural yok; bunlar renksiz `.badge` olarak cikar. CSS'in kendi ilkesi "yalniz sorunlar renk alir" (`components.css:138`) ile celisir: `rejected`, `late`, `absent` ayirt edilemez. Benzer sekilde mesaj turleri (43 `success`, 8 `warning`, 1 `info` kullanimi) icin `.flash-success/-warning/-info` yok; uyari mesaji basarili mesajla ayni gorunur, yalniz `.flash-error` farkli.
- Kanıt: `grep "badge-leave\|badge-state\|flash-warning" static/css` bos.
- Öneri: `.badge-leave-rejected`, `.badge-state-late/absent`, `.flash-warning` vb. ekle.

### F-420 Messaging modülü hiçbir iş akışına bağlı değil; bildirim zinciri yok

Önem: **Düşük** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-1`
- Dosyalar: `messaging/events.py:14`, `messaging/services.py:234-246`
- Açıklama: `message_posted` sinyalini gönderen kod var ama dinleyen yok; `messaging` başka hiçbir uygulamadan import edilmiyor ve kendisi de `farm/hr/tasks` vb. import etmiyor. Görev atanması, izin kararı, arınma bitişi, düşük stok, geciken rapor gibi olaylar kimseye mesaj/bildirim olarak gitmiyor; hepsi yalnız ilgili sayfa açılınca okunuyor.
- Kanıt: `grep -rn message_posted` yalnızca `messaging/` içinde ve testlerde; `grep -rn "from messaging"` dışarıdan sıfır sonuç. `messaging/events.py` docstring: "Nothing in the MVP listens".
- Öneri: Bilinçli MVP sınırı ise README'de "olay -> bildirim" akışlarının olmadığı açıkça yazılsın; ilk adım olarak görev atama ve izin kararı gibi olaylar için `on_commit` dinleyicisi tasarlansın.

### F-421 Silme engeli mesajı var olmayan "Close" eylemine yönlendiriyor

Önem: **Düşük** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-2`
- Dosyalar: experiments/models.py:150-153
- Açıklama: "It has started: it is kept as a record. Close it instead." mesajı 48-1 nedeniyle kullanıcıyı çıkmaza sokar.
- Öneri: 48-1 ile birlikte çözülür.

### F-422 Task `in_progress` -> `open` geri dönüşü yok

Önem: **Düşük** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-6`
- Dosyalar: tasks/services.py:104-166, tasks/models.py:384-387
- Açıklama: `start` yalnızca open'dan; `reopen` `OPEN_STATUSES` içindeki (in_progress dahil) görevleri reddeder ("This task is open already"). Yanlışlıkla başlatılan görev ya tamamlanır ya iptal edilip yeniden açılır (başlatan bilgisi silinir). Durum makinesi kasıtlı olabilir ama "unstart" yok.
- Öneri: belgelenmeli ya da `in_progress -> open` eklenmeli.

### F-423 Üretim organizasyon şeması tüm üretim bölümlerini ve yöneticilerini ekip kapsamından bağımsız gösterir; yalnız hr.view_employee ister

Önem: **Düşük** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-3`
- Dosyalar: hr/read.py:492-509; hr/views.py:215-227; config/navigation.py (Production › Team › Organization chart)
- Açıklama: `org_tree(realm=PRODUCTION)` her `ProductionDepartment`'ı site ve yönetici adıyla listeler; yalnızca kişi sayıları kapsamla (`head_counts`) daraltılır. `hr.view_employee` takım-kapsamlı bir izindir (lider yalnız ekibini görür), ama şemada tüm bölümler/yöneticiler görünür. Şirket tarafında aynı sayfa `hr.view_officedepartment` ister: iki farklı izin modeli aynı görünümü korur.
- Kanıt: `ProductionDepartment.objects.select_related('site', 'manager').order_by('name')` filtresiz; `organisation_chart`: `has_perm(place.entry.perm)` (mount'a göre değişir).
- Öneri: Tasarım kararı olarak belgele veya yalnız erişilebilen bölümleri göster.

### F-424 Özel 403/404/500 şablonu yok; yetkisiz erişimler düz Django yanıtı verir (modal istekleri dahil)

Önem: **Düşük** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-7`
- Dosyalar: templates/ (403.html/404.html/500.html yok); `handler403` tanımı yok (grep boş); core/crud.py:553-557 (PermissionDenied)
- Açıklama: Tüm yetki reddi `PermissionDenied` ile 403 üretir; kullanıcı menüye dönüş bağlantısı olmayan çıplak "403 Forbidden" görür. `X-Modal` ile açılan diyalog (core/crud.py:86-87) 403 olduğunda modal içinde çıplak metin gösterebilir.
- Kanıt: `find templates -name "40*"` boş.
- Öneri: Marka şablonlu 403/404 sayfaları ve modal için kısa parça.

### F-425 Mesaj gönderiminde idempotency yok

Önem: **Düşük** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-5`
- Dosyalar: messaging/services.py, messaging/views.py
- Açıklama: `post` kilitli ve atomik ama token almaz; çift tıklama ya da zaman aşımı sonrası yeniden gönderim aynı mesajı iki kez yazar. Stok/sağlık formlarındaki token modeli burada uygulanmamış.
- Kanıt: messaging/services.py:231-247; messaging/views.py:92-98 (form token'ı yok).
- Öneri: Forma token ekle veya kısa pencerede aynı yazar+gövde tekrarını yoksay.

### F-426 Yükleme boyutu global sınırları ve proxy/HTTPS başlığı ayarları yok

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-X2`, `06-X2`  (yalnız çapraz görüş)
- Dosyalar: config/settings.py
- Açıklama: Yükleme boyutu ayarları (DATA_UPLOAD_MAX_MEMORY_SIZE vb.) ve proxy/HTTPS başlığı ayarları yok
- Birleştirilen kayıtlar:
  - `06-X2` (Bilgi): Yükleme/indirme boyutu için global Django sınırları ayarlanmamış (DATA_UPLOAD/FILE_UPLOAD)

### F-427 restore/soft delete audit satırında değer yok, hard delete kurtarma bilgisi eksik

Önem: **Düşük** | Güven: belirtilmedi | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-X3`, `12-X4`  (yalnız çapraz görüş)
- Dosyalar: core/softdelete.py, core/audit.py
- Açıklama: Audit RESTORE/soft delete satırlarında değer yok ve hard delete log'u kurtarma için kullanılamaz: kurtarma bilgisi iki yerde de eksik
- Birleştirilen kayıtlar:
  - `12-X4` (Düşük): restore audit satirinda degisiklik icerigi yok

### F-428 Aynı sıcaklık için üç ayrı tanım (arınma, bit raporu, su kartı)

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-X1`, `22-X1`  (yalnız çapraz görüş)
- Dosyalar: farm/water/degree_days.py, reports/compute/lice.py, farm/health/withdrawal.py
- Açıklama: Ayni batch icin uc farkli sicaklik tanimi: arinma, bit raporu ve su karti
- Birleştirilen kayıtlar:
  - `22-X1` (Düşük): Aynı sıcaklık için üç ayrı tanım: bit raporu (3 m nokta ortalaması), arınma derece-günü (batch günlük ortalaması), yemleme tablosu

### F-429 Supplier/Location durum alanı davranışsız/asimetrik

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-X1`, `48-X3`  (yalnız çapraz görüş)
- Dosyalar: farm/models/supplier.py:141, inventory/services.py:187-195
- Açıklama: Durum alanı davranışsızlığı Supplier.status'a da uzanıyor
- Birleştirilen kayıtlar:
  - `48-X3` (Düşük): Tedarikçi ve lokasyon durum denetimi asimetrik

### F-430 Site.altitude doğrulayıcısız

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-X2`, `50-X3`  (yalnız çapraz görüş)
- Dosyalar: farm/models/site.py:80-87, farm/forms/water.py:427, farm/water/chemistry.py:367
- Açıklama: Site.altitude modelde doğrulayıcısız; sınır yalnız hesaplayıcı formunda
- Birleştirilen kayıtlar:
  - `50-X3` (Düşük): Site.altitude sınırsız: pressure_atm aşırı değerde ValueError, su okuması çöker

### F-431 README gunicorn/cron varsayar, repoda karşılığı yok

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: belirtilmedi | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-X2`, `39-X2`  (yalnız çapraz görüş)
- Dosyalar: README.md, docker-compose.yml, tasks/management/commands/generate_tasks.py
- Açıklama: README gunicorn/cron/çok-worker varsayar ama repoda karşılığı yok
- Birleştirilen kayıtlar:
  - `39-X2` (Bilgi): README gunicorn'dan bahsediyor ama repoda dagitim tanimi yok

### F-432 Dil değiştirici etiket/aria/next tutarsızlığı

Önem: **Düşük** | özgün: Düşük/Bilgi | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-X1`, `45-X2`  (yalnız çapraz görüş)
- Dosyalar: templates/_language_switcher.html:5-7
- Açıklama: Dil degistirici hem aria-label ile gorunen etiketi eziyor hem request.get_full_path ile next uretiyor
- Birleştirilen kayıtlar:
  - `45-X2` (Bilgi): Dil değiştirici: aria-label ve title dil adı, görünen etiket dil kodu; sayfa dilinden bağımsız

### F-433 |lower Türkçe i sorunu şablonlarda

Önem: **Düşük** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-X2`, `44-X2`  (yalnız çapraz görüş)
- Dosyalar: templates/farm/_unit_drawer.html:106, templates/inventory/void.html:6, templates/farm/stock_void.html:12
- Açıklama: |lower kullanimi uc sablonda, i18n bulgusu yalnizca ikisini sayiyor
- Birleştirilen kayıtlar:
  - `44-X2` (Düşük): Türkçe |lower birleşik noktalı i üretir, ekran okuyucu telaffuzu da bozulur

### F-434 Parola sıfırlama token süresi açıkça ayarlanmamış (davet de aynı süre)

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-11`
- Dosyalar: config/settings.py, core/resources.py:66-69
- Açıklama: `PASSWORD_RESET_TIMEOUT` yok, varsayılan 3 gün hem davet hem unutulan parola için geçerli; davet için makul, reset için uzun. Süre geçince davetli kullanıcı kendi "yeni bağlantı iste" yolunu kullanıyor (test: core/tests.py:383).
- Kanıt: ayar yok.
- Öneri: Süreyi bilinçli seç (ör. 1 gün) ve belgele.

### F-435 E-posta benzersizliği yalnızca form düzeyinde; reset birden çok hesaba gider

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-8`
- Dosyalar: core/forms.py:122-125 (clean_email), 162-165
- Açıklama: `User.email` DB'de unique değil; benzersizlik sadece UserForm'da. Admin dışı yollar (createsuperuser, seed, shell) aynı e-postayı verebilir; `get_users` hepsine ayrı token gönderir. Admin'de User kaydı kaldırılmış (core/admin.py:72) bu yüzden risk düşük.
- Kanıt: `clean_email` formda; model alanında unique yok.
- Öneri: Case-insensitive unique kısıt (DB).

### F-436 Deney ekibi (`Member`) yetkiye etki etmiyor; `change_experiment` sahibi her deneyi düzenler/başlatır

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-10`
- Dosyalar: experiments/resources.py:93-100 (yalnızca "Mine" filtresi), experiments/resources.py:175-185; README.md ("permissions plan")
- Açıklama: Ekip yalnızca bilgi; "öğrenci yalnız ekibi olduğu deneyleri düzenler" henüz yok (docs/experiments.md:16). Ekip listesini de `change` sahibi herhangi biri değiştirebilir.
- Kanıt: `objects.filter(members__user=request.user)` yalnızca liste görünümünü daraltır.
- Öneri: `Resource.scoped/allowed` ile ekip tabanlı kural uygula veya "kullanılmıyor" diye belgele.

### F-437 Ekip kapsamındaki yönetici, kendi Employee kaydını düzenleyebilir (yerleşim, işe giriş/ayrılış tarihi, istihdam türü)

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-11`
- Dosyalar: hr/services.py:25-28, 50-52; hr/forms/employee.py:77-81; hr/resources/employee.py:40-42; hr/scope.py:127-135
- Açıklama: `self_plan` yalnızca vardiya/yoklama/izin için kendi kaydı engelliyor. `EmployeeResource.allowed` tanımlı değil (varsayılan True), `scope.team` kişinin kendisini içerir; `change_employee` sahibi kendi yerleşimini taşıyabilir, `joined_on/left_on` değiştirebilir. `user` alanı yalnızca `all` sahibine açık (iyi).
- Kanıt: hr/scope.py:135 `Q(user=user) | Q(pk__in=members)`; hr/resources/employee.py'de `allowed` override yok.
- Öneri: `EmployeeResource.allowed` içinde `self_plan` benzeri kural.

### F-438 Envanter sayımı/silme ve yazma ayrımı: sayım onayı ve iptal (void) aynı "Delete" izniyle; iki kişi kuralı yok

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-15`
- Dosyalar: inventory/views.py:275-348, 416-420; docs/aquaculture-platform-bugs.md STR-22
- Açıklama: `add_inventoryoperation` sahibi her tür (atık, düzeltme, sayım) kaydedebilir; belgedeki "count second person" kuralı uygulanmadı ("later (Q-S7)").
- Kanıt: inventory/views.py:416 `@permission_required(VOID)`; sayım için ayrı onay yok.
- Öneri: Açık karar olarak izle.

### F-439 Harici URL alanları yalnızca form doğrulayıcısıyla `http/https`e kısıtlı, şablonda doğrudan `href`

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-5`
- Dosyalar: knowledge/models/document.py:106, knowledge/models/entry.py:75, templates/knowledge/document_detail.html:26, templates/knowledge/entry_detail.html:24, knowledge/citation.py:112-114, farm/models/supplier.py:145
- Açıklama: `url` alanlarında `URLValidator(schemes=['http','https'])` var, ama bu yalnızca `full_clean`/ModelForm yolunda çalışır; DB `CheckConstraint` yok. Form dışı bir yazma yolu (içe aktarma, shell, ileride AI ajanları, seed) `javascript:` şeması kaydedebilir ve `<a href="{{ object.url }}">` ile `citation.reference()` bunu tıklanabilir basar (Django `javascript:` URL'ini kaçışlamaz, yalnızca HTML-escape eder). `farm/models/supplier.py:145` `website` alanı varsayılan URLValidator kullanır (http/https/ftp/ftps; `javascript:` reddedilir). Bugün form dışı yol kanıtlanmadı.
- Kanıt: `href="{{ object.url }}"`; citation.py: `<a href="{escape(url)}" ...>`.
- Öneri: DB düzeyinde şema kısıtı veya şablonda `url|urlize` yerine şema kontrolü yapan bir filtre; en azından `rel="noopener noreferrer"` zaten var (iyi).

### F-440 DOI bağlantısı iki yerde farklı üretiliyor (`urlencode` var/yok)

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-6`
- Dosyalar: knowledge/citation.py:97-99,112-114, templates/knowledge/document_detail.html:25
- Açıklama: Şablon `https://doi.org/{{ object.doi|urlencode:'/' }}` kullanır; `citation.link()` ise `f'{DOI_LINK}{document.doi}'` yazar, `escape` ile HTML'e güvenli ama URL olarak kodlanmaz. `#`, `?` veya boşluk içeren DOI iki yerde farklı hedefe gider. Güvenlik etkisi yok (HTML kaçışı doğru), tutarlılık sorunu.
- Kanıt: yukarıdaki satırlar.
- Öneri: Tek yardımcıdan üret (`citation.link` URL kodlamalı).

### F-441 `X-Modal-Redirect` / `X-Modal-Load` başlık değerleri istemcide şema/köken doğrulaması olmadan kullanılıyor

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-9`
- Dosyalar: frontend/components.ts:339-347, core/crud.py:98-107
- Açıklama: İstemci `window.location.assign(redirectTo)` ve `this.load(next)` çağırıyor; değer yalnızca sunucu başlığından geliyor (`core/crud.py:done(request, url, ...)`). Çağıranlar `reverse()`/`_return()` ile üretiyor (hr `_return` `url_has_allowed_host_and_scheme` kullanıyor). Tüm `done()` çağıranlarının kullanıcı girdisi geçirmediği tam doğrulanmadı.
- Kanıt: `response.headers.get('X-Modal-Redirect')` -> `window.location.assign(redirectTo)`.
- Öneri: İstemcide `new URL(value, location.href).origin === location.origin` kontrolü ekle.

### F-442 `Content-Disposition` dosya adı biçimlendirmesi tutarsız

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-10`
- Dosyalar: core/dbview.py:63, reports/views.py:220
- Açıklama: reports `content_disposition_header` (güvenli) kullanırken core/dbview.py elle `f'attachment; filename="{table.name}.csv"'` kuruyor. `table.name` model kaydından geldiği için bugün güvenli; ama tutarsız ve gelecekte kullanıcı kontrollü ada geçerse başlık enjeksiyonuna açık.
- Kanıt: dbview.py:63.
- Öneri: Her yerde `django.utils.http.content_disposition_header` kullanın.

### F-443 PDF ayrıştırma (pypdf) güvenilmeyen girdiyi yüklemede eşzamanlı işliyor

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-5`
- Dosyalar: knowledge/extraction.py:1-60, knowledge/models/document.py:224
- Açıklama: Hatalar `FAILED`'e çevriliyor (iyi), ancak çok sayfalı/sıkıştırma bombası PDF için sayfa sayısı/bellek/süre sınırı bulunmadı; yalnız dosya boyutu (`KNOWLEDGE_MAX_FILE_BYTES`) sınırlı. Bir enjeksiyon değil, ayrıştırıcı kötüye kullanımı (DoS).
- Kanıt: extraction.py `read_pdf` içinde sayfa/zaman sınırı yok.
- Öneri: Sayfa sayısı ve çıkarılan metin boyutu üst sınırı; ayrı işçi/zaman aşımı.

### F-444 DEBUG varsayılanı açık olduğundan DEBUG'a bağlı komutlar varsayılan çalışır

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-11`
- Dosyalar: README.md:2827, config/settings.py:28
- Açıklama: `seed_hr_demo` "yalnızca DEBUG açıkken" korumasına dayanıyor; DEBUG varsayılanı açık olduğundan (05-2) bu koruma yapılandırma hatasında devre dışı kalır ve demo verisi üretimde oluşabilir. (Komutun kendi kodu doğrulanmadı.)
- Kanıt: README.md:2827.
- Öneri: 05-2'nin düzeltilmesiyle kapanır.

### F-445 Yüklenen dosya adı denetimsiz saklanıyor; Windows yolu/kontrol karakterleri ve `text_error` içinde ham pypdf mesajı

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-10`
- Dosyalar: knowledge/models/document.py:258-264, knowledge/extraction.py:69-70, knowledge/models/document.py:253-254
- Açıklama: `_file_name` yalnızca `os.path.basename` ile kırpar (Linux'ta `\` ayırıcısını ve kontrol karakterlerini temizlemez; Django'nun `UploadedFile.name` zaten bazı temizlik yapar ama `\` korunabilir). Ad, Content-Disposition ve arayüzde gösterilir (Django başlığı kaçışlar, şablon otomatik kaçışlar; doğrudan zafiyet yok). `text_error` ise `f'{type(error).__name__}: {error}'` ile ham istisna mesajını (pypdf iç ayrıntıları) kullanıcıya gösterir (500 karakter).
- Kanıt: `name = os.path.basename(name or '') or 'document.pdf'`; `Extraction(FAILED, error=f'{type(error).__name__}: {error}'[:ERROR_LENGTH])`.
- Öneri: Adı `get_valid_filename` benzeri bir normalleştirmeden geçir; hata metnini sabit kullanıcı mesajıyla değiştirip ayrıntıyı log'a yaz.

### F-446 Yetkilendirme yalnızca model düzeyi `view` izni; dosya için ayrı izin ve çalışma-alanı kapsamı yok

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-13`
- Dosyalar: knowledge/views.py:20-30, core/crud.py (Resource.perm)
- Açıklama: `document_file` yalnızca `DocumentResource.perm('view')` kontrol eder; kütüphaneyi okuyabilen herkes tüm PDF'leri indirir (README'deki tasarımla uyumlu, bilinçli). Dosyayı görmek ile referansı görmek ayrı yetkilendirilemez; kapsamlı/özel belgeler (gizli sözleşme PDF'i) için ayrım yok. Not: dosya erişimi `Document.objects` (canlı kayıt) ile sınırlı, silinmiş belge 404 veriyor (test var).
- Kanıt: `_allowed(request, DocumentResource, 'view')` ve `get_object_or_404(Document.objects, pk=pk)`.
- Öneri: Gerekiyorsa belge başına görünürlük/`download_document` izni; mevcut tasarım belgelenmiş olduğundan bilgi amaçlı.

### F-447 Yükleme/indirme olayları denetim kaydına yazılmıyor; dosya içeriği değişimi izlenemiyor

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-7`
- Dosyalar: knowledge/views.py:26-40, knowledge/resources/document.py:81-89
- Açıklama: `document_file` erişimi (açma/indirme) audit log'a yazılmaz; kimin hangi PDF'i indirdiği izlenemez. Denetim anlık görüntüsü (`snapshot`) yalnızca `file_name`, `text_status`, `page_count` içerir; dosya değiştiğinde aynı adla yeni içerik yüklenirse log farkı yalnızca sayfa sayısı değişirse görünür; boyut/özet (hash) kaydedilmez.
- Kanıt: `snapshot` yalnızca `document.file_name`, `text_status`, `page_count` değerlerini ekler; `document_file` içinde `audit` çağrısı yok.
- Öneri: Dosya SHA-256 ve `file_size` değerlerini model alanı/snapshot olarak ekle; hassas içerik için indirme olayını günlükle.

### F-448 Sabitlenen dev araçları eski sürümler (playwright-core 1.49.1, typescript 5.6.3, @types/node 22.10.2, axe-core 4.10.2)

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-12`
- Dosyalar: package.json:24-28, package-lock.json
- Açıklama: Sürümler tam sabit, iyi; fakat hepsi 2024 sonu sürümleri, bugün (2026-11) birkaç majör sürüm geride olabilir (ağ doğrulaması yapılmadı). playwright-core eski, tarayıcı sürümleriyle uyumsuzluk riski taşır (Chrome/Edge makinenin kendisinden kullanılıyor). Yalnızca dev olduğu için çalışma zamanı riski düşük.
- Kanıt: `"playwright-core": "1.49.1"`, `"typescript": "5.6.3"`.
- Öneri: Düzenli güncelleme (bkz. 07-3).

### F-449 README kurulumunda `npm ci` yerine kurulum talimatı/sürüm sıkılığı belirtilmemiş; `pip install` yönergesi doğrulanamadı

Önem: **Düşük** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-14`
- Dosyalar: README.md:2982-2987, README.md:3403-3405
- Açıklama: Python kurulum adımları gösterilirken `pip install -r requirements.txt` ve `npm install` satırlarının kesin biçimi (kilitli kurulum) açık değil; README `npm install` ifadesi kullanıyor (satır 3403) bu da lock'u güncelleyebilir. `npm ci` daha güvenli.
- Kanıt: README.md:3403 "when Node and `npm install` are there".
- Öneri: `npm ci` ve `pip install --require-hashes -r ...` belgelensin.

### F-450 HR kişisel verisinin okunması (erişim) kaydı yok; günlük yalnız değişiklikleri tutuyor

Önem: **Düşük** | Güven: orta | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-11`
- Dosyalar: `hr/services.py:33-362` (yalnız yazma yolları `audit.record*`), `core/audit.py`, `hr/resources/leave.py`, `hr/resources/attendance.py`
- Açıklama: Kimin hangi çalışanın izin/yoklama/izin türü (sick = sağlık verisi) bilgisini okuduğu hiçbir yerde kaydedilmez; `audit.record` çağrıları yalnız create/update/delete'tir. HR "Everyone" sahiplerinin tüm kişilere erişimi vardır; kötüye kullanımın sonradan tespiti mümkün değildir (KVKK m.12 veri güvenliği, erişim izlenebilirliği).
- Kanıt: `hr/services.py` içinde yalnız yazma sonrası `audit.record_*` çağrıları; okuma akışlarında (`hr/read.py`, resource detail) çağrı yok.
- Öneri: Hassas HR alanlarının (izin türü/sebebi detay sayfaları, dışa aktarımlar) okunması için ayrı, kısıtlı erişim kaydı düşünün.

### F-451 Django admin, DB görüntüleyicinin maskelediği HR/serbest metin alanlarını maskesiz gösteriyor

Önem: **Düşük** | Güven: orta | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-6`
- Dosyalar: `core/admin.py:22-70`, `hr/admin.py`, `config/database.py:masked`, `hr/models/leave.py:80-81`, `hr/models/attendance.py:43`
- Açıklama: `register_audited('hr')` tüm HR modellerini salt-okunur olsa da alan sınırlaması olmadan kaydeder; admin değişiklik/detay sayfası `LeaveRequest.reason`, `decision_note`, `AttendanceRecord.note`, `ShiftAssignment.note` alanlarını gösterir. DB görüntüleyici aynı alanları açıkça maskeler ve README/checklist "platform admin okumaz" niyetini taşır. Takım kapsamı (`hr.scope`) da admin'de uygulanmaz. Yalnız superuser (is_staff UI'dan verilmiyor) etkilenir, bu yüzden low.
- Kanıt: `register_audited` `list_display`/`fields` kısıtlamaz; `masked={... 'leave_requests': ('reason','decision_note'), 'attendance_records': ('note',) ...}` yalnız viewer'da.
- Öneri: HR modelleri için admin'de `exclude`/`readonly` ile bu alanları gizleyin veya HR'yi admin'e kaydetmeyin; iki yüzeyin maske listesini tek kaynaktan türetin.

### F-452 DB görüntüleyicinin maske listesi eksik (e-posta, görev notları, kontaklar)

Önem: **Düşük** | Güven: orta | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-7`
- Dosyalar: `config/database.py` (`masked=`), `core/database.py:33`
- Açıklama: Maske yalnız `auth_user.password`, `messages.body`, `shift_assignments.note`, `leave_requests.reason/decision_note`, `attendance_records.note` için tanımlı. `auth_user` (email, ad, soyad), `task_notes.body`, `tasks.completion_note/cancel_reason`, kontak tabloları (`site_contacts`/`supplier_contacts` ad/e-posta/telefon), `reports.contact_*` görüntülenebilir ve CSV ile dışa aktarılabilir. Checklist 4.3 görüntüleyiciyi yalnız IT'ye ver diyor; yine de maske politikası kişisel veri sınıflandırmasına dayalı değil.
- Kanıt: `masked={'auth_user': ('password',), 'messages': ('body',), ...}` — başka PII kolonu yok.
- Öneri: Kişisel veri kolonlarının bir envanterini çıkarıp görüntüleyici/dışa aktarma maskelerini ona göre tamamlayın; `docs/data-map` içine "PII" sütunu ekleyin.

### F-453 Anahtarlı özet (`rev`) zayıf: 8 hex karakter ve SECRET_KEY için güvensiz varsayılan

Önem: **Düşük** | Güven: orta | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-8`
- Dosyalar: `core/audit.py:96-100`, `config/settings.py:25`
- Açıklama: "Private text" yerine günlüğe `HMAC-SHA256(SECRET_KEY, değer)[:8]` yazılır. `SECRET_KEY` ortam değişkeni yoksa herkesin bildiği `django-insecure-local-development-only` kullanılır; bu durumda kısa/ortak metinlerin (ör. "sick", "hastalık") özetleri sözlük saldırısıyla çözülebilir. Ayrıca aynı metin farklı kayıtlarda aynı `rev`'i üretir (eşitlik sızıntısı: iki kişinin aynı sebebi girdiğini günlük okuyucusu görür). SECRET_KEY değişirse eski `rev` değerleri karşılaştırılamaz hale gelir.
- Kanıt: `hmac.new(settings.SECRET_KEY.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:8]`; `SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-...')`.
- Öneri: Üretimde varsayılan SECRET_KEY'i reddedin (check framework); özetin kayıt kimliğini de içermesi eşitlik sızıntısını azaltır.

### F-454 `stock_of` her çağrıda mevcut stoklu partilerin tüm hareket geçmişini katlar (Üretim birimleri sayfası, izleme duvarı)

Önem: **Düşük** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-18`
- Dosyalar: farm/stock/read.py:327-335, 33-45; farm/stock/views.py:124-134; monitoring/read.py:314-317
- Açıklama: Şu an stokta olan her partinin tüm `StockMovement` satırları (hayat boyu) `ledger()` ile belleğe alınıp katlanır; bu sonuç Üretim birimleri sayfası, izleme kartları (poll 204 kısayolu dışında) ve raporlarda tekrar tekrar hesaplanır. Parti geçmişi büyüdükçe maliyet partilerin yaşıyla orantılı artar; önbellek veya anlık görüntü (snapshot) yok.
- Kanıt: `rows = list(StockMovement.objects.filter(batch_id__in=batch_ids, operation__is_deleted=False).values_list(...))` (read.py:36).
- Öneri: Ölçüm yap; gerekirse partiler için kısa ömürlü önbellek/özet tablo.

### F-455 README'nin görüntüleyici bölümü gösterilen uygulama listesini eksik veriyor

Önem: **Düşük** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-9`
- Dosyalar: README.md (Database viewer, "Tables are not listed one by one"), config/database.py:10-21
- Açıklama: README `farm, inventory, knowledge, messaging, reports, tasks, core, auth` sayıyor; gerçek yapılandırma ayrıca `hr`, `experiments` ve `monitoring` bölümlerini içerir. Dokümantasyon-kod tutarsızlığı (HR kişisel verilerinin görüntüleyicide göründüğünü okuyan biri README'den çıkaramaz).
- Kanıt: config/database.py:10-21 on bölüm; README'de sekiz uygulama.
- Öneri: README'yi güncelle (HR tablolarının ve maskeli HR sütunlarının listesini ekle).

### F-456 Otomatik onaylanan izinler çalışanın planlı vardiyalarını bildirmiyor / değiştirmiyor

Önem: **Düşük** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-11`
- Dosyalar: `hr/forms/leave.py:101-104`, `hr/views.py:119-131`, `hr/services.py` (`decide_leave`)
- Açıklama: Onay gerektiren izinde onay penceresi `read.leave_impact` ile planlı vardiyaları listeler. `needs_approval=False` olan türde talep, form içinde `status=APPROVED`, `decided_at=now` ile doğrudan yaratılır; `decided_by` boş kalır ve izin gününe denk gelen vardiya planları ne listelenir ne uyarı üretir. Çalışan hem izinli hem planlı görünür. Ayrıca `after_save` tarafında denetim kaydı "oluşturuldu" der ama onay izi (kim onayladı) yoktur.
- Kanıt: `self.instance.status = LeaveStatus.APPROVED; self.instance.decided_at = timezone.now()` (satır 102-103); `decide_leave` yolunu kullanmıyor.
- Öneri: Otomatik onayı `services` içinde tek yoldan yapın, çakışan vardiyaları aynı şekilde bildirin.

### F-457 Silme planı ile uygulama arasında alt kayıt eklenmesi kilitlenmiyor (yetim kayıt)

Önem: **Düşük** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-6`
- Dosyalar: `core/crud.py:767-790`, `core/softdelete.py:98-171`, `core/softdelete.py:174-187`
- Açıklama: `DeleteView.post` yalnızca silinen kaydı kilitler (`select_for_update(of=('self',))`). `plan_delete` çocukları kilitsiz okur; `CreateView` ise FK hedefini (örn. üst birim, site) kilitlemez. Silme transaction'ı sürerken başka biri o üst kayda bağlı yeni bir canlı kayıt eklerse (form seçenekleri yarış öncesi canlıydı), plan bunu görmez; sonuçta silinmiş (soft) bir üst kaydı gösteren canlı alt kayıt oluşur. Ayrıca `execute` çocuklara `record.soft_delete(user)` ile tam `save()` yapar; çocuk kayıtlar kilitli olmadığından aynı anda düzenlenen çocuğun değişikliği ezilebilir (sürüm artar ama alanlar eski değerlerle yazılır).
- Kanıt: `_collect` içinde `list(model.objects.filter({link: obj}))` kilitsiz; `execute` içinde `record.soft_delete(user)` -> `self.save()` (`core/models.py:52-58`).
- Öneri: Plan çocuklarını `select_for_update` ile alın veya silmede `blockers` kontrolünü aynı transaction'da yeniden yapın; `soft_delete`'i `update_fields` ile sınırlayın.

### F-458 `align_placements` yalnızca bekleyen izinleri iptal eder; işten ayrılış tarihini aşan onaylı izin/yoklama dokunulmaz, tarih geri alınınca kesilen yerleşimler geri gelmez

Önem: **Düşük** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-13`
- Dosyalar: hr/services.py:112-138, hr/resources/employee.py:90-96, hr/services.py:91-109
- Açıklama: `left_on` verilince `Posting` ve `ShiftAssignment` (day > left_on) silinir/kısalır; `LeaveRequest` için yalnızca `PENDING` ve `first_day > left_on` iptal edilir. `left_on`'u aşan onaylı izin ve `left_on` sonrası yoklama/`left_on`'u kesen bekleyen izin aynen kalır. Çalışan `left_on` sonradan temizlenirse (yanlış girildiyse) silinen/kesilen yerleşimler ve vardiya planları otomatik geri gelmez (restore ayrı ve elle). Etkisi raporlama tutarsızlığı.
- Kanıt: `LeaveRequest.objects.filter(employee=employee, status=LeaveStatus.PENDING, first_day__gt=employee.left_on)` (services.py:131).
- Öneri: Kuralı belgeleyip tutarlı hale getir (onaylı izinleri de uyar/işaretle), `left_on` geri alma akışı için uyarı ekle.

### F-459 Belge dosyası yüklemesi işlem geri alınınca depoda yetim kalır

Önem: **Düşük** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-15`
- Dosyalar: knowledge/models/document.py:215-241
- Açıklama: `Document.save` yeni PDF'i `super().save` sırasında depoya yazar; yalnızca eski dosyanın silinmesi `transaction.on_commit` ile yapılır. `UpdateView` işlemi geri alınırsa (örn. sonraki bir hata, `audit` hatası) yeni yazılan dosya silinmez; ayrıca eski dosya doğru biçimde korunur. Yetim dosya birikir. `pages.all().delete()` + `bulk_create` ise işlem içinde (atomik) olduğundan tutarlıdır.
- Kanıt: `transaction.on_commit(partial(self.file.storage.delete, stored))` yalnızca `stored` için (document.py:241).
- Öneri: Yeni dosya için `transaction.on_rollback` benzeri temizlik (`on_commit` ile başarısızlık denetimi) veya yetim dosya süpürücüsü.

### F-460 Migrasyon geri dönüşü (rollback) bazı veri dönüşümlerinde kayıplı veya engelli

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-13`
- Dosyalar: farm/migrations/0022_purging_degree_days.py:18-31,89, farm/migrations/0021_medicine_withdrawals.py, farm/migrations/0019_water_points.py:186-197, farm/migrations/0023_reports_fields.py:45,91, hr/migrations/0003_scheduling.py:120, farm/migrations/0004_production_departments.py:43
- Açıklama: Birçok RunPython geri yönü `noop`'tur (0023, 0007, 0004, hr/0003); veri geri dönüşte yeniden üretilmez. 0022 geri dönüşte `IrreversibleError` ile bilinçli reddeder (iyi), 0019 ve 0021 gerçek bir geri yön yazmış. Monitoring 0004 README:719 "a rollback loses nothing" iddiası var; bu kontrol edilmedi. Sonuç: şema geri alma güvenilir bir felaket kurtarma yolu değildir; tek gerçek yol yedektir ve bu da 12-1'e bağlıdır.
- Kanıt: `RunPython(provenances, migrations.RunPython.noop)` vb.
- Öneri: Yıkıcı migrasyon öncesi zorunlu yedek adımı ekleyin (deploy runbook).

### F-461 Donmuş (filed) rapor trigger'ları geri yükleme/veri yükleme sırasında engel olabilir ve yönetici düzeltme yolu yok

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-14`
- Dosyalar: reports/migrations/0002_filed_reports_frozen.py, reports/models.py:162-163, monitoring/migrations/0002_card_templates.py (README.md:707-711)
- Açıklama: Gönderilmiş raporlar, snapshot'lar ve audit_log için UPDATE/DELETE trigger'ları var. Bu, `pg_restore --clean`, `TRUNCATE` dışı yeniden yükleme veya satır bazlı veri onarımı yaparken engel çıkarır ve yedekten tek satır kurtarma işlemi için trigger'ların devre dışı bırakılması gerekir. Bu prosedür belgesiz. (Tam veri yükleme için `session_replication_role = replica` gerekebilir; denenmedi.) Olumlu yan: donmuş rapor korumaları veri bütünlüğü açısından güçlüdür.
- Kanıt: `RAISE EXCEPTION 'regulatory report % was filed: it is never deleted'`.
- Öneri: Geri yükleme runbook'unda trigger ve `session_replication_role` yönetimi sırasını belirtin.

### F-462 Üst düzey geri yükleme kontrolü: restore() yalnızca doğrudan FK ebeveynlerini ve full_clean'i kontrol eder

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-15`
- Dosyalar: core/softdelete.py:185-203
- Açıklama: `restore` kaydın kendi FK'larında silinmiş hedef olup olmadığına bakar; fakat `delete_blockers()`'a eşdeğer bir "geri getirme engeli" yok, M2M bağlı silinmiş kayıtlar (ör. ekipmanın silinmiş sistemleri) kontrol edilmez, ve geri getirilen kaydın model düzeyindeki iş kuralları (ör. kayıt kapasite, kodun başka kayıtta alınması dışında) `full_clean` kapsamıyla sınırlıdır. Ayrıca `restore` içinde `select_for_update` yok; eşzamanlı restore ve düzenleme yarışabilir (version artırılıyor ama karşılaştırma yok).
- Kanıt: `record.version += 1`, `record.full_clean()`, `record.save()`; sürüm karşılaştırması yok.
- Öneri: Restore'da satır kilidi ve `restore_blockers()` kancası ekleyin.

### F-463 AuditLog yalnızca DB trigger'ı ile korunuyor; DB yedeği olmadan log kendisi tek noktadır ve süresiz büyür

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-8`
- Dosyalar: core/migrations/0003_audit_log_append_only.py, core/models.py:81-125
- Açıklama: Trigger UPDATE/DELETE'i engeller (iyi), fakat tablo tüm silmeleri engellediği için arşivleme/saklama süresi (retention) politikası uygulanamaz; trigger kaldırılmadan satır budanamaz. Log tablosu hypertable değildir ve bölümlenmemiştir. Log ayrıca ana veritabanıyla aynı volume'de olduğundan yedek yoksa "değişmez" olması felakette bir koruma sağlamaz. Süper kullanıcı trigger'ı kaldırabilir (migration geri alma da bunu yapar: reverse_sql=DROP).
- Kanıt: `CREATE TRIGGER ... BEFORE UPDATE OR DELETE ON audit_log`; `reverse_sql=DROP`; AuditLog için `create_hypertable` yok.
- Öneri: Log'u ayrı yere akıtın (WAL/dış arşiv), saklama/arşiv stratejisi belirleyin (örn. bölümleme veya ayrı rol ile arşiv işlemi).

### F-464 Görev "planlı görev" üretimi (`materialise`) GET okumasında log yazıyor ve `system` adı gerçek bir kullanıcıyla çakışabilir

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-10`
- Dosyalar: tasks/services.py:211-254, core/audit.py:147-158, core/forms.py:92
- Açıklama: `audit.record(None, ...)` kullanıcı yokken `user_name='system'` yazar. Kullanıcı adı alanında `system` yasak değil; böyle bir kullanıcı oluşturulursa gerçek kullanıcı eylemleri ile sistem eylemleri log'da ayırt edilemez (`user` FK'si `NULL` olduğu için `user_id` ile ayrılabilir, ama arayüz `user_name` filtresi kullanır: `entries.filter(user_name=filters['user'])`). `materialise_due` görev sayfalarını okurken çalıştığından, bir GET isteği yazma ve audit üretir.
- Kanıt: `user_name=user.get_username() if user and user.is_authenticated else 'system'` (audit.py:149); `entries.filter(user_name=filters['user'])` (views.py:44).
- Öneri: Sistem satırlarını `user_name` yerine ayrı bir işaretle ayırt et (ör. `user IS NULL` filtresi) ve `system` kullanıcı adını rezerve et.

### F-465 Erişim kısıtı (`audit.restrict`) kayıt sayfası geçmişinde ve veritabanı görüntüleyicide uygulanmıyor; tür adı karakter dizisi eşlemesine bağlı

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-11`
- Dosyalar: core/crud.py:651-653, core/audit.py:25-43, hr/apps.py:9-14, core/views.py:38, core/dbview.py:34
- Açıklama: Etkinlik logu listesi `audit.readable(user)` ile kısıtlı ama kayıt sayfasındaki "History" sekmesi `AuditLog.objects.filter(entity_type=..., entity_id=...)` ile doğrudan okuyor; korumayı yalnızca sayfaya erişimin kendisi (ekip kapsamı) sağlıyor (hr/apps.py yorumu "which the team scope already guards"). `core.browse_database` izni olanlar `audit_log` tablosunu görüntüleyicide tüm satırlarıyla (HR dahil) görür (`audit_log` DB görüntüleyicide listeleniyor). Ayrıca kısıt, İngilizce `verbose_name` metinlerine ("plan", "placement", ...) göre eşleşir; model adı değişirse veya aynı ada sahip başka tür eklenirse ("plan" genel bir sözcük) kısıt sessizce bozulur veya yanlış gizler.
- Kanıt: `history = AuditLog.objects.filter(entity_type=r.entity_type(), entity_id=str(obj.pk))[:20]` (crud.py:652); `_restricted[entity_type] = perm` (audit.py:31).
- Öneri: Geçmiş sorgusunu `audit.readable(request.user, ...)` üzerinden geçir, kısıtı model sınıfına (content type) bağla, görüntüleyicide audit_log HR satırlarını gizle veya izni kısıtla.

### F-466 `private` alanlar için kısaltılmış (32 bit) ve `SECRET_KEY`'e bağlı HMAC özeti

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-13`
- Dosyalar: core/audit.py:95-100
- Açıklama: Kişisel metin yerine `hmac(SECRET_KEY, text)[:8]` hex saklanıyor. 8 hex = 32 bit: iki farklı metnin aynı özete düşme ihtimali (~1/4 milyar) "değişiklik yok" gibi görünmesine yol açar (düşük risk). `SECRET_KEY` döndürülünce bütün eski özetler yeni değerle farklılaşır, yani anahtar rotasyonundan sonra ilk kaydetmede sahte "değişti" satırı oluşur. Anahtarı bilen biri kısa metinleri kaba kuvvetle sınayabilir.
- Kanıt: `hmac.new(settings.SECRET_KEY.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:8]` (audit.py:98-99).
- Öneri: Ayrı bir `AUDIT_PRIVATE_KEY` kullan, rotasyonu belgele; özeti uzat veya sürüm numarası ekle.

### F-467 `entity_type` sütunu 50 karakterle sınırlı ama `label`'ın aksine `bounded()` uygulanmıyor

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-15`
- Dosyalar: core/models.py:180, core/audit.py:118-124, core/audit.py:151-155
- Açıklama: `entity_label` taşmasını önlemek için `bounded()` var (EXP-01 hatası sonrası), fakat `entity_type` (`max_length=50`) ve `user_name` (150) aynı korumayı almıyor. Uzun bir `Resource.name`/`verbose_name` (veya İngilizce kaynak metin) eklenirse `DataError` fırlar ve loglanan işlemin kendisi başarısız olur. Bugün mevcut adlar 50 altında (inceleme sırasında en uzunu ~26 karakter), yani yalnızca gelecekteki bir regresyon riski; bunu yakalayan test de yok.
- Kanıt: `entity_type = models.CharField(max_length=50, db_index=True)` (models.py:180); `entity_type=english(entity_type or entity_type_of(type(instance)))` kesme yok (audit.py:151).
- Öneri: `entity_type` için de `bounded` veya sistem kontrolü (`check`) ile tüm model/Resource adlarının ≤50 olduğunu doğrula.

### F-468 Etkinlik logu sayfası büyüyen tabloda pahalı sorgular çalıştırır; saklama/arşiv politikası yok

Önem: **Düşük** | Güven: orta | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-17`
- Dosyalar: core/views.py:35-72, core/models.py:189-197
- Açıklama: Her istekte `Paginator` `COUNT(*)`, `readable.order_by('user_name').values_list(...).distinct()` ve `entity_type` için `DISTINCT` çalıştırır; `user_name` üzerinde indeks yok, `entity_label__icontains` indeksiz tarama yapar. Tablo yalnızca büyür (silme yasak, bölümleme/saklama yok), yani log büyüdükçe sayfa yavaşlar. Tabloda TimescaleDB hypertable/bölümleme kullanılmıyor.
- Kanıt: `'users': readable.order_by('user_name').values_list('user_name', flat=True).distinct()` (views.py:70-71); indeksler yalnızca `created_at`, `entity_type`, `(entity_type, entity_id)`, kısmi critical (models.py:171,180,192-197).
- Öneri: Kullanıcı/tür listesini önbellekle veya ayrı arama tablosundan al, `user_name` için indeks ve arama için `pg_trgm` ekle, saklama/arşiv politikası belirle.

### F-469 Test kapsamı: bazı elle yazılmış migration'ların hiç testi yok

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-11`
- Dosyalar: farm/migrations/0004_production_departments.py, farm/migrations/0007_equipment_types.py, farm/migrations/0017_handling_rules.py, farm/migrations/0023_reports_fields.py, reports/migrations/0009_open_questions_listed.py, hr/migrations/0003_scheduling.py
- Açıklama: `MigrationExecutor` kullanan testler yalnızca monitoring (2), hr/test_hardening, experiments, reports/test_notices (0005), farm 0019/0021/0022 için var. 0023 (`organisation_numbers` regex dönüşümü, geri dönüşsüz), 0004 (RenameModel + RunPython), 0017 (`write`/`remove`), reports 0009 için migration seviyesinde test bulunamadı. `makemigrations --check` yalnızca core/tests.py:108 ve monitoring/tests/test_boards.py:264'te (monitoring'e özel).
- Kanıt: `grep -l MigrationExecutor` çıktısı 8 dosya; 0023 için `organisation_numbers` referansı testlerde yok.
- Öneri: 0023 için veri dönüşüm testi (rakamlı/NO...MVA/anlamsız giriş), 0017 reverse testi.

### F-470 reports 0009 / farm 0017 / farm 0007 seed geri alma verilerini kullanıcı düzenlemeleri nedeniyle eksik siliyor veya fazla siliyor

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-14`
- Dosyalar: reports/migrations/0009_open_questions_listed.py:49-52, farm/migrations/0017_handling_rules.py:49-52, farm/migrations/0007_equipment_types.py:15
- Açıklama: reports 0009 `remove` kodu `Q1..Q12`'ye sahip her satırı siliyor; kullanıcı bu sorulara cevap girdiyse (status/answer) cevap kaybolur. farm 0017 `remove` yalnızca not metni değişmemiş satırları siliyor (kullanıcı düzenlediyse kalır, tutarlı). farm 0007 reverse noop: tipler kalır. Üç seed için üç farklı geri alma stratejisi.
- Kanıt: 0009:50-52 `filter(code__in=...).delete()`; 0017:49-52 `note__in=...`, `created_by__isnull=True`.
- Öneri: Seed geri almasını tek ilkeye bağlamak (yalnızca dokunulmamış satırı sil).

### F-471 farm 0019 tek transaction'da bütün sample'ları güncelliyor; büyük hacimde uzun kilit

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-8`
- Dosyalar: farm/migrations/0019_water_points.py:36-52,186-205
- Açıklama: İleri yön, tüm birim/sistemler için nokta oluşturup (bulk_create) `water_measurements` hypertable'ında tüm satırları tek `UPDATE ... Subquery` ile güncelliyor, ardından NOT NULL AlterField, kolon/index düşürme; hepsi bir transaction ve tablo üzerinde ACCESS EXCLUSIVE. Docstring "tek transaction, hata veritabanını olduğu gibi bırakır" diyor (olumlu), ancak kilit süresi/dağıtım penceresi hakkında yönerge yok. Ayrıca `template_for(owner_type, owner.kind)` bilinmeyen birim türünde `KeyError` verir (DEFAULTS yalnızca tank/pond/cage); şu an `Tank.kind` seçenekleri bunlarla sınırlı olduğundan düşük.
- Kanıt: 0019:36-52 (create_points_and_move_samples), points.py:21-27 DEFAULTS.
- Öneri: Prod'da bakım penceresi notu; büyük hacim için parçalı UPDATE.

### F-472 `uq_tasks_series_occurrence` soft-delete'e duyarsız

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-13`
- Dosyalar: tasks/models.py:~397-399
- Açıklama: Diğer tüm unique kısıtlar `is_deleted=False` koşullu iken (series, occurrence_date) koşulsuz; silinmiş (soft-deleted) bir görev aynı günün yeniden üretilmesini sonsuza kadar engeller. Kasıtlı olabilir (yeniden üretimi önlemek), ancak yorumla belirtilmemiş.
- Kanıt: `UniqueConstraint(fields=['series','occurrence_date'], condition=Q(series__isnull=False))`.
- Öneri: Niyeti yoruma yaz veya restore akışında çakışmayı test et.

### F-473 Çok-sütunlu null'lanabilir FK ile polimorfik bağ (tasks, monitoring, sampling points)

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-14`
- Dosyalar: tasks/models.py:337-342, monitoring/models.py (CardTemplateAssignment), farm/migrations/0019_water_points.py
- Açıklama: Yer bilgisi 5 ayrı nullable FK + "tek yer" CHECK ile tutuluyor (site, bölüm, sistem, birim, ekipman). Bütünlük DB'de güvenceli ama sütun sayısı arttıkça şema ve kısıt ifadeleri çoğalıyor; yeni yer türü eklemek migrasyon + CHECK + unique'leri değiştirmeyi gerektirir.
- Kanıt: `chk_tasks_one_place`, `chk_monitor_card_assignments_one_scope`, `chk_water_sampling_points_one_owner`.
- Öneri: Bilgilendirme; ortak "place" tablosu düşünülebilir.

### F-474 `audit.revision()` 5 dakikalık `LATE_COMMIT` penceresi varsayımına dayanıyor

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-11`
- Dosyalar: core/audit.py:125-141, core/models.py:171
- Açıklama: `created_at` satır oluşturulurken (`auto_now_add`, uygulama saati) damgalanır, görünürlük commit'te başlar. 5 dakikadan uzun süren bir işlem ya da kilit beklemesi, geç commit olan satırı belirteçte görünmez kılar; sayfa "değişiklik yok" sanabilir.
- Kanıt: `LATE_COMMIT = timedelta(minutes=5)`; `created_at__gte=newest - LATE_COMMIT`.
- Öneri: Pencereyi belgele veya sıra numarası (sequence/xmin tabanlı) bir belirteç kullan.

### F-475 `record_feeding` yem satırını kilitlemiyor; yem pasifleştirmesiyle yarışır

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-12`
- Dosyalar: farm/feeding/services.py:46-56
- Açıklama: Tank kilitleniyor ama `Feed.all_objects.get(pk=...)` kilitsiz. Yem aynı anda "active" dışı yapılırsa yeni besleme pasif yemle kaydedilebilir (küçük tutarsızlık; stok servislerindeki "kilit sonrası doğrula" desenine uymuyor).
- Kanıt: `feed = Feed.all_objects.get(pk=feed.pk)`; `if feed.is_deleted or feed.status != Feed.Status.ACTIVE`.
- Öneri: `select_for_update(of=('self',))` kullan.

### F-476 `latest()` numuneleri yalnızca `id` ile getirir; zaman filtresi yok.

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-3`
- Dosyalar: farm/water/read.py:~300 (`latest`, `samples = WaterMeasurement.objects.select_related(...).in_bulk(ids)`)
- Açıklama: Hypertable'da PK `(id, measured_at)` olduğundan chunk exclusion çalışmaz, her chunk'ta indeks araması yapılır.
- Kanıt: `_newest_ids` zaten `measured_at__gte=since` ile 30 günlük pencere bulur ama `in_bulk(ids)` bu bilgiyi kullanmaz; model docstring'i (farm/models/water.py:88) bunu "cheap at a farm's volume" diye kabul eder. Her izleme kartı/pano isteğinde çalışır.
- Öneri: `.filter(measured_at__gte=since)` eklenmeli (in_bulk yerine filter + dict).

### F-477 DST belirsiz/olmayan yerel saatler doğrulanmıyor.

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-6`
- Dosyalar: farm/forms/water.py:209, 308
- Açıklama: `timezone.make_aware(moment, zone_of(...))` ZoneInfo ile hata vermez; ilkbahar geçişinde olmayan saat (örn. 02:30) sessizce bir saat kaydırılır, sonbaharda belirsiz saat `fold=0` (ilk oluşum) alınır. Numune zamanı dakika duyarlıklı serilerde 1 saat hatalı saklanabilir.
- Öneri: `zone.utcoffset` / `fold` ile gap/overlap tespiti ve kullanıcıya sorma veya doğrulama hatası.

### F-478 Günlük sıcaklık ortalaması örneklerin zaman ağırlıksız aritmetik ortalamasıdır.

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-7`
- Dosyalar: farm/water/degree_days.py:50-62, 67-70
- Açıklama: Bir gün içinde sabah turunda çok, gün boyu az numune varsa ortalama sapar; derece-gün (ilaç arınma/ açlık) hesapları buna dayanır.
- Kanıt: `sum(found)/len(found)`. Docstring bunu "daily mean of the live samples" diye tanımlar, yani tasarım kararı; yine de sıcaklık doğruluğu açısından kayda geçirilir.
- Öneri: Karar belgelensin; sensör gelirse zaman ağırlıklı ortalama/ saatlik aggregate kullanılsın.

### F-479 `Context` tuzluluk serisini `since - WINDOW`'dan şimdiye kadar sınırsız çeker.

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-8`
- Dosyalar: farm/water/read.py:~250-252 (`Context.__init__`), farm/water/read.py `Series.__init__`
- Açıklama: `history()` eski bir dönem için çağrılınca `Series(..., since - WINDOW)` `until` olmadan o günden bugüne tüm tuzluluk satırlarını belleğe alır; `latest()` ise her istekte 60 günlük pencere okur.
- Kanıt: `until=None` varsayılanı; `history` -> `Context(points, min(sample.measured_at))`.
- Öneri: `until` olarak `max(sample.measured_at)` geçilmeli.

### F-480 Seri okumaları tüm satırları Python listelerine yükler (aggregate DB'de yapılmıyor).

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-9`
- Dosyalar: farm/water/degree_days.py:50-62, farm/water/read.py (`Series`)
- Açıklama: `Temperatures` bir partinin tüm geçmişi (örn. 800 gün) için ham numuneleri okuyup günlük ortalamayı Python'da hesaplar; `time_bucket`/GROUP BY yok. Mevcut elle veri hacminde kabul edilebilir, sensör hacminde değil.
- Öneri: Günlük ortalamayı SQL'de (`date_trunc` / `time_bucket` site zone'una göre) hesaplayın.

### F-481 Rapor `scope` parmak izi: ledger dışı kaynaklar (su örnekleri) ve doğrulama komutu eksik

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-10`
- Dosyalar: reports/compute/biomass.py:109-125; reports/compute/common.py:96-107; reports/integrity.py:30-48
- Açıklama: Biyokütle projeksiyonu su sıcaklıklarını okuyor ama parmak izi bunları içermiyor (kod yorumu da kabul ediyor). `check_reports` dosyalanmış raporun dayandığı kaynak sonradan void edilmiş mi (örn. kaçış operasyonu void) bakmıyor; yalnızca site eşleşmesi ve hash. Bildirilen kayıt ile mevcut defter ayrışabilir ve tarayıcı bunu raporlamaz.
- Kanıt: biyokütle `scope()` docstring'i "a past sample voided later is shown by the page's own comparison, not by this fingerprint".
- Öneri: `check_reports`'a "dosyalanmış rapor kaynağının parmak izi şimdiki ile aynı mı" bilgi satırı.

### F-482 `_number` ondalık metni float'a çeviriyor (JSON API çıktısı)

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-11`
- Dosyalar: reports/exports.py:31-38
- Açıklama: İçerik "tam karşılaştırma için metin" ondalık olarak donduruluyor (common.text), fakat API JSON'unda `float(text)` ile sayıya çevriliyor; çok büyük değer/çok ondalıkta ikili kesirli sapma ve `int(value)==value` ayrımı (12.0 -> 12) tür tutarsızlığı doğurabilir. Mevcut alan genişlikleri için pratikte güvenli.
- Kanıt: `value = float(text); return int(value) if value == int(value) else value`.
- Öneri: `Decimal` ile JSON'a `Decimal` kodlayıcı veya sabit ondalık sayı.

### F-483 Besleme bandı "boşluksuz" kuralı yalnızca kaydetme anında; DB yalnızca çakışmayı engelliyor

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-13`
- Dosyalar: farm/models/feeding_protocol.py:145-147, 177-185
- Açıklama: Docstring "bantlar boşluksuz buluşur (kaydedilirken kontrol)" ve "asla çakışmaz (veritabanı)" diyor; boşluk kontrolü DB'de yok. Bir boşluktaki ağırlık için ration bulunamazsa besleme/öngörü sessizce boş dönebilir. (Okuma yolunun boşluğu nasıl ele aldığı incelenmedi.)
- Kanıt: `excl_feeding_protocol_bands_overlap` tek DB kuralı; `uq_feeding_protocol_bands_start`.
- Öneri: Okuma yolunda boşluk testi veya bütünlük tarayıcısına kural.

### F-484 Rapor içeriğinde yuvarlama: parti bazında yuvarlanan değerlerin toplamı birim/site toplamıyla uyuşmayabilir

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-6`
- Dosyalar: reports/compute/biomass.py:76, 113-115; reports/compute/common.py:36-51
- Açıklama: Biyokütle her parti için `text(grams/1000, 1)` ile yarım-yukarı 0,1 kg'a yuvarlanıp ayrı satır olarak dosyalanıyor; birim/site toplamı raporu okuyan taraf tarafından satırlar toplanarak bulunursa gerçek toplamdan sapabilir. Hacim `water_volume_m3 or volume_m3` 3 ondalıktan 1'e yuvarlanıyor (`text(..., 1)`), oysa kapasite/yoğunluk 3 ondalıklı hacimle hesaplanıyor. Kayıp kg'ı `line.kilos` (ölçülen veya defter) karışık kaynaktan.
- Kanıt: `'biomass_kg': text(figure['grams'] / 1000, 1)` ve `'volume_m3': text(unit.water_volume_m3 or unit.volume_m3, 1)`.
- Öneri: Toplamı tam hassasiyetle hesaplayıp tek yuvarlama; hacimde `or` yerine `is not None` (0 hacmi yanlışlıkla sonraki alana düşmesin).

### F-485 `water_volume_m3 or volume_m3` iki yerde, `Coalesce(water_depth, depth)` üçüncü yerde: aynı kural üç kez yazılmış

Önem: **Düşük** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-7`
- Dosyalar: farm/stock/read.py:267-269; reports/compute/biomass.py:76; farm/models/tank.py:380-384
- Açıklama: satırlar. "Etkin hacim" kuralı DB'de `Coalesce(F('water_depth'), F('depth'))` ile (max_biomass), Python'da `or` ile (yoğunluk, rapor) ayrı yazılmış. `or` Decimal('0.000') değerini de "yok" sayar (örn. su derinliği 0 girilirse yoğunluk toplam hacme göre hesaplanır, max_biomass ise 0 hacme göre 0 olur) - iki gösterge birbirini tutmaz. water_depth için alt sınır CHECK'i (>0) var mı doğrulanmadı.
- Kanıt: bkz.
- Öneri: Tek yerde `effective_volume_m3` GeneratedField veya özellik; `is not None` kullan.

### F-486 Protokol emeklilik kontrolü şirket saatini, atama kuralları ünite sitesinin saatini kullanıyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-14`
- Dosyalar: farm/models/feeding_protocol.py:131-136, farm/models/feeding_protocol.py:318-326, farm/feeding/assignments.py:83
- Açıklama: `FeedingProtocol.clean` "bugün" için `zone_of(None)` (şirket saati) kullanıyor; atama satırlarının `started()`/`today()` ve `end()` fonksiyonları ünite sitesinin saat dilimini kullanıyor. Farklı saat dilimlerindeki sitelerde, gece yarısı civarında bir protokol "aktif atama yok" diye emekliye alınabilir ya da tam tersi engellenir.
- Kanıt: `today = timezone.localdate(timezone=zone_of(None))` (feeding_protocol.py:133) vs `local_today(row.unit)` (assignments.py:83).
- Öneri: Emeklilik kontrolünü her atamanın kendi `today()` değeriyle yapın.

### F-487 Silinmiş bir besleme protokolü geri yüklenince, bu arada silinen yeme bağlı bantlar geri geliyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-8`
- Dosyalar: farm/models/feed.py:230-240, core/softdelete.py:189-205, farm/models/feeding_protocol.py (`ProtocolBand.feed` PROTECT)
- Açıklama: `Feed.delete_blockers` yalnızca `protocol__is_deleted=False` olan protokollerin bantlarını sayıyor. Soft-deleted bir protokolün bandındaki yem silinebilir. `softdelete.restore` ise yalnızca kaydın kendi somut FK'lerini (species) kontrol ediyor; bantlar `AuditedModel` olmadığı için kontrol edilmiyor. Geri yüklenen protokol silinmiş bir yeme bağlı bantlarla "aktif" kalır; `read.tables` `select_related('feed')` ile silinmiş yemi okur ve board/forecast bu yemi önerir; `record_feeding` ise yalnızca aktif yem kabul ettiğinden kayıt reddedilir.
- Kanıt: `self.protocol_bands.filter(protocol__is_deleted=False)` (feed.py:234); `restore` döngüsü yalnızca `record._meta.concrete_fields` üzerinde (softdelete.py:194-198).
- Öneri: Protokol için geri yükleme kontrolü (bantların yemlerinin canlı olması) ekleyin veya yem silmede silinmiş protokol bantlarını da engelleyici sayın.

### F-488 Atama oluşturma ve protokol emeklilik kontrolleri protokol satırını kilitlemiyor; tablo kaydıyla yarışabilir

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-9`
- Dosyalar: farm/feeding/assignments.py:31-67, farm/feeding/protocols.py:49-70, farm/models/feeding_protocol.py:128-136
- Açıklama: `save_table` protokolü `select_for_update` ile kilitleyip `is_assigned()` kontrolü yapıyor; ancak atama yazan yol (`rows()` + `save()`) protokol satırını kilitlemiyor, yalnızca `full_clean` içinde durumunu (ACTIVE) okuyor. READ COMMITTED altında `save_table` `is_assigned()=False` görüp bantları silip yeniden yazarken eşzamanlı bir atama commit edebilir; "atanmış tablo sabittir" kuralı (Q3) bozulur. Aynı biçimde `FeedingProtocol.clean` içindeki "bugün veya sonrası için atama var mı" emeklilik kontrolü kilitsiz.
- Kanıt: `protocol = FeedingProtocol.objects.select_for_update().get(pk=protocol.pk)` yalnızca protocols.py:53'te; assignments.py:57-67 `save()` yalnızca `transaction.atomic()` ve satır kaydı yapar.
- Öneri: Atama kaydında da protokolü kilitleyin ve `is_assigned/status` kontrolünü kilit altında tekrarlayın.

### F-489 31 günden eski tedavi iptal edilemiyor; arınma sürüyorken yanlış kayıt silinemez

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-6`
- Dosyalar: `farm/stock/services.py:498-512`, `farm/health/services.py:245-252`, `farm/templatetags/health.py:68-72`,
- Açıklama: `config/settings.py:217` `voided` kaydı `entry.date` (tedavide `start_date`) ile `site_earliest` karşılaştırır; 31 günden eski tedavi "Operations older than 31 days cannot be voided" ile reddedilir. Derece-gün cinsinden arınma süresi soğuk suda haftalarca sürebilir ve son gün planlanan 28 güne kadar ileri olabilir; bu durumda yanlış girilmiş ama hâlâ hasadı engelleyen bir tedavi iptal edilemez. `change_last_day` de hem eski hem yeni son gün pencereden eskiyse reddeder.
- Kanıt: `services.py:509-512`, `templatetags/health.py:72` `record.date >= earliest(unit)`.
- Öneri: Arınması hâlâ süren tedavilerde pencere kontrolünü bitiş gününe göre yap veya yetkili bir istisna yolu tanımla.

### F-490 Canlı balık teslimi (delivery) sırasında arınma uyarısı yok; bilgi müşteriye aktarılmıyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-7`
- Dosyalar: `farm/handling/check.py:101-103,201-206`, `farm/stock/services.py:728-739`, `farm/models/handling.py:205-210`,
- Açıklama: `README.md:519-520` Arınma uyarısı yalnızca `HARVEST` için çalışır; `DELIVERY` (şirket dışına canlı balık, "smolt satışı" dahil) yalnızca oruç denetimi alır. Belgelenmiş bir tasarım kararı, ancak teslim edilen balığın alıcı tarafından yiyecek amaçlı kesilebileceği ve arınma süresindeki partinin sistemden çıkıp izlenemez hale geldiği durumda hiçbir uyarı/not yok.
- Kanıt: `check.py:103` `WITHDRAWAL_KIND = HandlingKind.HARVEST`; `check.py:202-203` yalnızca bu tür için `_withdrawal`.
- Öneri: Teslimde arınma altındaki partiler için en azından bilgilendirici not (uyarı değil) göster ve teslim kaydına arınma bitiş tarihini yaz.

### F-491 Sağlık olayı kuralları yalnızca formda; servis kapalı veya ileri tarihli olayı kabul ediyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-9`
- Dosyalar: `farm/health/services.py:119-126`, `farm/forms/health.py:269-273`, `farm/models/health.py:460-531`
- Açıklama: Tedavi formu yalnızca açık (`closed_on` boş) olayları listeler, ancak `_check_event` kapalı olayı reddetmez (yalnızca silinmiş, site ve tarih). Doğrudan servis çağrısı veya eski form ile kapalı olaya tedavi bağlanabilir. Ayrıca `_check_event` olay tarihi <= tedavi başlangıcı kuralını yalnızca kayıt anında uygular; olay sonradan düzenlenip tarihi ileri alınırsa kural sessizce bozulur. `HealthEvent.units` için modelde "birim olayın sitesine ait" kuralı yok, yalnızca formun queryset'i kısıtlar.
- Kanıt: `services.py:124` yalnızca `event.date > day`; `forms/health.py:272` `closed_on__isnull=True`.
- Öneri: Kural tek yerde (servis) toplansın; olay düzenlemesi bağlı tedaviler varken tarihi ileri almayı reddetsin.

### F-492 Stok okumaları her istekte tüm geçmiş defteri katlıyor (ölçeklenme riski)

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-14`
- Dosyalar: farm/stock/read.py:33-48,59-62,327-335, farm/stock/services.py:294-340, farm/harvest/read.py:98-114, farm/harvest/views.py:96-120, farm/resources/harvest_plan.py:99-135
- Açıklama: `stock_of`, `share_on`, `_validate`, `moved_grams` ve harvest listesi, ilgili batch'lerin tüm satırlarını (`ledger`) belleğe alıp baştan katlar; her yazma ayrıca besleme yürüyüşünü ve sağlık kayıtlarını yeniden kurar. Harvest listesi sayfalamadan önce tüm filtrelenmiş satırlar için `moved_grams` çalıştırır. Plan listesi satır başına `check.in_force`/`check.earliest` (N+1) çağırır.
- Kanıt: read.py:33-48 `ledger` tüm satırlar; harvest/views.py:96-97 `rows = read.harvests(lines)` sonra `Paginator(rows, ...)`. - Etki: yıllar süren veri ve çok birimle yavaşlama; her stok yazımı uzar (kilit süresi artar).
- Öneri: kapanan batch'ler için kontrol noktası/önbellek, harvest listesinde sayfa bazlı hesap ve plan satırlarında toplu sorgu.

### F-493 Harvest/tartım/ölü balık ağırlıkları için makullük (plausibility) kontrolü yok

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-8`
- Dosyalar: farm/forms/stock.py:198-202,255-258,544-548, farm/harvest/read.py:31-36
- Açıklama: Harvest `measured_weight_kg` kitap ağırlığıyla veya makul adet başı ağırlıkla karşılaştırılmaz (yalnızca > 0). Fark yalnızca listede gösterilir. Benzer şekilde tartım ortalaması önceki ağırlığa/tahmine göre sınırlandırılmaz; sadece `_estimate` fark gösterir (kaydı engellemez). Besleme tarafında "gram yerine kilo" hatası için bir kontrol (FEEDING_ACK_PERCENT) varken stok tarafında yok.
- Kanıt: forms/stock.py:544-546 `min_value=Decimal('0.001')` dışında sınır yok; harvest/read.py:31-36 fark yalnızca hesaplanır. - Etki: yazım hatası (örn. 10 g yerine 10 kg) kitap biyokütlesini ve sonraki yem/projeksiyonu bozar; harvest kg'ı raporlara gider.
- Öneri: kitaba göre belirli bir sapma eşiğinde (ör. +-30%) onay isteyin (ack mekanizması zaten var).

### F-494 Ünite grafiği ve hesaplayıcı, farklı örneklerden/zamanlardan gelen "en son" değerleri tek bir su gibi birleştiriyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-10`
- Dosyalar: farm/water/read.py:24-27,393-413, farm/water/calculation.py:217-246,297-337
- Açıklama: `latest()` her parametrenin en yeni değerini ayrı ayrı alıyor (tasarım gereği, WQ-04). `chart_of()`/`offers()` sıcaklık, pH, alkalinite, tuzluluk ve TAN'ı bu bağımsız okumalardan birleştirip tek bir Deffeyes noktası olarak çiziyor; tazelik farkı büyük: sıcaklık 24 sa, pH 72 sa, alkalinite 336 sa, tuzluluk 168 sa. Kullanıcıya her girdinin yaşı gösteriliyor ancak çizilen NH₃/CO₂ sınır pH'ı farklı günlerin değerleriyle hesaplanıyor ve grafik "tutarlı bir örnek" gibi görünüyor; girdiler arasındaki maksimum zaman farkı için bir eşik/uyarı yok.
- Kanıt: `values = {name: float(found[name].value) ...}` her ad ayrı `Reading`'ten (calculation.py:310); `parameters.py` `fresh_hours` değerleri 24/72/336/168.
- Öneri: Girdiler arasında örnek zamanı farkı belirli bir eşiği (örn. 24 sa) aşıyorsa grafikte uyarı gösterin.

### F-495 pH aralıkları tutarsız: örnek 2-12, hesaplayıcı girişi/hedef 4-12, pH sınır alanları 0-14, grafik 4-12.5

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-11`
- Dosyalar: farm/water/parameters.py (ph low=2, high=12), farm/forms/water.py:413,428,435-438, farm/water/deffeyes.py:47, farm/water/calculation.py:35,297-337
- Açıklama: Bir örnek 2-12 arası pH ile kaydedilebiliyor ve `offers()` bu değeri hesaplayıcıya taşıyor; ancak hesaplayıcı formu pH alanını 4-12 ile sınırlıyor (`_measured('ph', low=4)`), dolayısıyla 4 altı bir pH (asit şoku, tam kritik durum) için hesaplayıcı form hatası veriyor ve aynı pH, `chart_of`'ta kullanıma girerse grafik alanı (4-12.5) dışında kalıyor. pH limit sınırı alanları ise 0-14 kabul ediyor (hesaplayıcıda), WaterLimit modelinde 2-12.
- Kanıt: `ph = _measured('ph', required=True, low=4)`; `PH_RANGE = (4.0, 12.5)`; `_parameter('ph', ..., 2, 2, 12, 72, 'acid', ...)`; `PH_FIELDS` alanları `number_field(..., 0, 14, 2)`.
- Öneri: Aralıkları tek sabitte toplayın; 4 altı pH için hesaplayıcıda "grafik bu pH'ı çizemez" gibi açık mesaj verin.

### F-496 Kart "blind" kuralı yalnızca sıcaklık ve oksijene bakıyor; bayat pH/TAN/NH₃ değeri ne alarm ne uyarı üretiyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-12`
- Dosyalar: monitoring/read.py:380-393,430-439, farm/water/parameters.py (fresh_hours), farm/water/read.py:359-369
- Açıklama: Tazelik süresi geçen her değer `STALE` olup alarm listesinden (`alerts`) düşüyor. `state_of()` yalnızca sıcaklık ve O₂ eksik/bayat ise kartı "blind" yapıyor; pH (72 sa), TAN/NO₂/TGP/tuzluluk (168 sa) bayatlayınca kart "OK" kalıyor. TAN ve nitrit ölçümü için 7 günlük "taze" süre RAS'ta toksik bir olay için çok uzun, TGP için de (hızlı değişir) 7 gün uzun görünüyor; bunlar sabit koda gömülü ve çiftlik/tür bazlı ayarlanamıyor.
- Kanıt: `_key_readings` yalnızca `parameters.TEMPERATURE` ve oksijen döndürüyor; `_parameter('tan_mg_l', ..., 168, ...)`, `_parameter('tgp_pct', ..., 168, ...)`.
- Öneri: Tazelik sürelerini yapılandırılabilir yapın (veya limitin olduğu her parametre için bayat durumda not üretin); kararı belgeleyin.

### F-497 Bar, birden çok tür/limit satırında yalnızca ilk satırı çiziyor; durum ise en kötü satıra göre

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-7`
- Dosyalar: monitoring/cards/render.py:143-170, farm/water/evaluate.py:66-77
- Açıklama: `assess()` aynı ünitedeki her tür için ayrı satır bulup en kötü durumu veriyor ve tüm satırları `reading.limits`'e koyuyor; `bar()` ise `reading.limits[0]`'ı çiziyor. Karma stoklu ünitede (somon + temizleyici balık) durum "kritik" iken bar, ilk satıra göre tamamen yeşil/OK bantlarla ve işaretçi güvenli bölgede çizilebilir; `aria-label` da yalnızca ilk satırın sınırlarını söylüyor.
- Kanıt: `limit = reading.limits[0]` (render.py:149). `found` sırası `exposures` sırasına bağlı (`read.py:286-289`), sıralama deterministik değil (tür kümesi).
- Öneri: Durumu belirleyen (en kötü) satırı çizin ya da en sıkı sınırları birleştirin; en azından `reading.limits` içinden status'ü üreten satırı seçin.

### F-498 Overview: stoğu hiç olmayan yem için "karşılanmamış besleme" görünmüyor; düşük stok yalnız lokasyon bazlı

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-13`
- Dosyalar: inventory/read.py:69-80, 205-260
- Açıklama: `folds()` yalnız var olan `InventoryItem` kayıtları üzerinde döner; item, ilk teslimat/reorder level ile yaratılıyor (`item_for`). Hiç teslimatı girilmemiş bir yem için FeedingRecord varsa uncovered besleme hiç hesaplanmaz/gösterilmez (veri sessizce kapsam dışı). Düşük stok kıyası da lokasyon bazlı (aynı sitedeki diğer lokasyondaki stok sayılmaz) ve süresi geçmiş stok "mevcut" sayılıyor (Q-S4 kararı olabilir).
- Kanıt: `_feeding([item.feed_id for item in items if item.feed_id])`; low döngüsü `held[(location.pk, item.pk)]`.
- Öneri: Beslemesi olan ama item'ı olmayan yemleri overview'da "stok kaydı yok" olarak listele; belgede kararı yaz.

### F-499 `check_inventory` bütünlük denetimi kapsam boşlukları ve hiçbir yerde zamanlanmamış

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-14`
- Dosyalar: inventory/integrity.py:295-363, inventory/management/commands/check_inventory.py
- Açıklama: Kontrol edilmeyenler: canlı satırı olan ama soft-deleted lot, aynı sayımda bir lotun iki kez geçmesi (DB unique kısmen), pasif lokasyona gelen arrival (tarihsel), lot SKT tutarlılığı, sayım satırının item/lot lokasyon ilişkisi, teslimat tedarikçisinin durumu. Ayrıca `operation.supplier` None ise (DB kısıtı engeller ama elle düzenleme senaryosu) `AttributeError` ile tüm denetim çöker. README yalnız testlerde çalıştığını söylüyor; cron/CI/deploy'da çağrı bulunamadı (grep: yalnız README ve tests/helpers.py).
- Kanıt: integrity.py:303 `operation.supplier.supplies`; repo genelinde `check_inventory` yalnız yönetim komutu ve test yardımcılarında geçiyor.
- Öneri: Eksik kuralları ekle, None-guard koy, periyodik çalıştır.

### F-500 Tamamlanan/iptal edilen görevler düzenlenebilir ve checklist'i değişebilir

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-10`
- Dosyalar: `tasks/forms.py:243-250`, `tasks/resources.py:58-72,166-180`
- Açıklama: Edit formu durumdan bağımsızdır: kapalı görevin başlık, due_date, atananları değiştirilebilir (audit'li). Tik hiç atılmamış kapalı görevin checklist'i tamamen değiştirilebilir. "Tamamlandı" kaydının tarihsel doğruluğu yalnız audit'e bağlı.
- Kanıt: `TaskForm.Meta.fields` durum alanı yok ama kapalı durum kontrolü de yok; `TaskChecklistFormSet.clean` yalnızca tik kontrolü yapar.
- Öneri: Kapalı görevi salt-okunur yap veya düzenlemeden önce reopen iste.

### F-501 `complete`/`cancel` servisleri not ve neden uzunluğunu doğrulamaz

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-14`
- Dosyalar: `tasks/services.py:117-148`, `tasks/models.py:317-325`
- Açıklama: Sınır (1000/500) yalnız `CompleteForm`/`CancelForm`'da; servis doğrudan (API/asistan) çağrılırsa PostgreSQL `DataError` (500) oluşur, `add_note` ise uzunluğu servis içinde kontrol ediyor: tutarsız.
- Kanıt: `add_note` `len(body) > MAX_LENGTH` kontrolü var; `complete`/`cancel` yok.
- Öneri: Uzunluk kontrolünü servise taşı.

### F-502 `materialise_due` "geride" ölçütü farklı saat dilimlerinde sürekli yeniden çalıştırır

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-4`
- Dosyalar: `tasks/services.py:260-262`
- Açıklama: `latest = max(clock.today) + horizon`; her seri kendi site gününe göre `generated_until = site_today + horizon` yazar. Günü daha geride olan saat dilimindeki seriler `generated_until < latest` kalır ve saatlerce her sayfa yüklemesinde kilitlenip `save` edilir.
- Kanıt: `exclude(generated_until__gte=latest)` ile `materialise` içindeki `last = today(site) + horizon` farklı gün tabanları kullanır.
- Öneri: Karşılaştırmayı serinin kendi site gününe göre yap.

### F-503 Görev "not eklendi/tik" version'ı artırmaz; edit formundaki iyimser kilit bunları yakalamaz

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-9`
- Dosyalar: `tasks/services.py:190-203`, `tasks/services.py:158-187`, `core/crud.py:725-735`
- Açıklama: `tick` ve `add_note` görevin `version`'ını artırmaz; bu yüzden aynı anda açık edit formu kaydında ikisi de fark edilmez. Etkisi sınırlı (notlar append-only, düzenleme tikleri silmez), ancak edit sırasında checklist'in ilk tiki yarışırsa `TaskChecklistFormSet.clean` kontrolü ile satır değiştirme arasında pencere kalır (kilitsiz kontrol).
- Kanıt: `tick` yalnızca `item.save(update_fields=...)`; formset `clean` kilitsiz `exists()`.
- Öneri: Checklist satırı değişimini görev kilidi altında doğrula.

### F-504 Kapsam kararları tek bir güne (ilk gün) bağlı; yerleşim değişimi aşan izin talebi

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-14`
- Dosyalar: hr/services.py:271-275, hr/resources/leave.py:158, hr/read.py:549
- Açıklama: İzin karar/okuma yetkisi `first_day`'e göre `scope.can_reach` ile verilir; talep sırasında birimi değiştiren kişinin sonraki günlerinde yeni yönetici talebi göremez/karar veremez, oysa `away_on`/pano o günlerde izni gösterir.
- Kanıt: services.py:275 `scope.can_reach(user, leave_request.employee, leave_request.first_day)`.
- Öneri: Davranışı belgele veya gün-bazlı görünürlük ekle.

### F-505 Form yolu `ShiftAssignmentForm` kilitsiz değerlendirme yapar, servis yolu kilitler

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-15`
- Dosyalar: hr/forms/roster.py:47-64, hr/services.py:183-219
- Açıklama: Tek hücre kaydı formda `evaluate` ile kuralları kilit olmadan çalıştırır; toplu yol çalışan satırını `select_for_update` ile kilitler. Eşzamanlı iki kayıt arasında kural (örn. dinlenme/çakışma) kontrolü eski plana göre yapılabilir. Ayrıca `evaluate` site/saat dilimini yalnızca `min(changes)` gününe göre seçer.
- Kanıt: forms/roster.py:58 `services.evaluate(employee, {day: shift})`; services.py:193 kilit yalnızca toplu yolda; services.py:164.
- Öneri: Form kaydını da aynı servise yönlendir.

### F-506 Lice: iki haftaya yayılan tedavi her iki haftanın raporunda tam miktarla yer alıyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-10`
- Dosyalar: reports/compute/lice.py:34-39, 241-276
- Açıklama: `week_treatments` haftayla kesişen tedavileri alır; hafta sınırını aşan tedavi her iki haftanın raporunda aynı `amount_value` ile çıkar. Docstring "in both" diyerek bunu kabul ediyor ama Mattilsynet toplamlarında miktar iki kez sayılabilir; hangi haftaya ait olacağı doğrulanmamış.
- Kanıt: lice.py:36 `start_date__lte=period.end, end_date__gte=period.start`; `_kind` miktarı bölüştürmez.
- Öneri: Miktarın hangi haftaya yazılacağını yetkiliyle doğrula (R-sorusu) ve ya başlangıç haftasına bağla ya da uyarı ekle.

### F-507 `site_in_use` / `site_emptied` bildirimleri "ilk balık / son balık" koşulunu doğrulamıyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-13`
- Dosyalar: reports/compute/notices.py:87-110
- Açıklama: `site_in_use` yalnızca o gün siteye INPUT/TRANSFER_IN girişi olduğunu ve `site_emptied` yalnızca günün sonunda stok kalmadığını kontrol eder. Site o gün öncesinde zaten kullanımdaysa (başka tank doluysa) giriş yine "kullanıma alındı" bildirimi olarak hazır görünür; `site_emptied` için o gün balık çıkışı olduğu doğrulanmaz (zaten boş bir sitede herhangi bir tarih seçilebilir). Hiçbiri due listesinde üretilmez, kişi başlatır; bu yüzden yanlış bildirime karşı tek koruma kullanıcıdır.
- Kanıt: notices.py:106 `elif read.stock_on(units, day): problems.append(...)` (yalnızca bu koşul); site_in_use'ta önceki stok kontrolü yok.
- Öneri: `site_in_use` için `stock_on(units, day - 1) == {}` ve `site_emptied` için o gün çıkış hattı varlığını problem olarak kontrol et.

### F-508 Filing sırasında içerik ve parmak izi ayrı okumalarla alınıyor (tutarsız anlık görüntü olabilir)

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-14`
- Dosyalar: reports/services.py:61-82
- Açıklama: `compute.compute(current)` içeriği üretir, kısa süre sonra `compute.fingerprint(result.scope)` aynı sorguları yeniden çalıştırır; ikisi arasında yazılan bir kayıt (READ COMMITTED) içerikte yok, parmak izinde var olabilir. Sonuç: filed rapor doğumundan itibaren "kayıtlar değişti" olarak işaretlenir (yanlış pozitif) ya da tersi. Rapor satırı kilitli ama ledger/besleme satırları kilitli değil.
- Kanıt: services.py:51 `select_for_update()` yalnızca `Report`; services.py:82 `compute.fingerprint(result.scope)`.
- Öneri: Parmak izini içerikle aynı transaction'da `REPEATABLE READ` altında üret veya iki okuma arasında hash karşılaştırması yap.

### F-509 `due._periodic_line` her dönem için tüm (birim, parti) zaman çizelgelerini tarıyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-15`
- Dosyalar: reports/due.py:222-235
- Açıklama: Her tür için `reports_from`'dan bugüne her dönemde `any(... presence.present_between ...)` tüm `presence.timelines` üzerinde döner: dönem sayısı × zaman çizelgesi sayısı × tür sayısı × site. Haftalık lice raporunda yıllar içinde yüzlerce dönem; bu çarpım 26-2'deki liste yavaşlığına katkıda bulunur.
- Kanıt: due.py:226-227 `if not any(_category(batches[batch])[fish] and presence.present_between(...) for unit, batch in presence.timelines)`; `_category` her çağrıda yeni sözlük kurar.
- Öneri: Kategori başına bir kez aralık birleşimi hesapla ve dönemleri o aralıklarla kesiştir.

### F-510 Yıllık görevler (`duties`) `reports_from`'u yok sayıyor; "salmonid" tanımı iki yerde farklı

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-16`
- Dosyalar: reports/duties.py:140-153, reports/due.py:209-210, reports/services.py:151-153
- Açıklama: `lines_of` her uygun site için 2026'dan bugüne tüm yılların 1 Ekim görevlerini üretir; sitenin `reports_from` tarihi, ya da o yıl balık tutup tutmadığı dikkate alınmaz (yeni bir site için sonradan geçmiş yıllar "gecikmiş" görünür). `salmonids` due'da `presence` (zaman çizelgesi) ile, `record_duty_done`'da `Batch.objects ... movements__unit__...` (silinmiş partiler hariç, farklı sorgu) ile hesaplanıyor; bir görev satırı listelenir ama kaydedilemez ya da tersi olabilir.
- Kanıt: duties.py:149 `for year in range(FIRST_YEAR, today.year + 1)`; services.py:151 `Batch.objects.filter(movements__unit__production_department__site=site)`.
- Öneri: Yılları `max(FIRST_YEAR, site.reports_from.year)`'dan başlat ve salmonid kararını tek fonksiyonda topla.

### F-511 `authority_id` doğrulanmadan URL yoluna ve HTTP başlığına yazılıyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-6`
- Dosyalar: reports/forms.py:~186-190 (SubmitForm.authority_id), reports/exports.py:373-376, reports/views.py:222-225
- Açıklama: `authority_id` serbest metin (`CharField`, 100) olarak alınır; düzeltme için `PUT {path}/{authority_id}` yolu ve `X-Api-Path` başlığı bundan üretilir. `/`, `?`, `..` veya satır sonu içeren bir değer yanlış yol üretir; satır sonu Django'nun başlık doğrulamasında `BadHeaderError` (500) verir (taslak düzeltmenin export'unda).
- Kanıt: exports.py:374 `path=f'{path}/{original.authority_id}'`; views.py:223 `response['X-Api-Path'] = call['path']`.
- Öneri: `authority_id` için regex/uzunluk doğrulaması (UUID veya alfanümerik) ve yol için `urllib.parse.quote`.

### F-512 Düzeltme (correction) raporu her zaman orijinalin son tarihine göre "geç" işaretleniyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-8`
- Dosyalar: reports/services.py:83-84, reports/models.py:223-227 (deadline), reports/services.py:177-199
- Açıklama: Düzeltme, orijinalle aynı `period_start` taşır; `current.deadline_on = compute.deadline(current)` aynı dönem kuralını verir. Düzeltme doğası gereği orijinalden sonra gönderildiğinden `filed_late` neredeyse her zaman `True` olur ve "Filed N days after its deadline" rozeti çıkar. Bu bir gecikme ihlali değil; istatistik/rozet yanıltıcı.
- Kanıt: services.py:84 `current.filed_late = (periods.oslo_today(submitted_at) > current.deadline_on) if current.deadline_on else False` (corrects kontrolü yok).
- Öneri: Düzeltmelerde `deadline_on/filed_late`'ı `None` bırak ya da orijinalin değerini taşı.

### F-513 Biomass: sayım düzeltmesiyle artan stok "kayıp" satırı olarak negatif adetle yazılıyor; ölüm ve itlaf aynı nedende

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-9`
- Dosyalar: reports/compute/biomass.py:34-48, 98-101
- Açıklama: `ADJUSTMENT` hatları (artış dahil) `losses` listesine `fish = -line.count` ile girer; pozitif düzeltme (recount up) negatif "kayıp" ve negatif kg üretir (`-(line.kilos or ZERO)`). Ayrıca `MORTALITY` ve `CULL` aynı `dead` nedenine eşlenir; neden adları "unverified" (D-15) olduğu için sınıflama doğruluğu bilinmiyor. Cleaner raporu aynı durumu uyarı ve ayrı alanla ele alıyor (cleaner.py:107-119), biomass'ta bu koruma yok.
- Kanıt: biomass.py:99-100 `row['losses'].append({... 'fish': -line.count, 'kg': text(line.kilos if line.count < 0 else -(line.kilos or ZERO), 1)})`.
- Öneri: Artan düzeltmeleri ayrı alana/uyarıya taşı; negatif kayıp üretme.

### F-514 Çalışan deneyde bırakma sonrası replikat tanksız kalabilir; bütünlük kontrolü yakalamaz

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-11`
- Dosyalar: experiments/services.py:791-819, experiments/design.py:225-230, experiments/integrity.py
- Açıklama: `release_unit` yerine tank koymadan yerleşimi kısaltır; replikatın kalan günleri tanksız kalır. `check_places` yalnız replikatın hiç yerleşimi yoksa `slot_without_tank` üretir; kısmi günlük boşluk ne `check_experiments`'ta ne sapmalarda görünür (yalnız Overview'da FCR "gap").
- Kanıt: design.py:228-229 `if not rows:`; release_unit'te kapsama kontrolü yok.
- Öneri: Replikat-gün kapsama kontrolü (sapma olarak).

### F-515 Kopyalama: aynı token farklı kaynak/kullanıcıya ait kaydı döndürür

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-12`
- Dosyalar: experiments/services.py:691-694
- Açıklama: İdempotans yalnız `entry_key` ile bakar; token başka bir kaynaktan veya kullanıcıdan yapılmış deneye aitse o kayıt "kopya" olarak döner (yalnız UUID tahmini ile mümkün, pratik risk düşük). Ayrıca yeni kopyanın `starts_on` değeri `day_0_too_old` açısından kopyalama anında doğrulanmaz (ancak Start'ta).
- Kanıt: `Experiment.all_objects.filter(entry_key=token).first()` kaynak/kullanıcı karşılaştırması yok.
- Öneri: Token eşleşmesini kaynak ve kullanıcı ile sınırla.

### F-516 Çalışan deneyde gün-0 sonrası balık/tür/tartı kontrolü hiç yenilenmez; `check_experiments` bunu da kapsamaz

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-17`
- Dosyalar: experiments/design.py:334-337, experiments/integrity.py:52-63
- Açıklama: `HOLDS_AFTER_START = [check_experiment, check_groups, check_places]`; `check_protocols`, `check_feeding`, `check_day_zero` bilinçli dışarıda (aktif protokol emekli olabilir vb.). Sonuç: başlamış deneyin başlangıç taban çizgisi ihlalleri (ör. tankta balık yok, iki parti) hiçbir yerde kalıcı olarak raporlanmaz; yalnızca başlatma anında kabul edilen uyarı metni günlüğe düşer.
- Kanıt: design.py:334-337 yorumu; integrity `_of`.
- Öneri: Gün-0 bulgularını başlatmada deney kaydına bağlayıp sonradan gösterme (salt-okunur).

### F-517 Veri sekmesi yemi tür filtresi olmadan topluyor (Overview'dan farklı tanım)

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-4`
- Dosyalar: experiments/read.py:263-276, docs/experiments.md ("Derived, never stored")
- Açıklama: Doküman "rakamlar yalnızca deneyin türünün partilerini okur" diyor; `overview` partiyi türe göre süzerken `data()` yalnızca `record.target` (üretim/temizleyici balık) ile süzüyor. Tankta başka (temizleyici olmayan) türde bir parti varsa yem kilosu denemeye yazılır, FCR ise yazılmaz.
- Kanıt: read.py:273-274 `... and record.target == target` (tür/parti kontrolü yok).
- Öneri: Tanım tek yerde birleştirilsin veya Data sekmesinde sınırlama açıkça belirtilsin.

### F-518 Randomizasyon sınırsız yinelenip üzerine yazılabilir (araştırmacı serbestlik derecesi)

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-6`
- Dosyalar: experiments/services.py:518-568, experiments/forms.py:497
- Açıklama: Taslakta farklı tohumla `randomise` istenildiği kadar çalıştırılıp beğenilen dağılım seçilebilir; önceki denemeler yalnızca denetim günlüğünde kalır, bir "bu tahsis nihai" kilidi veya deneme sayacı yok. Form her açılışta yeni rastgele tohum öneriyor.
- Kanıt: `randomise` her çağrıda `_write_places` + `_set_allocation(RANDOMISED, seed)`; yineleme sınırı/uyarısı yok.
- Öneri: Birden fazla tahsis denemesini Start diyaloğunda uyarı olarak göster; denemeleri günlükte listele.

### F-519 Replikatlar arası tank sayısı dengesizliği kontrol edilmiyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-8`
- Dosyalar: experiments/design.py:200-213, experiments/services.py:534-568
- Açıklama: `check_balance` yalnız replikat sayısını karşılaştırır. Havuzda farklı büyüklükte sistemler (farklı tank sayısı) varsa bir replikat 2, diğeri 6 tank alabilir; hiçbir uyarı yok, oysa birim başına sonuç ve biyokütle karşılaştırılamaz.
- Kanıt: `counts` yalnız `len(design.replicates...)`; `randomise` havuz öğelerinin tank sayısını karşılaştırmaz (`tanks_of`).
- Öneri: Replikat başına tank sayısı eşitsizliği için uyarı.

### F-520 En az bir faktör gerekmiyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-9`
- Dosyalar: experiments/design.py:136-159, 200-213
- Açıklama: Faktörsüz tek grup tasarımı hata vermeden (yalnız `one_group` uyarısı) başlatılabilir; iki faktörsüz grup ise `same_levels` hatası alır. Karşılaştırma anlamı olmayan bir "deney" ön-kayıt edilebilir.
- Kanıt: `check_groups` yalnız grup/replikat/seviye kontrol eder; faktör sayısı kontrolü yok.
- Öneri: Başlatma için en az bir faktör ve iki grup şartı (veya hata seviyesi).

### F-521 Sorgu 12 kelimeden fazlaysa fazlasi sessizce atilir;

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-11`
- Dosyalar: knowledge/search.py:39-44, 94, 104-124
- Açıklama: Sorgu 12 kelimeden fazlaysa fazlasi sessizce atilir; kullaniciya bilgi verilmez. Ayrica her kelime 3+ harfli ise 4 dilin kok on eki olarak eslesir ("running" -> "run:*" -> "runway"); asiri eslesme ve fazla gurultu olasi. Faz-arama ("...") yok (README bunu belirtir).
- Kanıt: search.py:94 `[:MAX_WORDS]`; lexeme search.py:101 on ek.
- Öneri: Kesme uyarisi goster; ust dizeyi ranking'te on eke gore dusur.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-522 Girdi aramasi belgenin baslik/ozet vektorunde de eslesir;

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-12`
- Dosyalar: knowledge/search.py:157-169, knowledge/resources/entry.py:312-318
- Açıklama: Girdi aramasi belgenin baslik/ozet vektorunde de eslesir; kutuphane okuma izni olmayan (yalniz girdi okuma izni olan) kullanici girdi listesi aramasiyla belgenin metnini dolayli sorgulayabilir (sonuc sadece var/yok ve siralama ile). Belge sayisi (`entry_count`) da izinsiz gorunebilir.
- Kanıt: search.py:164-165 `document__search_vector` filtresi izin kontrolu olmadan; entry resource `can_read_library` yalniz baglanti gosterimini kontrol eder (entry.py:353).
- Öneri: Kutuphane okuma izni yoksa belge vektorunu aramaya katma.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-523 Girdinin dogrulama bosluklari:

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-13`
- Dosyalar: knowledge/models/entry.py:376-378, 468-472
- Açıklama: Girdinin dogrulama bosluklari: `observed_on` gelecekte olabilir; expert kaynaginda tarih yoksa "ne zaman" belirsiz; `citation`/`url` ayni belgeyi kutuphane Document'inden ayirt etmez (ayni DOI'li makale hem kutuphanede hem "external" olarak cift kaynak olabilir); statement tekrar kontrolu yok (ayni bilgi iki kez girilebilir).
- Kanıt: entry.py:378 DateField'de ust sinir yok; clean() yalniz kaynak turunun gerekli alanini kontrol eder.
- Öneri: observed_on'a bugunden sonrasini reddet; DOI iceren external kaynak icin kutuphaneyi oner.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-524 Eksik test kapsami:

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-17`
- Dosyalar: knowledge/tests/*.py (test_entries.py:218-263, test_search.py, test_languages.py)
- Açıklama: Eksik test kapsami: belge degisince review'un durumu (28-1), el girisli metinde "CO₂" arama (28-2), Turkce buyuk harf (28-3), parola korumali/bozuk PDF'in 20MB ust siniri, sayfa araligi dogrulamasi (28-4), cok sayfali PDF'te `matching_pages` limiti.
- Kanıt: test_search.py ve test_entries.py test adlari bu senaryolari icermez.
- Öneri: Yukaridaki senaryolar icin regresyon testleri ekle.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-525 Turkce i/I buyuk-kucuk harf:

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-3`
- Dosyalar: knowledge/models/common.py:7-11, knowledge/search.py:111-113
- Açıklama: Turkce i/I buyuk-kucuk harf: depolama tarafi `simple` yapilandirmasi ve DB locale'inin lower()'ina baglidir. "BALIK" -> `balik`, depolanan "balık" ile eslesmeyebilir; "İstanbul" benzeri birlesik noktali i de tutarsiz olabilir. ASCII klavyeyle ("balik") Turkce metin bulunmaz. test_languages.py'de bu yonde test yok.
- Kanıt: SEARCH_CONFIG='simple'; sorgu 'turkish' stemmer okumasi da ayni DB lower'ina baglidir; testte yalnizca "balıklarda" benzeri kucuk harf senaryolari var (test_search.py:47).
- Öneri: unaccent/Turkce katlama (ı/i, İ/i) icin sorgu ve depo tarafinda ek okuma; DB collation'i ile test et.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-526 Document.save, belge satirini kaydedip sonra sayfalari siler/yazar;

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-8`
- Dosyalar: knowledge/models/document.py:217-243
- Açıklama: Document.save, belge satirini kaydedip sonra sayfalari siler/yazar; kendi transaction'ini acmaz (transaction.atomic yok, sarmal cagiranin sorumlulugunda). Cagiran atomik degilse (admin disi script, shell) belge `text_status=extracted` iken sayfalari eksik kalabilir. Ayrica `_stored_file` bos gelirse (file alani defer edilmisse) eski dosya yetim kalir.
- Kanıt: document.py:232-241 `super().save` ile `bulk_create` ayri adimlar; from_db 181 yalnizca 'file' yuklenmisse.
- Öneri: save icinde `transaction.atomic()` kullan; defer durumunda stored degerini DB'den oku.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-527 Yazar satirinda virgul "soyad, ad" ayiricisi sayilir;

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-9`
- Dosyalar: knowledge/citation.py:38-44, 28-30, 57-62
- Açıklama: Yazar satirinda virgul "soyad, ad" ayiricisi sayilir; virgul iceren kurum adlari ("Norwegian Veterinary Institute, Oslo") "Norwegian Veterinary Institute, O." olarak kisaltilir ve metin ici atifta (`family_name`) kurumun sadece ilk parcasi kullanilir. Form yardim metni kurumlar icin virgulsuz yazmayi soylemez.
- Kanıt: apa_author citation.py:40-44; family_name citation.py:29.
- Öneri: Kurum yazari icin acik isaret (ornegin sonda isaret veya ayri alan) veya yardim metni uyarisi.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-528 Doğrudan konuşmanın iki katılımcı kuralı DB'de yok; `title()` `.get()` ile 500 verebilir

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-11`
- Dosyalar: messaging/models.py:56-68, 82-103; messaging/read.py:86-92, 66-69
- Açıklama: CHECK yalnızca kind/direct_key/name şeklini zorlar; direct konuşmada katılımcı sayısı kodla korunur (`owner()` kanal ister). Tutarsız veri (elle/asistan akışı) olursa `title()`'daki `.get(conversation=...)` MultipleObjectsReturned fırlatır; `inbox` `others` sözlüğü ikinci katılımcıyı sessizce ezer.
- Kanıt: `str(Participant.all_objects....exclude(pk=participant.pk).get(conversation=conversation))`.
- Öneri: Dayanıklı yazım (`.first()`) ve yalnız servis yolundan katılımcı ekleme kuralı + test.

### F-529 Okunmamış rozeti her render'da hesaplanır; sorgu Message tablosundan başlar

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-14`
- Dosyalar: messaging/read.py:25-31; core/navigation.py:69, 182; config/navigation.py:172-173
- Açıklama: Rozet, kenar çubuğu her çizildiğinde ve her 30 sn'de ayrıca `Message.objects...Exists(...)count()` ile hesaplanır; sorgu kullanıcıdan değil mesajlar tablosundan başlar, planlayıcıya bağlı olarak tüm mesajlar taranabilir. Ek olarak `inbox` 15 sn'de bir, kullanıcı başına konuşma başı 3 ilişkili alt sorgu çalıştırır. Büyük mesaj hacminde pahalı olabilir (ölçülmedi). (09-data-read ile örtüşür.)
- Kanıt: `Message.objects.filter(is_deleted=False).filter(Exists(mine)).count()`.
- Öneri: Katılımcıdan başlayan (veya sayaç sütunlu) sorgu; EXPLAIN ile doğrulayın.

### F-530 Form uzunluk sınırı `\r\n` ile servis sınırından farklı sayar

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-8`
- Dosyalar: messaging/forms.py:31; messaging/services.py:237-241
- Açıklama: Tarayıcı textarea satır sonlarını `\r\n` gönderir; form `max_length=4000`'i bunlarla sayar, servis ise `\r\n`'i `\n`'e çevirip sonra sınar. Çok satırlı ~3990 karakterlik mesaj serviste geçerken formda reddedilir.
- Kanıt: `max_length=MAX_BODY` (form) / `text = body.replace('\r\n', '\n').strip()`; `len(text) > MAX_BODY`.
- Öneri: Form sınırını kaldırıp servise bırakın ya da normalleştirmeyi `clean_body`da yapın.

### F-531 `services.post` NUL karakteri ve tür doğrulamasını yapmaz; API/asistan yolu 500 üretebilir

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-9`
- Dosyalar: messaging/services.py:232-248
- Açıklama: Docstring servisi API ve asistanlar için tek kural yeri sayar, ama NUL (`\x00`) denetimi yalnız Django form alanında (ProhibitNullCharactersValidator) var; servis doğrudan çağrılırsa PostgreSQL DataError (500). `body` str değilse AttributeError.
- Kanıt: `text = body.replace(...).strip()`; hiçbir NUL kontrolü yok.
- Öneri: Kuralı servise taşıyın.

### F-532 Başlık: regulatory_unit_id site bazlı tekilliği DB'de değil departman bazında; site bazı yarış durumuna açık

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-13`
- Dosyalar: farm/models/tank.py:421-430, 464-473
- Açıklama: Kısıt (production_department, regulatory_unit_id); aynı sitenin iki departmanında aynı numara DB'ye girebilir, yalnızca clean()/check_stock yakalar. Kod yorumu da bunu kabul ediyor. Eşzamanlı iki kayıtta veya admin dışı yazımda kural delinir.
- Kanıt: tank.py:421-430 yorumu "all a constraint can see".
- Öneri: Tankta site_id denormalize kolonu (tetikleyiciyle) veya DB trigger; ya da kaydetmede site satırı kilidi.

### F-533 Başlık: Site.TIMEZONES sabit 6 öğelik liste; zone_of geçersiz değerde bozulabilir

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-14`
- Dosyalar: farm/models/site.py:50-57, 148-152
- Açıklama: Model alanı choices ile sınırlı (form dışı yazımda doğrulanmaz, DB CHECK yok); zone_of ZoneInfo(site.timezone) yanlış değerde ZoneInfoNotFoundError atar ve HR/rapor/görev saatleri çöker. Norveç operasyonu için listede yalnız Europe/Oslo anlamlı; diğerleri (Tokyo, New York) üretim sitesi için alışılmadık. docs SITE-09 bu riski belirtmişti.
- Kanıt: zone_of site.py:148-152; DB CHECK yok.
- Öneri: CHECK ile choices'ı eşleyin ya da zone_of'ta geçersiz değeri yakalayın.

### F-534 Başlık: Ekipman başka siteye taşınınca silo (StorageLocation.feeder) site tutarlılığı kontrol edilmiyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-8`
- Dosyalar: farm/models/equipment.py:178-215, inventory/models.py:85-90, 109-114
- Açıklama: StorageLocation.clean feeder'ın sitesini yalnızca kendi kaydında doğrular. Equipment.clean departman değişiminde parçaları kontrol ediyor ama `silos` ilişkisini kontrol etmiyor; EquipmentForm production_department'ı değiştirmeye izin verir (fixed_after_creation yok). Yem silosu başka sitedeki yemleyiciye bağlı kalabilir.
- Kanıt: equipment.py clean() içinde `silos` yok; grep `silos` yalnız inventory/models.py:86.
- Öneri: Equipment.clean'e "silosu varken site değişemez" kontrolü ekleyin.

### F-535 Başlık: Site silme engeli yalnızca stok hareketine bakıyor; diğer geçmiş (sağlık olayı vb.) DO_NOTHING ile siteye işaret ediyor

Önem: **Düşük** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-9`
- Dosyalar: farm/models/site.py:116-122
- Açıklama: HealthEvent.site (farm/models/health.py:480) DO_NOTHING; silinen siteye işaret eden canlı kayıt kalabilir. Silme planı bunları "kept" sayıyor ama blocker yok. Stok hareketi olmayan ama sağlık olayı/su ölçümü olan site (örn. kuluçka öncesi) mesaj olmadan düşer.
- Kanıt: Site.delete_blockers tek koşul StockMovement; softdelete _keep akışı yalnız not düşer.
- Öneri: Geçmişi olan site için "Closed yap" yönlendirmesi sağlık/su kayıtlarını da kapsasın.

### F-536 Merkezi izin alanları listesi app'leri string adlarla tanıyor (core/config ters bağ)

Önem: **Düşük** | Güven: orta | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-8`
- Dosyalar: config/access.py, core/access.py
- Açıklama: `AREAS` tüm app'lerin modellerini ('farm.Site', 'inventory.StorageLocation', 'monitoring.MonitorBoard' vb.) tek yerde tutuyor; `core.access` `apps.get_model` ile çözüyor. Yeni app/model eklemek merkezi dosyayı düzenlemeyi gerektirir, bozuk bir ad ancak çalışma anında (get_model) patlar.
- Kanıt: config/access.py:8-41; core/access.py:36,40.
- Öneri: Her app kendi alanını kayıt etsin (apps.ready), ya da en azından bir test tüm AREAS adlarının çözüldüğünü doğrulasın (varlığı doğrulanmadı).

### F-537 Üç `integrity.py` aynı iskeleti kopyalıyor; ileti metinleri çeviri dışı f-string

Önem: **Düşük** | Güven: orta | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-5`
- Dosyalar: farm/stock/integrity.py, inventory/integrity.py, reports/integrity.py
- Açıklama: Üçü de "`problems()`: found=[], satırları gruplayıp operasyon başına kuralları if/elif zinciriyle kontrol et, cümle listesi dön" kalıbını ve `name = f'{kind} {pk} ...'` önekini tekrarlıyor; ortak çerçeve yok. Ayrıca iletiler `_()` içermiyor, oysa `reports/compute/*` aynı türden iletileri `_()` ile çeviriyor: iki farklı kalıp.
- Kanıt: farm/stock/integrity.py:33-35,68 ve inventory/integrity.py:18-60 (aynı yapı); reports/integrity.py:14-20; karşılaştırma: reports/compute/cleaner.py:45-46 (`_()` kullanımı).
- Öneri: bunların kasıtlı olarak yalnız yönetici/komut çıktısı olduğu belgelensin ya da ortak bir `Problems` yardımcısı çıkarılsın.

### F-538 Kaynak hatası log throttle'ı süreç-yereli global sözlük; sayaç/metrik yok, başarısızlık sıklığı görünmez

Önem: **Düşük** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-6`
- Dosyalar: monitoring/read.py
- Açıklama: FAILED_AT (monitoring/read.py:86) modül düzeyi dict; çok süreçli (gunicorn worker) dağıtımda her worker ayrı throttle tutar ve dakikada en fazla bir kayıt yazılır. Hata sürerken yalnızca ilk istisna kaydedilir, kaç kartın/ne kadar süre etkilendiği hiçbir yerde sayılmaz. Ek olarak kart tarafı yalnızca 'no data' gösterir; kullanıcı kaynağın bozuk olduğunu operatöre bildirmek için ipucu görmüyor olabilir (failed seti kartlara geçiyor; kapsam doğrulanmadı).
- Kanıt: monitoring/read.py:86-87, 270-278.
- Öneri: Throttle'ı koruyun ama sayaç/son hata zamanı metriği veya sağlık ucu (health endpoint) ekleyin.

### F-539 farm.placements.of: bozuk sağlayıcı her istekte günlüğe istisna basar (throttle yok), üstelik TypeError dahil her şeyi yutar

Önem: **Düşük** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-7`
- Dosyalar: farm/placements.py
- Açıklama: 'except Exception' (farm/placements.py:49) 'fail open' olarak her istekte logger.exception çağırıyor; monitoring/read.py'deki gibi dakikada-bir sınırlaması yok. Kalıcı bir sağlayıcı hatası her sayfa/poll isteğinde tam stack trace yazar (log seli). Ayrıca sağlayıcının dönüş tipi doğrulaması için fırlatılan TypeError (satır 46-47) aynı genel yakalayıcıya düşüyor, yani sözleşme ihlali sessizce 'chip yok'a dönüşüyor; testler dışında fark edilmez.
- Kanıt: farm/placements.py:41-52.
- Öneri: Throttle ekleyin (monitoring/read.py ile ortak yardımcı); sözleşme ihlalini ayrı seviyede (error) ve ayrı mesajla kaydedin.

### F-540 `ReplicateUnit` ve `_touch` toplu `update()` çağrıları `version`'ı artırmıyor (optimistik kilidi atlatır)

Önem: **Düşük** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-7`
- Dosyalar: experiments/services.py:199-200, experiments/services.py:584-585, experiments/services.py:196-197, experiments/services.py:814-816
- Açıklama: `_touch`, `move_span` (584) ve `_park` kayıtları `QuerySet.update()` ile değiştirir; `updated_by/updated_at` güncellenir ama `version` güncellenmez (814'te `row.version + 1` bayat Python değerinden, F() değil). Optimistik kilit (`core/crud.py:726`) bu değişiklikleri algılamaz; aynı kaydı eşzamanlı düzenleyen biri sessizce üzerine yazabilir. Deney tasarım kaydetme yolu `locked_draft` ile deney sürümünü kontrol ettiği için çoğu yolda korunuyor.
- Kanıt: `_touch`: `.update(updated_by=user, updated_at=..., values)`.
- Öneri: `version=F('version')+1` ekleyin.

### F-541 `leave_company` istemciden sürüm almadan çalışıyor (kayıp güncelleme)

Önem: **Düşük** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-9`
- Dosyalar: hr/services.py:95-110
- Açıklama: Satır kilitlenip taze okunuyor, `version += 1` yapılıyor ama çağıran formun gördüğü sürümle karşılaştırılmıyor; aynı çalışan kaydını açmış başka kullanıcının düzenlemesi (CRUD yolu sürüm kontrollü) ile yarışta "son yazan kazanır"; ayrıca `align_placements` sonrası alt kayıtlar (Posting/ShiftAssignment/Leave) sürüm kontrolsüz değiştirilir. Eylem niteliğinde olduğu için bilinçli olabilir.
- Kanıt: hr/services.py:96-103.
- Öneri: Gerekirse beklenen sürümü parametre alın.

### F-542 Bilgi kutuphanesi aramasi: belge basina 4 iliskili alt sorgu ve tum eslesmeler icin Rank hesabi

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-13`
- Dosyalar: knowledge/search.py:127-145, knowledge/search.py:149-155
- Açıklama: `search_documents` her belge icin `best` sayfa sorgusunu 4 ayri `Subquery` olarak (`page_rank`, `number`, `label`, `Headline(text)`) tekrar calistiriyor; `ORDER BY rank` tum eslesen belgeler icin hesaplanmadan sayfalanamaz. `Headline` tum sayfa metni uzerinde calisiyor. GIN indeksleri dogru kurulmus (olumlu), asil maliyet siralama asamasinda.
- Kanıt: `hit_text=Subquery(best.annotate(passage=Headline(F('text'), query.any)).values('passage')[:1])` (search.py:143).
- Öneri: Once indeksli eslestirmeyle kucuk aday kumesi cikar; Headline'i yalniz sayfadaki belgeler icin ikinci bir sorguda hesapla.

### F-543 Gorev "Tamamlanan" gorunumu ifade ile siralaniyor; indeks yalniz (status, due_date)

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-17`
- Dosyalar: tasks/read.py:70-86, tasks/models.py:406
- Açıklama: Kapali gorevler `Coalesce('completed_at','cancelled_at')` ifadesine gore azalan siralaniyor; bu ifade icin indeks yok (tek indeks `status, due_date`). Kapali gorev sayisi surekli artar; her sayfa isteginde butun kapali kumeler siralanir, `Paginator` ayrica COUNT yapar. Ayrica her satir icin iki iliskili alt sorgu (`lines`, `lines_done`) ve cok sayida `select_related`/`prefetch_related` var (sayfa 50 ile sinirli, kabul edilebilir).
- Kanıt: `closed = Coalesce('completed_at', 'cancelled_at')` / `.order_by(closed.desc(), 'title')` (read.py:78-80); `indexes = [models.Index(fields=['status', 'due_date'], name='tasks_status_due_idx')]` (models.py:406).
- Öneri: Kapanis zamanini tek bir `closed_at` sutununa denormalize edip indeksle ya da ifade indeksi ekle.

### F-544 Sayfalama olmayan buyuyen listeler: Uretim birimleri, yemleme panosu, hasat plani

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-20`
- Dosyalar: farm/stock/views.py:125-141, farm/feeding/views.py:238-262, farm/resources/harvest_plan.py:154-160, core/crud.py:396
- Açıklama: Bu sayfalar tum birimleri ve her birim icin hesaplanan satirlari tek sayfada uretiyor (sayfalama yok); satir sayisi birim sayisiyla (ciftlik buyudukce) artar ve her satir `stock_of`/`project`/`latest` sonuclarini gerektirir. `ListView` `page_size=None` ise (ic ice listeler) tum kayitlari listeler.
- Kanıt: `units = list(Tank.objects.select_related(...))` + `stock = read.stock_of(units)` + `water_views.unit_water(request.user, shown)` (stock/views.py:125-143); `projection = read.project([unit.pk for unit in stocked], ...)` (feeding/views.py:259).
- Öneri: Filtre varsayilanlarini daralt (site/bolum) ve sayfalama ya da sanal kaydirma ekle; ayrintiyi cekmece (drawer) icin tembel yukle.

### F-545 Su orneklerinde 30 gunluk pencere icin tum satirlarin id'leri ArrayAgg ile toplaniyor; hypertable'da id ile arama tum chunk'lari tarar

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-21`
- Dosyalar: farm/water/read.py:377-413, farm/models/water.py:78-90, farm/models/water.py:125-131
- Açıklama: `_newest_ids` her nokta icin 30 gunluk penceredeki TUM satir id'lerini slot basina (12+ parametre) `ArrayAgg(... order_by=...)` ile toplayip ilkini aliyor; manuel ornekleme seyrek oldugu icin simdilik kabul edilebilir, fakat sensor akisi eklenirse nokta basina on binlerce satir id'si 12 kez tasinir. `in_bulk(ids)` hypertable'da yalniz `id` ile aradigi icin (birincil anahtar `(id, measured_at)`) tum chunk'lar taranir; model dokumantasyonu bunu "ciftlik hacminde ucuz" diye kabul ediyor. Hypertable icin sikistirma/saklama politikasi tanimli degil.
- Kanıt: `First(ArrayAgg('id', filter=condition, order_by=('-measured_at', '-created_at')))` (read.py:384-386); `samples = WaterMeasurement.objects.select_related(*POINT_RELATED).in_bulk(ids)` (read.py:401); "an update by id alone (a void) looks in every chunk" (models/water.py:88).
- Öneri: `DISTINCT ON (point_id)`/LATERAL ile slot basina en yeni satiri sec ve `(id, measured_at)` ile getir; sensor verisi planlaniyorsa continuous aggregate ve sikistirma ekle.

### F-546 Statik dosyalar ve sunucu yigini: sikistirma, hashli statik depolama, uretim sunucusu yok; DEBUG varsayilan acik

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-23`
- Dosyalar: config/settings.py:28, config/settings.py:64-78, config/settings.py:173-174, requirements.txt, static/css/components.css, docker-compose.yml
- Açıklama: Ara katmanda `GZipMiddleware` yok, statik dosyalar icin `ManifestStaticFilesStorage`/WhiteNoise yok (onbellek-surumleme ve sikistirma yok); requirements'ta gunicorn/uvicorn yok (yalniz Django); `DEBUG` varsayilan `'1'` (DEBUG acikken Django her baglantida sorgu gunlugu tutar ve bellek kullanimi artar). `components.css` 61 KB, minify edilmemis. docker-compose yalniz veritabani iceriyor.
- Kanıt: `DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'` (settings.py:28); MIDDLEWARE listesi GZip icermiyor; `static/css/components.css` 61042 bayt.
- Öneri: Uretim profilinde GZip + WhiteNoise/CDN ve hashli depolama ac; `DEBUG` varsayilanini kapali yap (ayrica guvenlik uzmanini ilgilendirir).

### F-547 Saat dilimi tutarsizligi: `date.today()` ile `timezone.localdate()` karisik

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-10`
- Dosyalar: experiments/tests/test_places.py:500, farm/tests/test_water.py:712, monitoring/tests/test_pages.py:203, config/settings.py:160
- Açıklama: TIME_ZONE='UTC'. test_places.py sistem yerel saatiyle `date.today()` kullaniyor, uygulama UTC `localdate` kullaniyor; makine saat dilimi UTC disindaysa gece yarisi civarinda `starts_on` ve uygulama bugunu farkli gunler olabilir (flaky). Ayrica 24 yerde gercek saat okunuyor, yalniz hr testleri `timezone.now`'u mock'luyor; gece yarisi sinirinda gun degisirse testler kirilabilir.
- Öneri: `timezone.localdate()` kullan veya `now`'i sabitle.

### F-548 Sabit kodlanmis tarih/kod degerleri (2026) zamanla bayatlayabilir

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-11`
- Dosyalar: experiments/tests/test_places.py:502-503 (`E-2026-00N`), cok sayida `date(20xx,...)` (387 eslesme)
- Açıklama: Gercek saate bagli (`STOCK_BACKDATE_DAYS=31` gibi) kurallar ile sabit takvim tarihleri karisirsa yil/pencere ilerleyince testler kirilir. Bugun 2026-11-06; deney kodu yili ve geriye donuk tarih penceresi sabit tarihlerle etkilesiyorsa risk vardir. Dosya bazinda dogrulanmadi.
- Öneri: sabit tarihli testlerde saati mock'la, kod yilini bugunden turet.

### F-549 Kimlik dogrulama: yalniz temel login/logout testi, kaba-kuvvet/oturum testleri yok

Önem: **Düşük** | Güven: orta | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-6`
- Dosyalar: core/tests.py:34-46
- Açıklama: `test_home_requires_login` ve `test_login_and_logout` var; parola sifirlama, hatali giris tekrari, pasif kullanici girisi, oturum sabitleme gibi negatif durumlar icin dogrudan test bulamadim (login/password sablonlari ve `config/urls.py` var). Kapsam disi olabilir; kesin olmayan, confidence orta.
- Öneri: pasif kullanici, yanlis parola, password_reset akisi icin negatif testler.

### F-550 TimescaleDB imaj sürümü sabit, ama yükseltme ve extension uyumu süreci belgelenmemiş

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-11`
- Dosyalar: docker-compose.yml:4, core/migrations/0001_timescaledb.py:7-12
- Açıklama: İmaj `timescaledb:2.17.2-pg17` olarak pinlenmiş (iyi), fakat digest yok ve mevcut volume'de imaj yükseltildiğinde `ALTER EXTENSION timescaledb UPDATE` gerekir; migration yalnızca `CREATE EXTENSION IF NOT EXISTS` yapar, reverse noop. CI/test ortamı için aynı imaj kullanımı güvence altında değil. Ayrıca `hr/migrations/0002_people.py:21` btree_gist extension'ı yaratır: yönetilen DB'de superuser/izin gerektirir, belgelenmemiş.
- Kanıt: 0001_timescaledb.py:9-12; hr/migrations/0002_people.py:21.
- Öneri: Yükseltme prosedürü ve gerekli extension/izinleri dağıtım belgesine yazın.

### F-551 tsconfig.test.json derleme çıktısı ve test script'i taşınabilirlik/izolasyon sorunları

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-14`
- Dosyalar: package.json:41, scripts/mark-esm.mjs, tsconfig.test.json
- Açıklama: `npm test` tek satırda `&&` zinciri ve tırnaklı glob kullanıyor (Node 22 gerekli; engines yok). `playwright-core` tarayıcı indirmez, makinedeki Chrome/Edge'e bağımlı (THIRD_PARTY.md:12): CI'da tarayıcı yoksa test davranışı belirsiz (atlanır mı başarısız mı, doğrulanmadı). `scripts/` dizininde başka betik yok: DB hazırlığı, seed, yedek vb. için betik eksik.
- Kanıt: package.json:41; THIRD_PARTY.md:12; node_modules kurulu olmadığı için çalıştırılmadı.
- Öneri: Node sürümü sabitleme ve tarayıcı yoksa net hata/atlama politikası.

### F-552 Çalışma zamanı ölçeklenme önkoşulları: önbellek, oturum, medya depolaması tek-düğüm varsayımlı

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-17`
- Dosyalar: config/settings.py:35-62, 180, 110-126
- Açıklama: CACHES tanımsız (varsayılan LocMemCache, süreç başına), medya yerel dosya sistemine (`MEDIA_ROOT`) yazılır ve dosya yalnızca view ile servis edilir; çok replika/konteyner dağıtımında paylaşımlı volume ya da nesne depolama gerekir, belgelenmemiş. İstek gövde sınırı (nginx 25m) yalnızca yorum/README'de; DATA_UPLOAD_MAX_MEMORY_SIZE vb. ayarı yok. `SECURE_PROXY_SSL_HEADER` yok: TLS sonlandıran proxy arkasında Django isteği http sanır (kapsam: güvenlik bulguları 05'te).
- Kanıt: `grep -n "CACHES\|SECURE_PROXY\|DATA_UPLOAD" config/settings.py` boş; settings.py:180, 182-185.
- Öneri: Dağıtım topolojisi belgesi; paylaşımlı medya depolama ve proxy başlığı yapılandırması.

### F-553 `X-Modal` ile içerik değişen yanıtlarda `Vary: X-Modal` yok

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-10`
- Dosyalar: core/crud.py:86-93, frontend/components.ts:334
- Açıklama: Aynı URL, `X-Modal: 1` başlığına göre `modal_base.html` veya `app_base.html` ile render ediliyor. Sayfa yanıtlarında `Cache-Control`/`Vary: X-Modal` ayarlanmıyor (yalnızca poll parçaları ve PDF için ayarlı). Tarayıcı geri-ileri önbelleği veya ara önbellek modal parçasını tam sayfa olarak gösterebilir.
- Kanıt: `grep Vary|vary_on` kodda eşleşme yok; `is_modal` yalnızca başlık okur.
- Öneri: `render_page` içinde `patch_vary_headers(response, ('X-Modal',))`.

### F-554 Rapor dışa aktarımı: ham `X-Api-*` başlıkları ve ek bağımlılık; `api_call` None ise TypeError riski

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-17`
- Dosyalar: reports/views.py:200-215, reports/exports.py:115-139
- Açıklama: JSON export'ta `shaped = exports.api_json(...)` None değilse `call = exports.api_call(report)` çağrılıyor ve `call['method']` doğrudan indeksleniyor; `api_call` uç noktası olmayan türlerde None döndürür. `api_json` ile `api_call` farklı koşullarla (şekil vs. ENDPOINTS) karar verdiğinden, ikisi ayrışırsa 500. Şu an tutarlı olup olmadığı testle kilitlenmemiş (doğrulanmadı).
- Kanıt: `call = exports.api_call(report)`; `call['method']`.
- Öneri: `if call is None: raise Http404` veya tek kaynaktan türetme + test.

### F-555 Yıkıcı/sonlandırıcı eylemlerde ikinci istek idempotent değil: 404 veya hata

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-8`
- Dosyalar: reports/views.py:104-120 (`close`, `_due_row`), reports/views.py:124-130 (`reopen`), reports/views.py:179-185 (`duty_undo`), messaging/views.py:262-272
- Açıklama: `close` çift gönderilince ikinci istekte `_due_row` None döner -> 404 (kullanıcıya "Nothing is owed" yerine sayfa bulunamadı); `reopen`/`duty_undo` ikinci istekte `get_object_or_404` -> 404. Buna karşılık `messaging.delete_message` ve `tasks.tick` bilinçli idempotent. Sözleşme tutarsız.
- Kanıt: `if row is None: raise Http404`.
- Öneri: bilinçli kararla ikinci istekte aynı sonuç sayfasına yönlendirme veya kullanıcı dostu mesaj.

### F-556 "What works today" listesi Production panelini sayarken Research > Experiments, Reports (Regulatory reports), Monitoring

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-10`
- Dosyalar: README.md:1-40 (giris), config/access.py:16,28,68
- Açıklama: "What works today" listesi Production panelini sayarken Research > Experiments, Reports (Regulatory reports), Monitoring ve Card templates'i anmaz; ayrica Roles bolumundeki erisim alani listesi (README:2850-2870) `Experiments`, `Monitoring boards`, `Card templates`, `Card template rules`, `Questions for the authority` alanlarini saymaz (ilk ikisi baska bolumlerde anlatiliyor).
- Kanıt: access.py:16 `Area(_('Monitoring boards') ...)`, :28 `Card template rules`, :68 `Questions for the authority`; README Roles listesinde bu adlar yok.
- Öneri: Ozet listeleri guncellensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-557 Email bolumu SMTP icin `MAILERS` ayarina isaret eder;

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-13`
- Dosyalar: README.md:3251-3256, config/settings.py:191-196
- Açıklama: Email bolumu SMTP icin `MAILERS` ayarina isaret eder; yalnizca console backend ornegi var, SMTP icin gereken anahtarlar (host, port, kimlik) anlatilmaz. `MAILERS` sozlesmesi Django surumune bagli oldugundan ve burada dogrulanamadigindan guven orta.
- Kanıt: settings.py:191-195.
- Öneri: Ornek SMTP yapilandirmasi eklensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-558 docs/aquaculture-platform-bugs.md başka bir reponun dahili notlarını içeriyor

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-13`
- Dosyalar: docs/aquaculture-platform-bugs.md:1-9
- Açıklama: Dosya başka bir kod tabanının (`aquaculture_platform`, branch `snowball-test`, commit `352aa2a8`) hata listesi; ✔ işaretsiz girdiler "doğrulanmamış". Bu repoda kaynak/hijyen açısından yabancı içerik ve içindeki iç yol/commit referansları dışarı sızmış olabilir.
- Kanıt: dosyanın ilk satırları ("Source read: `aquaculture_platform`, branch `snowball-test`").
- Öneri: Mülkiyet/gizlilik açısından uygunluğunu doğrula; ayrı repoya taşımayı değerlendir.

### F-559 Test-önce / uygulama commit çiftleri ayrı commit'ler: ara commit'ler kırık test durumunda

Önem: **Düşük** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-5`
- Dosyalar: .git (örn. 625e165, 49f22a6, 0484a84, 55cf25b)
- Açıklama: "Test: ... written down first. Seen failing: ..." desenli commit'ler bilerek kırık testle commitlenmiş (28 "Test" öneki ile başlayan commit, ayrıca "Test: [ts]" varyantları). Bu geçmiş `git bisect` için güvenilmez; her commit yeşil değil. Commit 4204a63 "Seen failing: the trigger refuses every insert" gibi.
- Kanıt: 625e165 "Seen failing on the step-5 code: the partials are missing"; 49f22a6 "Seen failing against a stub resolver: 18 failures, 11 errors".
- Öneri: Test+kod aynı commit'te olsun veya kırık commit'ler `bisect skip` için etiketlensin.

### F-560 Yoklama: her yönlendirme "gone" sayılıyor

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-14`
- Dosyalar: `frontend/poll.ts:193-196`, `:313`
- Açıklama: `response.redirected` doğrudan "kapsam dışı/oturum bitti" kabul edilir; yorumda "giriş sayfasına yönlendirme" deniyor ama hedef denetlenmiyor. Eğik çizgi ekleme (APPEND_SLASH), http->https veya dil önekine yönlendirme gibi zararsız yönlendirmeler yoklamayı kalıcı durdurur ve pencereyi kapatır (`windows.ts:178`). `components.ts:335` giriş yolunu kontrol ediyor; iki yer tutarsız.
- Öneri: yönlendirme hedefinin `pathname`'ini giriş yoluyla karşılaştır (ortak yardımcı).

### F-561 Sekme görünür olunca tüm izlenen öğeler aynı anda istek atıyor

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-15`
- Dosyalar: `frontend/poll.ts:117-123`, `:187`
- Açıklama: Başlık "ekranlar hizalanmasın" diye rastgele sapma uyguluyor, fakat `shown()` her izlenen öğenin `refresh()`'ini hemen çağırır; gizli sekmede zamanlayıcı zinciri de kasıtlı kopar (satır 187, `schedule` çağrılmadan dönüş). Sonuç: görünür olduğunda eşzamanlı istek patlaması (grid, pencereler, mesaj listesi) ve duvar ekranı sekmesi arka plandayken hiç güncellenmez.
- Öneri: `shown()` içinde küçük rastgele gecikme; duvar ekranı için görünürlük politikasını belgele.

### F-562 Duyuru: aynı metin tekrar okunmaz; bekleyen zamanlayıcılar birikir

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-18`
- Dosyalar: `frontend/announce.ts:279-288`
- Açıklama: `node.textContent = out` aynı metin art arda atandığında DOM değişmediğinden ekran okuyucular tekrar okumaz (aynı kart iyileşip yeniden kritikleşirse aynı cümle). Ayrıca pencere dolmadan birden çok `speak` çağrısı, her biri bekleyen metin varken yeni `setTimeout` kurar (en fazla bir süre sonra boşalır ama gereksiz zamanlayıcılar).
- Öneri: metne görünmez bir ayırıcı ekle ya da önce boşalt; tek zamanlayıcı tut.

### F-563 `create()` yarım kurulabilir: sonradan `required` hatası yoklamayı ve öksüz öğeyi bırakır

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-21`
- Dosyalar: `frontend/windows.ts:158-207`
- Açıklama: Sıra: `host.append(element)`, `watch(body)`, `opened.set`, sonra `required('[data-window-handle]')` ve `[data-window-close]`. Şablonda bu öğelerden biri yoksa istisna fırlar; DOM'da pencere, çalışan yoklama ve `opened` kaydı kalır, ama kapanma/sürükleme bağlanmamıştır. Ayrıca `template.content.firstElementChild as HTMLElement` null için denetlenmiyor (satır 159).
- Öneri: tüm `required` çağrılarını öğeyi DOM'a eklemeden önce yap.

### F-564 Vardiya planı: `aria-selected` rolsüz `td` üzerinde; boş gönderimde sessiz iptal

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-22`
- Dosyalar: `frontend/roster.ts:368-373`, `:396-401`, `templates/hr/roster.html:45`
- Açıklama: `<table data-roster>` için `role="grid"` yok (grep ile bulunamadı); `aria-selected` yalnızca `gridcell/option/row/tab` gibi rollerde geçerlidir, düz `td`'de axe/ARIA ihlali olur. Form gönderiminde seçim yoksa `preventDefault` ile sessizce hiçbir şey olmaz, kullanıcıya mesaj yok.
- Öneri: seçili durumu `aria-pressed`/`aria-selected` ile geçerli bir role bağla ya da `role="grid"` ekle; boş gönderimde çevrilmiş uyarı göster.

### F-565 Mobil ray ve açılır menülerde odak yönetimi eksik

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-25`
- Dosyalar: `frontend/shell.ts:107-166`
- Açıklama: Telefon rayı açıldığında odak içeri alınıyor, ama içerik `inert`/`aria-hidden` yapılmıyor, odak tuzağı yok (Tab arka plana kaçar). Açılır menüler Tab ile dışarı çıkıldığında kapanmıyor (yalnızca tıklama ve Esc).
- Öneri: `inert` ya da `focusout` ile kapatma.

### F-566 `live()` formu: sınırlı hata geri bildirimi ve URL kurma varsayımları

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-27`
- Dosyalar: `frontend/poll.ts:296-332`
- Açıklama: `!response.ok` (5xx) durumunda sessiz dönülür; `aria-busy` kalkar ama kullanıcı sonucun eskidiğini bilmez. `fetch(`${url}?${query}`)` `data-live` adresi zaten `?` içeriyorsa bozuk URL üretir. `history.replaceState` `#hash`'i atar. `queryOf` dosya alanlarını atlar. Formda `name="action"` alanı varsa `form.action` bir öğeye dönüşür.
- Öneri: `new URL` ile sorgu birleştir; hata durumunda `aria-live` bildirimi.

### F-567 `aria-invalid` boş değerle ekleniyor (`toggleAttribute`)

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-6`
- Dosyalar: `frontend/designer.ts:515-518`, `static/css/monitor.css:231`
- Açıklama: `node.toggleAttribute('aria-invalid', bad)` özniteliği `aria-invalid=""` olarak yazar; ARIA'da boş değer "false" gibi ele alınır, yardımcı teknolojiye hata bildirilmez. CSS `[aria-invalid]` ile eşleştiği için görsel olarak çalışır, ama ekran okuyucu için etkisiz. Ayrıca öğe `button` olduğu için rolü `aria-invalid` desteklemeyebilir.
- Kanıt: satır 517-518. Sorunlar listesi ayrıca `role="status"` ile duyuruluyor (test şablonu satır 56), bu kısmen telafi eder.
- Öneri: `setAttribute('aria-invalid','true')` / `removeAttribute`; hata ilişkisini `aria-describedby` ile kur.

### F-568 Denetçi her değişiklikte yeniden kuruluyor: klavye odağı kayboluyor

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-7`
- Dosyalar: `frontend/designer.ts:143-178`, `:205-257`, `:220`
- Açıklama: `render()` her çağrıda `renderInspector()` ile denetçi DOM'unu `replaceChildren` ile tümüyle değiştirir; odak yalnızca tuval içindeyse geri verilir (satır 171-173). Sayı alanında değeri yazıp Tab'a basan kullanıcıda `change` olayı tetiklenir, ardından odaklanan sonraki alan yok edilir ve odak `body`'ye düşer. Sürükleme sırasında da her `pointermove` `renderOrder` + `renderInspector` yeniden kurar (performans).
- Kanıt: `onMove` -> `this.render()` (satır 430-433) tüm denetçiyi her hareket olayında yeniden oluşturur.
- Öneri: denetçiyi yalnızca seçim/öğe değeri değiştiğinde yeniden kur, ya da odaklı alanın `data-field` anahtarına göre odağı geri ver; sürükleme sırasında yalnız tuvali güncelle.

### F-569 `monitoring/_card.html` satır içi `style="{{ view.style }}"`

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-11`
- Dosyalar: templates/monitoring/_card.html:23, monitoring/cards/render.py:40, farm/production_units.html:112, farm/_unit_capacity.html:4
- Açıklama: Stil Python'da dize olarak üretiliyor (şu an yalnızca tamsayılar, güvenli) ve CSP `style-src` kısıtlanırsa kırılır. Genişlik çubukları da satır içi style. Değerler sayısal olmaktan çıkarsa enjeksiyon yüzeyi.
- Kanıt: `return f'--x:{self.x};--y:{self.y};…'`; `style="width: {{ stock.capacity|bar_width }}%"`.
- Öneri: `data-x`/`data-w` + CSS/TS ya da `<progress>`; CSP kararı ile hizala (05-secrets-config bulgularıyla ilişkili).

### F-570 Çoğul formları: `{{ count }} due` tekil/çoğul aynı

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-12`
- Dosyalar: templates/reports/report_list.html:43
- Açıklama: `blocktrans count … {{ count }} due{% plural %}{{ count }} due` - iki biçim aynı; Türkçe/diğer dillerde gereksiz çeviri maliyeti, anlamsız plural. Diğer yerlerde (task_list:64, inbox:27) doğru kullanılmış.
- Kanıt: satır 43.
- Öneri: plural'ı kaldır, düz `trans` kullan.

### F-571 Liste arama formu `request.GET.items` ile çok değerli parametreleri tek değere indiriyor

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-13`
- Dosyalar: templates/crud/list.html:15
- Açıklama: Gizli input'lar `request.GET.items` (her anahtar için son değer) ile üretiliyor; çok değerli filtre (`?a=1&a=2`) aranınca kaybolur. Ayrıca `supplier_list.html:7-10` filtre formu yalnızca `q`'yu taşıyor, `unit`/başka parametreleri düşürüyor: iki form arasında filtre durumu korunması tutarsız.
- Kanıt: `{% for key, value in request.GET.items %}…<input type="hidden"`; supplier_list.html: `{% if query %}<input type="hidden" name="q"…`.
- Öneri: görünümde `hidden_params` listesi (urlencode/lists) üret; filtre formlarında ortak include.

### F-572 Şablonlarda DB'ye gidebilen ilişki erişimleri prefetch'e bağımlı

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-14`
- Dosyalar: templates/farm/treatment_list.html:83, farm/health_event_list.html:54, tasks/task_list.html:88, core/user_list.html:23, knowledge/document_list.html:44
- Açıklama: `.units.all`, `.assignees.all`, `.groups.all`, `.species.all` listelerde kullanılıyor; şablon tarafında prefetch yapıldığını gösteren bir ipucu/test yok. Denetlenen görünümlerin hepsinde prefetch var (farm/health/views.py:110, tasks/resources.py:214, core/resources.py:49, knowledge/resources/document.py:43) ama `farm/_unit_drawer.html:159` `operation.acknowledgements.all` ve `farm/feeding_protocol_form.html:19` için doğrulanmadı.
- Kanıt: ilgili grep; `_unit_drawer.html:159`.
- Öneri: `assertNumQueries` testleri; bağımlılığı şablon başlık yorumuna yaz.

### F-573 `crud/confirm_delete.html` döngü değişkeni `group` sayfa bağlamındaki `group` ile çakışıyor

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-17`
- Dosyalar: templates/crud/confirm_delete.html:5,22-45; crud/list.html:8, form.html:8
- Açıklama: Aynı şablonda eyebrow `{{ group }}` (menü grubu), `plan.*_groups` döngüsü `group` adını yeniden kullanıyor. Döngü dışında etkisiz, ama content bloğuna eklenecek ek bir `{{ group }}` yanlış değer verir; adlandırma bağlam değişkenini gölgeliyor.
- Kanıt: `{% for group in plan.deleted_groups %}` ve `{% block eyebrow %}{{ group }} · {{ title }}`.
- Öneri: döngü değişkenini `bucket` yap.

### F-574 `_field.html` dinamik etiket adı ve yardım/hata kimlikleri

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-19`
- Dosyalar: templates/registration/_field.html:3-4, 20-21
- Açıklama: `<{{ tag }}>` dinamik eleman adı (div/fieldset); fieldset için `<legend>` var ama `aria-describedby` yardım kimliğine (`{{ field.auto_id }}_helptext`) bağlanması widget'ın `aria-describedby`'ine bağlı; use_fieldset alanlarında yardım/hata `legend` ile ilişkilendirilmiyor. `{{ field.errors }}` kimliksiz.
- Kanıt: satır 20-21.
- Öneri: hata listesine `id="{{ field.auto_id }}_error"` ve widget attrs'a describedby ekle.

### F-575 `mounted` filtresi yalnızca hr'nin bazı şablonlarında; kalan ~182 `{% url %}` sabit

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-4`
- Dosyalar: templates/hr/leave_list.html, hr/employee_list.html (mounted); hr/holiday_list.html:16, hr/shift_list.html:17, hr/leave_type_list.html:15, hr/department_list.html:28 (mounted'sız); hr/resources/*.py (`mounts = (Mount(...))`)
- Açıklama: Sayfalar iki yerden (mount) sunulabildiği için `mounted` gerekli (core/templatetags/crud.py:9). Hangi kaynağın mount'lu olduğu şablondan görünmüyor; bir kaynağa sonradan mount eklenirse ilgili şablon sessizce yanlış alana link verir. Şu an mount'sız kaynaklar için doğru, ama kural şablonlarda örtük.
- Kanıt: grep: `{% url 'hr:` satırlarının mounted'lı/mounted'sız dağılımı; tests_crud_mount.py yalnızca crud tarafını sınar.
- Öneri: crud şablonlarında URL'leri görünümden gelen değişkenlere (`edit_url`, `delete_url` zaten var) bağla; `mounted` testine "mount'lu resource şablonları mounted kullanır" denetimi ekle.

### F-576 Çift gönderim koruması yalnız Create'te; modal/sayfa düğmeleri gönderim sırasında devre dışı bırakılmıyor

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-7`
- Dosyalar: frontend/components.ts:318-322, core/crud.py:668-700, templates/farm/stock_void.html:18-26
- Açıklama: Create `entry_key` ile idempotent; ancak void, leave approve/reject, görev tamamla, stok/su kaydı gibi POST'larda gönderim sırasında buton kilitlenmiyor, yavaş ağda çift tık ikinci isteği gönderir (void için sunucu "zaten void" hatası/çift kayıt riski servis katmanına bağlı, doğrulanmadı).
- Kanıt: submit işleyicisi yalnız `preventDefault` + `load`; buton `disabled` yok.
- Öneri: Submit sırasında butonu devre dışı bırak ve "Saving..." göster.

### F-577 Çekmece (drawer) modal değil, Esc ile kapanmıyor, odak yönetilmiyor, arkadaki içerik odaklanabilir

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-12`
- Dosyalar: `templates/tasks/_task_drawer.html:6-12`, `templates/farm/_unit_drawer.html:7`, `static/css/components.css:1128-1133`
- Açıklama: `aside.drawer` `position:fixed` ile sayfanın sağını kaplıyor, DOM'da sayfanın sonunda; Tab sırasında önce arkadaki tüm tablo satırları gelir. Esc kapatmıyor (`frontend/` içinde `drawer` ile ilgili kod yok), kapatma yalnızca bağlantı (`close_url`). Açılışta (sayfa yeniden yüklendiği için) odak çekmeceye taşınmıyor, ekran okuyucu içerik değişikliğini fark etmez. Dar ekranda (`min(30rem,100vw)`) çekmece sayfanın tamamını örter ama arka içerik hâlâ odaklanabilir.
- Kanıt: `grep drawer frontend/*.ts` boş; `components.css:1129` `position: fixed ... z-index: 45`.
- Öneri: Açılışta odağı `#drawer-title`'a taşıyan küçük betik; Esc ile `close_url`'e git; mobilde arka planı inert yap.

### F-578 Grafik renkleri beyaz zeminde 3:1 altında (pH grafikleri, Deffeyes)

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-13`
- Dosyalar: `static/css/components.css:690-704,822-835`
- Açıklama: Seri/çizgi renkleri `#F59E0B` (2.15:1), `#10B981` (2.54:1), `#FF8F73` (2.23:1) beyaz üzerinde WCAG 1.4.11 grafik nesneleri için 3:1'in altında. Lejant ve sayısal metin ("facts") ile desteklendiği ve SVG `role="img"` + `aria-labelledby` ile adlandırıldığı için etki sınırlı; ayrıca `.ph-series-*` renkleri yalnızca renkle ayrışıyor (çoğu seri aynı kalınlık/aynı çizgi stili), renk körü kullanıcı seriler arasında kaybolabilir (izleme kartlarında şekil/desen kullanılırken burada kullanılmamış).
- Kanıt: `components.css:693-698`; hesaplanan oranlar yukarıda.
- Öneri: Daha koyu tonlar kullan ve seri başına farklı `stroke-dasharray`/işaretçi ekle.

### F-579 Başlık seviyesi atlamaları ve tablo başlık/caption eksikliği

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-17`
- Dosyalar: `templates/monitoring/_card.html:7`, `templates/app_base.html:73`, `templates/crud/list.html:36,44`, 95 `<table>` / 3 `<caption>`
- Açıklama: Sayfa `h1` (üst çubuk) ardından izleme kartları `h3` kullanıyor; `h2` atlanıyor. Çoğu veri tablosunda `<caption>` yok (95 tablo, 3 caption) ve tablolar bölüm başlığıyla ilişkilendirilmemiş (`aria-labelledby` yok); `<th>` taraması `scope` olmayan `<th>` bulmadı (iyi). Boş durum başlığı `h2` olarak sayfaya giriyor ama sayfada başka `h2` yok.
- Kanıt: `_card.html:7` `<h3 id="card-title-...">`; `grep -rn "<caption" templates` 3 sonuç.
- Öneri: Kart başlığı için `h2` kullan veya sayfaya gizli `h2` ekle; çok tablolu sayfalarda `caption`/`aria-labelledby`.

### F-580 Giriş alanlarında odak göstergesi yalnızca 2-3px yarı saydam gölge + kenarlık rengi

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-4`
- Dosyalar: `static/css/base.css:59-65,151-153`, `static/css/components.css:70,959`
- Açıklama: `.field input:focus` ve `:focus-visible` için `outline:none`; odak, `border-color: var(--stripe)` ve `box-shadow: 0 0 0 3px rgba(184,69,95,.2)` ile gösteriliyor. Gölge %20 opak olduğundan tek başına belirgin değil; kenarlık değişimi de (sage -> stripe) görsel fark yaratsa da forced-colors (Windows Yüksek Karşıtlık) modunda `box-shadow` yok sayılır ve kenarlık rengi sistem rengine zorlanır, odak halkası kaybolabilir. `monitor.css:181` forced-colors desteği yalnızca izleme için var, form alanları için yok.
- Kanıt: `base.css:151-153` global 3px outline'ı alanlar için açıkça kapatıyor.
- Öneri: Alanlarda da `outline` bırak (veya forced-colors için `outline: 2px solid` ekle).

### F-581 Test kapsamı gettext dışı sabit metni yakalamıyor

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-13`
- Dosyalar: `core/test_catalogs.py`, `docs/i18n.md`
- Açıklama: Testler yalnızca katalog bütünlüğü, `Resource` sekmeleri, menü ve TS'yi denetliyor (`test_a_tabs_*`, `test_menu_and_access_areas_*`, `test_no_ui_text_in_the_typescript`). Şablonlarda `{% trans %}` dışı metin, `ValueError`/`Http404`/`JsonResponse` metinleri veya `.lower()` kullanımı için denetim yok; bu yüzden 45-1, 45-6, 45-7 gibi sapmalar yakalanmıyor.
- Öneri: Şablon taraması (etiket dışı kelime) ve `i18n` kural testleri ekleyin.

### F-582 Rapor CSV'sinde UTF-8 BOM yok, ayraç virgül

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-3`
- Dosyalar: `reports/exports.py:190-197`, `reports/views.py:210`, `core/dbview.py:52-54`
- Açıklama: Veritabanı görüntüleyicinin CSV'si Excel için BOM ekliyor (`core/dbview.py:54`, yorumu "æ, ø, å"), ancak `reports/exports.py: csv_text` ve `reports/views.py:210` BOM eklemiyor; oysa içerik Norveççe alan adları (`år`, `planlagteLokaliteter`, `antallAvlivetForeståendeHåndteringAvLaksen`) ve Türkçe/Norveççe metin taşıyor. nb/tr yerelindeki Excel ayrıca `;` bekler, `csv.writer` varsayılan `,` kullanıyor.
- Kanıt: `grep -n "ufeff\|BOM" reports/*.py` sonuçsuz; `reports/exports.py:193` `csv.writer(out, lineterminator='\n')`.
- Öneri: Aynı BOM yardımcısını rapor CSV'sinde de kullanın; ayraç/yerel kararını belgeleyin.

### F-583 Varsayılan numune noktası adları İngilizce veri olarak kaydediliyor

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-8`
- Dosyalar: `farm/water/points.py:22-26`, `farm/migrations/0019_water_points.py:39`
- Açıklama: Yeni birim/sistem için `Inlet`, `Middle`, `Side outlet`, `Bottom drain`, `Outlet`, `Loop` adları düz `str` olarak `SamplingPoint.name` alanına yazılıyor, `gettext_noop` ile işaretli değil ve gösterimde çevrilmiyor; Türkçe/Norveççe kullanıcı birimi oluşturunca İngilizce nokta adları görür. `Loop` katalogda hiç yok (diğerleri `PointKind` etiketi olarak var).
- Kanıt: `farm/water/points.py:22` `(PointKind.INLET, 'Inlet')`; `Loop` için msgid yok (Babel taraması).
- Öneri: Adı oluşturan kişinin diline göre `gettext` ile üretin (benzersizlik kısıtı `uq_water_sampling_points_*_name` ile birlikte düşünülmeli) ya da bunu belgeleyin.

### F-584 Opaklikla azaltilmis metinler dusuk kontrastli

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-12`
- Dosyalar: `static/css/components.css:958` (placeholder `opacity:.55`), `:870` (`.faint`), `:980-990` (`.null`, 11px), `:993` (`.bool-false`)
- Açıklama: Hesaplanan kontrastlar (beyaz zemin): `.grid-filter` placeholder 2.37:1, `.bool-false` 2.59:1, `.null` rozeti 3.56:1 (11px), `.faint` 3.88:1. Metin icin 4.5:1 gerekir (placeholder ve ikincil metin dahil).
- Öneri: `opacity` yerine yeterli kontrastli bir token kullan.

### F-585 `form-grid-*` kurallari site formunun alan kimliklerine bagli ve baska formlara sizar

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-14`
- Dosyalar: `static/css/components.css:228-247`, `:384-388`, `templates/crud/form.html:32`, `farm/forms/tank.py:90`
- Açıklama: Genel `components.css` icinde `#id_timezone`, `#id_street`, `#id_site_manager`, `#id_city`, `#id_latitude` vb. site alanlarina ozel `:has()` secicileri var. Sinif adi `form-grid-{{ tab.key }}` oldugundan, ayni anahtara (`location`) sahip tank formunun sekmesi de 6 sutunlu `.form-grid-location` duzenini alir (tesadufen calisir). Mobilde `grid-column: 1 / -1 !important` kullaniliyor (tek `!important` bu nedenle).
- Öneri: Site'a ozgu kurallari `site_form` kapsamina al veya veri-oznitelik ile ifade et.

### F-586 `100vh` kullanimi mobil adres cubugunda tasma yapar

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-17`
- Dosyalar: `static/css/app.css:61,71`, `components.css:456,465,486-487,901`, `messages.css:8`, `auth.css:7`, `monitor.css:45,85`
- Açıklama: `dvh/svh` hic kullanilmiyor. Sticky `.rail` (`height:100vh`), tam ekran `.modal` (mobil `height:100vh`), sohbet yuksekligi ve izleme alt sayfasi (`70vh`) mobil tarayicilarda dinamik arac cubugu yuzunden alt kismi (modal eylem dugmeleri, rail alt metni) gorunur alanin disinda kalabilir.
- Öneri: `100dvh` (yedek `100vh` ile).

### F-587 Favicon yalniz metin tabanli SVG; PNG/ico/apple-touch yok; `/favicon.ico` 404

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-20`
- Dosyalar: `static/favicon.svg`, `templates/app_base.html:11`, `templates/auth_base.html:10`
- Açıklama: SVG `font-family="system-ui"` ile "S" harfi cizen `<text>`; yazi tipi platforma gore degisir ve harf yol olarak cizilmemis. `.ico`/PNG/`apple-touch-icon`/`theme-color` yok; tarayici `/favicon.ico` istedigi icin 404 gunlugu olusur (repo icinde bu yola rota yok).
- Öneri: Harfi `<path>`'e cevir, ek ikon boyutlari ekle.

### F-588 Ikon seti (Lucide) icin lisans atfi yok

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-21`
- Dosyalar: `templates/icons/*.svg`, `README.md:3388`, `THIRD_PARTY.md:1-14`
- Açıklama: README ikonlarin "Lucide icons" oldugunu soyluyor; `THIRD_PARTY.md` yalniz gelistirme araclarini listeliyor ve tarayiciya gonderilen bir sey olmadigini iddia ediyor. Lucide ISC lisansli; telif/lisans metni dagitilmiyor. (Ikonlarin Lucide oldugu README'ye dayanir, dosya basliklarinda dogrulanmadi.)
- Öneri: `THIRD_PARTY.md`'ye Lucide (ISC) ve font girdisi ekle.

### F-589 `button-danger-text` hover'da koyu renge doner

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-23`
- Dosyalar: `static/css/tasks.css:32`, `static/css/components.css:27`
- Açıklama: `.button-ghost:hover { color: var(--speck) }` (0,2,0) `.button-danger-text { color: var(--error) }` (0,1,0) kuralini hover'da ezer; tehlike metni ustune gelince kirmizi rengini kaybeder. Ayrica tanim yalniz `tasks.css`'te (genel bir dugme varyanti sayfa-ozel dosyada).
- Öneri: `.button-ghost.button-danger-text:hover` tanimla, `components.css`'e tasi.

### F-590 Hareketli pencereler: CSS `z-index:40` JS tarafindan 11+ ile eziliyor (ust cubugun ve cekmecenin altinda kalir)

Önem: **Düşük** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-8`
- Dosyalar: `static/css/monitor.css:39`, `frontend/windows.ts:55,106-108,173`, `static/css/app.css:228`, `static/css/components.css:1129`
- Açıklama: `.monitor-window { z-index: 40 }` ama `windows.ts` `let top = 10` ile baslayip her `raise()`'te inline `z-index = 11, 12, ...` atiyor (acilista `raise` cagriliyor, satir 173). Inline deger CSS'i ezer; sonuc sticky `.topbar` (30) ve `.drawer` (45) altinda kalan pencereler. CSS'teki 40 olu deger. Z-index olcegi (1,2,3,30,40,45,50,60,100) token degil, dosyalara dagilmis ve yorumla elle senkron.
- Öneri: JS'te `top`'u CSS tabanindan (ornegin `getComputedStyle`) baslat veya `--z-window` token'i kullan.

### F-591 Depo servisi yemin durumunu/silinmişliğini doğrulamıyor; kural yalnız formda

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-4`
- Dosyalar: `inventory/services.py:71-82` (`item_for`), `inventory/services.py:271-285` (`receive`), `inventory/forms.py:208`, `farm/feeding/services.py:57-61`
- Açıklama: Yemleme servisi yemin aktif ve silinmemiş olmasını kendi içinde zorluyor; depo servisi (`receive`, `item_for`, `count` içindeki `found`) bunu yapmıyor, yalnız form `Feed.objects.filter(status=ACTIVE)` sunuyor. API/asistan gibi başka çağıranlar (modül docstring'i "later the API and the assistants call the same ones" diyor) pasif/silinmiş yeme depo öğesi ve teslimat açabilir. Sayımın "bulunan lot"u formda tüm yemleri sunuyor (23-18 ile ilişkili).
- Kanıt: `item_for` yalnız `InventoryItem.objects.filter(feed=feed).first()` / `create`; `_check_static` yem durumuna bakmıyor.
- Öneri: Kuralı `_check_static`/`item_for` içine taşı; form yalnız kolaylık olsun.

### F-592 İK izin/işten ayrılma bilgisi görev, deney ve yemleme akışlarına hiç yansımıyor

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-7`
- Dosyalar: `hr/leave.py:74-79` (`away_on`), `hr/services.py:91-109` (`leave_company`), `tasks/services.py:117-131`, `tasks/read.py:120-124`
- Açıklama: `hr.leave.away_on` ("başkalarının yalnız izinde olup olmadığını öğrenebileceği yerler için") üretim kodunda hiç çağrılmıyor (yalnız `hr/tests/test_leave.py`). `leave_company` çalışanın hesabını ve açık görev atamalarını değiştirmiyor; görevler izindeki/ayrılmış kişiye atanmış kalıyor, vardiya planı ile görev ataması ayrı dünyalar. Hesap pasifleştirmesi "platform yöneticisinin tercihi" (docstring), bu yüzden ayrılan kişi `readers()`'da kalıyor ve yeni seri görevleri alabiliyor (24-7, 25-11 ile ilişkili).
- Kanıt: `grep -rn away_on` yalnız tanım ve test; `leave_company` yalnız `left_on` ve placement hizalar.
- Öneri: Atama ekranında `away_on` ile "izinde" rozeti; `leave_company` sonrası açık görevler için uyarı listesi.

### F-593 KnowledgeEntry: değişiklikle draft'a dönüş formda, doğrudan model yazımında değil

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-13`
- Dosyalar: knowledge/forms/entry.py:88, knowledge/models/entry.py:176-181, knowledge/views.py:72-80
- Açıklama: "reviewed kayıt değişince draft'a döner" kuralı yalnızca `KnowledgeEntryForm` içinde; model `save()`/servis düzeyinde değil. Başka bir yazma yolu (import, API, shell) incelenmiş kaydı reviewed bırakarak içeriğini değiştirebilir. AI ajanlarının yalnızca reviewed kayıtla çalışacağı belirtildiğinden (entry.py:~42) risk anlamlı.

### F-594 Tank geçişleri yalnızca `clean()` ile korunuyor (DB tetikleyicisi yok)

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-5`
- Dosyalar: farm/models/tank.py:530-541, 587-597
- Açıklama: Experiment'ta tetikleyici var, Tank/Task/Leave/KnowledgeEntry'de yok; `objects.update()`, shell veya `save()` doğrudan çağrısı geçersiz geçiş yazabilir. Task/Leave'de en azından CheckConstraint'ler durum-alan uyumunu tutuyor, ama geçiş yönünü (ör. rejected -> approved) hiçbir DB kuralı engellemiyor (hr/migrations/0005_leave.py yalnızca self-decision tetikleyicisi içeriyor).
- Öneri: Kritik geçişler (Leave kararı, Task done/cancel) için tetikleyici düşünülmeli.

### F-595 Çalışan ayrılınca (left_on) ayrılış gününü kapsayan pending izin iptal edilmiyor, onaylı izinler olduğu gibi kalıyor

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-9`
- Dosyalar: hr/services.py:130-136
- Açıklama: `align_placements` yalnızca `first_day > left_on` olan pending talepleri `cancelled` yapar. `left_on` sonrasına uzanan pending talep (first_day <= left_on < last_day) ve `first_day > left_on` olan APPROVED talepler dokunulmadan kalır; ayrılmış kişide hayalet onaylı izin oluşur.
- Öneri: approved/pending izinleri de ayrılışa göre kısalt veya iptal et.

### F-596 Messages: Read sahibi her kullanıcı, Messages iznine sahip tüm aktif hesapların (platform yöneticisi dahil) adlarını listeleyebilir

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-11`
- Dosyalar: messaging/services.py:47-58; messaging/views.py (start/new, add_members)
- Açıklama: `contacts()` tüm aktif `messaging.view_conversation` sahiplerini (+ superuser) döndürür; yeni konuşma/kanal üye seçicisi bunu gösterir. Roller arası kişi dizini sızıntısı (HR kapsamından bağımsız): üretim işçisi ofis çalışanlarının/yöneticilerin adını görebilir. Tasarım gereği olabilir.
- Kanıt: `get_user_model().objects.with_perm(USE, is_active=True, include_superusers=True)`.
- Öneri: Belgele veya iletişim listesini rol/bölüm ile sınırla.

### F-597 /admin/ salt-okunur detay sayfaları HR özel alanlarını (izin nedeni, yoklama/vardiya notu) gösterebilir; DB görüntüleyici bunları maskeliyor

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-5`
- Dosyalar: hr/admin.py:1-6; core/admin.py:12-24,56-67; config/database.py:masked
- Açıklama: `register_audited('hr')` HR modellerini ReadOnlyAdmin ile kaydeder; görüntüleme izni olan (superuser) kullanıcıya alanlar salt-okunur formda tam gösterilir (`exclude`/`readonly_fields` ile gizleme yok). Oysa `/database/` `leave_requests.reason|decision_note`, `attendance_records.note`, `shift_assignments.note`, `messages.body` sütunlarını maskeler ve HR günlüğü `audit.restrict` ile kısıtlıdır. Erişim yalnız `is_staff` (UserForm'da ayarlanamaz) olduğundan etki düşük, ama maskeleme politikası iki yerde farklı.
- Kanıt: `masked={'leave_requests': ('reason', 'decision_note'), ...}` vs `AuditedModelAdmin` alan gizlemesi yok. Çalıştırılarak doğrulanmadı.
- Öneri: Admin'de aynı maskeli sütunları `exclude` et veya HR'ı admin'den çıkar; politikayı tek yerde tanımla.

### F-598 Kilitten önce okunan nesne: eşzamanlı silmede UpdateView/RowListView 500

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-7`
- Dosyalar: core/crud.py
- Açıklama: `get_object` (404 verir) ile kilit alan `.get(pk=pk)` ayrı sorgular; aradaki pencerede kayıt silinirse `.get` `DoesNotExist` fırlatır, 404 yerine 500. DeleteView `get_object_or_404` kullandığı için tutarsız.
- Kanıt: core/crud.py:724 ve :815 (`.get(pk=pk)`) ve :770 (`get_object_or_404`).
- Öneri: `get_object_or_404` kullan.

### F-599 Silme: çift tıklamada ikinci istek 404, çocuk kayıtlar kilitlenmiyor

Önem: **Düşük** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-8`
- Dosyalar: core/crud.py, core/softdelete.py
- Açıklama: Başarılı silmeden sonra ikinci POST 404 sayfası döner (idempotent başarı değil). Ayrıca plan yalnız `obj` satırını kilitler; plan hesaplandıktan sonra eşzamanlı eklenen bir çocuk, silinmiş ebeveyne bağlı canlı kayıt olarak kalabilir (düşük olasılık).
- Kanıt: core/crud.py:767-790 (kilit yalnız `of=('self',)`); core/softdelete.py:117-150 (`_collect` çocukları kilitsiz listeler), :162-172 (`execute`).
- Öneri: Zaten silinmiş kaydı başarı olarak ele al; çocuk eklemede ebeveyn canlılığını kilit altında doğrula.

### F-600 Oturum süresi ve rol/izin iptali sonrası oturum davranışı belgesiz

Önem: **Düşük** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-X5`  (yalnız çapraz görüş)
- Dosyalar: config/settings.py
- Açıklama: Oturum süresi ve rol/izin iptali sonrası oturum davranışı belgesiz

### F-601 Envanter hareket filtresi silinmiş tedarikçileri listeliyor

Önem: **Düşük** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-X2`  (yalnız çapraz görüş)
- Dosyalar: inventory/views.py:144
- Açıklama: Envanter hareket filtresi silinmiş tedarikçileri listeliyor

### F-602 İndirme dosya adında bidi/kontrol karakteri filtresi yok

Önem: **Düşük** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-X1`  (yalnız çapraz görüş)
- Dosyalar: knowledge/views.py:37, knowledge/models/document.py:258
- Açıklama: İndirme dosya adında bidi/kontrol karakteri filtresi yok

### F-603 next ve e-posta bağlantıları Host başlığına güveniyor; ALLOWED_HOSTS DEBUG varsayılanına bağlı

Önem: **Düşük** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-X3`  (yalnız çapraz görüş)
- Dosyalar: config/settings.py:30, hr/views.py:38
- Açıklama: next ve e-posta bağlantıları Host başlığına güveniyor; ALLOWED_HOSTS DEBUG varsayılanına bağlı

### F-604 Compose'un DB varsayılan kullanıcısı superuser; migration'ların uzantı gereksinimi belgelenmemiş

Önem: **Düşük** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-X3`  (yalnız çapraz görüş)
- Dosyalar: docker-compose.yml, core/migrations/0001_timescaledb.py, hr/migrations/0002_people.py
- Açıklama: Compose'un DB varsayılan kullanıcısı superuser; migration'ların uzantı gereksinimi belgelenmemiş

### F-605 Metin temizliği yalnız `Cc` kategorisini atıyor; yalnız (lone) surrogate PostgreSQL/psycopg'de 500 üretebilir

Önem: **Düşük** | Güven: düşük | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-11`
- Dosyalar: knowledge/extraction.py:50-53, knowledge/models/document.py:235-238
- Açıklama: `clean` NFKC sonrası yalnızca kontrol karakterlerini (Cc) çıkarır. Bozuk kodlamalı bir PDF'ten gelen tek başına surrogate (kategori `Cs`) karakteri UTF-8'e kodlanamadığı için `bulk_create` sırasında istisna oluşturabilir; bu çağrı `read_pdf`'in try/except'inin dışında olduğundan FAILED'e dönüşmez, kullanıcı 500 görür. Doğrulayamadım (pypdf'in bu durumda tam olarak ne döndürdüğü denenmedi).
- Kanıt: `''.join(ch for ch in text if ch in KEPT_CONTROLS or unicodedata.category(ch) != 'Cc')`; `bulk_create` try dışında.
- Öneri: `Cs` (ve gerekirse `Cn`) kategorilerini de at veya `encode('utf-8','replace')` ile temizle; hatalı sayfaya karşı test ekle.

### F-606 Dosya okuma izi yok ve audit_log TRUNCATE'e açık: iz bırakmadan erişim ve iz silme

Önem: **Düşük** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-X1`  (yalnız çapraz görüş)
- Dosyalar: knowledge/views.py:30-40, core/migrations/0003_audit_log_append_only.py
- Açıklama: Dosya okuma izi yok ve audit_log TRUNCATE'e açık: iz bırakmadan erişim ve iz silme

### F-607 TimescaleDB uzantı sürümü ile migration bağı belgesiz

Önem: **Düşük** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-X2`  (yalnız çapraz görüş)
- Dosyalar: docker-compose.yml, core/migrations/0001_timescaledb.py
- Açıklama: TimescaleDB uzantı sürümü ile migration bağı belgesiz

### F-608 psycopg-binary üretim için tercih edilmiş, gerekçesiz

Önem: **Düşük** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-X3`  (yalnız çapraz görüş)
- Dosyalar: requirements.txt
- Açıklama: psycopg-binary üretim için tercih edilmiş, gerekçesiz

### F-609 `Grid.queryset` okunabilir sütun listesi boşsa `values_list()` tüm sütunları (maskelenmişler dahil) okur

Önem: **Düşük** | Güven: düşük | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-7`
- Dosyalar: core/dbgrid.py:131-133, 168; core/dbgrid.py:183-186
- Açıklama: `values_list(*[])` argümansız çağrıldığında Django tüm alanları döndürür. `masked` içine bir tablonun tüm (pk dahil) sütunları yazılırsa maskeli değerler yine veritabanından okunur; hücre eşleştirmesi de (`next(values)`) kayar. Bugünkü yapılandırmada ulaşılamaz (pk hiç maskelenmemiş); yalnızca yapılandırma hatasına karşı savunma eksikliği. Başka dosyada doğrulanmadı.
- Kanıt: `return rows.order_by(*order, 'pk').values_list(*[select(column) for column in self.readable])` (dbgrid.py:168).
- Öneri: `readable` boşsa `rows.none()` döndür veya her zaman pk'yi seç.

### F-610 Görüntüleyici yalnızca-sil modu ve audit atlama: audit.restrict ve silinmiş satırlar aynı yolda sızar, geri alma raporları bunu kaynak sayıyor

Önem: **Düşük** | Güven: belirtilmedi | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-X3`  (yalnız çapraz görüş)
- Dosyalar: core/dbgrid.py, core/views.py:38, core/admin.py
- Açıklama: Görüntüleyici yalnızca-sil modu ve audit atlama: audit.restrict ve silinmiş satırlar aynı yolda sızar, geri alma raporları bunu kaynak sayıyor

### F-611 Ayrılan çalışan için ayrılış tarihinden sonra yazma engellenmiyor (izin, devam, vardiya)

Önem: **Düşük** | Güven: düşük | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `10-12`
- Dosyalar: `hr/forms/leave.py`, `hr/forms/attendance.py`, `hr/services.py:174-204` (`plan_shifts`), `hr/services.py:92-110` (`leave_company`)
- Açıklama: `left_on` yalnızca çalışan formunda ve `align_placements`/`move` içinde kullanılıyor. İzin, devam kaydı ve vardiya yazma yollarında (`LeaveRequestForm.clean`, `AttendanceRecordForm.clean`, `plan_shifts`) ayrılış tarihinden sonraki günler kontrol edilmiyor; `scope.can_reach` yerleşim (posting) olmayan günde takım üyeliğini düşürdüğü için çoğu lead engellenir, fakat "Everyone" yetkisi olan kullanıcı için `can_reach` her güne izin veriyorsa bu yollar ayrılmış çalışana kayıt yazabilir. `leave_company` ayrıca çalışanın `left_on` sonrasına uzanan onaylı izinlerini/devam kayıtlarını kısaltmaz (yalnızca bekleyen izinleri iptal eder).
- Kanıt: `grep left_on hr/forms/leave.py hr/forms/attendance.py hr/services.py` yalnızca `leave_company`, `align_placements` ve `move` içinde sonuç verir. `scope.can_reach` ALL için davranışı tam doğrulanmadı.
- Öneri: İlgili yazma yollarına `left_on` kontrolü ekleyin; `align_placements`'ın onaylı izinleri de ele alıp almayacağına karar verin.

### F-612 Soft delete düz (AuditedModel olmayan) satırlardan gelen PROTECT bağlarını izlemez; yalnızca elle yazılan `delete_blockers` korur

Önem: **Düşük** | Güven: düşük | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-11`
- Dosyalar: core/softdelete.py:99-123, farm/models/site.py:116-122, reports/models.py:356, 388, farm/models/health.py:219
- Açıklama: `_collect` yalnızca `AuditedModel` ilişkilerini izler. `OutsideDutyDone.site`, `DueClosure.site` (PROTECT) ve `MedicineWithdrawal.species` (PROTECT) düz modellerdir; `Site.delete_blockers` yalnızca stok hareketini, `Species` için blokaj yok. Dolayısıyla beyan edilmiş yıllık görevi/kapatması olan site soft delete edilebilir; veri kalır ama listelerden (ve `Site.objects` ile okunan yerlerden) kaybolur, DB'nin PROTECT'i soft delete'te zaten devreye girmez. Her model için blocker yazma yükü geliştiriciye bırakılmış, yeni düz satırda unutma riski var.
- Kanıt: `if not relation.one_to_many or not issubclass(model, AuditedModel): continue` (softdelete.py:99-101).
- Öneri: PROTECT için düz satırları da say (canlılık filtresi olmadan) ya da sistematik test ekle.

### F-613 Silme akışında tek işlemde (transaction) atomiklik: ATOMIC_REQUESTS yok, bazı akışlar atomic dışında olabilir

Önem: **Düşük** | Güven: düşük | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-11`
- Dosyalar: config/settings.py (ATOMIC_REQUESTS ayarı yok), core/crud.py:770-785, core/audit.py:1-2
- Açıklama: audit.py "değişiklik ve log satırı aynı işlemde" kuralını çağırana bırakır. `ATOMIC_REQUESTS` tanımlı değildir; crud.py'deki silme görünüm kodu `select_for_update` kullandığı için bir `transaction.atomic` içinde olduğu anlaşılıyor, ancak tüm servislerin bu kurala uyduğu tek merkezden zorlanmaz. Bir servis unutulursa kayıt-log tutarsızlığı oluşabilir ve yedekten geri yüklemede fark edilmez. Tüm çağrı noktalarını doğrulamadım.
- Kanıt: grep `ATOMIC` -> sonuç yok; `softdelete.execute` "inside the caller's transaction" der.
- Öneri: `execute`/`record` içinde `transaction.get_connection().in_atomic_block` iddiası (assert) veya kendi `atomic` bloğu ekleyin.

### F-614 Tek komutla (down -v) tum veri silinebilir, uyari yok

Önem: **Düşük** | Güven: belirtilmedi | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-X3`  (yalnız çapraz görüş)
- Dosyalar: docker-compose.yml
- Açıklama: Tek komutla (down -v) tum veri silinebilir, uyari yok

### F-615 Otomatik üretilen planlı görevler log'da 'system' olarak görünür, tetikleyen kullanıcı kaybolur

Önem: **Düşük** | Güven: belirtilmedi | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-X2`  (yalnız çapraz görüş)
- Dosyalar: tasks/services.py:250, tasks/resources.py:92
- Açıklama: Otomatik üretilen planlı görevler log'da 'system' olarak görünür, tetikleyen kullanıcı kaybolur

### F-616 queryset.update() yazmaları (experiments _touch/_park) version ve updated_at ile audit tutarlılığına bağımlı, değiştirilemezlik kapsamı dışı

Önem: **Düşük** | Güven: belirtilmedi | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-X3`  (yalnız çapraz görüş)
- Dosyalar: experiments/services.py:193-200, experiments/services.py:814, experiments/services.py:874
- Açıklama: queryset.update() yazmaları (experiments _touch/_park) version ve updated_at ile audit tutarlılığına bağımlı, değiştirilemezlik kapsamı dışı

### F-617 0023: veri RunPython'ı ile şema değişikliği aynı transaction'da, SET CONSTRAINTS ALL IMMEDIATE yok

Önem: **Düşük** | Güven: düşük | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-5`
- Dosyalar: farm/migrations/0023_reports_fields.py:34-45,90-95
- Açıklama: 0019/0021/0022 migration'ları veri güncellemesinden sonra "tablo bekleyen FK tetikleyici olaylarıyla değiştirilemez" hatasına karşı `SET CONSTRAINTS ALL IMMEDIATE` çalıştırıyor. 0023 `Site.save()` ve `Batch.update()` sonrası aynı tablolara (`sites` RenameField/AlterField/AddConstraint, `batches` AddConstraint) DDL yapıyor ama bu önlemi uygulamıyor. Yalnızca FK sütunu değişirse sorun olur (burada değişmiyor), bu yüzden muhtemelen çalışır; tutarsız önlem.
- Kanıt: 0023:45 ve 91'de RunPython sonrası 46-/92- satırlarında hemen AlterField/AddConstraint var; 0019:186-197'deki desenle kıyas.
- Öneri: Tutarlılık için aynı `SET CONSTRAINTS ALL IMMEDIATE` çağrısını eklemek veya veri adımlarını ayrı migration'a bölmek. (Doğrulanmadı: gerçek DB'de çalıştırılmadı.)

### F-618 audit_log action değerleri için DB CHECK yok, severity için var

Önem: **Düşük** | Güven: belirtilmedi | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-X1`  (yalnız çapraz görüş)
- Dosyalar: core/migrations/0006_audit_void.py, core/migrations/0007_audit_severity.py
- Açıklama: audit_log action değerleri için DB CHECK yok, severity için var

### F-619 DueClosure hard delete ile audit referansı değersiz; şema soft-delete'e geçmeli

Önem: **Düşük** | Güven: belirtilmedi | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-X1`  (yalnız çapraz görüş)
- Dosyalar: reports/services.py, core/models.py
- Açıklama: DueClosure hard delete ile audit referansı değersiz; şema soft-delete'e geçmeli

### F-620 Gelecek zaman kontrolü tolerans içermez (`measured_at > timezone.now()`):

Önem: **Düşük** | Güven: düşük | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-13`
- Dosyalar: farm/water/services.py:~120 (`_check_time`)
- Açıklama: cihaz/tarayıcı saat farkı olan elle girişte veya ileride sensör saatinde reddedilir. Mevcut formda saat dakikaya yuvarlandığı için sorun çıkmaz.
- Öneri: Sensör ingest'i için ayrı tolerans.

### F-621 Su gecmisi ?to=9999-12-31 OverflowError (500) ve from>to sessiz bos sonuc

Önem: **Düşük** | Güven: belirtilmedi | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-X1`  (yalnız çapraz görüş)
- Dosyalar: farm/water/views.py
- Açıklama: Su gecmisi ?to=9999-12-31 OverflowError (500) ve from>to sessiz bos sonuc

### F-622 Pasif ilaç denetimi her çağrıda uygulanıyor; eski tedavi düzenlemesi pasifleşen ilaçla reddedilebilir (10-10 ile aynı kalıp)

Önem: **Düşük** | Güven: belirtilmedi | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-X3`  (yalnız çapraz görüş)
- Dosyalar: farm/health/services.py
- Açıklama: Pasif ilaç denetimi her çağrıda uygulanıyor; eski tedavi düzenlemesi pasifleşen ilaçla reddedilebilir (10-10 ile aynı kalıp)

### F-623 Yemleme tüketimi stok defterinde yalnızca site+gün+kg, yemleme ekranları ise ünite/batch bazında; iki taraf uzlaştırılmıyor

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-X1`  (yalnız çapraz görüş)
- Dosyalar: inventory/read.py, inventory/fold.py, farm/feeding/read.py
- Açıklama: Yemleme tüketimi stok defterinde yalnızca site+gün+kg, yemleme ekranları ise ünite/batch bazında; iki taraf uzlaştırılmıyor

### F-624 `change_last_day` ve `void_treatment` birimleri kilitlemiyor; hasatla yarış mümkün

Önem: **Düşük** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-5`
- Dosyalar: `farm/health/services.py:175,218-252`, `farm/stock/services.py:134-150`
- Açıklama: Modül belgesi "tedavi ve hasat birimi kilitleyerek sırayla çalışır" der; `record_treatment` birimleri `locked(Tank, ...)` ile kilitler, fakat `change_last_day` yalnızca tedavi satırını `select_for_update`, `void_treatment` da yalnızca tedaviyi kilitler. Eşzamanlı bir hasat, kilitli birimlerle uyarı hesaplarken eski (kısa) `end_date`'i okuyabilir; son gün uzatılıyorsa uyarı üretilmeden hasat tamamlanabilir.
- Kanıt: `services.py:223` `Treatment.all_objects.select_for_update(of=('self',))`; `locked(Tank` yalnızca 175 ve 260 satırlarında (tedavi kaydı ve sayım kaydı).
- Öneri: Son gün değişikliğinde ve iptalde de ilgili birimleri (ve partileri) hasatla aynı sırayla kilitle.

### F-625 31 gun geriye donuk pencere stok, tedavi voidi ve change_last_day icin ortak ama devir yolu yok

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-X1`  (yalnız çapraz görüş)
- Dosyalar: farm/stock/services.py, farm/health/services.py
- Açıklama: 31 gun geriye donuk pencere stok, tedavi voidi ve change_last_day icin ortak ama devir yolu yok

### F-626 Bit raporu deniz sıcaklığı: sitedeki tüm 3 m derinlik noktalarının örnek ortalaması (ünite türü/su tipi filtresi yok)

Önem: **Düşük** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-15`
- Dosyalar: reports/compute/lice.py:52-73
- Açıklama: `depth_samples()` site genelindeki `kind=DEPTH, depth_m=3` noktalarının tüm örneklerini alıp aritmetik ortalamasını § 6 "deniz sıcaklığı" olarak veriyor. Aynı sitede tatlı su tankı/havuzu da bir 3 m derinlik noktasına sahipse o sıcaklık deniz sıcaklığına karışır; ortalama zaman ağırlıklı değil, günde çok örnek alınan noktalar ağır basar. Güven düşük: sitelerin gerçekte tankları ile kafeslerini karıştırıp karıştırmadığı veri durumuna bağlı.
- Kanıt: `water.samples_of(site=site, ...).filter(point__kind=PointKind.DEPTH, point__depth_m=TEMPERATURE_DEPTH_M)`; `sum(...) / len(found)`.
- Öneri: Yalnızca deniz kafesi/tuzlu su ünitelerinin noktalarını alın ve günlük ortalamaların ortalamasını kullanın.

### F-627 Lot numarası eşlemesi Python `.upper()` ile, kısıt Postgres `Upper()` ile: bazı karakterlerde eşleşme/IntegrityError riski

Önem: **Düşük** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-11`
- Dosyalar: inventory/services.py:106, inventory/models.py:214-218
- Açıklama: `_resolve` DB `Upper('number')` ile Python `number.upper()` sonucunu karşılaştırıyor. `ß` gibi karakterlerde Python 'SS', Postgres (locale'e bağlı) 'ß' verebilir; bilinen lot bulunamayıp yeni lot oluşturulmaya çalışılırsa `uq_inventory_lots_number_live` (Upper) çakışması IntegrityError olarak 500 dönebilir. Gerçek lot numaralarında düşük olasılık.
- Öneri: Karşılaştırmayı tamamen DB tarafında (`Upper(Value(number))`) yap veya IntegrityError'ı yakala.

### F-628 Scheduler yok ve cok dugumlu cron kilitsiz materialise_due ile cift gorev uretebilir

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-X1`  (yalnız çapraz görüş)
- Dosyalar: tasks/management/commands/generate_tasks.py, tasks/services.py, tasks/views.py
- Açıklama: Scheduler yok ve cok dugumlu cron kilitsiz materialise_due ile cift gorev uretebilir

### F-629 Planlı kesim: planı olmayan kesimde kilo yoksa yanlış mesaj; planı olmayan günler API'de `null`

Önem: **Düşük** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-11`
- Dosyalar: reports/compute/slaughter.py:77-85, 53-60, reports/exports.py:425
- Açıklama: Plansız kesimin `planned_kg` değeri tartım (`measured_weight_kg`) olup `None` olabilir; mesaj "The planned harvest ... has no planned kilos" olarak plansız kesimi planlıymış gibi anlatır. Ayrıca `species` içinde planı olmayan gün `None` bırakılır ve JSON'da `mandagKg: null` gider; API'nin 0/atlanan alan beklentisi doğrulanmamış (docs'ta yok).
- Kanıt: slaughter.py:85 `species.setdefault(code or '', {day: None for day in WEEKDAYS})[weekday] = whole(kilos)`.
- Öneri: Mesajı `item.planned` ayrımına göre düzelt; API şemasında nullable olup olmadığını doğrula.

### F-630 Kaçak bildirimi `_escape` ve `Report.clean` tek-hat varsayımına dayanıyor

Önem: **Düşük** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-12`
- Dosyalar: reports/compute/notices.py:61-72, reports/models.py:251-253
- Açıklama: `operation.movements...get()` birden fazla hat olursa `MultipleObjectsReturned` verir (model docstring'i "her birim için ayrı kayıt" diyor, bu yüzden bugün tek hat bekleniyor); `fish` 0 ise `abs(moved.grams) / fish` sıfıra bölme olur. `Report.clean` `movements...first().unit` için `None` kontrolü yapmaz (hatsız operasyon `AttributeError`). Mevcut kısıtlar bunu engelliyor olabilir; sertleştirilmemiş.
- Kanıt: notices.py:62 `line = operation.movements.select_related('unit', 'batch__species').get()`; models.py:253 `.first().unit`.
- Öneri: Savunmacı kontrol ekle (hata mesajı ile problem olarak raporla).

### F-631 Plansız kesim satırında measured_weight_kg boş olabilir ve rapor bunu sessiz geçebilir

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-X3`  (yalnız çapraz görüş)
- Dosyalar: reports/compute/slaughter.py
- Açıklama: Plansız kesim satırında measured_weight_kg boş olabilir ve rapor bunu sessiz geçebilir

### F-632 move_span: tank kilidi yok ve IntegrityError yakalanmıyor

Önem: **Düşük** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-10`
- Dosyalar: experiments/services.py:571-586, experiments/forms.py:89-93
- Açıklama: Gün 0/süre değişiminde yerleşimler `update` ile taşınıyor; `save_places`/`randomise`'ın aksine tanklar `stock_locked` ile kilitlenmiyor ve DB dışlama kısıtı ihlali (başka deneyin eşzamanlı rezervasyonu) `IntegrityError` olarak yakalanıp okunur mesaja çevrilmiyor; form kontrolü (`clashes_when_moved`) yarışa karşı korumasız. DB bütünlüğü korunur ama kullanıcı 500 görebilir (crud güncelleme yolunun IntegrityError'ı nasıl ele aldığı doğrulanmadı).
- Kanıt: move_span `ReplicateUnit.objects.filter(pk__in=...).update(from_on=..., until_on=...)` try/except yok.
- Öneri: Aynı kilit sırası ve hata çevirisi.

### F-633 Deney diyet ataması (unit, protocol, valid_from) sezgisiyle bulunuyor; çiftlik formunda değişirse release/replace atamayı bitirmez

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-X1`  (yalnız çapraz görüş)
- Dosyalar: experiments/services.py:772-781, farm/feeding/assignments.py:76-82
- Açıklama: Deney diyet ataması (unit, protocol, valid_from) sezgisiyle bulunuyor; çiftlik formunda değişirse release/replace atamayı bitirmez

### F-634 Servis katmanı doğrulama boşluğu alanlar arası ortak desen

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-X1`  (yalnız çapraz görüş)
- Dosyalar: knowledge/search.py, farm/stock/services.py, farm/health/services.py, inventory/services.py
- Açıklama: Servis katmanı doğrulama boşluğu alanlar arası ortak desen

### F-635 Mesajlaşma için otomatik URL-yetki taraması yok

Önem: **Düşük** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-X1`  (yalnız çapraz görüş)
- Dosyalar: messaging/tests/test_pages.py, hr/tests/test_scope.py
- Açıklama: Mesajlaşma için otomatik URL-yetki taraması yok

### F-636 Servis/okuma katmanlari farm.stock.dates gibi alt modullere geniş bagimli; hr, inventory, reports farm iç modüllerini import ediyor

Önem: **Düşük** | Güven: belirtilmedi | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-X1`  (yalnız çapraz görüş)
- Dosyalar: hr/scope.py:19, hr/services.py:14, inventory/read.py:20-21, reports/due.py:20-28
- Açıklama: Servis/okuma katmanlari farm.stock.dates gibi alt modullere geniş bagimli; hr, inventory, reports farm iç modüllerini import ediyor

### F-637 `_day`/`_days` adlari farkli anlamlarla farkli modullerde

Önem: **Düşük** | Güven: belirtilmedi | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-X1`  (yalnız çapraz görüş)
- Dosyalar: hr/scope.py:122, experiments/read.py:297, farm/health/withdrawal.py:63, farm/water/views.py:214, core/views.py:27
- Açıklama: `_day`/`_days` adlari farkli anlamlarla farkli modullerde

### F-638 Silme/geri alma view'larında (reports.reopen, duty_undo) ValidationError yakalanmıyor; kardeş view'lar yakalıyor

Önem: **Düşük** | Güven: düşük | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-15`
- Dosyalar: reports/views.py, reports/services.py
- Açıklama: reports/views.py:123-131 reopen ve :178-182 duty_undo, services.reopen/undo_duty_done çağrısını try/except olmadan yapıyor; aynı dosyadaki diğer POST view'ları (satır 63-67, 107-110, 162-165, 192-194) ValidationError'ı mesaja çeviriyor. services.reopen ve undo_duty_done içinde 'raise' bulunmadığı için şu an tetiklenmiyor (grep ile doğrulandı), fakat servis ileride bir kural eklerse 500 olur; tutarsız desen.
- Kanıt: reports/views.py:123-131, 178-182 vs 55-70, 94-120, 147-175, 187-195.
- Öneri: Aynı deseni (try/except ValidationError -> messages.error) uygulayın veya servislerin hata fırlatmadığını testle sabitleyin.

### F-639 Silme yolu (`DeleteView.post`) yalnızca silinen satırı kilitler; çocuk/bağımlı kayıt eklemeleriyle yarış

Önem: **Düşük** | Güven: düşük | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-2`
- Dosyalar: core/crud.py:768-781, core/softdelete.py:98-190
- Açıklama: `select_for_update(of=('self',))` ile sadece hedef kilitlenir; `plan_delete` çocukları/blocker'ları kilitsiz okur. Hedefin FOR UPDATE kilidi, çocuk INSERT'ünün FK (KEY SHARE) kilidiyle çakıştığı için çoğu durumda seri hale gelir; ancak silme önce kilidi alırsa bekleyen çocuk insert'i commit sonrası soft-delete edilmiş ebeveyne canlı çocuk olarak eklenebilir (form/servis insert sırasında ebeveynin `is_deleted` durumunu kilit altında tekrar kontrol etmiyorsa). Tüm yazma yollarında doğrulanmadı.
- Kanıt: crud.py:770 yalnızca `obj` kilidi; `plan_delete(obj)` 774.
- Öneri: Bağımlı kayıt yazan servislerin ebeveyni kilitleyip `is_deleted` kontrolü yaptığını doğrulayın (stock/inventory/water bunu yapıyor, CRUD formları için ayrıca bakın).

### F-640 Her GET'te boşuna seri satır kilidi: `behind` filtresi en geç saat dilimine göre

Önem: **Düşük** | Güven: düşük | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-5`
- Dosyalar: tasks/services.py:257-262, tasks/services.py:228-233
- Açıklama: `latest = max(clock.today ...) + HORIZON`; bir sitenin kendi "bugün"ü daha geriyse `generated_until = site_today+HORIZON` her zaman `latest`'ten küçük kalır. Seri "behind" sayılır, kilitlenir, `first > last` ile `[]` döner ve hiçbir şey yazılmaz. Sonuç: o seriler için her sayfa yükünde gereksiz FOR UPDATE ve serileşme. `clocks()` tanımı doğrulanamadığı için güven düşük.
- Kanıt: materialise satır 231-235 `if first > last: return []`.
- Öneri: Filtre için seri başına site gününü kullanın ya da kilitsiz ön kontrol yapın.

### F-641 Su ölçümü kilitleme sırası pk sıralı garantisine dayanmıyor (olası kilit sırası tutarsızlığı)

Önem: **Düşük** | Güven: düşük | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-8`
- Dosyalar: farm/water/services.py:69-86, farm/stock/services.py:119-126
- Açıklama: Stock `locked()` sorguya `order_by('pk')` ekler; su servisinin `_locked_points` ise `in_bulk(sorted(pks))` kullanır: Python'da sıralama yalnızca `pk__in` listesini sıralar, SQL'de ORDER BY yok (yapıya göre PG kilitleri tarama sırasıyla alır; `Meta.ordering` de olabilir). İki eşzamanlı tur (round) farklı sırada kilitlerse deadlock mümkün; PG tespit edip birini iptal eder (500). Sahipler (units/systems/equipment) ile Tank kilitleri stock `locked(Tank)` ile aynı satırlara denk gelir, sıra farkı karşılıklı bekleme yaratabilir.
- Kanıt: water/services.py:80-83 (`in_bulk(sorted(...))`, `order_by` yok) ve stock/services.py:125 (`order_by('pk')`).
- Öneri: `.order_by('pk')` ekleyin; kilit sırasını tek yardımcıda toplayın.

### F-642 Gerçek eşzamanlı yarış testi yok; kilit sırası ve bayat liste senaryoları doğrulanmıyor

Önem: **Düşük** | Güven: belirtilmedi | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-X2`  (yalnız çapraz görüş)
- Dosyalar: config/test_runner.py, config/settings.py:121
- Açıklama: Gerçek eşzamanlı yarış testi yok; kilit sırası ve bayat liste senaryoları doğrulanmıyor

### F-643 Her kaydedilen kayit icin denetim anlik goruntusu M2M ve FK `str()` sorgulari yapiyor

Önem: **Düşük** | Güven: düşük | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-22`
- Dosyalar: core/audit.py:62-67, core/audit.py:144-160, core/softdelete.py:177-190, core/dbgrid.py:125-132
- Açıklama: `_display` ManyToMany alanlari icin `getattr(instance, name).all()` ve FK icin `str(related)` cagiriyor; ilgili nesne onceden yuklenmediyse her kayitta ek sorgular (alan basina). Veritabani gezgininde `labels()` `select_related()` (argumansiz) kullaniyor: yalniz null olmayan FK'leri izler, `__str__` null olabilir bir FK kullanan modellerde (ornegin Treatment `self.medicine.name`) satir basina ek sorgu olusabilir. Bu madde kod yolu okumasina dayaniyor, sorgu sayimiyla dogrulanmadi.
- Kanıt: `', '.join(sorted(str(item) for item in getattr(instance, field.name).all()))` (audit.py:67); `.select_related()` (dbgrid.py:128); `what = self.medicine.name if self.medicine_id else ...` (farm/models/health.py:404).
- Öneri: Kritik formlar icin `assertNumQueries` testleri ekle (repoda yalniz 4 kullanim var); `select_related`'i acik alan listesiyle ver.

### F-644 Satir basi silme ve audit: withdraw ve soft-delete planlari ayni O(n) sorgu desenini paylasiyor

Önem: **Düşük** | Güven: belirtilmedi | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-X3`  (yalnız çapraz görüş)
- Dosyalar: tasks/services.py, core/softdelete.py
- Açıklama: Satir basi silme ve audit: withdraw ve soft-delete planlari ayni O(n) sorgu desenini paylasiyor

### F-645 Audit log degistirilemezligi icin TRUNCATE/DROP TRIGGER negatif testi yok

Önem: **Düşük** | Güven: belirtilmedi | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-X1`  (yalnız çapraz görüş)
- Dosyalar: core/tests.py, monitoring/tests/test_templates_db.py
- Açıklama: Audit log degistirilemezligi icin TRUNCATE/DROP TRIGGER negatif testi yok

### F-646 LOGGING, DEBUG varsayilani ve hata isleyicileri icin test yok

Önem: **Düşük** | Güven: belirtilmedi | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-X2`  (yalnız çapraz görüş)
- Dosyalar: config/settings.py, core/tests_settings.py
- Açıklama: LOGGING, DEBUG varsayilani ve hata isleyicileri icin test yok

### F-647 Performans ve kimlik olaylari bulgulari icin regresyon testi yok

Önem: **Düşük** | Güven: belirtilmedi | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-X3`  (yalnız çapraz görüş)
- Dosyalar: monitoring/tests/test_read.py, core/tests.py
- Açıklama: Performans ve kimlik olaylari bulgulari icin regresyon testi yok

### F-648 Hata zarfı biçimleri app'ler arasında tutarsız (JSON {'error':..} vs gövdesiz 400)

Önem: **Düşük** | Güven: belirtilmedi | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-X1`  (yalnız çapraz görüş)
- Dosyalar: monitoring/views.py:188, monitoring/views.py:193, hr/views.py:63, hr/views.py:73
- Açıklama: Hata zarfı biçimleri app'ler arasında tutarsız (JSON {'error':..} vs gövdesiz 400)

### F-649 Guvensiz varsayilanlar icin .env.example yok; fail-open ayarlar belgesiz

Önem: **Düşük** | Güven: belirtilmedi | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-X1`  (yalnız çapraz görüş)
- Dosyalar: config/settings.py, docker-compose.yml
- Açıklama: Guvensiz varsayilanlar icin .env.example yok; fail-open ayarlar belgesiz

### F-650 `data-uppercase`: desteklenmeyen girdi türlerinde `setSelectionRange` istisna fırlatır

Önem: **Düşük** | Güven: düşük | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-13`
- Dosyalar: `frontend/components.ts:73-81`
- Açıklama: `type=email/number` gibi girdilerde `setSelectionRange` `InvalidStateError` fırlatır. Ayrıca IME bileşimi (`isComposing`) sırasında değer yeniden yazılır. Şablonlarda hangi türlerde kullanıldığı doğrulanmadı.
- Öneri: `try/catch` ve `isComposing` kontrolü.

### F-651 `merge`: yinelenen anahtarlı parça davranışı tanımsız

Önem: **Düşük** | Güven: düşük | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-26`
- Dosyalar: `frontend/poll.ts:79-100`
- Açıklama: Gelen parçada aynı anahtar iki kez geçerse `current.get(id)` aynı `old` öğesini iki kez döndürür; ikinci `replaceWith` bağlantısı kopuk öğede etkisizdir ve `done.replaced` yinelenen girdi alabilir (duyuru yinelenir). Ayrıca `old.outerHTML === node.outerHTML` karşılaştırması DOM'u JS ile değiştirilmiş öğede (sınıf, aria) her yoklamada "farklı" bulup yeniden kurar (odak/durum kaybı).
- Öneri: yinelenen anahtarda `null` dön (tam değiştirme).

### F-652 [hidden] CSS ezilmesi (46-2) JS'in hidden kullanimini kiriyor

Önem: **Düşük** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-X2`  (yalnız çapraz görüş)
- Dosyalar: frontend/components.ts, static/css/components.css
- Açıklama: [hidden] CSS ezilmesi (46-2) JS'in hidden kullanimini kiriyor

### F-653 Sayfa-ozel CSS yukleme sablon bazinda elle yapiliyor; hr.css siniflari baska uygulamada kullanilmis

Önem: **Düşük** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-X3`  (yalnız çapraz görüş)
- Dosyalar: templates/experiments/experiment_detail.html:31, static/css/hr.css:14, templates/hr/leave_list.html:31, templates/hr/_board.html:21
- Açıklama: Sayfa-ozel CSS yukleme sablon bazinda elle yapiliyor; hr.css siniflari baska uygulamada kullanilmis

### F-654 Flash/mesaj blogu iki sablonda kopya ve hata ile bilgi ayni canli bolgede

Önem: **Düşük** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-X4`  (yalnız çapraz görüş)
- Dosyalar: templates/app_base.html:98-102, templates/modal_base.html:12-16
- Açıklama: Flash/mesaj blogu iki sablonda kopya ve hata ile bilgi ayni canli bolgede

### F-655 Saat girişi/çıkışı (Clock in/out) ve görev/İK eylemlerinde geri bildirim `next` sayfasına dönüyor; başarısızlıkta durum tutarsız

Önem: **Düşük** | Güven: düşük | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-19`
- Dosyalar: templates/hr/today.html:12-13, hr/views.py:109-118
- Açıklama: Punch formları sayfa yenilemesiyle çalışıyor; `_run` hata durumunda yalnız `messages.error` verip sayfaya döner. Clock out için onay/geri alma (yanlış çıkış) kullanıcı akışı görünmüyor; düzeltme yalnız attendance kaydı düzenlemesi olabilir (doğrulanmadı).
- Kanıt: today.html:12 `<form method="post" action="{% url 'hr:punch'|mounted:request 'out' %}"`.
- Öneri: Yanlış basış için "Undo" (kısa pencere) veya belgelenmiş düzeltme yolu.

### F-656 Mesaj listesi aria-live=polite ile tüm eklenen içeriği okur

Önem: **Düşük** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-X3`  (yalnız çapraz görüş)
- Dosyalar: templates/messaging/inbox.html
- Açıklama: Mesaj listesi aria-live=polite ile tüm eklenen içeriği okur

### F-657 `Accept-Language: no` / `nn` tarayıcıları İngilizceye düşer (olası)

Önem: **Düşük** | Güven: düşük | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-9`
- Dosyalar: `config/settings.py:153`, `core/test_languages.py:45`
- Açıklama: `LANGUAGES` yalnızca `nb` içeriyor; Django'nun varsayılan dil çözümlemesi `no` (veya `nn`) için `nb`'ye düşmez. Norveçli tarayıcıların çoğu `nb-NO` gönderir; yalnızca `no` gönderenler İngilizce görür. Testte yalnızca `nb-NO,nb;q=0.9` var. Django burada çalıştırılamadığı için davranış koddan değil bilgiden çıkarıldı.
- Öneri: Gerekirse küçük bir ara katman/`Accept-Language` eşlemesiyle `no` -> `nb` yapın ve test ekleyin.

### F-658 Frontend TS sabit/çevrilmemiş metin riski: duyuru ve modal hata metinleri şablon dışı

Önem: **Düşük** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-X1`  (yalnız çapraz görüş)
- Dosyalar: frontend/announce.ts, frontend/components.ts, frontend/designer.ts
- Açıklama: Frontend TS sabit/çevrilmemiş metin riski: duyuru ve modal hata metinleri şablon dışı

### F-659 SVG grafik metin boyutlari dar ekranda/3 sutunda 8px altina iner

Önem: **Düşük** | Güven: düşük | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-15`
- Dosyalar: `static/css/components.css:682-686`, `:823-824`, `farm/water/charts.py:166`
- Açıklama: pH grafikleri `viewBox 0 0 400 260` ve `width:100%`; tick metinleri `10px`, eksen `11px`, etiket `10px` viewBox birimi. Telefonda (~290px) olcek ~0.72, `>=1400px`'te 3 sutunda ~280px sutun olcek ~0.7: etkin yazi 7px civari. Tarayicida dogrulanmadi.
- Öneri: Dar ekranda grafik minimum genislik + yatay kaydirma veya font-size'i olcege gore buyut.

### F-660 Sekme cubugu `overflow-x:auto` ile alt gosterge cizgisi kesilebilir

Önem: **Düşük** | Güven: düşük | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-24`
- Dosyalar: `static/css/components.css:179-185`, `:201-208`
- Açıklama: `.tabs { overflow-x:auto }` hesaplanan `overflow-y`'yi de `auto` yapar; secili sekmenin `::after`'i `bottom:-1px` tasar, bu da bazi tarayicilarda 1px dikey kaydirma cubugu/kesme uretebilir. Tarayicida dogrulanmadi.
- Öneri: `overflow-y: hidden` veya `padding-bottom:1px`.

### F-661 z-index olcegi bes dosyaya dagilmis, yorumlarla elle senkron

Önem: **Düşük** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-X1`  (yalnız çapraz görüş)
- Dosyalar: static/css/app.css, static/css/components.css, static/css/monitor.css
- Açıklama: z-index olcegi bes dosyaya dagilmis, yorumlarla elle senkron

### F-662 Rapor tamlığı kullanıcı bağlantılarına bağlı; due listesi çapraz doğrulama yapmıyor

Önem: **Düşük** | Güven: belirtilmedi | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-X1`  (yalnız çapraz görüş)
- Dosyalar: farm/health/services.py, reports/compute/lice.py, reports/compute/slaughter.py, reports/due.py
- Açıklama: Rapor tamlığı kullanıcı bağlantılarına bağlı; due listesi çapraz doğrulama yapmıyor

### F-663 Form ve servis katmanları farklı geçiş kuralları uyguluyor (atama son günü)

Önem: **Düşük** | Güven: belirtilmedi | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-X2`  (yalnız çapraz görüş)
- Dosyalar: farm/forms/feeding_protocol.py, farm/feeding/assignments.py
- Açıklama: Form ve servis katmanları farklı geçiş kuralları uyguluyor (atama son günü)

### F-664 Rapor gönderiminde ağır hesap kilit altında, içerik hash yarışına karşı uzun işlem

Önem: **Düşük** | Güven: düşük | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-11`
- Dosyalar: reports/services.py
- Açıklama: `submit` rapor satırını kilitlemişken `compute.compute` çalıştırır (problem varsa iki kez). Uzun hesap kilidi uzatır; ayrıca DB zaman aşımı olmadığından (50-3) tüm rapor sayfaları bekleyebilir. Gönderim yalnızca kaydı tutar, yetkiliye gerçek iletim yok; bu yüzden "gönderildi" kaydı ile gerçek iletim ayrışabilir (süreç riski).
- Kanıt: reports/services.py:49-62 (compute kilit altında), :63-66 (ikinci compute).
- Öneri: Sonucu tek kez hesapla; uzun hesapları kilit dışına al.

### F-665 Menu rozeti (okunmamis mesaj) her sayfada ve 30 sn'de bir tum Message tablosunu tarayabilir

Önem: **Düşük** | özgün: Yüksek | Güven: orta | Alan: Performans ve test | Doğrulama: çürütüldü/şüpheli

- Kaynaklar: `35-2`
- Dosyalar: messaging/read.py:23-33, core/navigation.py:69-70, core/navigation.py:163-197, config/settings.py:89-96, messaging/views.py:136-138, messaging/models.py (index message_timeline)
- Açıklama: `unread_total` sorgusu `Message.objects.filter(is_deleted=False).filter(Exists(<Participant correlated>)).count()` seklinde; yani sürücü tablo Message (butun konusmalar, butun kullanicilar). PostgreSQL planinda genelde tum canli mesajlar taranip her biri icin Participant alt sorgusu denenir; kullanicinin kendi konusmalarindan baslayip mesajlara gitmek (Participant -> Message(conversation, id > last_read)) yerine ters yon kullaniliyor. Bu sorgu `core.navigation.rail` baglam islemcisi icinden her tam sayfa render'inda calisiyor (rozet, `rail()` icinde yalnizca aktif panele degil, kullanicinin gorebildigi TUM panellerin tum girdileri icin `entry.badge_for(user)` ile hesaplaniyor) ve ayrica her istemci icin 30 sn'de bir poll ediliyor.
- Kanıt: `return Message.objects.filter(is_deleted=False).filter(Exists(mine)).count()` (messaging/read.py:23-28); `'badge': entry.badge_for(user)` (core/navigation.py:182) tum workspace'ler icin dongu icinde; `data-poll-every="30"` (core/test_frontend_contract.py:75 yoluyla shell sablonu). Index yalniz `message_timeline (conversation, id)`.
- Öneri: Sorguyu `Participant.objects.filter(user=user)` uzerinden baslat ve `Message.objects.filter(conversation=..., id__gt=last_read)` toplamini (index `message_timeline` ile) hesapla; ya da Participant'ta `unread_count` sayaci tut. Rozeti yalnizca gorunen panelde hesapla.
- Doğrulama `35-2`: ÇÜRÜTÜLDÜ/ŞÜPHELİ (confirmed=false); doğrulayıcı önemleri Düşük/Düşük -> nihai Düşük. Kod gerçekleri doğru (messaging/read.py:23-28, config/navigation.py:173) ancak doğrulayıcılar iddianın etkisini/ölçeğini onaylamadı (confirmed=false).

## Bilgi önem (161)

### F-666 Ters yönlü kayıt desenleri (olumlu, ama hata yutma riski)

Önem: **Bilgi** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulandı

- Kaynaklar: `31-11`
- Dosyalar: farm/placements.py, experiments/apps.py, reports/apps.py, core/audit.py
- Açıklama: farm, experiments/reports'u import etmeden `placements.register` ve `notices.register` ile genişletiliyor; bağımlılık yönü korunuyor. Ancak placements sağlayıcı hatası `logger.exception` ile yutuluyor (fail-open); sürekli bozuk sağlayıcı sadece log'da görünür.
- Kanıt: farm/placements.py:41-52; experiments/apps.py:12; reports/apps.py:12-15; core/audit.py:24.
- Öneri: Desen doğru; başarısızlık sayacı/izleme ekle ve tüm yeni app'lerde aynı yaklaşımı kullan (31-7 ile birlikte).
- Doğrulama `31-11`: doğrulandı; doğrulayıcı önemleri Bilgi/Bilgi -> nihai Bilgi. farm/placements.py:41-52 sağlayıcı hatası logger.exception ile kaydediliyor; bilinçli fail-open tasarım notu, kusur değil.
- Çapraz görüş itirazı `31-11`: error-handling: "Hatalar yutuluyor" kısmen yanlış; farm/placements.py:49-50 logger.exception ile kaydediyor. Asıl eksik throttle/metrik (33-6/33-7).

### F-667 Test dosya adlandırması tutarsız

Önem: **Bilgi** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-13`, `36-12`
- Dosyalar: core/tests.py, core/tests_assets.py, core/tests_crud_mount.py, core/tests_schema.py, core/tests_scope.py, core/tests_settings.py, core/tests_templates.py, core/tests_widgets.py, core/tests_workspaces.py, core/test_*.py, farm/tests/, hr/tests/
- Açıklama: `core` içinde hem `tests_*.py` hem `test_*.py` hem `tests.py` var; diğer app'ler `tests/` paketi kullanıyor. Django varsayılan keşfi `test*.py` olduğundan çalışır, ama kalıp tutarsız; `core`'un testleri paket altında değil.
- Kanıt: `ls core` çıktısı (core/tests.py, core/tests_*.py, core/test_*.py).
- Öneri: `core/tests/` paketine taşı, tek ad kalıbı.
- Birleştirilen kayıtlar:
  - `36-12` (Bilgi): Test dosya adlandirma tutarsizligi (core)

### F-668 Açık (login_not_required) view envanteri

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-12`
- Dosyalar: core/views.py:16, config/urls.py:27-28
- Açıklama: Projedeki tek `@login_not_required` `set_language`; Django auth view'ları (login, reset) kendi muafiyetini taşır. Medya dosyaları public değil, view ile korunuyor (knowledge/views.py:26-40; settings.py:177-180). Olumlu. Eksik: tüm URL'lerin korumalı olduğunu otomatik doğrulayan test yok (yalnızca `/` için test_home_requires_login, core/tests.py:34).
- Kanıt: grep sonucu tek dekoratör.
- Öneri: URL resolver'ı gezen "tüm yollar girişe yönlenir, beyaz liste dışında" testi.

### F-669 set_language anonim POST'a açık ve oturum hesabına yazıyor

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-13`
- Dosyalar: core/views.py:16-24
- Açıklama: Tasarım gereği açık; CSRF korumalı, `next` Django tarafından doğrulanıyor. Sadece oturum açıksa hesap dilini kaydediyor. Sorun yok, kayıt amaçlı.
- Kanıt: `request.user.is_authenticated` kontrolü satır 22.
- Öneri: Yok.

### F-670 Test kapsamı boşlukları

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-14`
- Dosyalar: core/tests.py:34-80
- Açıklama: Var olanlar: login/logout, reset akışı, bilinmeyen e-posta. Eksik: pasif kullanıcı girişi reddi ve resetten dışlanması (yalnız is_active=False kaydı test edilmiş, giriş denemesi yok), token yeniden kullanımı/süresi, parola değişince oturum, brute force, anonim oturum oluşumu (01-4), açık-yönlendirme (`next=`).
- Kanıt: grep `inactive|is_active` yalnız kullanıcı formu testlerini gösteriyor.
- Öneri: Bu senaryolar için testler.

### F-671 Django admin yalnızca superuser ile erişilir; `AuditedModelAdmin.restore` günlüğe yazılmayan geri yükleme yolu

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-16`
- Dosyalar: core/admin.py:28-55, 72; config/urls.py:41
- Açıklama: `UserForm` is_staff/is_superuser vermiyor, yönetici dışında kimse admin'e giremez. Admin `restore` eylemi `softdelete.restore` çağırır (günlüğe yazıp yazmadığı bu denetimde doğrulanmadı). /admin/ herkese açık adreste ve 2FA/oran sınırı yok (authn alanı).
- Kanıt: core/admin.py:32-35 `has_restore_permission`.
- Öneri: Admin'i ağ düzeyinde kısıtla; restore'un denetim izini doğrula.

### F-672 CSRF kapsaması doğrulandı; testler CSRF'yi hiç zorlamıyor

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-11`
- Dosyalar: config/settings.py:70, templates/, frontend/designer.ts:69-70,467-470, templates/_language_switcher.html:3, templates/app_base.html:90
- Açıklama: `csrf_exempt` repoda yok; çıkış (`logout`, POST + token), dil değiştirme (`login_not_required` ama CSRF'li), giriş formu, modal ve tasarımcı önizlemesi token taşıyor. Durum değiştiren GET görünümü aranmadı ayrıntılı (bu alan başka uzmana ait) ama incelenen `@require_POST`'lar yerinde. Test istemcisi varsayılan olarak CSRF'yi atladığı için (`enforce_csrf_checks` hiç kullanılmamış) bir şablonda `{% csrf_token %}` unutulursa testler yakalamaz.
- Kanıt: `grep -rn csrf_exempt` boş; `grep -rn enforce_csrf_checks --include=*.py` boş.
- Öneri: Şablonlardaki `method="post"` formlarının token içerdiğini tarayan tek bir test ekle.

### F-673 İyi uygulamalar (kayıt)

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-13`
- Dosyalar: core/dbgrid.py:35-38, reports/exports.py:196, knowledge/views.py:37-39, knowledge/tests/test_documents.py:245, monitoring/cards/validate.py:152, templates/monitoring/_card.html:23
- Açıklama: CSV dışa aktarımları `formula_safe` ile formül enjeksiyonuna karşı korunuyor (reports ve DB görüntüleyicisi `Grid.export`); PDF `content_type='application/pdf'` ve nosniff ile sunuluyor (dosya adı sunucu üretimi, `%PDF-` doğrulaması); kart yerleşimindeki `style="--x:..."` değerleri doğrulayıcıda `int` zorunlu (`_is_int`), CSS enjeksiyonu yok; `target=_blank` kullanımı yok, harici bağlantılar `rel="noopener noreferrer"`; `json_script` ile veri aktarımı güvenli.
- Kanıt: belirtilen satırlar.
- Öneri: Yok.

### F-674 `highlight()` `mark_safe` doğru kaçışlıyor; güvenlik bir invariant'a dayanıyor

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-7`
- Dosyalar: knowledge/search.py:43-44,170-176, knowledge/extraction.py:17,51
- Açıklama: `escape(passage)` sonra `\x02`/`\x03` işaretleri `<mark>` ile değiştiriliyor; yani en kötü durumda sahte `<mark>` oluşur, betik değil. Yorum "kontrol karakterleri depolanan metinde yoktur" diyor; bu PDF çıkarımı için doğru (kontrol karakterleri siliniyor), kullanıcının elle yazdığı entry alanları için doğrulanmadı ama etkisi yalnızca görsel.
- Kanıt: `mark_safe(escape(passage).replace(START, '<mark>').replace(STOP, '</mark>'))`; test `knowledge/tests/test_search.py:97`.
- Öneri: Eylem gerekmez; sadece not.

### F-675 Şablon enjeksiyonu yok; `autoescape off` yalnız düz metin e-postada

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-12`
- Dosyalar: templates/registration/password_reset_email.html:1, core/templatetags/assets.py:41, knowledge/citation.py:111-115
- Açıklama: Kullanıcı verisiyle `Template()/from_string` yok. `autoescape off` düz metin e-postada (HTML değil) kullanılıyor, uygun. `citation.reference` ve `highlight` `escape` ile `mark_safe` ediyor (doğru). Importmap `json.dumps` `</script>` kaçışı yok (03-3'te kayıtlı; girdi geliştirici kontrolünde).
- Kanıt: citation.py:113-115.
- Öneri: Yok.

### F-676 Ham SQL kullanımları parametreli ve sabit

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-6`
- Dosyalar: inventory/services.py:75-76, knowledge/search.py:109-114, core/codes.py:12-13, core/database.py:127-132
- Açıklama: Tüm `cursor.execute` çağrıları sabit SQL + `%s` parametresi kullanıyor; `lexeme()` tsquery operandını tırnaklayıp `\` ve `'` kaçışlıyor. `.raw/.extra/RawSQL` yok. Tablo adları (`core/database.py`) model kayıt defterinden geliyor, istekten değil.
- Kanıt: search.py:21-23 `quoted = "'" + text.replace('\\', '\\\\').replace("'", "''") + "'"`.
- Öneri: Yok; bu kalıbı koruyun, `lexeme` için tsquery metakarakter testleri bulunsun.

### F-677 Dinamik `filter({...})`/`order_by` anahtarları beyaz listeden geliyor

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-7`
- Dosyalar: tasks/resources.py:111,122,128, core/dbgrid.py:137-168
- Açıklama: `filter({key: ...})` anahtarları sabit (`priority`,`category`,`due_date__gte/lte`, `places.field_of`), değerler `Priority.values`/`Category.values` ile doğrulanıyor; dbgrid'de `sort`/`f_<ad>` yalnızca `by_name` sütun sözlüğünde varsa kullanılıyor. ORM alan adı enjeksiyonu (ör. `filter(request.GET)`) bulunmadı.
- Kanıt: dbgrid.py:138 `sort = self.by_name.get(params.get('sort'))`.
- Öneri: Yok.

### F-678 Yol geçişi ve SSRF yüzeyi yok

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-8`
- Dosyalar: knowledge/models/document.py:53-55, knowledge/views.py:30-39, config/settings.py:177-180
- Açıklama: Depolama adı `uuid4().hex + '.pdf'` ile sunucuda üretiliyor, yüklenen ad yalnız `file_name` (basename) olarak saklanıyor; indirme `document.file.name` (DB'den) ile yapılıyor, istekten yol alınmıyor. `requests/urllib/httpx` ile giden istek kodu yok; `url`/`doi` alanları yalnızca bağlantı olarak saklanıp çıktılanıyor (`URLValidator(schemes=['http','https'])`).
- Kanıt: document.py:55 `return f'knowledge/documents/{uuid.uuid4().hex}.pdf'`.
- Öneri: Yok.

### F-679 Komut/deserialization yüzeyi test dışında yok

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `04-9`
- Dosyalar: core/tests_settings.py:13, core/test_catalogs.py:236-243
- Açıklama: `subprocess` yalnızca testlerde ve sabit argümanlarla; `pickle/yaml.load/eval/exec/os.system` üretim kodunda yok. `json.loads` tek istek-gövdesi kullanımı monitoring/views.py:190 (boyut sınırlı).
- Kanıt: grep sonucu; üretim kodunda eşleşme yok.
- Öneri: Yok.

### F-680 Git geçmişinde gerçek sır bulunmadı

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-13`
- Dosyalar: git geçmişi (299 commit)
- Açıklama: `git log --all -S'SECRET'/'django-insecure'` yalnızca aynı geliştirme varsayılanını gösterdi; silinmiş dosyalar arasında .env/pem/key/sql/dump yok; izlenen `.sql/.pem/.key/.sqlite3/.csv` dosyası yok. Gerçek DB parolası veya üretim anahtarı sızmamış görünüyor (tam entropi taraması yapılmadı).
- Kanıt: `git log --all --diff-filter=D --name-only` filtresi boş; `git ls-files | grep -iE '\.(sql|dump|pem|key|sqlite3|csv)$'` boş.
- Öneri: CI'ya gitleaks/trufflehog ekle.

### F-681 İyi uygulamalar

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-14`
- Dosyalar: config/database.py:20-28, .gitignore, requirements.txt
- Açıklama: `auth_user.password` ve mesaj gövdeleri DB görüntüleyicide maskeli; `.env`, `/media/`, `db.sqlite3` ignore'da; bağımlılıklar sabit sürümlü (`==`), pypdf için güvenlik gerekçesi yorumlanmış; telemetri kapalı (`timescaledb.telemetry_level=off`); `LoginRequiredMiddleware` global.
- Kanıt: ilgili satırlar yukarıda.
- Öneri: Korunmalı.

### F-682 Bağımlılık kilidi hash'siz; `requirements.txt` sürümleri sabit ama `--require-hashes` yok

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-15`
- Dosyalar: requirements.txt
- Açıklama: Tedarik zinciri sertleştirmesi (hash doğrulama, pip-audit) yok; sürümler kilitli olduğundan risk düşük.
- Kanıt: requirements.txt satırları `paket==sürüm`.
- Öneri: pip-compile --generate-hashes ve pip-audit CI adımı.

### F-683 Test kapsamı boşlukları

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-14`
- Dosyalar: knowledge/tests/test_documents.py
- Açıklama: Test edilenler: sahte PNG, boş dosya, yanlış uzantı, sınır +-1 bayt, uzun ad, sunum başlıkları, izin, 405, depodan eksik dosya, geri alma ile eski dosya korunması. Eksikler: yeni dosya yetimi (06-1), çok sayfalı/büyük PDF ve süre, şifreli PDF (parola gerekli/yalnız owner parolası), polyglot başlık, Range/ETag, çok parçalı gövde 413, `DATA_UPLOAD_*` sınırları, kalıcı silme. Şifreli PDF için kodda dal var (`reader.decrypt('')`) ama bunu doğrulayan test aranmadı.
- Kanıt: grep ile test adları (test_a_pdf_without_text..., test_a_file_above_the_limit..., test_a_save_that_is_rolled_back_keeps_the_file).
- Öneri: Yukarıdaki durumlar için testler ekle.

### F-684 Yükleme yüzeyi tek (knowledge Document.file); doğrulama istemci tarafına da dayanıyor ama sunucuda tekrarlanıyor

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-15`
- Dosyalar: knowledge/forms/document.py:66, knowledge/models/document.py:115-118
- Açıklama: `accept="application/pdf,.pdf"` yalnızca istemci ipucu; sunucu doğrulaması (uzantı, boyut, imza) ayrıca var ve `file_size`/`file_name` istemciden değil sunucudan türetiliyor. Repoda başka FileField/ImageField, ek dosya veya messaging eki yok (docs/aquaculture-platform-bugs.md'deki MSG-01 gibi ek sorunları bu portta yok). Bilgi amaçlı olarak olumlu bulgu: dosya adı depoda UUID, MEDIA_URL rotası yok (`/media/...` 404 testi var), `.gitignore`'da `/media/`.
- Kanıt: config/urls.py'de media rotası yok; test_the_storage_has_no_public_address.
- Öneri: Yeni yükleme yüzeyleri eklenirse aynı kalıp (sunucu adı, görünüm ile sunum, imza kontrolü) kullanılsın.

### F-685 npm lock dosyası sağlam: integrity hash'li, yalnızca resmi registry, dev işaretli

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-13`
- Dosyalar: package-lock.json:1-65
- Açıklama: lockfileVersion 3, tüm paketler `registry.npmjs.org`, `integrity` sha512 var, hepsi `dev: true`; tarayıcıya çalışma zamanı npm paketi gitmiyor (THIRD_PARTY.md:1-3 ile tutarlı). package.json'daki aralıksız sürümler lock ile eşleşiyor. `postinstall` betiği yok.
- Kanıt: `"integrity": "sha512-..."` her pakette; package.json `scripts` içinde yalnızca build/watch/check/test.
- Öneri: Kurulumda `npm ci` kullanılmasını README'de belirt.

### F-686 Doğrudan import edilen paketler requirements ile tutarlı; kullanılmayan doğrudan bağımlılık yok

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-15`
- Dosyalar: requirements.txt, core/catalogs.py:15-18, knowledge/extraction.py:24
- Açıklama: babel, pypdf, psycopg import ediliyor; asgiref/sqlparse/tzdata/typing_extensions Django ve pypdf'in dolaylı gereksinimi olup elle sabitlenmiş (tutarlı ama bkz. 07-1: kısmi kilit). `psycopg` ve `psycopg-binary` birlikte sabit; binary paket üretim için psycopg belgelerince önerilmeyen bir tercih olabilir (sistem libpq yerine gömülü libpq; güvenlik yamaları paketle gelir).
- Kanıt: requirements.txt:6-7; `grep` ile yalnızca bu import'lar bulundu, requests/celery/pandas vb. yok.
- Öneri: `psycopg-binary` tercihini (gömülü libpq/OpenSSL güncelleme sorumluluğu) belgele.

### F-687 `filter_by` sorgu kümesi seçeneklerinin tüm pk'lerini her istekte çeker

Önem: **Bilgi** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-20`
- Dosyalar: core/crud.py:603-618; reports/resources.py:150-152; farm/resources/*.py (filter_list)
- Açıklama: Filtre değerini doğrulamak için `choices.values_list('pk', flat=True)` tümüyle çalıştırılıp küme yapılır; ardından aynı sorgu kümesi şablonda seçenek listesi için tekrar okunur (iki kez okuma). Küçük tablolar için zararsız; doğrulama `choices.filter(pk=chosen).exists()` ile tek satırlık olabilir.
- Kanıt: `allowed = {str(pk) for pk in choices.values_list('pk', flat=True)}` (crud.py:612).
- Öneri: Gereksiz tekrarı kaldır.

### F-688 Görüntüleyici okumaları denetim izine/erişim günlüğüne yazılmaz

Önem: **Bilgi** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-6`
- Dosyalar: core/dbview.py:25-64
- Açıklama: Tablo gezme ve CSV dışa aktarma (auth_user e-postaları, çalışan adları, rapor iletişim bilgileri vb. dahil 50.000 satıra kadar) hiçbir `audit.record` veya erişim günlüğü yazmaz; "kim hangi tabloyu ne zaman indirdi" sorusu cevapsız. Görüntüleyici "salt okur" olduğu için tutarlı ama veri çıkışı izlenemiyor.
- Kanıt: dbview.py'de `audit` içe aktarımı yok.
- Öneri: En azından dışa aktarmaları ayrı bir önem düzeyiyle (ör. NOTICE) denetim günlüğüne kaydet.

### F-689 Deney tasarımı `_touch`/`_park` `queryset.update()` ile yazar: `version` artmaz, `AuditedModel` sözleşmesi dışında kalır

Önem: **Bilgi** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-14`
- Dosyalar: experiments/services.py:193-200, 245, 266-270
- Açıklama: `Factor` ve `ExperimentGroup` kayıtları yeniden adlandırma/sıra değişiminde `update(updated_by, updated_at, ...)` ile yazılır; `version` sabit kalır, `updated_at` elle atanır. Kayıtlar bu yüzden doğrudan düzenlenmez (tasarım Experiment sürümüyle kilitlenir ve loglanır), dolayısıyla pratik etki yok; ancak `AuditedModel`'in "her değişiklik version artırır" invariantı bu modeller için geçerli değil, ileride bu satırlar için ayrı bir form eklenirse kilit çalışmaz. `_park` geçici `~uuid` adları yalnızca işlem içinde görünür.
- Kanıt: `model.objects.filter(pk=record.pk).update(updated_by=user, updated_at=timezone.now(), values)` (services.py:200).
- Öneri: Sözleşmeyi dokümante et veya `version=F('version')+1` ekle.

### F-690 Yönetici geri getirmesi yalnızca Django admin içinde; uygulama arayüzünde çöp kutusu yok

Önem: **Bilgi** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-16`
- Dosyalar: core/admin.py:27-53, core/crud.py:770-789
- Açıklama: Silme (silmeden önce onay ekranı ile) kullanıcı arayüzünde var, geri getirme yalnızca `change_<model>` iznine sahip admin kullanıcısı için Django admin'inde. Üretimde Django admin'in açık olup olmadığı (URL yönlendirmesi) bu denetimde incelenmedi. Kullanıcı hatalı silmeyi kendi başına geri alamaz.
- Kanıt: `actions = ['restore']`; has_restore_permission yalnızca change yetkisine bağlı.
- Öneri: Çöp kutusu ekranı veya (güvenli kısa süre içinde) "geri al" bağlantısı düşünün.

### F-691 Veritabanı kimlik bilgileri varsayılan, `restart: unless-stopped` ile yedek yokken tek örnek

Önem: **Bilgi** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `12-17`
- Dosyalar: docker-compose.yml:8-12, config/settings.py:113-117
- Açıklama: Varsayılan kullanıcı/parola `balik/balik`; yedek istemcisinin kullanacağı ayrı salt-okunur yedek rolü yok. Yedekleme tasarlanırken bir `pg_dump` rolü ve `.pgpass` gerekir; bu hazırlık yok. Sağlık kontrolü (`healthcheck`) tanımı da yok.
- Kanıt: `POSTGRES_PASSWORD: ${DB_PASSWORD:-balik}`; healthcheck anahtarı yok.
- Öneri: Yedek rolü ve healthcheck ekleyin.

### F-692 Görev notunun tam metni log'a yazılıyor ve `restrict` kapsamında değil

Önem: **Bilgi** | Güven: yüksek | Alan: Yedekleme ve denetim izi | Doğrulama: doğrulanmadı

- Kaynaklar: `13-18`
- Dosyalar: tasks/services.py:192-203
- Açıklama: `add_note` metni olduğu gibi `{NOTE: [None, body]}` olarak log'a yazar (docstring: "logged with its text"). `private_fields` kullanılmayan bu alan, `view_auditlog` iznine sahip herkesin okuyabileceği kalıcı (silinemez) bir kopya olarak kalır; HR notları için yapılan gizleme burada yok. Bilinçli bir tasarım olabilir ama kişisel yorum içerebilir.
- Kanıt: `audit.record(user, AuditLog.Action.UPDATE, task, {str(NOTE): [None, body]})` (tasks/services.py:202).
- Öneri: Not metnini özetle/`private` yap veya görev notlarını `restrict` ile ilgili izne bağla; kararı belgele.

### F-693 core 0001 timescaledb: uzantı geri alma noop, kullanıcı yetkisi varsayımı

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-13`
- Dosyalar: core/migrations/0001_timescaledb.py:9-12
- Açıklama: `CREATE EXTENSION IF NOT EXISTS timescaledb` ve `reverse_sql=noop`. Uzantı sürümü migration'da sabitlenmemiş (README/compose'taki imaj sürümüne bağlı); uzantı yükseltmesi migration dışında. Bilgi amaçlı.
- Kanıt: 0001_timescaledb.py:9-12.
- Öneri: Beklenen minimum TimescaleDB sürümünü (by_range API: >=2.13) migration'da veya system check'te doğrulamak. (farm 0014'te `by_range` kullanılıyor.)

### F-694 Migration yaşam döngüsü: birleştirilmemiş squash yok, 26 farm migration'ı ve elle düzenlenmiş "Generated" migration'lar

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-16`
- Dosyalar: farm/migrations/0001..0026, experiments/migrations/0001_initial.py:1, farm/migrations/0014_water.py:1, farm/migrations/0015_feeding_protocols.py:1
- Açıklama: Merge migration ihtiyacı yok (tek yaprak/uygulama; `replaces` yok). Birçok migration "Generated by Django ... elle düzenlendi" notu taşıyor; elle düzenlenen kısımlar (hypertable, composite FK, trigger) `makemigrations`'ın bunları fark etmeyeceği nesneler: composite FK'ler (experiments 0001:364, messaging 0001:170) Django durumunda yok, şema/DB sapması yalnızca testle yakalanır (experiments/tests/test_migrations.py).
- Kanıt: experiments 0001:364 `RunSQL(COMPOSITE_KEYS, DROP_COMPOSITE_KEYS)`; messaging 0001:170.
- Öneri: Bu "Django dışı" nesneler için tek bir şema-katalog testi (pg_constraint/pg_trigger) ve docs listesi.

### F-695 Güçlü yanlar

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `15-15`
- Dosyalar: core/models.py, farm/models/stock.py, hr/models/posting.py, reports/models.py, messaging/models.py
- Açıklama: Defter satırlarında işaret/ödeme CHECK'leri, tarih aralığı ExclusionConstraint'leri (btree_gist), mesaj-konuşma bileşik FK mantığı (`participant_in_conversation`), donmuş rapor tetikleyicileri, GeneratedField'lar (Tank hacmi, search_vector), `period_start` takvim CHECK'leri iyi düşünülmüş. Eksiklik değil, doğrulandı.
- Kanıt: ilgili model Meta.constraints blokları.
- Öneri: Yok.

### F-696 İşlem sınırı politikası belgesiz: `ATOMIC_REQUESTS` yok, izolasyon varsayılan; doğruluk her servisin kendi `atomic`'ine bağlı

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-13`
- Dosyalar: config/settings.py:121, core/crud.py:678, 723, 769, 811
- Açıklama: `core/crud` her yazma görünümünde açıkça `atomic` açıyor (iyi), fakat `Document.save`, `softdelete.restore`, `align_placements`, `withdraw` gibi genel fonksiyonlar çağıranın işleminde olduğunu varsayıyor ve belgede (docstring) bu her yerde yazmıyor. Yeni bir çağıran işlem açmazsa kısmi yazma oluşur.
- Kanıt: `softdelete.execute` docstring "inside the caller's transaction" (softdelete.py:175) yalnızca bunda var; `align_placements` (hr/services.py) kendi `atomic`'ini açar ama `restore` açmaz.
- Öneri: Çağıranın işlemde olmasını gerektiren fonksiyonlara `transaction.get_connection().in_atomic_block` doğrulaması veya `@transaction.atomic` ekle.

### F-697 Sensör/otomatik ingest yolu yok.

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-1`
- Dosyalar: farm/feeding/temperature.py:3-4, farm/water/services.py, README.md:1062-1068
- Açıklama: Tek yazıcı elle giriş formudur (`record`, `record_round`); `temperature.py` docstring'i "Sensors will be one more source" der ama hiçbir ingest, API ucu, toplu yükleme veya `source` değeri sensör için tanımlı değildir.
- Kanıt: `Source` seçenekleri meter/kit/lab (farm/models/water.py:24 civarı, README:1055).
- Öneri: Sensör verisi planlanıyorsa ayrı bir geniş-şekilli ham tablo/hypertable, cihaz kimliği, idempotent toplu yazma ve kalibrasyon/kalite bayrağı tasarımı ADR olarak yazılmalı.

### F-698 TimescaleDB yalnızca geliştirme compose'unda tanımlı.

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-10`
- Dosyalar: docker-compose.yml:5, README.md:4, config/settings.py:110-123
- Açıklama: Sürüm 2.17.2-pg17 sabit; üretim DB'si için repoda yapılandırma/uyumluluk (managed PG'de timescaledb eklentisi olmayabilir; `CREATE EXTENSION` migration'ı `core/migrations/0001_timescaledb.py` başarısız olur) belgelenmemiş.
- Öneri: Üretim gereksinimi ve sürüm uyumluluğu (by_range API >= 2.13) belgelensin.

### F-699 Geri alma (reverse) davranışı:

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-11`
- Dosyalar: core/migrations/0001_timescaledb.py:11-12, farm/migrations/0014_water.py:102
- Açıklama: `RunSQL` ters adımları noop; `0014` geri alınırsa tablo ve chunk'lar düşer (CreateModel tersi) — veri kaybı. Eklenti kaldırılmaz. Kayıt amaçlı (dokümante edilmiş, 0014:94-95).

### F-700 Saat dilimi mimarisi tutarlı:

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `17-12`
- Dosyalar: config/settings.py:160,167, farm/models/site.py:185-188, farm/stock/dates.py
- Açıklama: DB `timestamptz`, `TIME_ZONE='UTC'`, `USE_TZ=True`; günler site saat diliminde (`zone_of`, `start_of`/`end_of` ZoneInfo ile). `farm/feeding/read.py:115` UTC gece yarısı kullanır ama -1 gün + 7 günlük geri bakış payı ile kapsanır; hata bulunmadı. Pozitif doğrulama kaydı.

### F-701 Batch.input_date ile giriş operasyonu tarihi bilinçli çift kaynak; yalnızca tarayıcı denetliyor

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-14`
- Dosyalar: farm/models/stock.py:174-176, 211; farm/stock/integrity.py:47-48; farm/stock/services.py:153
- Açıklama: `input_date` "listeler için tek değer" olarak Batch'te tutuluyor, aynı gün giriş operasyonunda da var; servis ikisini yazıyor, `correct_batch` bu alanı değiştirmiyor (BatchDetailsForm yalnızca year_class/provenance). Void edilip yeniden girişte ikisi birlikte yeni olur. Risk: admin (farm/admin.py:35 list_display) veya SQL ile tek taraflı değişiklik; yalnızca `check_stock` yakalar. Bilgi amaçlı.
- Kanıt: integrity.py:47-48 kuralı.
- Öneri: `input_date`'i operasyondan türeyen GeneratedField/annotation yap veya admin'de salt-okunur yap (admin.py'de readonly olduğu doğrulanmadı).

### F-702 Yemleme toplamları ekrandan ekrana farklı tanımlanıyor (üretim+temizleyici balık, iptal edilenler)

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-11`
- Dosyalar: farm/feeding/views.py:116-118 ve 418-433, farm/feeding/views.py:186-188
- Açıklama: Üretim genel bakışındaki "Feed today / last 7 days" kutucukları temizleyici balık yemini de toplar (`target` süzülmez); by-day görünümünde, SFR/FCR'de ve `Week` içinde temizleyici balık ayrı tutulur (D-1). Kayıt listesinde `count` iptal edilenleri de sayar (voided=1 iken) ama `kilos` yalnızca iptal edilmemişleri toplar; "N kayıt, X kg" satırı aynı kümeyi tanımlamaz.
- Kanıt: `FeedingRecord.objects.filter(date__range=...).aggregate(today=Sum(...), week=Sum('amount_kg'))` target süzmeden (views.py:425-426); `records.aggregate(count=Count('pk'), kilos=Sum('amount_kg', filter=Q(is_deleted=False)))` (views.py:116).
- Öneri: Kutucuklarda hedefi (üretim/temizleyici) belirtin ya da ayırın; `count` ve `kilos` için aynı filtreyi kullanın.

### F-703 Biçim/okunabilirlik: `read.py` içinde tek satırda boşluklu `else None`

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-15`
- Dosyalar: farm/feeding/read.py:457
- Açıklama: `in_use = current if ... >= stock[unit.pk].since else None` ifadesinde uzun boşluk dizisi var (satır sonu devamı birleşmiş görünüyor); geçerli Python ama bakım/linter açısından tutarsız.
- Kanıt: read.py:457.
- Öneri: Satırı normal biçimlendirin.

### F-704 "N of M units with fish now" etiketi geçmiş haftalara güncel stokla uygulanıyor

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-12`
- Dosyalar: `farm/health/views.py:286-288`, `templates/farm/lice_list.html:56`
- Açıklama: `week.stocked` her hafta için bugünkü stoklu birim sayısıdır. Etiket "units with fish now" dediği için yanıltıcı değil, ancak geçmiş bir hafta için "3 of 4" göstermek o haftanın kapsama durumunu yansıtmaz (kapsama hesabı yalnızca rapor modülünde `_coverage` ile doğru yapılıyor).
- Kanıt: `views.py:286` `stocked = read.stocked_by_site(_units_with_fish(production=True))` her hafta için aynı.
- Öneri: Geçmiş haftalar için etiketi gizle veya o haftanın stok durumunu kullan.

### F-705 Derece-gün bilinmiyorsa gün cinsinden alt sınır dikkate alınmıyor

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-16`
- Dosyalar: `farm/health/withdrawal.py:225-234`
- Açıklama: Hem gün hem derece-gün verilen kuralda derece-gün sonu hesaplanamazsa (`by_degrees is None`) sonuç tamamen "bilinmiyor" olur; kesin olarak bilinen gün tabanlı alt sınır (`by_days`) gösterilmez. Muhafazakâr ve güvenli, ancak kullanıcıya "en erken şu tarihten önce olmaz" bilgisi verilemiyor.
- Kanıt: `withdrawal.py:229-230` `if by_degrees is None: until, estimated = None, True`.
- Öneri: Bilinmeyen sonu korurken `by_days`'i ayrı bir "en erken" bilgisi olarak sakla.

### F-706 Sınırdaki değerin durumu iki yargılayıcıda farklı: eşitlik `evaluate.judge`'da iç banda, `deffeyes.judge`'da kritik banda

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-9`
- Dosyalar: farm/water/evaluate.py:46-55, farm/water/deffeyes.py:137, farm/water/calculation.py:83
- Açıklama: Limit satırı için "sınıra eşit değer iç banttadır" (`<`/`>` katı). `deffeyes.judge` ise `margin <= 0` ile sınıra eşit pH'ı kritik sayıyor ve `margin <= ALERT_PH` ile uyarı sınırını dahil ediyor. Simülatörün pH adımı `judge_bounds` ile (eşitlik iç bant) yargılanırken NH₃/H₂S/CO₂ adımları `deffeyes.judge` ile (eşitlik kritik) yargılanıyor: aynı `JudgedStep` içinde iki kural. Ölçüm hassasiyeti (float) nedeniyle pratikte nadir ama tutarsız.
- Kanıt: `status = Status.CRITICAL if margin <= 0 else Status.WARNING if margin <= ALERT_PH else Status.OK`.
- Öneri: Kararı tek yerde belgeleyin; tercihen `margin < 0` ile `evaluate`'ın "eşitlik iç banttadır" kuralına uyun.

### F-707 Silinen yem / pasif yem durumları: giriş ekranı yalnız ACTIVE yem sunuyor ama sayımın "bulunan lot"u tüm yemleri sunuyor

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-18`
- Dosyalar: inventory/forms.py:208, 370
- Açıklama: `ReceiptLineForm` yalnız `Feed.Status.ACTIVE`, `FoundLotForm` ise `Feed.objects.order_by('name')` (pasif yemler dahil). Tutarsız; pasif yemin stoğu sayımla sisteme girebilir.
- Öneri: Bilinçli ise belgele, değilse hizala.

### F-708 İlaç stoğu (kapsam: yem/ilaç) uygulanmamış; `LOT_REQUIRED` ve integrity ilaç kuralları test edilemez ölü kod

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-9`
- Dosyalar: inventory/models.py:132-141,150, inventory/services.py:45-47,94-97, inventory/integrity.py:344-346, inventory/forms.py:29
- Açıklama: `InventoryItem` tek bağ `feed`; DB check `feed IS NOT NULL`; `SupplyCategory.MEDICINES` için lot numarası/SKT zorunluluğu kodu var ama hiçbir yol buna ulaşamıyor. README bunu planlı olarak belirtiyor (health modülü). `Medicine` eklendiğinde `chk_inventory_items_one_link` (şu an `feed__isnull=False`), `category` GeneratedField, `ReorderLevel.ordering = item__feed__name`, `InventoryItem.ordering`, `read.overview` (`record.item.feed_id`), `read._feeding`, integrity `item.feed_id is None` kontrolü ve `label()` (`item.product.code`) birlikte güncellenmeli; birden çok yer feed'e sabit bağlı.
- Öneri: Medicine geçişi için kontrol listesi/test ekle; o zamana dek ölü kodu işaretle.

### F-709 Tamamlama, açık checklist satırlarını denetlemez

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-11`
- Dosyalar: `tasks/services.py:117-133`
- Açıklama: `complete` tikli olmayan satırlar varken de görevi tamamlar; uyarı yok. İş kuralı olarak tanımlı olmayabilir ama checklist'in amacıyla (saha kontrol listesi) çelişir.
- Kanıt: `complete` yalnızca durum ve yetkiyi kontrol eder.
- Öneri: Karar belgele; en azından UI'da onay uyarısı.

### F-710 `reopen` orijinal başlangıç bilgisini siler ve durum geçişi tek yönlü

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-12`
- Dosyalar: `tasks/services.py:151-169`, `tasks/models.py:326-332`
- Açıklama: Devam ediyor görevi tamamlanıp yeniden açılınca `started_at/by` sıfırlanır (yalnız audit'te kalır); "in_progress -> open" geri dönüş yolu yok (yanlış Start geri alınamaz, yalnız cancel+reopen).
- Kanıt: `task.started_at = task.started_by = ... = None` (reopen).
- Öneri: İhtiyaca göre "stop/unstart" ekle veya karar belgele.

### F-711 Atama filtresi, artık seçilemeyen kullanıcıların görevlerini süzemez

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-16`
- Dosyalar: `tasks/resources.py:112-117`
- Açıklama: `assignee` filtresi yalnızca `read.readers()` içindeki kullanıcıları kabul eder; yetkisi alınmış/pasif kullanıcıya atanmış görevler (README: "kalır, işaretli") kişiye göre filtrelenemez.
- Kanıt: `params['assignee'] in {str(pk) for pk in people.values_list('pk', flat=True)}`.
- Öneri: Filtre seçeneklerine mevcut atananları da ekle.

### F-712 Sertifika/yetkinlik/eğitim kavramı HR modülünde yok

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-17`
- Dosyalar: hr/models/ (employee.py, leave.py, scheduling.py)
- Açıklama: Çalışan, izin, vardiya var; sertifika, eğitim veya yetkinlik (ör. balıkçılık/dalış/gıda hijyeni sertifikası) modeli yok, vardiya atama sertifika süresi kontrolü yapmaz. Repo genelinde "certif" yalnızca eski platform hata dokümanında ve tedarikçi alanında geçer (docs/aquaculture-platform-bugs.md:956 STK-72 "health certificates marked required but never checked").
- Kanıt: `grep -ri certif hr/` boş.
- Öneri: Kapsam kararı: ihtiyaçsa ayrı model ve vardiya/rol kuralı; değilse README'de açıkça belirt.

### F-713 Rapor okuma izni (`reports.view_report`) tüm sitelerin canlı hesaplanan verisini açar (02-6 ile çakışır)

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-18`
- Dosyalar: reports/views.py:31-35, 202-226, reports/resources.py:122-124
- Açıklama: Export/print/detay yalnızca model izni ister; `queryset()` site kapsamı uygulamaz ve taslak içerik stok/yem/ilaç/lice kayıtlarından anlık üretilir. Authz uzmanı bunu 02-6 olarak kaydetmiş; burada yalnızca raporlar tarafında kanıtlandı: `ReportResource.queryset()` tüm `Report.objects`'ı döner.
- Kanıt: resources.py:123 `Report.objects.select_related(...)` (filtre yok).
- Öneri: 02-6 önerisiyle birlikte ele alın.

### F-714 İstatistik katmanı yok; `error_df` yalnız sayım

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-13`
- Dosyalar: experiments/read.py:77-81, experiments/variables.py, docs/experiments.md (Not here)
- Açıklama: Test, güç analizi, veri seti ve bitiş raporu bilinçli olarak kapsam dışı. `error_df` tanksız replikatları da sayar (tasarım düzeyi), yalnız `edit_extras`'ta gösterilir. Birincil uç nokta yalnız 4 çiftlik türevi (bfcr, efcr, survival, biomass_gain); ağırlık/büyüme yok. Birincil uç nokta Overview'da vurgulanmıyor.
- Kanıt: variables.py:95-99; read.py:77-81.
- Öneri: Yol haritasında izlensin.

### F-715 "closed" durumu erişilemez/kullanılmıyor

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-14`
- Dosyalar: experiments/models.py (TRANSITIONS), experiments/read.py:215-218, experiments/migrations/0002_design_frozen.py, docs/experiments.md
- Açıklama: `running -> closed` geçişi, tetikleyici dalları ve `window_end(closed)` var ama kapatan servis/arayüz yok ("Only Start is built here"). Deneyler sonsuza dek "running" kalır; durum filtresi "Closed" seçeneğini sunar ama sonuç hep boştur; kapalı yollar test edilmemiş kod riski taşır.
- Kanıt: services.py'de `Status.CLOSED` atayan fonksiyon yok.
- Öneri: Yaşam döngüsü planı gelene kadar belgelenmiş durum olarak kalsın.

### F-716 Doküman referansı olmayan dosyaya: plan/area1/PLAN.md

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-15`
- Dosyalar: docs/experiments.md ("Where the code differs from the plan")
- Açıklama: Doküman "plan/area1/PLAN.md" planından sapmaları anlatır ama depoda `plan/` dizini yok; sapma listesi doğrulanamaz.
- Kanıt: `ls /home/user/tromso-mvp/plan` -> yok.
- Öneri: Planı depoya ekle veya bölümü kaldır.

### F-717 Start içinde değerlendirme iki kez yapılıyor

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-16`
- Dosyalar: experiments/services.py:655-662, experiments/resources.py:307
- Açıklama: `design_module.assess(locked)` uyarılar için tekrar çağrılır (aynı işlem içinde aynı sonuç, gereksiz sorgu); görünüme de bir kez daha (kilitsiz) çağrılır. Davranış hatası değil, performans/netlik.
- Kanıt: services.py:655 ve 662.
- Öneri: İlk `assessment.warnings` metinleri `audit.source_language()` altında yeniden üretilebilir; ikinci tam değerlendirme gerekmez.

### F-718 Dokuman/kod tutarsizligi kucuk notlari:

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-16`
- Dosyalar: README.md:2559-2562, knowledge/screens.py:21-25, templates/knowledge/entry_form.html
- Açıklama: Dokuman/kod tutarsizligi kucuk notlari: README "Review tab of its dialog" der ve form sablonu bunu saglar (dogru); README'nin ajan bolumunde `knowledge_rules` tablosu "yok" olarak isaretli, ama `Topic` aciklamasi ve form yardim metni "AI agents will read ..." diye mevcut gibi yazar. Ek olarak `DocumentPage.screen` ozelligi yalniz sablonda kullanilir; testlerde dogrudan kapsami yok.
- Kanıt: models/common.py:15-17 docstring; forms/entry.py:131 yardim metni.
- Öneri: Kullaniciya gorunen metinde "gelecekte" ifadesi kullan.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-719 Mesaj gönderme için hız sınırı / spam koruması yok

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-15`
- Dosyalar: messaging/views.py:92-103; messaging/services.py:232-248
- Açıklama: Her kullanıcı sınırsız sıklıkta mesaj yazabilir; poll 5 sn, tek mesaj 4000 karakter. Asistanlar eklendiğinde taşma riski artar.
- Kanıt: Sınırlama kodu yok.
- Öneri: Kişi/konuşma başına oran sınırı.

### F-720 Test boşlukları

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-18`
- Dosyalar: messaging/tests/test_pages.py, test_services.py
- Açıklama: Bulunmayan testler: bozuk `before/after` parametreleri (29-5), POLL_LIMIT=200 taşması, >50 okunmamışta işaretçi (29-7), son üye ayrılınca yetim kanal davranışı yalnızca "izin verilir" olarak sabitlenmiş (29-1), olay dinleyicisi istisnası (29-6), eşzamanlı remove/leave yarışı, asistan katılımcısı ile `post`/`title`. Eşzamanlı `start_direct` testi var (iyi).
- Kanıt: grep sonucu: POLL_LIMIT ve kötü parametre testi yok.
- Öneri: Yukarıdaki durumlar için test ekleyin.

### F-721 Başlık: Site.country/region/state serbest metin; ülke-bölge-lice_area ilişkisi doğrulanmıyor

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-15`
- Dosyalar: farm/models/site.py:70-75, 105-108; farm/models/site.py:21-27
- Açıklama: lice_area (kuzey/güney) kullanıcı tarafından ayrıca seçiliyor; region/lokalitet/enlem ile tutarlılığı kontrol edilmiyor, yanlış alan seçimi yanlış yasal eşik haftası uygulatır. Bilgi amaçlı.
- Kanıt: forms/site.py:13-24 alanlar bağımsız; kontrol yok.
- Öneri: Enlemden varsayılan öner/uyarı ver.

### F-722 Tutarsız app iç düzeni

Önem: **Bilgi** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-10`
- Dosyalar: farm/, hr/, experiments/, inventory/, monitoring/, reports/
- Açıklama: farm alt paketlere (feeding/stock/water...), hr kısmen (models/, forms/, resources/), experiments/inventory/monitoring tek dosya modüllerle düzenlenmiş; "read/services/views/screens/resources/integrity" adlandırma kalıbı ortak ama paketleme farklı.
- Kanıt: `ls` çıktıları: experiments/models.py, inventory/models.py, monitoring/models.py (dosya) vs hr/models/, farm/models/ (paket); experiments/services.py 886 satır.
- Öneri: Büyüyen tek dosyalı modülleri (experiments/services.py) bölmek için eşik belirle.

### F-723 Fonksiyon-içi (lazy) cross-app import'lar

Önem: **Bilgi** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-13`
- Dosyalar: hr/scope.py, monitoring/read.py, farm/health/notices.py
- Açıklama: Döngüyü/yükleme sırasını aşmak için lazy import'lar var (hr/scope.py:188, monitoring/read.py:285 `from farm import placements`); izlenmesi zor, statik analizle görülmez.
- Kanıt: hr/scope.py:188 (`from farm.models import ProductionDepartment`), hr/scope.py:213 (`from core.crud import mount_of`), monitoring/read.py:285.
- Öneri: Mümkünse üst-seviyeye taşı veya import kuralı testi ekle.

### F-724 Kullanılmayan değişkenler / döngü değişkenleri (üretim kodu)

Önem: **Bilgi** | Güven: yüksek | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-8`
- Dosyalar: experiments/forms.py, experiments/services.py, monitoring/cards/resolve.py
- Açıklama: B007: kullanılmayan döngü değişkenleri `group`, `replicate`, `why`; testlerde ayrıca 5 F841 (atanmış ama kullanılmayan `response`, `late`, `low`, `unit`).
- Kanıt: experiments/forms.py:491; experiments/services.py:428; monitoring/cards/resolve.py:134; hr/tests/test_employees.py:28, tasks/tests/test_pages.py:269, experiments/tests/test_pages.py:299, farm/tests/test_protocols.py:885.
- Öneri: `_` öneki ya da silme.

### F-725 hr.views.plan: anlamsız 'except PermissionDenied: raise' ve 'cells' ayrıştırma hatasında nedensiz boş 400

Önem: **Bilgi** | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-13`
- Dosyalar: hr/views.py
- Açıklama: 'except PermissionDenied: raise' (hr/views.py:80-81) davranışı değiştirmez, ölü koddur (yalnızca ValidationError/IntegrityError'dan önce sıralama niyeti olabilir). Biçimi bozuk 'cells' veya bilinmeyen vardiya için HttpResponseBadRequest() cevabında neden yok; gerçek kullanıcı formlarında bu durum yalnızca sahte istekte oluşur, bu nedenle etkisi düşük.
- Kanıt: hr/views.py:60-74, 78-88.
- Öneri: Gereksiz except'i kaldırın; 400 yanıtlarına kısa neden ekleyin.

### F-726 `DB_CONN_MAX_AGE` varsayılanı 0; kalıcı bağlantı + advisory xact kilitleri güvenli, ancak ayar belgesi/dağıtım tanımı yok

Önem: **Bilgi** | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-11`
- Dosyalar: config/settings.py:117-123, README.md:2991, docker-compose.yml
- Açıklama: Varsayılan 0, `CONN_HEALTH_CHECKS=True` (bağlantı yeniden kullanımdan önce kontrol). Advisory kilitler `pg_advisory_xact_lock` (transaction kapsamlı) olduğundan kalıcı bağlantıda kilit sızıntısı olmaz. Repoda gunicorn/worker sayısı/pool için yapılandırma yok; `DB_CONN_MAX_AGE>0` ile worker×thread sayısı Postgres `max_connections` ile ilişkilendirilmemiş (yalnızca runserver uyarısı var). Uygulama `ATOMIC_REQUESTS` kullanmıyor; servisler kendi `atomic` bloklarını açıyor.
- Kanıt: settings.py:121-122.
- Öneri: Dağıtım dokümanına worker/thread/max_connections hesabı ekleyin.

### F-727 Süreç-içi paylaşılan durum: `monitoring.read.FAILED_AT` ve `lru_cache`

Önem: **Bilgi** | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-13`
- Dosyalar: monitoring/read.py:86, monitoring/read.py:270-278, farm/water/chemistry.py:344
- Açıklama: `FAILED_AT` sözlüğü her worker'da ayrı ve kilitsiz (GIL altında güvenli, yalnızca log hız sınırı; çoklu worker'da dakikada bir yerine worker başına bir log). `equilibria` `lru_cache`'i saf fonksiyon, güvenli. Uygulamada `CACHES`, `threading`, global değişken durumu başka yok.
- Kanıt: ilgili satırlar.
- Öneri: Gerekmez.

### F-728 Test altyapisi: MD5 hasher ve tek DB; paralel kosu icin yonerge sinirli

Önem: **Bilgi** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-13`
- Dosyalar: config/test_runner.py:6-9, config/settings.py:124, README.md
- Açıklama: Testlerde MD5 hasher aciliyor; bu hizlandirir ama parola dogrulama/uyumluluk (hasher yukseltme, `check_password`) davranislarini gercek hasher ile denemez. Ayrica TimescaleDB eklentisi gerektirdigi icin testler yalniz gercek Postgres ile calisir (SQLite yok); `--parallel` kullanimi belgelenmemis, iki kosu icin `DB_TEST_NAME` elle verilmeli.
- Öneri: hasher'a bagli tek bir test, README'ye paralel kosu notu.

### F-729 Testler calistirilamadi (dogrulama siniri)

Önem: **Bilgi** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-15`
- Dosyalar: requirements.txt, docker-compose.yml
- Açıklama: Denetim ortaminda Django kurulu degil, `pg_isready -p 5433` yanit vermedi; yesil/kirmizi durum, gercek skip sayisi ve sure olculemedi. Kapsam (coverage) araci repoda yapilandirilmamis (coverage/pytest-cov yok).
- Öneri: coverage ayari ekle; ilk CI kosusunda skip sayisini raporla.

### F-730 Middleware dogrudan test edilmiyor

Önem: **Bilgi** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `36-8`
- Dosyalar: core/middleware.py:1-15, core/tests_workspaces.py
- Açıklama: `WorkspaceMiddleware` icin ozel test dosyasi/ad eslesmesi yok; yalniz `navigation.workspace_of` ve calisma alani testleri dolayli kapsiyor. Oturum anahtari yazma davranisi (degismediginde yazmama) dogrulanmiyor olabilir.
- Öneri: kucuk bir birim testi.

### F-731 Dağıtım/operasyon dokümantasyonu eksik (runbook, sürümleme, geri alma)

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `37-18`
- Dosyalar: README.md (2977-2995 "Local setup"), docs/
- Açıklama: README ~3300 satır ve 320 KB, ancak "Deploy/Production/Operations" bölümü yok; docs/ altında dağıtım, rollback, migration sırası, sürüm etiketleme, ortam matrisi belgesi yok (yalnızca özellik ve i18n belgeleri). Git deposunda sürüm etiketi/CHANGELOG izi doğrulanmadı.
- Kanıt: `ls docs` -> aquaculture-platform-bugs.md, data-map.*, experiments.md, hr-launch-checklist.md, i18n.md, regulatory-reports.md; README'de "gunicorn" yalnızca DB_CONN_MAX_AGE açıklamasında geçer.
- Öneri: docs/deploy.md: topoloji, build sırası, migrate stratejisi (sıfır kesinti), geri alma, yedek/geri yükleme, izleme.

### F-732 Poll istemcisi `Retry-After` başlığını yok sayar

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-13`
- Dosyalar: monitoring/views.py:67-72, frontend/poll.ts:196-199
- Açıklama: Sunucu 503'te `Retry-After: 30` gönderir; poll.ts `!response.ok` -> `failed()` (kendi geri çekilmesi) ve başlığı okumaz (`grep Retry-After frontend/poll.ts` boş). Sunucunun beklenen aralığı ile istemcinin geri çekilmesi birbirinden bağımsız.
- Kanıt: dosyalar yukarıda.
- Öneri: `Retry-After` varsa gecikme için kullan veya sunucu başlığını kaldırıp belgeleyin.

### F-733 `document_file` `?download` değerinden bağımsız indirir

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-16`
- Dosyalar: knowledge/views.py:33
- Açıklama: `as_attachment='download' in request.GET` — `?download=0` bile indirmeye zorlar. Ayrıca PDF yanıtı `X-Content-Type-Options` yalnız SecurityMiddleware varsayılanına bağlı (dosyada açık belirtilmedi).
- Kanıt: satır 33.
- Öneri: `request.GET.get('download') in ('', '1')` gibi açık kural.

### F-734 Sözleşme testi yalnızca `data-poll*` kancalarını kapsar

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-18`
- Dosyalar: core/test_frontend_contract.py:1-40
- Açıklama: Şablon <-> poll.ts sözleşmesi test edilmiş; ancak `X-Modal`, `X-Modal-Redirect`, `X-Modal-Load`, `X-Poll-Next` başlık adlarının sunucu (core/crud.py:102-109, monitoring/views.py:136, messaging/views.py:121) ve istemci (components.ts:339-344, poll.ts:201) arasında eşleştiğini doğrulayan bir sözleşme testi yok; ad değişikliği sessizce kırar. Designer JSON yanıt şeması da testsiz.
- Kanıt: dosya başlığı yalnızca `data-poll|live|scroll-end|submit-on-enter` regex'i.
- Öneri: başlık sabitlerini tek yerden paylaşan/doğrulayan test.

### F-735 Durum değiştiren GET'ler (okundu işareti, oturum yenileme)

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `38-9`
- Dosyalar: messaging/views.py:63-80 (`conversation`), messaging/views.py:108-122 (`poll`), monitoring/views.py:50-58
- Açıklama: `GET /messages/<id>/` ve `GET /messages/<id>/new/` `mark_read` ile veritabanına yazar; `GET` monitoring `?wall=1` günde bir oturumu yeniler. Docstring'ler bunu belgeliyor (bilinçli) ancak GET'in güvenli/önbelleklenebilir olması varsayımını ihlal eder; prefetch/link önizleme araçları mesajları okundu işaretler. Poll yanıtı `no-store` olduğundan önbellek riski düşük.
- Kanıt: `services.mark_read(participant, ...)` GET içinde.
- Öneri: belgeleyin; mümkünse okundu işaretini ayrı bir POST/beacon'a taşıyın.

### F-736 Bug belgesi dis repo (`aquaculture_platform`, commit 352aa2a8) kaynagina baglidir ve "yeni tab portlandikca buyur" der;

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-15`
- Dosyalar: docs/aquaculture-platform-bugs.md:7-8, README.md:3238
- Açıklama: Bug belgesi dis repo (`aquaculture_platform`, commit 352aa2a8) kaynagina baglidir ve "yeni tab portlandikca buyur" der; atiflanan dosya yollari (`*.entity.ts` vb.) bu repoda yoktur ve dogrulanamaz. Belge "✔" olmayan maddelerin dogrulanmasi gerektigini kendisi belirtir; dogru ama kullanici icin ayrica bir uyari yeterli.
- Kanıt: belge basligi; dis yollar `find` ile bulunamadi.
- Öneri: Kaynak commit'in erisilebilir oldugu notu (veya arsiv) eklensin.
- Not: kaynak kayıtta başlık yoktu; başlık açıklamanın ilk cümlesinden türetilmiştir.

### F-737 satirlar yukarida ve config/settings.py, core/dbgrid.py:25-26, frontend/nav-boot.ts:5.

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `39-16`
- Dosyalar: README.md:3396-3408, docs/data-map.md:1-5
- Açıklama: Dogrulananlar (tutarli): komut adlari ve seed_hr_demo DEBUG kosulu ve demo kullanici adlari, DB_TEST_NAME, DJANGO_MEDIA_ROOT, KNOWLEDGE_MAX_FILE_BYTES=20 MB, STOCK_BACKDATE_DAYS=31, EXPORT_LIMIT=50.000, PAGE_SIZE=100, rail 296/110 px, AUTO_COLLAPSE_BELOW=1100, audit_log append-only trigger, hr_roles rolleri, TabRulesTests/TabTranslationTests varligi, Layout tablosundaki dosya yollarinin tamami mevcut, THIRD_PARTY.md paketleri package.json ile uyumlu.
- Kanıt: ilgili
- Öneri: Yok.

### F-738 Çalışma ağacında takipsiz docs/audit/ ve temiz-olmayan durum

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-15`
- Dosyalar: docs/audit/
- Açıklama: `git status --short` yalnızca `?? docs/audit/` gösteriyor (denetim çıktıları); başka kirlilik yok.
- Kanıt: `git status --short`.
- Öneri: Denetim çıktıları commitlenecekse ayrı bir commit ile, değilse .gitignore'a.

### F-739 Commit'ler imzasız, tek yazar, noreply e-posta

Önem: **Bilgi** | Güven: yüksek | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-6`
- Dosyalar: .git
- Açıklama: Tüm 299 commit tek kimlikten; `%G?` = N (imzasız). Review/ikinci göz izi yok (denetim izi açısından zayıf).
- Kanıt: `git log --format='%an <%ae>' | sort | uniq -c` -> 299 Okan-wqm; `%G?` N.
- Öneri: Üretim öncesi imzalı commit/branch protection değerlendirilsin.

### F-740 `load()` içindeki yorum ile davranış çelişiyor

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-20`
- Dosyalar: `frontend/windows.ts:125-129`
- Açıklama: Yorum "bring it forward, close this one" der; kod yalnızca öteki pencereyi öne alır, mevcut pencereyi kapatmaz ve bağlantı tıklamasını yutar (kullanıcı hiçbir değişiklik görmez).
- Öneri: yorumu düzelt ya da davranışı yorumla hizala.

### F-741 `NavState.saved()` türü gevşek; `shell.ts` `window.suderraNav` varlığını varsayıyor

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-24`
- Dosyalar: `frontend/globals.d.ts:3-5`, `frontend/nav-boot.ts:53`, `frontend/shell.ts:73,89`
- Açıklama: `saved(): string | null` oysa yalnızca `'open' | 'collapsed'` anlamlı; `localStorage` ham string döner. `nav-boot.js` yüklenmezse (klasik betik, başka şablon) `nav` `undefined` olur ve `nav.save` `TypeError` fırlatır; tip bildirimi her zaman var der.
- Öneri: `saved(): 'open' | 'collapsed' | null` olacak şekilde doğrula; `window.suderraNav?` koruması.

### F-742 Tasarımcı ile `types.ts` arasında yinelenen `Problem` tipi ve sabit kodlanmış sınırlar

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-28`
- Dosyalar: `frontend/designer.ts:39-44`, `frontend/grid/types.ts:361-365`, `frontend/designer.ts:214-216`
- Açıklama: İki farklı `Problem` arayüzü (sunucu sorunu vs. geometri sorunu) aynı ad altında; karışıklığa açık. Denetçide `y` için `999` ve `h` için `99` sabitleri sunucunun gerçek sınırlarından türetilmemiş (sunucu doğrulayıcısıyla eşleştiği doğrulanmadı). `grid/layout.ts`'deki `check` tasarımcıda kullanılmıyor (yalnızca testler), sunucu sorunlarına güveniliyor. `clamp` içinde `min_w > min(max_w, columns)` ise `within` alt sınırın altına düşer (satır 152).
- Öneri: sunucu tipi `ServerProblem` olarak adlandırılsın; sınırlar katalogdan gelsin.

### F-743 Başlık hiyerarşisi: sayfa `<h1>` sonrası doğrudan `<h3>` ve modalda `h2` + `h3`

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-16`
- Dosyalar: templates/crud/form.html:28,50, crud/_row_list.html:7, app_base.html:~82 (h1), modal_base.html:7 (h2)
- Açıklama: Form sekme panelleri `h3 panel-title` kullanıyor; sayfa modunda h1 -> h3 seviye atlıyor. Liste boş durumu `h2`. Ekran okuyucu gezinmesi için tutarsız.
- Kanıt: ilgili satırlar.
- Öneri: `h2` yap ya da bölüm başlıklarını CSS sınıfıyla ayır.

### F-744 Marka adı "Suderra" şablonlara sabit gömülü, çevrilemez ve repo adıyla uyumsuz

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-9`
- Dosyalar: templates/app_base.html:9, auth_base.html:6,18, _workspace_brand.html:3, farm/water_calculator_report.html:10
- Açıklama: 5 yerde ham metin; repo "tromso-mvp". Marka değişimi şablon taraması gerektirir.
- Kanıt: `· Suderra</title>`, `<p class="brand">Suderra</p>`.
- Öneri: tek context değişkeni/ayar (`BRAND_NAME`).

### F-745 Rail altbilgisi ve varsayılan başlıklar sabit/yer tutucu: "Fish farm", "Panel"

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-17`
- Dosyalar: templates/app_base.html:6,61,69-70
- Açıklama: `rail_foot` varsayılanı "Fish farm", `eyebrow` varsayılanı "Panel", `heading` varsayılanı "Overview"; bir şablon bloğu doldurmayı unutursa yanlış bağlam ("Panel · Overview") görünür. Panel adı (Company/Production) eyebrow'da dinamik değil.
- Kanıt: `{% block eyebrow %}{% trans "Panel" %}{% endblock %}`, `{% block heading %}{% trans "Overview" %}`.
- Öneri: Varsayılanları `workspace.label` ve boş başlık yap; test ile doldurulmamış blok yakala.

### F-746 Kayıt oluşturma sonrası akış: Create -> düzenleme formu, Update -> liste (tutarsız)

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-9`
- Dosyalar: core/crud.py:700 (done(... stay=True)), core/crud.py:745
- Açıklama: Yeni kayıt kaydedilince diyalog/sayfa aynı kaydın düzenleme formuna geçer (sekmeli; History sekmesi için gerekçeli), düzenleme kaydedilince listeye dönülür. Kullanıcı "Create" sonrası listeye dönmeyi bekler; diyalogda ikinci bir "Cancel" ile kapatmak gerekir ve kapanışta sayfa yeniden yüklenir.
- Kanıt: `return done(request, self.url('edit', obj.pk), stay=True)` vs `return done(request, self.url('list'))`.
- Öneri: Davranışı bilinçli belge/ipucu ile belirt (ör. "Created. Add details" başlığı) ya da basit formlarda listeye dön.

### F-747 Yeni sekmede açılan bağlantılar ve yalnızca simge/kısaltma bağlantı metni

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-18`
- Dosyalar: `templates/knowledge/document_list.html:47`, `templates/knowledge/document_detail.html:35`, `templates/farm/calculator/_actions.html:2`, `templates/reports/outside_duties.html:47`
- Açıklama: `target="_blank"` bağlantılar yeni pencerede açıldığını belirtmiyor (WCAG 3.2.5 AAA/G201 önerisi). Doküman listesinde bağlantı metni yalnızca "PDF" (simge + kısaltma), hangi belge olduğu bağlamdan çıkarılıyor (satır bağlamı dışında okunduğunda anlamsız). `rel="noopener"` doğru kullanılmış.
- Kanıt: `document_list.html:47` `<a href=... target="_blank" rel="noopener">...PDF</a>`.
- Öneri: sr-only "(yeni sekmede açılır)" ve belge adını içeren erişilebilir ad.

### F-748 Parola göster/gizle düğmesinde hem değişen etiket hem `aria-pressed`

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-19`
- Dosyalar: `frontend/auth.ts:11-15`, `templates/registration/_field.html:166`
- Açıklama: Düğme etiketi Show/Hide olarak değişirken aynı anda `aria-pressed` de güncelleniyor; ekran okuyucu "Hide, toggle button, pressed" gibi çelişkili duyurur (etiket değişiyorsa `aria-pressed` kullanılmamalı veya etiket sabit kalmalı). Düğme `aria-controls` ile girdiye bağlı (iyi). Dokunmatik hedef `padding:.375rem .625rem` (~30px yükseklik).
- Kanıt: `auth.ts:13-14`.
- Öneri: Etiketi sabit tut ("Show password") + `aria-pressed`, ya da etiketi değiştir ve `aria-pressed`'i kaldır.

### F-749 Katalogda tırnak ve kesme işareti biçimi karışık

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-10`
- Dosyalar: `locale/tr/LC_MESSAGES/django.po` (örn. `Mesajlar'ı`, `pH'de`, `CaCO₃'ün`), `locale/nb/LC_MESSAGES/django.po`
- Açıklama: tr: 23 msgstr düz `'`, 92 msgstr `’`; 8 msgstr düz `"` ile 83 msgstr `“ ”` karışık. nb: 87 msgstr `« »` (doğru), ancak 1 msgstr İngilizce `“ ”` (`Hvor vannet tas, f.eks. “Sideutløp”...`) ve 2 düz `"` içeriyor.
- Öneri: Tek bir stil seçip (tr `’`/`“”`, nb `«»`) katalog testine ekleyin.

### F-750 Türkçede ayrı kavramlar aynı çeviriye çökmüş

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-11`
- Dosyalar: `locale/tr/LC_MESSAGES/django.po`
- Açıklama: `Cancelled` ve `Voided` ikisi de `İptal edildi`; `Cancel` = `İptal`, `Void` = `İptal et`. Sözlük `void` için `iptal etmek` seçmiş ama bir kayıt "iptal edilmiş" (void) mi "iptal edilmiş" (cancelled) mi ayırt edilemez. NB'de ayrı (`Avlyst` / `Annullert`).
- Öneri: `Voided` için `Geçersiz kılındı`/`Hükümsüz` gibi ayrı bir terim düşünün.

### F-751 Tarih biçimleme yardımcısı dört yerde kopyalanmış

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-12`
- Dosyalar: `farm/handling/check.py:53-54`, `farm/stock/dates.py:58`, `farm/templatetags/feeding.py:48`, `farm/templatetags/health.py:45`
- Açıklama: Hepsi `formats.date_format(day, 'DATE_FORMAT')`; ortak bir yerde toplanırsa 45-4 de tek noktadan çözülür.

### F-752 Etkinlik günlüğünün birleşik metinleri gettext dışı, İngilizce f-string

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-14`
- Dosyalar: `experiments/services.py:363-373`, `inventory/services.py:122-124,236-246`
- Açıklama: `describe_places`, `_lot_name`, `describe` İngilizce sabit sözcükler (`to`, `expires`, `lot`, `at`) ve `isoformat()` ile metin kuruyor. `docs/i18n.md` "composed text stays English in the log" diyerek bunu belgeliyor; yine de bu satırlar Türkçe/Norveççe okuyucuya İngilizce görünür, katalogda karşılığı yok. Kabul edilmiş tasarım sınırı olarak kaydedilir.

### F-753 Uygulama etiketleri ve PO başlığında yer tutucu/ad tutarsızlığı

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-15`
- Dosyalar: `inventory/apps.py:9`, `reports/apps.py:9`, `locale/tr/LC_MESSAGES/django.po:2-6`, `core/catalogs.py:101`
- Açıklama: `django.contrib.admin` kurulu (`config/settings.py:36`) ve `inventory/apps.py` `verbose_name = 'Storage'`, `reports/apps.py` `verbose_name = 'Reports'` çevrilebilir değil (diğer uygulamalarda yok). PO başlığı `Project-Id-Version: balik-ciftligi 1.0`, `Report-Msgid-Bugs-To: EMAIL@ADDRESS`, `Last-Translator: Suderra`; arayüz markası "Suderra", depo adı `tromso-mvp`.
- Öneri: `verbose_name`'i `gettext_lazy` yapın veya kaldırın; başlık alanlarını gerçek değerlerle doldurun.

### F-754 Şablonda sabit " %" son eki (Türkçede `%12` önek biçimi)

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `45-7`
- Dosyalar: `templates/farm/feed_list.html:47`
- Açıklama: Yüzde `{{ x|floatformat }} %` olarak sabit yazılmış; katalogdaki yüzde mesajları doğru biçimde yerelleştirilmiş (`%(value)s %%` -> tr `%%%(value)s`), ama bu hücre değil.
- Kanıt: `feed_list.html:47` `... / {{ feed.fat_pct|floatformat:"-2"|default:"–" }} %`; `locale/tr/LC_MESSAGES/django.po:1238-1239`.
- Öneri: Yüzdeyi ortak `percent` filtresinden geçirin.

### F-755 Breakpoint'ler tutarsiz (px/rem karisik, 8 farkli esik) ve JS ile esitlenmemis

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-16`
- Dosyalar: `static/css/app.css:370`, `static/css/auth.css:107` (`48rem`), `static/css/monitor.css:77` (639), `:236` (799), `static/css/messages.css:104` (899), `static/css/components.css:667,671,725` (720/900/1400), `frontend/shell.ts:6`, `frontend/windows.ts:29`, `frontend/nav-boot.ts:5` (1100)
- Açıklama: Kabuk `max-width:767px`, auth `max-width:48rem` (=768px, dahil): tam 768px'te auth mobil, kabuk masaustu duzeninde. JS `matchMedia` degerleri CSS ile elle esitlenmis (yorum/ortak kaynak yok); rail otomatik daraltma esigi 1100 yalniz JS'te.
- Öneri: Ortak breakpoint tablosu/yorum; auth'u `767px`e esitle.

### F-756 Tek parca `components.css` (1298 satir) her sayfada; bolme stratejisi tutarsiz

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-18`
- Dosyalar: `static/css/components.css:606-856` (hesap makinesi/grafik), `:868-1036` (veritabani gorunumu), `templates/app_base.html:13-15`
- Açıklama: HR, gorev, mesaj, izleme kendi dosyasinda `extra_head` ile yukleniyor ama su/hesap makinesi, veritabani gorunumu, rapor ve depo kurallari tum sayfalara giden `components.css`'te. Her sayfa 3 render-engelleyici CSS + 1 harici font; minify/birlestirme yok.
- Öneri: Yukleme stratejisini tek kurala bagla (modul basina dosya) ve uretim derlemesinde birlestir.

### F-757 Olu/yinelenen kurallar ve bayat yorumlar

Önem: **Bilgi** | Güven: yüksek | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-22`
- Dosyalar: `static/css/components.css:178` (yorum `site-form.js` - dosya yok), `:538` ve `:884-891` (`.data-table tbody th` iki kez), `:589` ve `:1196` (`.is-voided td` iki kez), `static/css/app.css:405-407` (`.rail` reduced-motion, `base.css:155-157` global kuralla yinelenen), `static/css/monitor.css:1-2` ("no colour of its own" ama sabit `rgba` golge var), `static/css/components.css:1293` (`.number`) vs `:544` (`.num`)
- Açıklama: Gercek anlamda olu sinif tespit edilen yok (96 aday sinifin tamami dinamik uretilen `badge-*`, `deffeyes-*`, `ph-*`, `tone-N`, `depth-N`, `audit-*` onekleri veya form-grid anahtarlari; `form-grid-basic/-contact` `site.py` anahtarlariyla eslesiyor). Ancak yukaridaki yinelemeler ve tutarsiz adlandirma (`num`/`number`) mevcut. README dosya tablosu (`README.md:3387-3392`) `hr.css`, `tasks.css`, `messages.css`, `monitor.css`'i listelemiyor.
- Öneri: Yinelenenleri birlestir, yorumu duzelt, README tablosunu tamamla.

### F-758 Görevler iş akışı kayıtlarından bağımsız: tamamlamak ilgili kaydı doğrulamıyor, olaydan görev doğmuyor

Önem: **Bilgi** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-12`
- Dosyalar: `tasks/services.py:117-131`, `tasks/models.py` (`batch`, `unit`, `equipment` bağları)
- Açıklama: `complete` yalnız durum/kullanıcı/not yazıyor; "besle", "tedavi kaydet", "sayım yap" gibi görevler ilgili yemleme/tedavi/sayım kaydıyla eşlenmiyor. Tersine, hiçbir modül görev üretmiyor (`Task(` yalnız `tasks/` içinde): arınma bitişi, SKT yaklaşan lot, geciken rapor, düşük stok görev/uyarı olarak akmıyor.
- Kanıt: `grep -rn "Task(\|Task.objects.create" ` `tasks/` dışında sonuç yok; `complete` içinde başka modüle erişim yok.
- Öneri: Kasıtlı basitlik ise belgelensin; değilse olay -> görev köprüsü (örn. arınma bitişi, SKT) planlansın.

### F-759 Durum makinesi tanımları tutarsız biçimde dağılmış

Önem: **Bilgi** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-12`
- Dosyalar: farm/models/tank.py:175, experiments/models.py:50, tasks/services.py (servis içi), hr/services.py (can_decide/can_cancel), knowledge/views.py:55-85
- Açıklama: Yalnızca Tank ve Experiment'ta açık `TRANSITIONS` sözlüğü var; Task, Leave, KnowledgeEntry geçişleri servis fonksiyonlarındaki if'lerde, FeedingProtocol form/clean içinde. Aynı model için tek kaynak yok, test ve doküman zorlaşır.

### F-760 Menüde gizli ama URL ile erişilebilen uçların listesi (hepsi aynı izne bağlı, ek sızıntı yok)

Önem: **Bilgi** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-10`
- Dosyalar: config/navigation.py:70-72 (hidden=True: Shifts, Holidays, Leave types), 49-77 (`show_when=NOT_PRODUCTION_ONLY`), `LEADS`; farm/urls.py:33-36,41 (water calculator/results/report, unit chart); monitoring/resources.py:99-102 (preview, copy); hr/urls.py:39 (mount çifti); experiments/resources.py:174-185
- Açıklama: (1) `hidden=True` girişler menüde yok, `/hr/settings/...` rotaları `hr.view_shift|holiday|leavetype` ile açık (settings sayfası bağlantıyı `perms.` ile gösterir: templates/hr/settings_list.html:31,38; LeaveType için bağlantı yok). (2) `show_when` ile HR satırları üretim-yalnız kullanıcıdan gizlenir; sayfalar izin sahibine yine cevap verir (kod yorumu açık: "menu courtesy"). Aynı kayıtlar hem /hr/... hem /production/team/... altında realm filtresiyle sunulur. (3) Calculator/chart/preview/copy/design/places/start/release/replace uçlarının menü girişi yoktur; izinleri Water Read, Card templates Edit/Create, Experiments Edit/Create'tir.
- Kanıt: `Entry.shown_to` (core/navigation.py:~66-76) yalnız menüyü süzer; `ResourceView.as_view` (core/crud.py:553-557) gerçek denetimdir.
- Öneri: Yok; matris belgesine eklenebilir. (Leave types için settings sayfasında bağlantı yok: kullanıcı yalnız URL ile ulaşır, küçük UX tutarsızlığı.)

### F-761 Demo seed'de bilinen parola (DEBUG korumalı)

Önem: **Bilgi** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `01-15`
- Dosyalar: hr/management/commands/seed_hr_demo.py:15,46-47,75
- Açıklama: `demo-password-1` sabit; komut DEBUG kapalıyken reddediyor (iyi). Ancak 01-2 nedeniyle DEBUG yanlışlıkla açık kalan bir ortamda bu koruma da düşer.
- Kanıt: `if not settings.DEBUG: raise CommandError`.
- Öneri: 01-2 çözülünce yeterli.

### F-762 Parola sıfırlama e-postasında `{% autoescape off %}`

Önem: **Bilgi** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `03-12`
- Dosyalar: templates/registration/password_reset_email.html:1-7
- Açıklama: Düz metin e-posta için uygun; `user.get_username` kaçışsız yazılır. Yalnızca düz metin gönderildiği sürece sorun yok; bir HTML alternatifi eklenirse kullanıcı adı XSS/enjeksiyon olur. Bu e-posta `request.get_host()` tabanlı alan adı kullanır (`ALLOWED_HOSTS` boşken DEBUG=0'da tüm istekler reddedilir; DEBUG=1'de yalnızca yerel hostlar).
- Kanıt: ilgili satırlar; `settings.py:30`.
- Öneri: Not olarak bırak; HTML e-posta eklenirse autoescape'i aç.

### F-763 Denetim ortamındaki kurulu sürümler requirements ile uyuşmuyor

Önem: **Bilgi** | Güven: orta | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-16`
- Dosyalar: requirements.txt:4, requirements.txt:10
- Açıklama: Çalıştırma ortamında `cryptography 50.0.1` ve `pypdf 6.17.0` kurulu, requirements `50.0.2` ve `6.21.4` ister; Django hiç kurulu değil. Bu repo sorunu değil ama ortamın requirements'tan kurulmadığını gösterir, bu yüzden CVE/test taraması bu ortamda yapılamadı.
- Kanıt: `pip list` çıktısı.
- Öneri: Yok (bilgi); denetimlerde ortam requirements'tan kurulmalı.

### F-764 Rapor anlık görüntüsü/kontak bilgisi kişisel veriyi kopyalayıp sürdürüyor

Önem: **Bilgi** | Güven: orta | Alan: Gizlilik/KVKK | Doğrulama: doğrulanmadı

- Kaynaklar: `08-12`
- Dosyalar: `reports/models.py:85-87,265`, `reports/resources.py:132`, `reports/exports.py:28`
- Açıklama: Yeni rapor formu, oturumdaki kullanıcının adı ve e-postasını `contact_*` alanlarına önceden doldurur; dosyalandığında dondurulmuş `ReportSnapshot` içinde ve Mattilsynet JSON/CSV dışa aktarımında (`navn`, `epost`, `telefonnummer`) taşınır. Yasal bildirim için meşru olabilir, ancak kullanıcı pasifleştirilse/silme istese bile kopya kalır ve saklama süresi tanımlı değildir (08-3).
- Kanıt: `initial = {'contact_name': user.get_full_name() or user.get_username(), 'contact_email': user.email}`; `{'navn': report.contact_name, 'epost': report.contact_email, 'telefonnummer': report.contact_phone}`.
- Öneri: Hukuki dayanağı ve saklama süresini belgeleyin; kişisel kontak yerine rol/ortak posta kutusu kullanımını önerin.

### F-765 Form sayfasındaki "geçmiş" paneli `audit.readable` süzgecini kullanmaz

Önem: **Bilgi** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-21`
- Dosyalar: core/crud.py:650-654; core/audit.py:38-43; hr/apps.py:11-17
- Açıklama: `FormView.page` kaydın etkinlik geçmişini doğrudan `AuditLog.objects.filter(entity_type=..., entity_id=...)[:20]` ile okur; etkinlik günlüğü sayfası ise HR türlerini `readable()` ile gizler. `hr/apps.py` bunu "kaydın kendi geçmişi kendi sayfasında kalır, ekip kapsamı korur" diye bilinçli yapar; kapsam `get_object` ile uygulanıyor (core/crud.py:592-596) bu yüzden ek bir sızıntı bulunmadı. Yalnızca iki yolun kuralı farklıdır, belgeye değer.
- Kanıt: `history = AuditLog.objects.filter(entity_type=r.entity_type(), entity_id=str(obj.pk))[:20]` (crud.py:652).
- Öneri: Bilinçli kural olduğunu `audit.readable` docstring'ine yaz.

### F-766 Onay ekranı "admin'den geri alınabilir" der; deney tasarım parçaları ve stok/envanter benzeri kayıtlar için bu doğru değil

Önem: **Bilgi** | Güven: orta | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `11-16`
- Dosyalar: templates/crud/confirm_delete.html:49, experiments/admin.py:17-25, farm/admin.py:21-28
- Açıklama: Soft delete onayı tüm `AuditedModel`'ler için "restore edilebilir" sözü verir. `DesignRecordAdmin` ve `StockRecordAdmin` `actions = []` ile restore'u bilerek kapatır; bu kayıtlar için metin yanıltıcı olabilir (ör. deney taslağı restore edilir ama tasarımı yeniden girilir; parçalar tek başına dönmez). Ayrıca restore eylemi `has_change_` iznine bağlı iken admin sitesine yalnızca platform yöneticisi girer.
- Kanıt: confirm_delete.html:49; `actions = []` (farm/admin.py:27, experiments/admin.py:20).
- Öneri: Metni modele göre özelleştir (`restorable` bayrağı).

### F-767 monitoring: eski `mode` kolonları "bir sürüm" kalacak denmiş ama kaldırma migration'ı yok

Önem: **Bilgi** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `14-15`
- Dosyalar: monitoring/migrations/0003_template_pointers.py:1-3, monitoring/migrations/0004_backfill_modes.py:1-3, monitoring/models.py:39
- Açıklama: 0003/0004 docstring'leri eski `default_mode`/`mode` kolonlarının "bir sürüm" kalacağını söylüyor; bunları düşüren migration yok (modelde `CardMode` hâlâ var). İki kaynak (mode ve template) birlikte yaşıyor; 0004 geri yönü mod sütununa yalnızca built-in şablonlar için yazıyor, kullanıcı şablonuna geçmiş satırlarda `mode` eskir. Sürüm çevrimi planı açık değil.
- Kanıt: 0003:1-3 "The old modes stay for one release"; 0004:19-21 backward yalnızca MODE_OF.
- Öneri: Kaldırma migration'ı için tarih/sürüm sınırını belgelemek veya TODO bırakmak.

### F-768 Çıkarım tabanlı değerler başka örneklerin varlığına bağlı: NH3/oksijen türevleri geriye dönük değişir

Önem: **Bilgi** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-15`
- Dosyalar: farm/water/read.py:300-348
- Açıklama: Örnekte tuzluluk yoksa son 30 günde başka örnekten alınıyor (`salinity_for`); ardından NH3/NH4/oksijen türetimi o tuzluluğa göre. Sonradan tuzluluk örneği eklenir/void edilirse eski örneğin gösterilen NH3'ü ve değerlendirmesi (limit aşımı) değişir. Türetilen değer saklanmadığından kasıtlı; ancak limit aşımı olaylarının geçmişte "değişen" sonuç vermesi denetim izini etkiler.
- Kanıt: `_ammonia`/`_oxygen` ve `_salinity_missing` (read.py:300-337).
- Öneri: Gerekirse olay anındaki sonuç kaydı; en azından belgelemek.

### F-769 Envanter bütünlük tarayıcısı lot yetimlerini ve pasif konum varışlarını denetlemiyor

Önem: **Bilgi** | Güven: orta | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-16`
- Dosyalar: inventory/integrity.py:56-91; inventory/services.py:346-351
- Açıklama: Void edilen operasyonun tüm satırları gitmiş lotu servis soft-delete ediyor; ancak `problems()` "canlı satırı olmayan canlı lot" (el ile silme/bug ile oluşmuş yetim) kuralını içermiyor, pasif (`inactive`) konuma yeni giriş kuralını ve sayım satırlarının `lot.item` ile birimini de doğrulamıyor. `check_stock`'taki kadar kapsamlı değil.
- Kanıt: integrity.py'de `InventoryLot` için yalnızca numara/son kullanma kuralları (74-79).
- Öneri: "canlı lot, canlı satırı yok", "pasif konuma giriş", "sayım satırı kendi konumunda" kuralları.

### F-770 `project()` her çağrıda ünitelerin tüm yemleme geçmişini yürüyor (meal board, by-day, kartlar, rapor, tahmin)

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `19-13`
- Dosyalar: farm/feeding/read.py:58-68, 149-160, README.md (Measured at 100 units paragrafı)
- Açıklama: `feedings(unit_ids)` `since` vermeden tüm kayıtları okur; `lineage()` döngüsü de batch→unit zincirini DB'den tekrar tekrar çözer. README bunu ölçülmüş ve bilinçli bir bırakma olarak kaydediyor ("a measured slow screen would first bound the feeding walk"), ama kayıt sayısı büyüdükçe (yıllarca günlük kayıt) meal board, her kart yenilemesi ve yukarıdaki biyokütle raporu doğrusal yavaşlar; sınır/önbellek yok.
- Kanıt: `records = feedings(unit_ids)` (read.py:155) ve `lineage` döngüsü (read.py:77-91).
- Öneri: Yürüyüşü ilk ölçülen noktanın (son tartım/dikim) gününden başlatın veya sonuçları (UnitDay) kısa süreli önbellekleyin.

### F-771 Lice limit bölgesi (`lice_area`) isteğe bağlı ve konumla doğrulanmıyor

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-13`
- Dosyalar: `farm/models/site.py:96,176-177`, `farm/health/lice.py:404-416`, `farm/forms/site.py:60`
- Açıklama: Boş bırakılan bölge, 16-26. haftalar için 0,2 limit ve 14-26. haftalar için 20 balık gibi kasıtlı katı bir varsayım uygular (sayfa "Area not set" der). Bölge, sitenin `region`/`latitude` bilgisiyle çapraz kontrol edilmez; Tromsø/Troms bir site yanlışlıkla "south" seçilirse 21-26. haftalarda limit 0,5 olarak yanlış gevşek hesaplanır. Yönetmelik karşılaştırması: kod `>=` limit değerini aşım sayıyor ("færre enn"), uyumlu.
- Kanıt: `lice.py:394-395` `SPRING_WEEKS`/`LARGE_SAMPLE_WEEKS`, `site.py:96` `blank=True`.
- Öneri: Deniz sitesi için bölgeyi zorunlu veya enlemden öner/doğrula.

### F-772 Hastalık bildirimi yalnızca teşhisli olaydan veya 14 gün sonra açıklanamayan ölümden doğuyor

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-14`
- Dosyalar: `reports/due.py:365-396`, `farm/health/notices.py:48-54`, `farm/models/health.py:434-531`
- Açıklama: Bildirim yükümlülüğü `diagnosis in NOTIFIABLE` (şüpheli veya doğrulanmış) olaylardan çıkar. Teşhis alanı boş, ancak belirtileri (`signs`) listelenmiş bir gözlem olayı ("şüphe") hiçbir bildirim satırı üretmez; yalnızca `MORTALITY` türünde, teşhissiz, kapatılmamış ve 14 gün geçmiş olay "açıklanamayan ölüm" bildirimi doğurur. Ayrıca `site.reports_from` boşsa bildirim sessizce atlanır (`due.py:373-374`, `due.py:392-393`). Hepsi belgelenmiş tasarım seçimi; yönetmelik (§ 7: şüphede hemen bildir) ile arasındaki boşluk kullanıcıya açıkça söylenmiyor.
- Kanıt: `due.py:368` `HealthEvent.objects.filter(diagnosis__in=diseases.NOTIFIABLE)`, `due.py:373` `event.site.reports_from is None` ise `continue`.
- Öneri: `reports_from` boşken yükümlülüğü "kurulmadı" satırı olarak göster; belirtili ama teşhissiz olay için veteriner değerlendirme hatırlatması düşün.

### F-773 İlaçlı yem örtüsü (covers) ilacı eşlemiyor

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `20-15`
- Dosyalar: `farm/health/withdrawal.py:240-273`, `farm/models/feed.py` (yem modelinde ilaç alanı yok)
- Açıklama: İlaçlı yem beslemesi, aynı birimde ve günde herhangi bir `IN_FEED` tedavisi varsa "örtülmüş" sayılır; yemin hangi ilaçla hazırlandığı ve tedavinin ilacı ile aynı olup olmadığı kontrol edilmez. Farklı bir ilaçlı yemle beslenen birimde başka bir yem içi tedavi varsa, ilaçlı yemin arınması "bilinmiyor" yerine tedavinin (yanlış ilaç) arınmasına bağlanır.
- Kanıt: `withdrawal.py:263-267` `covers()` yalnızca yöntem, tarih ve birim; `grep -n medicin farm/models/feed.py` sonuç vermedi.
- Öneri: Yem kaydına ilaç bağlantısı ekle veya örtme kararını kullanıcıya açıkça göster.

### F-774 Boşaltan grading, kaynak biyokütlesini ölçülen toplama sıfırlıyor; kitap ile ölçülen arasındaki fark deftere yazılmıyor

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-9`
- Dosyalar: farm/stock/fold.py:98-111, farm/stock/services.py:650-674
- Açıklama: GRADING operasyonunda ayrılan balık `k * weight` ile çıkar, son balık için bile (`weight is not None and op.kind == GRADING` dalı `k == share.count` dalından önce). Kaynakta kalan balık yoksa kitap gramı sıfırlanır ve çıkan biyokütle yalnızca ölçülen toplamdır; kitap ile ölçülen arasındaki fark (kayıp/artış) hiçbir satırda izlenmez (harvest'teki "book vs scale" farkı gibi gösterilmez).
- Kanıt: fold.py:98-99 `if weight is not None and line.op.kind == OperationKind.GRADING: out = k * weight`; :111 `share.grams = share.grams - out if share.count else ZERO`. - Etki: biyokütle devamlılığı kırılır; fark raporlanmaz. Tasarım gereği ("grading is a weighing") olduğu için bilgi düzeyinde.
- Öneri: grading'de kitap-ölçülen farkını harvest'teki gibi gösterin.

### F-775 O₂ mg/L ile % tutarsızlığı yalnızca not; iki değer ayrı limitlerle bağımsız yargılanıyor

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-14`
- Dosyalar: farm/water/read.py:350-356, farm/water/read.py:66
- Açıklama: Girilen mg/L ve % değerleri beklenen oranla %10'dan fazla ayrışırsa yalnızca bir not konuluyor; iki okuma da girildiği gibi bırakılıp ayrı ayrı yargılanıyor. Mg/L limiti "OK" iken % limiti "kritik" olabilir (ya da tersi) ve kart durumu en kötüyü alır. Servis katmanı (`services.record`) de bu tutarsızlığı kayıt anında engellemiyor/uyarmıyor, yalnızca okuma anında not düşüyor.
- Kanıt: `if expected and abs(mg_l - expected) / expected > OXYGEN_TOLERANCE: note = ...; return {code: Reading(... getattr(sample, code), sample, False, note) ...}`.
- Öneri: Form kayıt anında aynı kontrolü uyarı olarak gösterin; tutarsız örneğin durumunu "kontrol et" notuyla birlikte işaretleyin.

### F-776 Yeniden oluşan lot/item ve yem silme: item bir kez oluşunca yem sonsuza dek silinemez

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-16`
- Dosyalar: inventory/models.py:133-134,150-152, inventory/screens.py:105
- Açıklama: `InventoryItem.feed` PROTECT ve item silinemez/düzenlenemez ("an item stays"). Hiç hareketi kalmamış (tüm teslimatlar void) bir yem için bile item kaldığından yem soft-delete edilemez (canlı item PROTECT engeli). `Feed.delete_blockers` (farm/models/feed.py:230-240) envanteri anmıyor; engel genel PROTECT mesajı üzerinden geliyor.
- Öneri: Hareketsiz item'ları temizleyen/gizleyen bir yol veya Feed engelinde açıklayıcı mesaj.

### F-777 `shared_today()` ve `clocks()` farklı site kümelerini kullanır

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-15`
- Dosyalar: `tasks/forms.py:29-34`, `farm/clocks.py:37-40`
- Açıklama: Form varsayılan günü `Site.objects` (silinmemiş) saat dilimlerinden, okuma ise `Site.all_objects` kümesinden hesaplar; ayrıca çok dilimli kurulumda forma şirket saati verilir. Yalnız varsayılan tarihi etkiler.
- Kanıt: `zones = {zone_of(site) for site in Site.objects.all()}` ile `Site.all_objects.only(...)`.
- Öneri: Aynı kaynağı kullan.

### F-778 Serinin atanan/başlık değişikliği dokunulmuş görevlere yayılmaz (kasıtlı, fakat belgesiz sapma)

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-8`
- Dosyalar: `tasks/models.py:424-437`, `tasks/services.py:274-287`
- Açıklama: Not eklenmiş, tikli, düzenlenmiş veya başlatılmış görevler eski kural ve atananlarla kalır; kural değiştiğinde (ör. günlük -> haftalık) bugünden önceki dokunulmamış gecikmiş görevler de olduğu gibi kalır. Kullanıcıya hangi görevlerin eski kuralda kaldığı gösterilmiyor.
- Kanıt: `planned` yalnızca `version=1`, açık, notsuz, tiksiz ve bugün/sonrası görevleri alır.
- Öneri: Seri kaydında "N görev değişmedi" bilgisi göster.

### F-779 Rol/yetki: Everyone için kapsam kısıtı yok, ek denetim izi dayanağı ayrı

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-18`
- Dosyalar: hr/scope.py:523-533, hr/apps.py:13-16, hr/admin.py:5
- Açıklama: `hr.all_employee` tüm çalışan, plan, izin nedeni ve yoklama için tam erişimdir; denetim logu bu modelleri yalnızca bu izne gösterir (olumlu). Admin salt okunur ve geri alma (restore) yalnızca `change_*` izniyle (soft-deleted plan/posting geri getirme, yeniden doğrulanır). Yetki ilişkisi iyi tasarlanmış; kayıt amaçlı not: PRODUCTION manager preset'i `all_production_employee` taşır, yani yöneticisiz departman için de tüm üretim izin tiplerini (karar yetkisiyle) görür (docs 3.x ile uyumlu).
- Kanıt: roles.py:26; scope.py:495-505.
- Öneri: Yok (bilgi).

### F-780 Export format sürümü ayrımı yok; `FORMAT_VERSION` değişirse eski dondurulmuş içerik `api_json`'da KeyError verebilir

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-17`
- Dosyalar: reports/exports.py:384-428, reports/compute/common.py:20, reports/views.py:31-35
- Açıklama: Filed rapor export'u `snapshot.content`'ı güncel `api_json` ile okur (alan adları doğrudan indekslenir: `content['treatments']`, `counts['adult_females']`, `unit['culled']` vb.). `format_version` bugün 1; `LEGACY_FORMAT=0` yalnızca bildirimlerde. Gelecekte içerik şekli değişirse eski filed raporların yeniden dışa aktarımı kırılır ya da farklı çıktı verir.
- Kanıt: exports.py:301-306 `content['treatments']`, `content['counts']`; views.py:34 `return report.snapshot.content, True` (sürüm kontrolü yok).
- Öneri: `format_version` ile dispatch (sürüm başına `api_json`) veya dondurulmuş içerik için migrasyon testi.

### F-781 Bildirimler (escape/disease/welfare) hiçbir zaman "gecikmiş" sayılmıyor; genel görünümdeki gecikme sayacına girmiyor

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-19`
- Dosyalar: reports/due.py:179-193, reports/views.py:49-51
- Açıklama: Olay bildirimlerinin `deadline`'ı `None` (kural "at once"); `_row` `overdue = deadline is not None and ...` ile her zaman `False` verir. Haftalardır bekleyen bir kaçış/hastalık bildirimi `overview_upcoming` içindeki `overdue` sayısına katılmaz, yalnızca "at once" olarak listelenir.
- Kanıt: due.py:193 `DueRow(kind, place, period, deadline, deadline is not None and today > deadline, report, event)`.
- Öneri: Olay tarihinden itibaren geçen gün sayısını gösteren bir "bekleyen bildirim" göstergesi ekle.

### F-782 İzni düşen/pasifleşen karşı taraf sessizce birikim yapar

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-16`
- Dosyalar: messaging/services.py:47-60, 70-75, 90-104
- Açıklama: `_reachable` yalnız konuşma/üye eklerken çalışır. Sonradan hesabı pasif veya izni kalkan kişi doğrudan konuşmada ve kanallarda katılımcı kalır; gönderen bunu görmez, mesajlar okunmadan birikir ve kişi geri dönerse tümü "okunmamış" olur. Rozet/okunmamış yalnızca canlı üyelik arar, kişinin etkinliğine bakmaz (kapsam dışı olabilir).
- Kanıt: `_reachable` çağrıları yalnız `start_direct`, `create_channel`, `add_members`.
- Öneri: Karşı tarafın durumunu konuşma başlığında göstermek; pasif kullanıcıları roster'dan ayıklamak.

### F-783 `leave` içinde kilit, üyelik denetiminden önce alınıyor

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-17`
- Dosyalar: messaging/services.py:77-79, 201-208
- Açıklama: `_locked(conversation_id)` `member()`'dan önce çağrılır: Messages iznine sahip herhangi biri bir konuşmanın UUID'sini bilirse üyesi olmadan satır kilidi alıp işlem süresince tutabilir (kısa). UUID tahmin edilemez, risk düşük; kural "üye olmayan için konuşma yoktur" ile tutarsızlık.
- Kanıt: `_locked(conversation_id); actor = member(user, conversation_id)`.
- Öneri: Önce `member()`, sonra kilit (tutarlı sırayla; `owner()` de aynı).

### F-784 Başlık: ACTIVE'ten doğrudan CLEANING geçişi yok; boş aktif birim yalnız FALLOW veya MAINTENANCE'a gidebilir

Önem: **Bilgi** | Güven: orta | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `30-16`
- Dosyalar: farm/models/tank.py:25-35, 236-243
- Açıklama: TRANSITIONS'ta ACTIVE -> (HARVESTING, MAINTENANCE, QUARANTINE, FALLOW); EMPTIED ACTIVE->FALLOW. Ölüm sonrası boşalan birim temizlik gerektirse CLEANING'e FALLOW'tan geçilemez (FALLOW -> PREPARING). Kaynaktaki politikayı yansıtıyor olabilir; yalnızca not.
- Kanıt: tank.py TRANSITIONS.
- Öneri: İş sahibi onayı ile doğrulayın.

### F-785 Magic number: ruff PLR2004 74 karşılaştırma

Önem: **Bilgi** | Güven: orta | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-10`
- Dosyalar: tüm repo (testler dahil)
- Açıklama: 74 yerde adsız sayısal karşılaştırma var; dosyaların çoğunda sabitler iyi adlandırılmış (ör. `LEFT_OUT_G`, `AT_TARGET`, `HISTORY_DAYS`), yani sorun dağınık. Tek tek sınıflandırılmadı; kısmen testlere ait olabilir.
- Kanıt: `ruff check --select PLR2004 --statistics .` -> 74.
- Öneri: üretim kodundaki alt kümeyi ayıklayıp adlandır.

### F-786 `core/softdelete.py` içinde gettext `_` döngü değişkeniyle gölgelenmiş

Önem: **Bilgi** | Güven: orta | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-14`
- Dosyalar: core/softdelete.py
- Açıklama: Satır 71'de `for _, link in pairs` generator ifadesi, modülde `_` (gettext, satır 33) adını kullanıyor. Generator kendi kapsamında olduğundan şu an çalışıyor; ancak benzer ifade fonksiyon gövdesine taşınırsa çeviri fonksiyonu bozulur (ruff F402).
- Kanıt: core/softdelete.py:71 (F402), import satır 33.
- Öneri: `for _unused, link` ya da `__`.

### F-787 `farm/stock/views.py _back` ile `farm/feeding/views.py _back` delegasyon kalıbı tutarsız; `_context` 8 kez

Önem: **Bilgi** | Güven: orta | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-15`
- Dosyalar: farm/stock/views.py, farm/feeding/views.py, çeşitli views
- Açıklama: `_context` adı 8 modülde, `_day` 7, `label` 7, `problems` 7, `compute` 6 kez tanımlı. Bunların çoğu modül-yerel olup normal, ama `_context`/`_day` gibi genel adlar grep/okuma maliyeti yaratıyor.
- Kanıt: yardımcı adı sayımı (`grep -rnE "^def ..."`): `_context` 8, `_day` 7, `_back` 6, `_refused` 5.
- Öneri: yalnız davranışı aynı olanları (bkz. 32-1, 32-2) birleştir.

### F-788 Frontend'de fetch yanıtları için merkezi hata/oturum-bitti kullanıcı bildirimi yok; yalnızca localStorage hataları yorumla yutuluyor (kabul edilebilir)

Önem: **Bilgi** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `33-14`
- Dosyalar: frontend/poll.ts, frontend/windows.ts, frontend/nav-boot.ts, frontend/designer.ts
- Açıklama: Boş catch blokları: windows.ts:61,77 ve nav-boot.ts:10,13 yalnızca localStorage erişimi için ve yorumlu (kabul edilebilir). windows.ts:228 'request.catch(() => undefined)' reddedilen bir isteği yorumla yutuyor. Asıl ağ çağrıları (poll.ts, designer.ts) için ortak bir hata raporlama/telemetri noktası yok; tarayıcı tarafı hatalar için window.onerror/unhandledrejection dinleyicisi veya sunucuya raporlama bulunmuyor (grep ile console.error/onerror eşleşmesi yok).
- Kanıt: grep: 'console\.(error|log)|onerror|unhandledrejection' frontend/*.ts (test/ hariç) -> eşleşme yok; frontend/windows.ts:61,77,228; frontend/nav-boot.ts:10,13.
- Öneri: Küçük bir ortak 'reportError' yardımcısı (kullanıcıya durum + isteğe bağlı sunucu log ucu) düşünün.

### F-789 `core.codes.next_code`: 32 bitlik `hashtext` advisory anahtarı, tek global kilit sınıfı

Önem: **Bilgi** | Güven: orta | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-12`
- Dosyalar: core/codes.py:7-16, inventory/services.py:74-79
- Açıklama: Kilit anahtarı `hashtext('<tablo>.code')` / `hashtext('inventory_items')`; farklı anahtarların hash çakışması ya da uygulama dışı başka advisory kullanımı gereksiz bekleme yaratabilir (yalnızca performans, doğruluk bozulmaz). Doğru kullanım: Batch kodu `_commit` transaction'ı içinde (stock/services.py:153), Experiment kodu CRUD atomic içinde (experiments/forms.py:97 `save` -> core/crud.py:679 atomic) alınıyor; benzersizlik ayrıca `uq_experiments_code` ile korunuyor.
- Kanıt: codes.py:13-14.
- Öneri: Gerekmiyor; bilgi amaçlı.

### F-790 farm/tests/deffeyes_reference/.gitignore ve dosya modları

Önem: **Bilgi** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-14`
- Dosyalar: farm/tests/deffeyes_reference/.gitignore
- Açıklama: Alt dizinde `out/`, `src/*`, `!src/index.ts`, `!src/shared-contracts.ts` kuralları var; bu, referans üretim için Node kaynağı barındıran bir alt proje izlenimi veriyor ama repo kökünde belgelenmemiş (not: içeriği ayrıca incelenmedi). Hiçbir dosyada 100755 modu yok (scripts/mark-esm.mjs dahil), `.gitattributes` `* text=auto eol=lf` ile tutarlı.
- Kanıt: `cat farm/tests/deffeyes_reference/.gitignore`; `git ls-files -s | grep -c '^100755'` = 0.
- Öneri: Alt dizin için kısa README ekle.

### F-791 Seçicilere kimlik değerleri `CSS.escape` olmadan enjekte ediliyor

Önem: **Bilgi** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-9`
- Dosyalar: `frontend/designer.ts:159`, `:277`, `:296`, `:304`
- Açıklama: `querySelector(`.designer-item[data-id="${item.id}"]`)` ve `#designer-${id}`. Bugün `parse` kimlikleri `ID = /^[a-z][a-z0-9_-]{0,15}$/` ile sınırlıyor (layout.ts:13) ve güvenli; ama `problem.widget` (sunucudan, `showProblems` satır 501-504) için aynı garanti yok. `components.ts` aynı yerde `CSS.escape` kullanıyor -> tutarsızlık.
- Öneri: tek bir yardımcı ile `CSS.escape`.

### F-792 Standalone rapor sayfası temel şablon dışı: `<html>` öncesi `{% comment %}` ve eksik `nav-boot`

Önem: **Bilgi** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `42-20`
- Dosyalar: templates/farm/water_calculator_report.html:1-6, 69
- Açıklama: `<!doctype html>` doğru yerde ama kalıtım yok; `components.js` elle ekleniyor, `shell.js`/`poll.js` yok (bilinçli olabilir). Kopya head için bkz. 42-8.
- Kanıt: dosya başı.
- Öneri: `report_base.html` oluştur.

### F-793 Silme engelli kayıtta düğme `disabled`, ama hata nedeni yalnız üstte; Cancel bağlantısı data-modal-close'a bağımlı

Önem: **Bilgi** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-15`
- Dosyalar: templates/crud/confirm_delete.html:16-23,53-55
- Açıklama: Engelleyiciler listeleniyor (iyi). `plan` yoksa (AuditedModel olmayan kayıt) "removes it permanently" gösterilir ama bağımlı kayıt etkisi (ilişkili kayıtlar) bilgisi yok; kalıcı silme tek onayla. Plan'lı kayıtta silinen/ayrılan listeleri var, hard delete dalında yok.
- Kanıt: confirm_delete.html:48-49 `{% else %}<p>This removes it permanently...`; core/crud.py:772-774 `audit.record_delete ... obj.delete()` plansız.
- Öneri: Hard delete'te de bağlı kayıt sayısını/PROTECT durumunu göster.

### F-794 Panel rozeti toplamı ve panel anahtarı hedefi: her zaman paneli ilk girişine (özet) götürür, son sayfayı hatırlamaz

Önem: **Bilgi** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-18`
- Dosyalar: core/navigation.py:186-190, templates/app_base.html:21-22
- Açıklama: Panel menüsü bağlantısı `sections[0]...entries[0]['url']` yani panelin özetidir; kullanıcı Production › Water chemistry'de iken Company'ye gidip dönerse son sayfasına değil özetine düşer (middleware `workspace` oturum anahtarı yalnız menü içeriğini hatırlar). Panel rozeti (menu-badge) toplam sayıdır ama URL'siz (`Badge(sum, '')`) olduğundan yoklanmaz, sayfa değişene dek eskir.
- Kanıt: `'url': sections[0]['groups'][0]['entries'][0]['url']`, `Badge(sum(badges), '')`.
- Öneri: Panelin son ziyaret edilen sayfasını oturumda sakla; rozeti de yoklanan bir fragmana bağla.

### F-795 Menü daraltma durumunda başlıklar gizleme biçimi ve etiket kısaltmaları

Önem: **Bilgi** | Güven: orta | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-15`
- Dosyalar: `static/css/app.css:130-150,207-232,300-312`, `frontend/shell.ts:12-18`
- Açıklama: (a) Daraltılmış rail'de `.rail-section`/`.rail-group` `color: transparent; height:1px; overflow:hidden` ile gizleniyor; metin hâlâ erişilebilirlik ağacında, yani ekran okuyucu bölüm başlıklarını okur (iyi), ancak `[data-nav="collapsed"] .rail-section + .rail-group { display:none }` yalnızca bazı grup başlıklarını tamamen kaldırıyor: ekran okuyucu/klavye kullanıcısı için tutarsız bölüm yapısı. (b) Daraltılmış rail'de bağlantı etiketleri `.8125rem` ve `max-width:100%` + `text-overflow:ellipsis` ile kırpılıyor; tam ad yalnızca `title` ile (dokunmatikte görünmez). (c) Rail durumu `localStorage`'da; `aria-expanded` ve etiket güncelliyor (`shell.ts:12-18`), bu iyi. (d) `.rail-badge` sayısı (okunmamış mesaj) için ekran okuyucu metni yok: badge yalnızca "3" gibi sayı okunur, "okunmamış" bağlamı yok; ayrıca `data-poll` ile güncellendiğinde duyurulmuyor.
- Kanıt: `app.css:223` `.rail-label { overflow:hidden; text-overflow: ellipsis }`; `app_base.html:55` `<span class="rail-badge" ...>{{ entry.badge.text }}</span>`.
- Öneri: Rozete `aria-label`/sr-only bağlam metni ekle; kırpılan etiket için daraltılmış durumda en az `aria-label` sağlam kalsın.

### F-796 `reports` kaydedilmezse hastalık bildirimi "borç yok" gibi, refah bildirimi "hepsi borç" gibi davranıyor (kapanış yönü tutarsız)

Önem: **Bilgi** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-10`
- Dosyalar: `reports/due.py:365-396`, `farm/health/notices.py:44-62`, `reports/apps.py:15-17`
- Açıklama: `notices.told()` sağlayıcı yokken `None` ("kontrol edilmedi") döner. `_diseases` `notices.pending(events) or []` ile bunu "bekleyen yok" sayar; `_unexplained` ise `notices.told(events) or {}` ile "hiçbiri bildirilmemiş" sayar. Sağlayıcı `reports.ready()` içinde kayıtlı olduğundan normalde sorun yok; ama sağlayıcı yokken iki akış zıt yönde sessizce başarısız olur. Arınma sağlayıcısı ise "kontrol edilmedi" notu üretiyor (doğru yaklaşım).
- Kanıt: yukarıdaki iki satır; karşılaştırma için `farm/handling/check.py:_withdrawal` açık not düşer.
- Öneri: İki yerde de `None`'u ayrı ele alıp "kontrol edilmedi" satırı üret.

### F-797 Arınma sağlayıcısı kayıt defterinde hata yalıtımı yok; deney çipi kaydı ise "fail open"

Önem: **Bilgi** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-11`
- Dosyalar: `farm/handling/withdrawal.py:36-46`, `README.md:2143` (placements kaydı)
- Açıklama: Placement çip sağlayıcıları kendi savepoint'inde, hata olursa sessizce çalışıyor; arınma sağlayıcısı (`blocks_of`) ise hata yalıtımsız: sağlayıcı istisna atarsa hasat sayfası/kaydı komple 500 verir. Güvenlik açısından "fail closed" savunulabilir; ama aynı mimari kalıbın (kayıt defteri) iki farklı hata politikası var ve belgede yalnız biri anlatılmış.
- Kanıt: `blocks_of` doğrudan `provider(units, day)` çağırıyor, try/except yok.
- Öneri: Politikayı bilinçli kararlaştır ve `farm/handling/withdrawal.py` docstring'ine yaz.

### F-798 Ana sayfalarda depo (düşük stok/SKT/kapsama günü) ve arınma altındaki birim özeti yok; modüller arası risk sinyalleri dağınık

Önem: **Bilgi** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `47-13`
- Dosyalar: `config/views.py:34-50`, `monitoring/read.py:56-77`, `inventory/read.py` (`overview`)
- Açıklama: Üretim genel bakışı stok, yemleme, su ve görev kutucuklarını gösteriyor; depo uyarıları (düşük stok, SKT, karşılanmamış besleme, kapsama günü) yalnız Depo sayfasında. `monitoring` `inventory` import etmiyor. Besleme tüketiminin stok kapsama günü ile ilişkisi (yemleme -> stok) bu yüzden operatörün günlük ekranında görünmez; arınma için ise birim satırında rozet var (iyi).
- Kanıt: `config/views.py` yalnız `feeding_tiles`, `overview_tiles`(stock), `water_tiles`, `task_tiles`; `grep inventory monitoring/*.py` sonuç yok.
- Öneri: Depo uyarılarından en az "karşılanmamış besleme" ve "düşük stok" üretim genel bakışına kutucuk olarak eklenebilir.

### F-799 FeedingProtocol: `active -> draft` onaysız (atanmamışsa) ve retired -> active serbest

Önem: **Bilgi** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-11`
- Dosyalar: farm/forms/feeding_protocol.py:54-59, farm/models/feeding_protocol.py:118-136
- Açıklama: Atanmamış aktif protokol draft'a döner (formda tüm seçenekler açık), atanmış olan dönemez. `retired -> active` her zaman serbest; deney başlatma (experiments/services.py:161) yalnızca ACTIVE protokolü kabul eder, geri aktifleştirme bu varsayımları değiştirir. Tutarlı ama açık bir geçiş tablosu yok (Tank/Experiment'ın aksine).

### F-800 OpenQuestion answered -> open dönüşü: answer alanı korunuyor, tarih siliniyor

Önem: **Bilgi** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-14`
- Dosyalar: reports/models.py:327-331, reports/forms.py:154-170
- Açıklama: Form status'ü serbest düzenler; CheckConstraint open için `answered_on IS NULL` ister ama `answer` metnini serbest bırakır. Yeniden açma yolu ayrı servis/audit olmadan form düzenlemesiyle olur.

### F-801 Task `reopen` tamamlanma/iptal geçmişini siler; tek kayıt audit

Önem: **Bilgi** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-7`
- Dosyalar: tasks/services.py:151-166
- Açıklama: Reopen completed_at/by, completion_note, cancel_reason alanlarını temizliyor; kayıt yalnızca activity log'da (audit.record_update) kalıyor. Tutarlı ama alan düzeyinde geçmiş yok; reopen sayısı/çevrimi sorgulanamaz.

### F-802 Leave: reddedilmiş/iptal edilmiş talep için yeniden gönderim yolu yok; terminal durumlar belirsiz

Önem: **Bilgi** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-8`
- Dosyalar: hr/services.py:272-290, 305-335; hr/forms/leave.py:80
- Açıklama: `rejected` ve `cancelled` terminaldir (kodda geri dönüş yok); kullanıcı yeni talep açmalı, bu pending/approved ile çakışma kısıtı (hr/models/leave.py ExclusionConstraint) nedeniyle çalışır, yani tasarım tutarlı. Onaylanmış talep, ilk gün başladıktan sonra hiç iptal edilemez (can_cancel) ve düzeltme yolu da görünmüyor.

### F-803 Fail-open okuma yolları DB kopmasını "veri yok" gibi gösterebilir

Önem: **Bilgi** | Güven: orta | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-15`
- Dosyalar: monitoring/read.py, farm/placements.py
- Açıklama: `_optional` ve `placements.of` her `Exception`'ı yutar ve bölümü boş gösterir (log dakikada bir). Tasarım gereği, ancak DB bağlantısı geçici koptuğunda kullanıcı "veri yok"u gerçek veri yokluğundan ayırt edemeyebilir; log hız sınırı tanıdık hataları gizler. `Unavailable` kullanımı kısmen bunu önlüyor.
- Kanıt: monitoring/read.py:265-276 (`except Exception`, FAILED_AT sınırı); farm/placements.py:43-52.
- Öneri: Başarısız kaynakları kart üzerinde "okunamadı" olarak belirt (zaten `failed` bayrağı var, kullanıldığını doğrula).

### F-804 04-10 Content-Disposition tutarsızlığı knowledge PDF için geçerli değil

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `06-X3`  (yalnız çapraz görüş)
- Dosyalar: core/dbview.py:63, reports/views.py:220, knowledge/views.py:37
- Açıklama: 04-10 Content-Disposition tutarsızlığı knowledge PDF için geçerli değil

### F-805 Güvenlik düzeltmeleri için yeni paket önerilirse lisans/sabitleme zinciri etkilenir

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `07-X4`  (yalnız çapraz görüş)
- Dosyalar: THIRD_PARTY.md, requirements.txt
- Açıklama: Güvenlik düzeltmeleri için yeni paket önerilirse lisans/sabitleme zinciri etkilenir

### F-806 Arınma değerleri marj sonrası tamsayıya yukarı yuvarlanıyor, etiket değeri ondalık kalıyor

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `18-X4`  (yalnız çapraz görüş)
- Dosyalar: farm/health/withdrawal.py
- Açıklama: Arınma değerleri marj sonrası tamsayıya yukarı yuvarlanıyor, etiket değeri ondalık kalıyor

### F-807 Kapasite metni ve seçim etiketi tutarsız; max biyokütle boşsa kontrol sessizce atlanıyor

Önem: **Bilgi** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `21-13`
- Dosyalar: farm/forms/stock.py:53-57, farm/stock/views.py:322-329, farm/stock/services.py:350
- Açıklama: Onay kutusu "Stock above the max density" der, kontrol ise biyokütle (kg) üzerinden yapılır (`max_biomass_kg`). `unit.max_biomass_kg is not None` koşulu nedeniyle null ise aşım kontrolü atlanır; seçim listesi ise `unit.max_biomass_kg or 0` ile "0 kg max/free" yazar. `depth` zorunlu olduğundan null olasılığı düşük (şekil/ölçü eksikliğinde oluşabilir); doğrulanmadı.
- Kanıt: views.py:325 `number(unit.max_biomass_kg or 0)`; services.py:350 `if unit.max_biomass_kg is not None and kilos > unit.max_biomass_kg`. - Etki: kullanıcıya yanıltıcı metin; olası sessiz kapasite atlaması.
- Öneri: etiketi "max biomass" olarak hizalayın ve max boşken açıkça uyarı verin.

### F-808 Departure/Dialog tarihi varsayılanı site saati yerine şirket saati olabilir

Önem: **Bilgi** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `23-17`
- Dosyalar: inventory/forms.py:138-141, inventory/views.py:335, inventory/services.py:176-181
- Açıklama: `Dialog.__init__` `site_today(site)` kullanıyor; `site` yalnız preset kova varsa veriliyor, aksi halde `site_today(None)` (şirket saat dilimi). Kayıt ise lokasyonun sitesi saatiyle doğrulanıyor; saat dilimleri farklı sitelerde varsayılan tarih "gelecekte" kabul edilip reddedilebilir.
- Öneri: Kaynak seçildiğinde tarih varsayılanını o sitenin gününe çek.

### F-809 Yalnızca silinmemiş görev sayıları/overview satır kapsamı yok

Önem: **Bilgi** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `24-17`
- Dosyalar: `tasks/views.py:138-146`, `tasks/resources.py:76-81`
- Açıklama: Görev kaynağı `scoped` ile satır kapsamı uygulamaz; yalnız rol matrisi var. Site bazlı sınırlama istenirse overview sayıları (`Task.objects.all()`) ve tüm aksiyon view'ları (`_task(pk)`) tüm sitelerin görevlerini görür. Mevcut tasarım (HR dışında scope yok) ile tutarlı olduğu için bilgi amaçlı.
- Kanıt: `read.counts(Task.objects.all())`; `_task` yalnızca `get_object_or_404`.
- Öneri: Çok-site yetkilendirmesi gelirse buraya da uygula.

### F-810 Punch uçlarında idempotency anahtarı yok; hata yalnızca flash mesajı

Önem: **Bilgi** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `25-X1`  (yalnız çapraz görüş)
- Dosyalar: hr/views.py, hr/services.py
- Açıklama: Punch uçlarında idempotency anahtarı yok; hata yalnızca flash mesajı

### F-811 `reports_from` dönem ortasında ise ilk (kısmi) dönemin tamamı borçlu sayılıyor

Önem: **Bilgi** | Güven: düşük | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `26-20`
- Dosyalar: reports/due.py:225, reports/periods.py:122-128
- Açıklama: `periods_between(grain, site.reports_from, ...)` `reports_from`'u içeren dönemin tamamını üretir; dönemin ilk günleri başka yerde raporlanmış olsa bile o dönem için tam rapor beklenir ve hesaplanır (tamamı raporlanır). Docstring "periods before were filed elsewhere" diyor; kısmi dönem için davranış belirtilmemiş.
- Kanıt: periods.py:124 `found, period = [], Period.of(grain, first)`.
- Öneri: Davranışı belgele veya `reports_from`'u dönem başına hizalamayı zorunlu kıl.

### F-812 Deney sağkalımı farm.feeding.fold.LOST kümesine bağlı; kayıp türü tanımı iki modülde ortak değil

Önem: **Bilgi** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `27-X2`  (yalnız çapraz görüş)
- Dosyalar: experiments/read.py:32, farm/feeding/fold.py:34
- Açıklama: Deney sağkalımı farm.feeding.fold.LOST kümesine bağlı; kayıp türü tanımı iki modülde ortak değil

### F-813 Bellekte arama/süzme ölçek kalıbı knowledge aramasında da var

Önem: **Bilgi** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `28-X2`  (yalnız çapraz görüş)
- Dosyalar: knowledge/search.py
- Açıklama: Bellekte arama/süzme ölçek kalıbı knowledge aramasında da var

### F-814 confirm.html POST action'ı sorgu parametrelerini taşıyor

Önem: **Bilgi** | Güven: belirtilmedi | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-X2`  (yalnız çapraz görüş)
- Dosyalar: templates/messaging/confirm.html, messaging/views.py
- Açıklama: confirm.html POST action'ı sorgu parametrelerini taşıyor

### F-815 Ortak 'void' diyalogu ve silme akisi sablonlari app bazinda kopya: sablon katmaninda mimari soyutlama eksik

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `31-X2`  (yalnız çapraz görüş)
- Dosyalar: templates/farm/water_void.html, templates/farm/stock_void.html, templates/farm/feeding_void.html
- Açıklama: Ortak 'void' diyalogu ve silme akisi sablonlari app bazinda kopya: sablon katmaninda mimari soyutlama eksik

### F-816 hr/services.py CLEAR sentinel'i object() ve dagilmis `is CLEAR` kontrolleri

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Mimari ve kod kalitesi | Doğrulama: doğrulanmadı

- Kaynaklar: `32-X2`  (yalnız çapraz görüş)
- Dosyalar: hr/services.py:203, hr/services.py:222
- Açıklama: hr/services.py CLEAR sentinel'i object() ve dagilmis `is CLEAR` kontrolleri

### F-817 Worker-yerel durum ve gözlemlenebilirlik eksikliği aynı kökten

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-X3`  (yalnız çapraz görüş)
- Dosyalar: monitoring/read.py:86, monitoring/read.py:274-278
- Açıklama: Worker-yerel durum ve gözlemlenebilirlik eksikliği aynı kökten

### F-818 Frontend, sablon tarafi sozlesmelerine (data-*, id) yazili test olmadan bagli

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `41-X4`  (yalnız çapraz görüş)
- Dosyalar: frontend/components.ts, frontend/poll.ts, core/tests_templates.py
- Açıklama: Frontend, sablon tarafi sozlesmelerine (data-*, id) yazili test olmadan bagli

### F-819 Silme/void onay formlari modalda ve sayfada farkli action kaynagi kullaniyor

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-X2`  (yalnız çapraz görüş)
- Dosyalar: templates/crud/confirm_delete.html, templates/farm/water_void.html, templates/crud/form.html
- Açıklama: Silme/void onay formlari modalda ve sayfada farkli action kaynagi kullaniyor

### F-820 Modal baslik/kapat kapsami: onay diyaloglarinda tekrarlayan akis kodu (Cancel link data-modal-close ile href'li)

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `43-X3`  (yalnız çapraz görüş)
- Dosyalar: templates/crud/confirm_delete.html, frontend/components.ts
- Açıklama: Modal baslik/kapat kapsami: onay diyaloglarinda tekrarlayan akis kodu (Cancel link data-modal-close ile href'li)

### F-821 Canlı mesaj listesi (`aria-live="polite"`) ve duyuru bölgelerinin sınırlamaları

Önem: **Bilgi** | Güven: düşük | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-20`
- Dosyalar: `templates/messaging/inbox.html:31`, `frontend/announce.ts:113-122`
- Açıklama: Sohbet listesi `<ol aria-live="polite">` ve poll ile eklenen her mesajı duyurur; `role="log"` bu iş için daha uygun olurdu. İzleme duyurusunda aynı metin art arda atanırsa (`node.textContent = out`) bazı ekran okuyucular aynı içeriği yeniden okumaz (içerik değişmedi). Poll aralığı kısa olduğunda yoğun duyuru riski sınırlayıcıyla (5 sn) azaltılmış (iyi).
- Kanıt: `announce.ts:117` `node.textContent = out;`.
- Öneri: `role="log"`; aynı cümle için boşaltıp yeniden yaz (clear-then-set) deseni.

### F-822 Kimlik doğrulama hata/kilit mesajları için erişilebilir durum yok

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `44-X4`  (yalnız çapraz görüş)
- Dosyalar: templates/registration/_field.html, config/urls.py
- Açıklama: Kimlik doğrulama hata/kilit mesajları için erişilebilir durum yok

### F-823 Dar/genis ekran yerlesimi: icerik sola yasli, ust baslik kesiliyor, satir ici stiller

Önem: **Bilgi** | Güven: düşük | Alan: Frontend, UX, erişilebilirlik, i18n | Doğrulama: doğrulanmadı

- Kaynaklar: `46-25`
- Dosyalar: `static/css/app.css:349-353` (`.content { max-width:1520px }`, `margin:auto` yok), `static/css/app.css:251-260` (`.topbar h1` nowrap+ellipsis), `templates/farm/production_units.html:112`, `templates/farm/_unit_capacity.html:4`, `monitoring/cards/render.py:40`
- Açıklama: Cok genis ekranda (>1520px + menu) icerik ortalanmaz. Telefonda `h1` tek satir ve ellipsis; uzun (TR/NB) basliklar kesilir, tam metne ulasmak icin `title` yok. Kapasite cubugu ve izleme widget yerlesimi inline `style=` kullaniyor; ileride siki CSP (`style-src`) konursa kirilir (su an CSP yok).
- Öneri: Gerekirse `margin-inline:auto`; baslikta 2 satira izin ver; inline stilleri CSS ozel ozellikleri/siniflariyla degistir.

### F-824 Document.text_status: FAILED durumundan yeniden deneme yok

Önem: **Bilgi** | Güven: düşük | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `48-15`
- Dosyalar: knowledge/models/document.py:75-81, 220-232
- Açıklama: Metin okuma yalnızca yeni dosya yüklenince çalışır; `FAILED`/`NO_TEXT` belge için "yeniden oku" eylemi görülmedi (tüm view'lar taranmadı).

### F-825 Özel 403 şablonu yok; raise_exception=True kullanan çok sayıda view çıplak 403 döndürür

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-X2`  (yalnız çapraz görüş)
- Dosyalar: reports/views.py, tasks/views.py, monitoring/views.py, templates
- Açıklama: Özel 403 şablonu yok; raise_exception=True kullanan çok sayıda view çıplak 403 döndürür

### F-826 Stok işlemlerinde kilit sırası tutarsızlığı (deadlock riski, düşük)

Önem: **Bilgi** | Güven: düşük | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `50-16`
- Dosyalar: farm/stock/services.py
- Açıklama: `_commit` önce Batch, sonra Tank, sonra plan kalemini kilitler; `void` önce StockOperation, sonra Batch, Tank kilitler. Postgres deadlock'u algılar ama bir istek 500 ile düşer; yeniden deneme yok.
- Kanıt: farm/stock/services.py:143-146 ve :215-217 (`_fulfil`) ile :746-750 (`void`).
- Öneri: Tek kilit sırası belirle veya 40P01'de bir kez yeniden dene.

## Olumlu doğrulamalar ve meta notlar (kusur değil)

### F-827 Doğrulanan olumlu kontroller (bulgu değil)

Önem: **Bilgi** | Güven: yüksek | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `02-17`
- Dosyalar: core/crud.py:557, 592-596; core/dbview.py:14-15; core/database.py:20; messaging/services.py:69-75; hr/services.py:271-276
- Açıklama: Her CRUD fiili izin + `scoped` ile korunuyor, kapsam dışı kayıt 404; veritabanı görüntüleyici `core.browse_database` ister ve matriste sunulmaz; mesaj konuşmaları üyelik dışı 404; izin kararları izin kontrolü sunucuda (düğme gizlemeye güvenilmiyor); izin onayında kendi talebini onaylama engelli (`_own`); sahte `next` yönlendirmeleri doğrulanıyor (hr/views.py:34-40, tasks/views.py:36-40).
- Kanıt: bkz. dosyalar.
- Öneri: Yok.

### F-828 Olumlu doğrulamalar (bulgu değil): HR okuma kapsamı, mesaj gizliliği, görüntüleyici girdi doğrulaması

Önem: **Bilgi** | Güven: yüksek | Alan: Veri okuma/yazma/değiştirme | Doğrulama: doğrulanmadı

- Kaynaklar: `09-23`
- Dosyalar: hr/scope.py, hr/read.py, hr/resources/leave.py, messaging/read.py, core/dbgrid.py, core/dbview.py
- Açıklama: Roster/bugün/özet okumaları sabit sayıda sorgu ve `visible_days`/`by_day` ile gün bazlı kapsam uyguluyor; kriz (crew) görünümü yalnızca düz değerlerden kuruluyor (`CrewCell`); izin türü/gerekçesi yalnızca kişi ve yetkilere gösteriliyor (`show_reason`, `type_shown`); silinmiş mesaj gövdesi şablonda gösterilmiyor ve `Message.__str__` metni dışarı vermiyor; mesaj ve görüntüleyici etiketleri (`Grid.labels`) maskeli sütunlara dokunmuyor; sıralama/filtre adları gerçek sütunlara karşı doğrulanıyor, `require_safe` ve `permission_required` her görüntüleyici görünümünde var; CSV hücreleri formül enjeksiyonuna karşı kaçışlı.
- Kanıt: core/dbview.py:14-15; core/dbgrid.py:133-138; hr/read.py:260-300; messaging/models.py:195-198.
- Öneri: Yok.

### F-829 Olumlu doğrulama: kilit sırası tutarlı, signal yok, `on_commit` doğru yerde

Önem: **Bilgi** | Güven: yüksek | Alan: Veritabanı ve veri bütünlüğü | Doğrulama: doğrulanmadı

- Kaynaklar: `16-14`
- Dosyalar: farm/stock/services.py:122-125, experiments/services.py (`_lock_tanks`, `save_places`, `replace_unit`), inventory/services.py:138-144, messaging/services.py:76-80
- Açıklama: Kilitler birincil anahtar sırasıyla ve hep aynı model sırasıyla (batch, tank, deney; öğe, konum) alınıyor; `grep` ile `post_save/pre_save/m2m_changed` alıcısı bulunmadı, gizli yan etki yok; `bulk_create` yolları audit'i açıkça yazıyor. Kod tabanında kilit sırası kaynaklı deadlock riski bulunamadı.
- Kanıt: `order_by('pk').in_bulk()` (stock/services.py:125); deneyde "tanklar önce, deney en son" (`save_places` docstring, experiments/services.py).
- Öneri: Yok; bu sırayı bir mimari notuna yaz.

### F-830 Olumlu doğrulamalar: birim dönüşümleri ve kimya sabitleri tutarlı

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `22-16`
- Dosyalar: farm/water/parameters.py, farm/water/chemistry.py, farm/water/dosing.py, farm/forms/water.py:400-460
- Açıklama: Yardım metinlerindeki dönüşümler doğru: alkalinite dKH × 17.85 (≈17.848), NH₄⁺ / 1.29 (18.04/14.007), NH₃ / 1.22 (17.03/14.007), NO₂⁻ / 3.29, NO₃⁻ / 4.43; `MG_CACO3_PER_MEQ=50.04345`, `H2S_PER_S=34.08088/32.065`, NH₃-N limiti varsayılanı 0.0103 = 0.0125 mg/L NH₃ × 14.007/17.031. Bound check'leri (`Round(F(bound), decimals)`), sıralı sınır kısıtı ve parametre başına duyarlılık tek kaynaktan türetiliyor. Saf Python ile: O₂ çözünürlüğü 10 °C tatlı su 11.288 mg/L, 10 °C %35 tuzluluk 9.024 mg/L; NH₃ payı pH 8, 15 °C tatlı su %2.66, deniz suyu %1.72 (beklenen aralıkta).
- Kanıt: Doğrudan `farm/water/chemistry.py` fonksiyonlarının çalıştırılması (`oxygen_solubility`, `nh3_fraction`, `pressure_atm`).
- Öneri: Yok; yalnızca regresyon testi olarak bu referans değerleri (11.29 mg/L, %2.66) `farm/tests/test_water.py`'ye sabitlemek faydalı olur.

### F-831 Olumlu doğrulamalar

Önem: **Bilgi** | Güven: yüksek | Alan: İş mantığı (alan modülleri) | Doğrulama: doğrulanmadı

- Kaynaklar: `29-19`
- Dosyalar: messaging/models.py, migrations/0001_initial.py, services.py
- Açıklama: Yazar-konuşma ve okundu işaretçisi-konuşma bileşik FK'leri DB'de; `direct_key` benzersiz, kanal adı büyük/küçük harf duyarsız benzersiz; post konuşma satırını kilitler (mesaj numaraları commit sırasıyla artar); mark_read tek UPDATE ile yalnız ileri; şablonlar otomatik kaçışla (linebreaksbr) XSS'e karşı güvenli; yanıtlar `no-store`; silme ve ayrılma POST+CSRF.
- Kanıt: migrations/0001_initial.py:14-22; services.py:236; views.py:62-64; templates/messaging/_messages.html.
- Öneri: Yok.

### F-832 Olumlu doğrulamalar (eşzamanlılık kontrolleri)

Önem: **Bilgi** | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-14`
- Dosyalar: hr/services.py:365-400, hr/models/attendance.py:52-62, inventory/services.py:129-160, farm/stock/services.py:119-150, tasks/services.py:104-190, core/crud.py:719-740, messaging/services.py:93-125
- Açıklama: clock_in/out çalışan satırı kilidi + `excl_attendance_employee_span` DB dışlama kısıtı; inventory/stock `_commit` pk sıralı kilit + `entry_key` unique ile idempotency; görev durum geçişleri satır kilidi altında kontrol-sonra-yaz; `start_direct` `IntegrityError` ile yarışı çözüyor; `CreateView` çift gönderimi `sent_before`/IntegrityError ile ele alıyor. Bu bölümlerde yarış bulunmadı.
- Kanıt: ilgili dosyalar.
- Öneri: Yok.

### F-833 Tekrarlayan görev üretiminin yinelenmeye karşı korumaları (olumlu) ve kalan tek zayıflık

Önem: **Bilgi** | Güven: yüksek | Alan: Hata yönetimi ve eşzamanlılık | Doğrulama: doğrulanmadı

- Kaynaklar: `34-6`
- Dosyalar: tasks/services.py:214-254, tasks/models.py:403
- Açıklama: Aynı gün için çift görev üretimi üç katmanla engelleniyor: seri satır kilidi (kilit altında `generated_until` yeniden okunur), `taken` kümesi (silinmişler dahil) ve `uq_tasks_series_occurrence` unique kısıtı. Çoklu worker + cron + sayfa tetikleyicisi birlikte güvenli. Kalan: kısıt ihlali olursa (örn. başka yoldan eklenmiş) `IntegrityError` yakalanmaz (bkz. 34-4).
- Kanıt: yukarıdaki satırlar.
- Öneri: Değişiklik gerekmez; 34-4 ile birlikte hata izolasyonu ekleyin.

### F-834 Olumlu dogrulamalar: toplu okuma, poll tasarimi ve indeksler (bilgi)

Önem: **Bilgi** | Güven: yüksek | Alan: Performans ve test | Doğrulama: doğrulanmadı

- Kaynaklar: `35-24`
- Dosyalar: monitoring/read.py:315-367, experiments/read.py:129-185, hr/read.py:180-262, farm/models/water.py:131, knowledge/models/document.py:172-173, frontend/poll.ts:118-187, messaging/read.py:48-76
- Açıklama: Kayda gecen iyi uygulamalar: (1) izleme kartlari kaynak basina tek toplu sorgu ve opsiyonel kaynaklar icin savepoint + log kisitlamasi kullaniyor; (2) HR haftalik cizelgesi kisi sayisindan bagimsiz sabit sayida sorgu yapiyor; (3) deney okumalari toplu (`stock_of`, `Presence`); (4) `water_meas_point_time_idx` (point, -measured_at) hypertable uzerinde mevcut, bilgi kutuphanesi aramasi GIN indeksli; (5) poll istemcisi sekme gizliyken durup jitter uyguluyor, sunucu 204 ile cevap veriyor; (6) `inbox()` iliskili alt sorgularla tek sorguda okunmamis sayilarini hesapliyor. Bu bolumler bulgu sayilmaz; yukaridaki bulgularin cogu ayni toplu tasarimin 'gecmisi tamamen katlama' temeline baglidir (35-1, 35-3, 35-7, 35-8).
- Kanıt: monitoring/read.py:1-37 (modul aciklamasi "ONE bulk call per source"), farm/models/water.py:131 (`water_meas_point_time_idx`), frontend/poll.ts:118 (`document.visibilityState !== 'visible'`).
- Öneri: Yok; mevcut deseni koruyup defter katlamasini onbellege/anlik goruntuye tasimak ana aksiyon (35-1).

### F-835 Doğrulanan olumlu noktalar (denetim kapsamı)

Önem: **Bilgi** | Güven: yüksek | Alan: Uçtan uca akış, durum ve dayanıklılık | Doğrulama: doğrulanmadı

- Kaynaklar: `49-14`
- Dosyalar: core/crud.py:546-570,592-596; core/resources.py; core/dbview.py:14-15; core/forms.py:97-113; core/admin.py:72
- Açıklama: Roller/kullanıcılar yalnız SU (auth.* matriste yok); /database/ yalnız SU ve `require_safe`; `UserForm` `is_staff/is_superuser` alanı sunmaz (yetki yükseltme yolu yok); Django admin'in Group/User kayıtları kaldırılmış; DeleteView/UpdateView `visible()` ile kilit altında kapsam yeniden doğrulanır; mount'lu HR rotaları `scoped` ile realm daraltır; mesajlaşmada üye olmayan 404; `document_file` login+izin ister ve MEDIA için URL rotası yok. IDOR/yatay yükseltme bulunamadı.
- Kanıt: bkz. dosyalar.
- Öneri: Yok.

### F-836 Repoya girmiş artefakt/sır yok (olumlu doğrulama)

Önem: **Bilgi** | Güven: orta | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-9`
- Açıklama: Takip edilen dosyalar arasında .sqlite/.db/.log/.pyc/.env/.pem/zip yok; en büyük dosyalar docs/data-map.json (852 KB), farm/tests/deffeyes_reference/reference.json (436 KB), .po dosyaları, README.md (316 KB). Pack boyutu 4.61 MiB, garbage 0. Silinen yalnızca iki şablon (_card_health.html, _card_water.html; adcda97) görüldü. Tarihsel içerikte sır taraması yapılmadı.
- Kanıt: `git ls-files | grep -Ei '\.(sqlite3?|db|log|pyc|zip|...)$|node_modules|...'` boş; `git count-objects -vH`.
- Öneri: Yine de gitleaks/trufflehog ile tüm geçmiş taraması CI'a eklensin.

### F-837 Güvenlik değerlendirmeleri Django kurulu olmadan yapılmış; check --deploy hiç koşulmadı

Önem: **Bilgi** | Güven: belirtilmedi | Alan: Güvenlik | Doğrulama: doğrulanmadı

- Kaynaklar: `05-X4`  (yalnız çapraz görüş)
- Dosyalar: requirements.txt
- Açıklama: Güvenlik değerlendirmeleri Django kurulu olmadan yapılmış; check --deploy hiç koşulmadı

### F-838 Denetim raporlari (docs/audit) takipsiz; komsu raporlar commitlenmedigi surece kaybolabilir

Önem: **Bilgi** | Güven: belirtilmedi | Alan: DevOps, API ve dokümantasyon | Doğrulama: doğrulanmadı

- Kaynaklar: `40-X2`  (yalnız çapraz görüş)
- Dosyalar: docs/audit/findings/31-architecture.md, docs/audit/findings/35-performance.md
- Açıklama: Denetim raporlari (docs/audit) takipsiz; komsu raporlar commitlenmedigi surece kaybolabilir

