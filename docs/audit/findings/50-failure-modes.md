# 50 - Felaket / Hata Senaryoları (failure-modes) Denetimi

## Özet
Çekirdek yazma yolları (stok, sağlık, yem, su, envanter operasyonları) iyi tasarlanmış: tek `transaction.atomic()`, `select_for_update` ile sıralı kilit, form başına `entry_key` token'ı ile çift gönderim koruması, `version` ile iyimser kilit. Zayıf noktalar bu yolların dışında kalıyor: genel CRUD `UpdateView`'in `IntegrityError` yakalamaması, token'sız modellerde (HealthEvent, KnowledgeEntry vb.) çift tıklama kopyası, DB timeout/kilit zaman aşımı ayarlarının olmaması, GET isteklerinde yazma (`materialise_due`), mesaj gönderiminde idempotency yokluğu, PDF yüklemede rollback'te yetim dosya, kurtarma (restore) yolunun yalnızca admin'de ve kısmi olması, yedekleme/DR dokümantasyonunun yokluğu. Hiçbir kritik bulgu yok; çoğu orta/düşük.

## İncelenen alanlar
core/crud.py (Create/Update/Delete/RowList), core/softdelete.py, core/audit.py, core/admin.py (restore), config/settings.py (DB, DEBUG), farm/stock/services.py (_commit, void, grading, harvest), farm/health|feeding|water servisleri (token), inventory/services.py, reports/services.py ve views.py, tasks/services.py, messaging/services.py, monitoring/read.py + placements (fail-open), knowledge/models/document.py + extraction.py, frontend/components.ts (modal submit) ve poll.ts, docker-compose.yml, README yedekleme/restore anlatımı.

## İncelenmeyen / sınırlı incelenen alanlar
hr/leave ve roster servisleri (yüzeysel), experiments servisleri (yalnızca atomic kullanımı sayıldı), farm/water hesaplama modülleri, migration geri alma yolları, testler çalıştırılmadı, gerçek DB kopması canlı denenmedi (salt-okunur analiz), kilit sırası kaynaklı deadlock analizi derinlemesine yapılmadı.

## Bulgular

### 50-1 - Genel UpdateView IntegrityError yakalamıyor (eşzamanlı benzersizlik ihlali 500 verir)
- Önem: medium | Güven: high
- Dosyalar: core/crud.py
- Açıklama: `CreateView.post` benzersiz kısıt ihlalini `constraint_error` ile forma çevirir; `UpdateView.post` aynı korumaya sahip değil. İki kişi farklı kayıtları aynı koda/ada eşzamanlı çevirirse (form doğrulaması kilitten önce çalışır, sadece kendi satırı kilitlenir) ikinci kayıt DB kısıtına çarpar.
- Kanıt: core/crud.py:715-742 (`form.is_valid()` kilitten önce, `transaction.atomic()` içinde `obj.save()`; `except IntegrityError` yok) ve karşılaştırma core/crud.py:687-696.
- Öneri: UpdateView'de de IntegrityError yakalanıp `constraint_error` ile forma yazılmalı.

### 50-2 - Token'sız modellerde çift tıklama/yeniden gönderim kopya kayıt üretir
- Önem: medium | Güven: medium
- Dosyalar: core/crud.py, farm/models/health.py, knowledge/models/entry.py, frontend/components.ts
- Açıklama: Genel CRUD create idempotency'si yalnızca modelde `entry_key` alanı varsa çalışır. `HealthEvent` ve `KnowledgeEntry` gibi, doğal benzersiz anahtarı olmayan AuditedModel'lerde `entry_key` yok; çift tıklama iki kayıt yaratır. İstemci tarafında gönderim sırasında buton devre dışı bırakılmıyor. Kodu olan modellerde (site, tank) ikinci istek ilkinin kodu yüzünden "kod kullanılıyor" hatası gösterir; kullanıcı kaydın aslında oluştuğunu anlamaz.
- Kanıt: core/crud.py:165-166 (`ENTRY_KEY` yalnızca alan varsa), core/crud.py:193-196; farm/models/health.py:460 (HealthEvent'te entry_key/benzersiz kısıt yok); knowledge/models/entry.py:46-130; frontend/components.ts:317-321 (submit'te buton kilidi yok).
- Öneri: Tüm genel create formlarına entry_key ekle veya modal/form submit'te butonu kilitle.

### 50-3 - DB bağlantı/ifade/kilit zaman aşımı tanımlı değil
- Önem: medium | Güven: high
- Dosyalar: config/settings.py
- Açıklama: DATABASES'te `OPTIONS` yok: `connect_timeout`, `statement_timeout`, `lock_timeout` yok. Servislerdeki `select_for_update()` kilidi süresiz bekler; takılan bir işlem arkasındaki tüm istekleri bloklar. DB erişilemezse bağlantı denemesi işletim sistemi zaman aşımına kadar asılı kalabilir.
- Kanıt: config/settings.py:110-125 (yalnızca CONN_MAX_AGE ve CONN_HEALTH_CHECKS); `select_for_update` kullanımı örn. farm/stock/services.py:125, core/crud.py:724.
- Öneri: OPTIONS içinde connect_timeout ve `-c lock_timeout/statement_timeout` ayarla; lock timeout hatasını kullanıcıya anlaşılır göster.

### 50-4 - GET isteklerinde yazma: tasks.materialise_due sayfa okumalarına bağlı
- Önem: medium | Güven: high
- Dosyalar: tasks/services.py, tasks/resources.py, tasks/views.py
- Açıklama: Görev listeleri ve ana (production_home) özet tile'ları her okumadan önce `materialise_due()` çağırır; bu görev yazar, denetim kaydı ekler, satır kilitler. Tek bir serinin hata vermesi liste kompreyonunu keser, tüm sayfa (ve üretim ana sayfası) 500 olur; kilit bekleyen okuyucular yığılır; salt-okunur DB replika/kopma senaryosunda okuma yolu yazmaya takılır. Hata yalıtımı (try/except) yok.
- Kanıt: tasks/services.py:257-262 (list comprehension, hata yalıtımı yok), tasks/resources.py:92 ve :226, tasks/views.py:142 (overview_tiles, config/views.py:production_home üzerinden); materialise kilidi tasks/services.py:205-212 (`select_for_update` bekleyen, skip_locked değil).
- Öneri: Üretimi cron'a (`generate_tasks`) bırak, sayfa okumasında hata yut/logla ve `skip_locked` kullan.

### 50-5 - Mesaj gönderiminde idempotency yok
- Önem: low | Güven: high
- Dosyalar: messaging/services.py, messaging/views.py
- Açıklama: `post` kilitli ve atomik ama token almaz; çift tıklama ya da zaman aşımı sonrası yeniden gönderim aynı mesajı iki kez yazar. Stok/sağlık formlarındaki token modeli burada uygulanmamış.
- Kanıt: messaging/services.py:231-247; messaging/views.py:92-98 (form token'ı yok).
- Öneri: Forma token ekle veya kısa pencerede aynı yazar+gövde tekrarını yoksay.

### 50-6 - Restore yolu kısmi ve kilitsiz
- Önem: medium | Güven: high
- Dosyalar: core/softdelete.py, core/admin.py
- Açıklama: (a) `restore` yalnızca kaydın kendisini geri getirir; silmeyle birlikte silinen CASCADE çocukları ve SET_NULL ile koparılan bağlar geri gelmez (belgelenmiş ama kurtarma yolu manuel). (b) `restore` satırı kilitlemez ve `version` kontrolü yapmaz; eşzamanlı bir düzenleme/silmeyle yarışabilir. (c) Geri yükleme yalnız Django admin eylemi; uygulama arayüzünde yok. Sonuç: yanlışlıkla silinen ağaç (ör. saha) geri alınırken çocuklar tek tek elle geri getirilmeli.
- Kanıt: core/softdelete.py:189-203 (docstring: "Only the record itself returns"; `select_for_update` yok); core/softdelete.py:171-186 (detach/cascade kaydı log'a yazılır ama geri alınmaz); core/admin.py:36-50.
- Öneri: Silme planını (audit kaydı) kullanan "plan ile geri al", restore'da `select_for_update` ve version kontrolü.

### 50-7 - Kilitten önce okunan nesne: eşzamanlı silmede UpdateView/RowListView 500
- Önem: low | Güven: medium
- Dosyalar: core/crud.py
- Açıklama: `get_object` (404 verir) ile kilit alan `.get(pk=pk)` ayrı sorgular; aradaki pencerede kayıt silinirse `.get` `DoesNotExist` fırlatır, 404 yerine 500. DeleteView `get_object_or_404` kullandığı için tutarsız.
- Kanıt: core/crud.py:724 ve :815 (`.get(pk=pk)`) ve :770 (`get_object_or_404`).
- Öneri: `get_object_or_404` kullan.

### 50-8 - Silme: çift tıklamada ikinci istek 404, çocuk kayıtlar kilitlenmiyor
- Önem: low | Güven: medium
- Dosyalar: core/crud.py, core/softdelete.py
- Açıklama: Başarılı silmeden sonra ikinci POST 404 sayfası döner (idempotent başarı değil). Ayrıca plan yalnız `obj` satırını kilitler; plan hesaplandıktan sonra eşzamanlı eklenen bir çocuk, silinmiş ebeveyne bağlı canlı kayıt olarak kalabilir (düşük olasılık).
- Kanıt: core/crud.py:767-790 (kilit yalnız `of=('self',)`); core/softdelete.py:117-150 (`_collect` çocukları kilitsiz listeler), :162-172 (`execute`).
- Öneri: Zaten silinmiş kaydı başarı olarak ele al; çocuk eklemede ebeveyn canlılığını kilit altında doğrula.

### 50-9 - PDF yükleme: rollback'te yetim dosya, istek içinde senkron ayrıştırma
- Önem: medium | Güven: medium
- Dosyalar: knowledge/models/document.py, knowledge/extraction.py, config/settings.py
- Açıklama: Yeni dosya `super().save()` sırasında depolamaya hemen yazılır (FileField pre_save); işlem sonradan geri alınırsa (örn. audit yazımı hatası) dosya MEDIA_ROOT'ta yetim kalır. Eski dosyanın silinmesi `on_commit` ile korunmuş ama yeni dosya için rollback temizliği yok. Ayrıca `read_pdf` istek içinde senkron çalışır; sayfa sayısı/süre sınırı yok (20 MB sınırı var), büyük/kötü PDF worker zaman aşımına yol açabilir; sonuç DocumentPage'leri toplu silip yeniden ekler.
- Kanıt: knowledge/models/document.py:217-250 (`read_pdf` ve `super().save()`; `on_commit` yalnızca eski dosya için), knowledge/extraction.py:58-76 (sayfa/süre sınırı yok), config/settings.py:185.
- Öneri: Rollback'te yeni dosyayı silecek `on_rollback`/temizlik işi; sayfa sayısı üst sınırı veya arka plan işi.

### 50-10 - Raporlar: close_due/record_duty_done kontrolü işlem dışında, yarışta 500; reopen çift log
- Önem: low | Güven: medium
- Dosyalar: reports/services.py, reports/views.py
- Açıklama: `close_due` "borçlu mu" kontrolünü işlemden ve kilitten önce yapar; eşzamanlı iki kapatmada `full_clean` ikisini de geçerse `uq_due_closures_period` IntegrityError'ı yakalanmaz (view yalnız ValidationError yakalar). `reopen` ve `undo_duty_done` kilitsiz; eşzamanlı iki istek DELETE log satırını iki kez yazabilir. `record_duty_done` için de aynısı (`uq_duties_done_year`).
- Kanıt: reports/services.py:111-128 (kontrol 114-115'te işlem dışı), :131-139, :142-165, :168-174; reports/views.py:105-117, :160-167.
- Öneri: Kontrolü atomic içine al, IntegrityError'ı ValidationError'a çevir.

### 50-11 - Rapor gönderiminde ağır hesap kilit altında, içerik hash yarışına karşı uzun işlem
- Önem: low | Güven: low
- Dosyalar: reports/services.py
- Açıklama: `submit` rapor satırını kilitlemişken `compute.compute` çalıştırır (problem varsa iki kez). Uzun hesap kilidi uzatır; ayrıca DB zaman aşımı olmadığından (50-3) tüm rapor sayfaları bekleyebilir. Gönderim yalnızca kaydı tutar, yetkiliye gerçek iletim yok; bu yüzden "gönderildi" kaydı ile gerçek iletim ayrışabilir (süreç riski).
- Kanıt: reports/services.py:49-62 (compute kilit altında), :63-66 (ikinci compute).
- Öneri: Sonucu tek kez hesapla; uzun hesapları kilit dışına al.

### 50-12 - Modal formda ağ hatası ele alınmıyor
- Önem: low | Güven: high
- Dosyalar: frontend/components.ts
- Açıklama: `Modal.load` içindeki `fetch` için try/catch yok; ağ kopması veya zaman aşımında promise reddedilir, modal sessizce eski haliyle kalır ve kullanıcı bilgi almadan tekrar gönderir (50-2 ile birleşince kopya). Zaman aşımı (AbortSignal) yok; poll.ts ise 20 sn zaman aşımı ve geri çekilme uygular, yani tutarsız.
- Kanıt: frontend/components.ts:334 (`await fetch` korumasız, `void this.load(...)` satır 322); frontend/poll.ts:60-62 (TIMEOUT 20000, STALE_AFTER).
- Öneri: Hata durumunda iletişim mesajı göster, göndermeyi kilitle, AbortSignal.timeout kullan.

### 50-13 - Yedekleme/felaket kurtarma planı ve prosedürü yok; DB tek tomlu
- Önem: medium | Güven: medium
- Dosyalar: docker-compose.yml, README.md, config/settings.py
- Açıklama: Repoda pg_dump/WAL arşivi/PITR veya medya (MEDIA_ROOT) yedeği betiği ya da dokümanı yok; DB tek `pgdata` volume'ünde. PDF'ler dosya sisteminde, DB'de yalnız yol var: DB ve medya ayrı yedeklenmezse tutarsız geri yükleme olur. README'deki "restore" geçişleri yalnız uygulama içi soft-delete restore'u anlatır. Olay/ölçüm (hypertable) verisi için chunk bazlı yedek stratejisi yok.
- Kanıt: docker-compose.yml:1-17 (tek volume, replika yok); README.md grep: "backup" geçmiyor; config/settings.py:177-185 (MEDIA_ROOT dosya sistemi).
- Öneri: DB+medya birlikte yedek/geri yükleme runbook'u ve test edilmiş prosedür.

### 50-14 - DEBUG varsayılanı açık; hata sayfaları ve loglama yapılandırılmamış
- Önem: low | Güven: medium
- Dosyalar: config/settings.py, config/urls.py, templates/
- Açıklama: `DJANGO_DEBUG` verilmezse DEBUG=1 (başarısız-açık varsayılan): üretimde env unutulursa ayrıntılı hata sayfaları açılır. Özel 404/500 şablonu ve `handler500` yok, `LOGGING` yok; `logger.exception` çağrılarının (monitoring, placements) nereye gideceği tanımsız. Sağlık/readiness uç noktası da yok; DB kopmasını orkestratör anlayamaz.
- Kanıt: config/settings.py:28 (`'1'` varsayılan), 24-25 (güvensiz SECRET_KEY geri dönüşü); config/urls.py (handler yok); `ls templates` çıktısında 404.html/500.html yok; monitoring/read.py:265-276 logger kullanır.
- Öneri: Varsayılanı DEBUG=0 yap, LOGGING ve /healthz ekle.

### 50-15 - Fail-open okuma yolları DB kopmasını "veri yok" gibi gösterebilir
- Önem: info | Güven: medium
- Dosyalar: monitoring/read.py, farm/placements.py
- Açıklama: `_optional` ve `placements.of` her `Exception`'ı yutar ve bölümü boş gösterir (log dakikada bir). Tasarım gereği, ancak DB bağlantısı geçici koptuğunda kullanıcı "veri yok"u gerçek veri yokluğundan ayırt edemeyebilir; log hız sınırı tanıdık hataları gizler. `Unavailable` kullanımı kısmen bunu önlüyor.
- Kanıt: monitoring/read.py:265-276 (`except Exception`, FAILED_AT sınırı); farm/placements.py:43-52.
- Öneri: Başarısız kaynakları kart üzerinde "okunamadı" olarak belirt (zaten `failed` bayrağı var, kullanıldığını doğrula).

### 50-16 - Stok işlemlerinde kilit sırası tutarsızlığı (deadlock riski, düşük)
- Önem: info | Güven: low
- Dosyalar: farm/stock/services.py
- Açıklama: `_commit` önce Batch, sonra Tank, sonra plan kalemini kilitler; `void` önce StockOperation, sonra Batch, Tank kilitler. Postgres deadlock'u algılar ama bir istek 500 ile düşer; yeniden deneme yok.
- Kanıt: farm/stock/services.py:143-146 ve :215-217 (`_fulfil`) ile :746-750 (`void`).
- Öneri: Tek kilit sırası belirle veya 40P01'de bir kez yeniden dene.
