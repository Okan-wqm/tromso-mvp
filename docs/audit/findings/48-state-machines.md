# 48 - Durum makineleri ve yaşam döngüleri denetimi

## Özet
Repodaki durum alanları (Tank, Experiment, Task, LeaveRequest, KnowledgeEntry, OpenQuestion, FeedingProtocol, Site ve diğer "aktif/pasif" alanlar) incelendi. Çoğu modelde CheckConstraint ile durum-alan tutarlılığı iyi korunmuş. Asıl riskler: (1) Experiment için `running -> closed` geçişi tanımlı ama hiçbir servis/UI yok, yani çalışan deney kilitli kalıyor; (2) Tank `maintenance` durumunda balık varken çıkış yolu yok; (3) stok servisinin `_follow_status` işlevi `TRANSITIONS` tablosunu atlıyor; (4) geçiş kuralları çoğunlukla yalnızca uygulama katmanında (Task, Leave, KnowledgeEntry, Tank), DB tetikleyicisi yalnızca Experiment ve Report'ta; (5) Site/Üretim bölümü durumları (closed/inactive) operasyonlarda hiç uygulanmıyor. Testler çalıştırılmadı.

## İncelenen alanlar
farm/models/tank.py, farm/stock/services.py (_follow_status), experiments/models.py + services.py + migration 0002, tasks/models.py + services.py, hr/models/leave.py + services.py + forms/leave.py, knowledge/models/entry.py + views.py + document.py, reports/models.py + services.py, farm/models/feeding_protocol.py, farm/models/harvest.py (PlanStatus), farm/models/site.py, inventory LocationStatus.

## İncelenmeyen alanlar
messaging modeli (durum alanı yok/çalışmadı), monitoring, core, farm Equipment/Supplier/Feed/Medicine/Species/SlaughterFacility status alanları (ayrıntılı geçiş incelenmedi), frontend TS durum gösterimi, testlerin çalıştırılması.

## Bulgular

### 48-1 - Çalışan deney kapatılamıyor (running -> closed için kod yok)
- Önem: high | Güven: high
- Dosyalar: experiments/models.py:50-54, experiments/services.py:653-669, experiments/migrations/0002_design_frozen.py:56, docs/experiments.md:51
- Açıklama: `TRANSITIONS` ve DB tetikleyicisi `running -> closed` geçişine izin veriyor, ancak `experiments/services.py` içinde yalnızca `start` (draft->running) var; `Status.CLOSED` atayan hiçbir servis, form veya view yok. Dokümantasyon "closing is not built" diyor. Başlayan her deney sonsuza kadar `running` kalır; silinemez (`delete_blockers`), tasarımı değişemez, kapanışa bağlı okuma mantığı (`read.py` `closed`) hiç tetiklenmez.
- Kanıt: `grep Status.CLOSED experiments/*.py` yalnızca experiments/read.py:163'te okuma; experiments/models.py:147-155 "Close it instead" mesajı olmayan bir eylemi gösteriyor.
- Öneri: `close` servisi (kilit + audit + tetikleyiciye uyumlu) eklenmeli ya da silme mesajı düzeltilmeli.

### 48-2 - Silme engeli mesajı var olmayan "Close" eylemine yönlendiriyor
- Önem: low | Güven: high
- Dosyalar: experiments/models.py:150-153
- Açıklama: "It has started: it is kept as a record. Close it instead." mesajı 48-1 nedeniyle kullanıcıyı çıkmaza sokar.
- Öneri: 48-1 ile birlikte çözülür.

### 48-3 - Tank `maintenance` durumunda balık varken çıkış yolu yok
- Önem: medium | Güven: high
- Dosyalar: farm/models/tank.py:175-184, 516-541
- Açıklama: `MAINTENANCE` yalnızca `PREPARING` ve `INACTIVE`'e gidebilir; ikisi de `NEEDS_NO_FISH`. `ACTIVE`'ten `MAINTENANCE`'a balıklı geçilebiliyor (`NEEDS_FISH`/`NEEDS_NO_FISH` dışında), ama bakımdaki balıklı tank `ACTIVE`'e (veya `QUARANTINE`'e) dönemez; ancak balık boşaltılırsa `preparing` mümkün olur. Ayrıca `QUARANTINE`'den balıksız `ACTIVE` yasak, `CLEANING`'e gidiş balıklıyken `NEEDS_NO_FISH` nedeniyle engellenir: karantinadaki balıklı tank da yalnızca `ACTIVE`'e dönebilir.
- Kanıt: TRANSITIONS[MAINTENANCE] = (PREPARING, INACTIVE); status_blocker satır 504-509.
- Öneri: MAINTENANCE -> ACTIVE (balıklıysa) geçişi eklenmeli ya da kasıtlıysa belgelenmeli.

### 48-4 - Stok servisinin otomatik durum değişikliği TRANSITIONS tablosunu atlıyor
- Önem: medium | Güven: high
- Dosyalar: farm/stock/services.py:407-431, farm/models/tank.py:175-184
- Açıklama: `_follow_status` doğrudan `unit.status = ...; unit.save()` yapar, `_check_status`/`TRANSITIONS` çalışmaz (clean çağrılmıyor). Örn. `cleaning -> active` ve `inactive -> active` (void ile balık geri gelirse) tablo dışıdır. Kodun yorumu bunu kasıtlı gösteriyor ama makine tek yerde tanımlı değil; model.save() de geçişi doğrulamıyor.
- Öneri: Geçerli "sistem geçişleri" ayrı bir tablo olarak açıkça tanımlanmalı; `save()` içinde invariant testi.

### 48-5 - Tank geçişleri yalnızca `clean()` ile korunuyor (DB tetikleyicisi yok)
- Önem: low | Güven: medium
- Dosyalar: farm/models/tank.py:530-541, 587-597
- Açıklama: Experiment'ta tetikleyici var, Tank/Task/Leave/KnowledgeEntry'de yok; `objects.update()`, shell veya `save()` doğrudan çağrısı geçersiz geçiş yazabilir. Task/Leave'de en azından CheckConstraint'ler durum-alan uyumunu tutuyor, ama geçiş yönünü (ör. rejected -> approved) hiçbir DB kuralı engellemiyor (hr/migrations/0005_leave.py yalnızca self-decision tetikleyicisi içeriyor).
- Öneri: Kritik geçişler (Leave kararı, Task done/cancel) için tetikleyici düşünülmeli.

### 48-6 - Task `in_progress` -> `open` geri dönüşü yok
- Önem: low | Güven: high
- Dosyalar: tasks/services.py:104-166, tasks/models.py:384-387
- Açıklama: `start` yalnızca open'dan; `reopen` `OPEN_STATUSES` içindeki (in_progress dahil) görevleri reddeder ("This task is open already"). Yanlışlıkla başlatılan görev ya tamamlanır ya iptal edilip yeniden açılır (başlatan bilgisi silinir). Durum makinesi kasıtlı olabilir ama "unstart" yok.
- Öneri: belgelenmeli ya da `in_progress -> open` eklenmeli.

### 48-7 - Task `reopen` tamamlanma/iptal geçmişini siler; tek kayıt audit
- Önem: info | Güven: medium
- Dosyalar: tasks/services.py:151-166
- Açıklama: Reopen completed_at/by, completion_note, cancel_reason alanlarını temizliyor; kayıt yalnızca activity log'da (audit.record_update) kalıyor. Tutarlı ama alan düzeyinde geçmiş yok; reopen sayısı/çevrimi sorgulanamaz.

### 48-8 - Leave: reddedilmiş/iptal edilmiş talep için yeniden gönderim yolu yok; terminal durumlar belirsiz
- Önem: info | Güven: medium
- Dosyalar: hr/services.py:272-290, 305-335; hr/forms/leave.py:80
- Açıklama: `rejected` ve `cancelled` terminaldir (kodda geri dönüş yok); kullanıcı yeni talep açmalı, bu pending/approved ile çakışma kısıtı (hr/models/leave.py ExclusionConstraint) nedeniyle çalışır, yani tasarım tutarlı. Onaylanmış talep, ilk gün başladıktan sonra hiç iptal edilemez (can_cancel) ve düzeltme yolu da görünmüyor.

### 48-9 - Çalışan ayrılınca (left_on) ayrılış gününü kapsayan pending izin iptal edilmiyor, onaylı izinler olduğu gibi kalıyor
- Önem: low | Güven: medium
- Dosyalar: hr/services.py:130-136
- Açıklama: `align_placements` yalnızca `first_day > left_on` olan pending talepleri `cancelled` yapar. `left_on` sonrasına uzanan pending talep (first_day <= left_on < last_day) ve `first_day > left_on` olan APPROVED talepler dokunulmadan kalır; ayrılmış kişide hayalet onaylı izin oluşur.
- Öneri: approved/pending izinleri de ayrılışa göre kısalt veya iptal et.

### 48-10 - Site/ProductionDepartment/System durumları (closed/inactive/maintenance) operasyonlarda uygulanmıyor
- Önem: medium | Güven: medium
- Dosyalar: farm/models/site.py:26-30, farm/models/production_department.py:40-52, farm/models/system.py:35-56
- Açıklama: `Site.Status` (active/maintenance/inactive/closed) için grep ile yalnızca silme engeli mesajı ("set its status to Closed instead", site.py:121) bulundu; kapalı sitedeki tanklara stok girişi, görev oluşturma veya rapor üretimi engellenmiyor, alt birimler (tank) kapanışta otomatik pasifleşmiyor. Durum yalnızca bilgi amaçlı. (Kapsamlı doğrulama sınırlı: tüm view'lar taranmadı.)
- Öneri: kapalı/pasif site için alt birim ve operasyon kuralları tanımlanmalı veya alanın yalnızca etiket olduğu belgelenmeli.

### 48-11 - FeedingProtocol: `active -> draft` onaysız (atanmamışsa) ve retired -> active serbest
- Önem: info | Güven: medium
- Dosyalar: farm/forms/feeding_protocol.py:54-59, farm/models/feeding_protocol.py:118-136
- Açıklama: Atanmamış aktif protokol draft'a döner (formda tüm seçenekler açık), atanmış olan dönemez. `retired -> active` her zaman serbest; deney başlatma (experiments/services.py:161) yalnızca ACTIVE protokolü kabul eder, geri aktifleştirme bu varsayımları değiştirir. Tutarlı ama açık bir geçiş tablosu yok (Tank/Experiment'ın aksine).

### 48-12 - Durum makinesi tanımları tutarsız biçimde dağılmış
- Önem: info | Güven: high
- Dosyalar: farm/models/tank.py:175, experiments/models.py:50, tasks/services.py (servis içi), hr/services.py (can_decide/can_cancel), knowledge/views.py:55-85
- Açıklama: Yalnızca Tank ve Experiment'ta açık `TRANSITIONS` sözlüğü var; Task, Leave, KnowledgeEntry geçişleri servis fonksiyonlarındaki if'lerde, FeedingProtocol form/clean içinde. Aynı model için tek kaynak yok, test ve doküman zorlaşır.

### 48-13 - KnowledgeEntry: değişiklikle draft'a dönüş formda, doğrudan model yazımında değil
- Önem: low | Güven: medium
- Dosyalar: knowledge/forms/entry.py:88, knowledge/models/entry.py:176-181, knowledge/views.py:72-80
- Açıklama: "reviewed kayıt değişince draft'a döner" kuralı yalnızca `KnowledgeEntryForm` içinde; model `save()`/servis düzeyinde değil. Başka bir yazma yolu (import, API, shell) incelenmiş kaydı reviewed bırakarak içeriğini değiştirebilir. AI ajanlarının yalnızca reviewed kayıtla çalışacağı belirtildiğinden (entry.py:~42) risk anlamlı.

### 48-14 - OpenQuestion answered -> open dönüşü: answer alanı korunuyor, tarih siliniyor
- Önem: info | Güven: medium
- Dosyalar: reports/models.py:327-331, reports/forms.py:154-170
- Açıklama: Form status'ü serbest düzenler; CheckConstraint open için `answered_on IS NULL` ister ama `answer` metnini serbest bırakır. Yeniden açma yolu ayrı servis/audit olmadan form düzenlemesiyle olur.

### 48-15 - Document.text_status: FAILED durumundan yeniden deneme yok
- Önem: info | Güven: low
- Dosyalar: knowledge/models/document.py:75-81, 220-232
- Açıklama: Metin okuma yalnızca yeni dosya yüklenince çalışır; `FAILED`/`NO_TEXT` belge için "yeniden oku" eylemi görülmedi (tüm view'lar taranmadı).
