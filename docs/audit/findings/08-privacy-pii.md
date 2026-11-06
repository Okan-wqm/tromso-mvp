# 08 - Gizlilik / Kişisel Veri (privacy-pii) Denetimi

## Özet

Depo kişisel veri açısından olgun bir tasarıma sahip: `Employee` modelinde maaş, banka, kimlik no, adres, iletişim kolonu yok (test ile korunuyor), izin sebebi / yoklama notu / karar notu `private_fields` ile aktivite günlüğünde metin olarak yazılmıyor, DB görüntüleyicide maskeleniyor, HR günlük kayıtları `hr.all_employee` iznine kısıtlanıyor, mesaj gövdesi görüntüleyicide maskeli. Buna karşın şu boşluklar var: (1) append-only denetim günlüğü kişisel veriyi (kontak e-posta/telefon, kullanıcı e-postası, görev notları) silinemez biçimde taşıyor; (2) kodda hiçbir saklama süresi / silme / anonimleştirme / veri sahibi erişim mekanizması yok (yalnızca HR kontrol listesinde karar bekleyen maddeler); (3) soft-delete edilen mesajların gövdesi veritabanında duruyor; (4) bazı serbest metin alanları "private" mekanizmasının dışında kalmış; (5) Django admin ve DB görüntüleyici maskelemesi tutarsız. Toplam 12 bulgu; kritik/yüksek yok.

## İncelenen alanlar

- `hr/models/*`, `hr/forms/employee.py`, `hr/resources/*`, `hr/scope.py`, `hr/services.py`, `hr/admin.py`, `docs/hr-launch-checklist.md`
- `core/audit.py`, `core/softdelete.py`, `core/admin.py`, `core/resources.py`, `core/forms.py`, `core/views.py` (activity_log), `core/migrations/0003_audit_log_append_only.py`
- `messaging/models.py`, `messaging/services.py`, `messaging/read.py`
- `tasks/models.py`, `tasks/services.py`
- `farm/models/contact.py`, `farm/resources/contact.py`, `core/crud.py` (RowList, private_fields)
- `reports/models.py`, `reports/exports.py`, `reports/resources.py`
- `config/settings.py`, `config/database.py` (DB görüntüleyici maske listesi), `docs/data-map.md`
- logger/print kullanımları (PII içeren log satırı bulunmadı)

## İncelenmeyen alanlar

- Frontend TypeScript (localStorage/tarayıcıda PII), şablonlar (`templates/`) içindeki maskeleme
- `knowledge` PDF yüklemeleri ve `media/` içeriği, `inventory`, `experiments` ekip üyeleri ayrıntısı
- Dağıtım/yedekleme/DB düzeyi şifreleme (repoda yok), reverse proxy erişim logları
- Çerez/oturum/CSRF (başka uzman alanı)
- Hukuki yeterlilik (KVKK/GDPR maddeleri doğrulanmadı; yalnızca kodda var olan/olmayan mekanizmalar)

## Bulgular

### 08-1 - Kontak e-posta/telefonu silinemez denetim günlüğüne düz metin yazılıyor
- Önem: medium
- Güven: high
- Dosyalar: `farm/resources/contact.py:14-20`, `core/crud.py:341-371`, `core/migrations/0003_audit_log_append_only.py`
- Açıklama: Site/tedarikçi kontak listesi kaydedilirken `RowList.save` eski/yeni özeti `describe()` ile günlüğe yazar. `ContactList.describe` ad, rol, **e-posta ve telefon**'u içerir. Bu özel veri `private_fields` mekanizmasından geçmez ve günlük tablosu DB trigger'ı ile UPDATE/DELETE'e kapalıdır. Kontak satırının kendisi silinse de (delete-all/insert-all) üçüncü kişinin e-postası/telefonu günlükte kalıcıdır.
- Kanıt: `describe`: `details = [value for value in (contact.role, contact.email, contact.phone) if value]`; `save`: `audit.record(user, UPDATE, obj, {str(cls.label): [before, after]}, ...)`; trigger `audit_log_append_only` "rows cannot be changed or deleted".
- Öneri: Kontak günlük özetinde e-posta/telefonu yazmayın (yalnızca ad/rol veya "değişti" + keyed digest) ya da günlük için anonimleştirme/redaksiyon yolu tasarlayın.

### 08-2 - Denetim günlüğü append-only: silme/anonimleştirme yolu yok, kullanıcı adı ve e-posta kalıcı
- Önem: medium
- Güven: high
- Dosyalar: `core/migrations/0003_audit_log_append_only.py`, `core/audit.py:129-143`, `core/resources.py:55-61`, `docs/hr-launch-checklist.md:59`, `core/models.py` (AuditLog)
- Açıklama: Trigger platform admin dahil herkesin UPDATE/DELETE yapmasını engeller (`docs/data-map.md` bunu "by design" yazar). `user_name` (kullanıcı adı) her satıra, kullanıcı oluşturma/değiştirme snapshot'ı ise e-posta, ad, soyadı (`UserForm` alanları) düz metin yazar. Silme/itiraz (KVKK m.7, GDPR m.17) talebinde bunları kaldırmanın yolu yoktur; hesaplar zaten silinmez, yalnız pasifleştirilir. Çakışma kontrol listesinde 4.2 olarak "owner karar verir" diye açık bırakılmış.
- Kanıt: `record(...)`: `user_name=user.get_username()`; `core/resources.py:58-59`: `fields = [... UserForm.tabs ...]; audit.snapshot(user, fields, ...)` (alanlar: username, first_name, last_name, email); trigger metni.
- Öneri: Günlükte kişisel alanları sözde-isimle (user id + ayrı çözümleme tablosu) tutun ya da yasal saklama süresi bitince anonimleştirmeye izin veren denetimli bir yol tanımlayın; kararı belgeleyin.

### 08-3 - Kodda saklama süresi, silme, anonimleştirme ve veri sahibi erişim/dışa aktarma mekanizması yok
- Önem: medium
- Güven: high
- Dosyalar: `hr/resources/employee.py:25-28`, `core/resources.py:42`, `hr/management/commands/` (check_hr, hr_roles, seed_hr_demo), `core/management/commands/`, `docs/hr-launch-checklist.md:56-59`
- Açıklama: Çalışan (`actions = ('add','change')`) ve kullanıcılar (`'people are deactivated, not deleted'`) asla silinmez; ayrılan çalışana yalnız `left_on` konur. Yoklama, izin, vardiya, yerleştirme, mesaj, görev notu kayıtları için temizleyen/anonimleştiren bir management komutu, zamanlanmış iş veya ayar yoktur. Veri sahibine erişim/taşınabilirlik dışa aktarımı yoktur. Bunlar yalnızca checklist 4.1'de "DPO belirler" diye kutucuk olarak duruyor.
- Kanıt: management komutları listesi (retention/purge/anonymize adı yok); depoda `retention` yalnızca README:1016 (yem kaydı bağlamında) ve checklist'te geçer.
- Öneri: Alan başına saklama süresi ayarı + denetimli anonimleştirme komutu (ayrılan çalışan, pasif kullanıcı, eski izin/yoklama) ve veri sahibi dışa aktarma ekleyin.

### 08-4 - Silinen mesajın gövdesi veritabanında duruyor (yalnız UI'da gizli)
- Önem: medium
- Güven: high
- Dosyalar: `messaging/services.py:268-276`, `messaging/models.py:138`, `messaging/views.py:269`
- Açıklama: `delete_message` yalnız `is_deleted/deleted_at/deleted_by` işaretler; `body` boş bırakılmaz/silinmez. Docstring "the text is never shown again" der ama metin satırda ve yedeklerde kalır; `Participant.last_read`/PROTECT ilişkileri nedeniyle satır da asla gerçek silinmez. Gövde yalnız DB görüntüleyicide maskelidir (`config/database.py`). Silme isteği fiilen silme olmaz.
- Kanıt: `message.is_deleted, message.deleted_at, message.deleted_by = True, timezone.now(), user; message.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])`.
- Öneri: Silmede `body`'yi boşaltın/yerine tombstone yazın (CHECK `message_has_text` buna göre gevşetilmeli) veya saklama süresi sonunda gövdeleri temizleyin.

### 08-5 - Görev notları, tamamlama notu ve iptal sebebi aktivite günlüğüne düz metin yazılıyor
- Önem: medium
- Güven: high
- Dosyalar: `tasks/services.py:37,200-202`, `tasks/models.py:357,493`, `core/audit.py:28-45`, `hr/apps.py:14`
- Açıklama: HR'deki izin sebebi/yoklama notu "kişinin kendi sözleri" olarak `private_fields` ile gizlenir; oysa görev notunun tam metni (`{str(NOTE): [None, body]}`) ve `completion_note`/`cancel_reason` (`LOGGED_AFTER`) günlüğe olduğu gibi yazılır. Görev günlük kayıtları `restrict` kapsamında değildir; `core.view_auditlog` sahibi herkes okur. Serbest metin kişisel veri (ör. bir çalışanın durumu, adı) içerebilir ve günlük silinemez (08-2).
- Kanıt: `audit.record(user, AuditLog.Action.UPDATE, task, {str(NOTE): [None, body]})`; `LOGGED_AFTER = [..., 'completion_note', ..., 'cancel_reason']`.
- Öneri: Bu alanları `private` (anahtarlı özet) kuralıyla günlüğe yazın veya günlükte yalnızca "not eklendi" gösterin; Task günlüğünü de kısıtlamayı düşünün.

### 08-6 - Django admin, DB görüntüleyicinin maskelediği HR/serbest metin alanlarını maskesiz gösteriyor
- Önem: low
- Güven: medium
- Dosyalar: `core/admin.py:22-70`, `hr/admin.py`, `config/database.py:masked`, `hr/models/leave.py:80-81`, `hr/models/attendance.py:43`
- Açıklama: `register_audited('hr')` tüm HR modellerini salt-okunur olsa da alan sınırlaması olmadan kaydeder; admin değişiklik/detay sayfası `LeaveRequest.reason`, `decision_note`, `AttendanceRecord.note`, `ShiftAssignment.note` alanlarını gösterir. DB görüntüleyici aynı alanları açıkça maskeler ve README/checklist "platform admin okumaz" niyetini taşır. Takım kapsamı (`hr.scope`) da admin'de uygulanmaz. Yalnız superuser (is_staff UI'dan verilmiyor) etkilenir, bu yüzden low.
- Kanıt: `register_audited` `list_display`/`fields` kısıtlamaz; `masked={... 'leave_requests': ('reason','decision_note'), 'attendance_records': ('note',) ...}` yalnız viewer'da.
- Öneri: HR modelleri için admin'de `exclude`/`readonly` ile bu alanları gizleyin veya HR'yi admin'e kaydetmeyin; iki yüzeyin maske listesini tek kaynaktan türetin.

### 08-7 - DB görüntüleyicinin maske listesi eksik (e-posta, görev notları, kontaklar)
- Önem: low
- Güven: medium
- Dosyalar: `config/database.py` (`masked=`), `core/database.py:33`
- Açıklama: Maske yalnız `auth_user.password`, `messages.body`, `shift_assignments.note`, `leave_requests.reason/decision_note`, `attendance_records.note` için tanımlı. `auth_user` (email, ad, soyad), `task_notes.body`, `tasks.completion_note/cancel_reason`, kontak tabloları (`site_contacts`/`supplier_contacts` ad/e-posta/telefon), `reports.contact_*` görüntülenebilir ve CSV ile dışa aktarılabilir. Checklist 4.3 görüntüleyiciyi yalnız IT'ye ver diyor; yine de maske politikası kişisel veri sınıflandırmasına dayalı değil.
- Kanıt: `masked={'auth_user': ('password',), 'messages': ('body',), ...}` — başka PII kolonu yok.
- Öneri: Kişisel veri kolonlarının bir envanterini çıkarıp görüntüleyici/dışa aktarma maskelerini ona göre tamamlayın; `docs/data-map` içine "PII" sütunu ekleyin.

### 08-8 - Anahtarlı özet (`rev`) zayıf: 8 hex karakter ve SECRET_KEY için güvensiz varsayılan
- Önem: low
- Güven: medium
- Dosyalar: `core/audit.py:96-100`, `config/settings.py:25`
- Açıklama: "Private text" yerine günlüğe `HMAC-SHA256(SECRET_KEY, değer)[:8]` yazılır. `SECRET_KEY` ortam değişkeni yoksa herkesin bildiği `django-insecure-local-development-only` kullanılır; bu durumda kısa/ortak metinlerin (ör. "sick", "hastalık") özetleri sözlük saldırısıyla çözülebilir. Ayrıca aynı metin farklı kayıtlarda aynı `rev`'i üretir (eşitlik sızıntısı: iki kişinin aynı sebebi girdiğini günlük okuyucusu görür). SECRET_KEY değişirse eski `rev` değerleri karşılaştırılamaz hale gelir.
- Kanıt: `hmac.new(settings.SECRET_KEY.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:8]`; `SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-...')`.
- Öneri: Üretimde varsayılan SECRET_KEY'i reddedin (check framework); özetin kayıt kimliğini de içermesi eşitlik sızıntısını azaltır.

### 08-9 - E-posta tek başına console backend: davet/şifre sıfırlama bağlantıları ve e-postalar stdout'a yazılır
- Önem: low
- Güven: medium
- Dosyalar: `config/settings.py:188-195`, `core/resources.py:62-70`, `core/forms.py:133-148`
- Açıklama: Yeni kullanıcı daveti `PasswordResetForm` ile gönderilir; `MAILERS['default']` tek tanımlı olarak console backend'dir ve ortam ile değiştirilmez. Üretimde yapılandırılmadıkça kullanıcı e-postası ve tek kullanımlık parola belirleme bağlantısı uygulama loglarına düşer (kişisel veri + kimlik bilgisi).
- Kanıt: `'BACKEND': 'django.core.mail.backends.console.EmailBackend'`.
- Öneri: Üretim için ortamdan e-posta backend'i ayarlayın; production'da console backend'i check ile reddedin.

### 08-10 - `DEBUG` varsayılan açık: hata sayfaları kişisel veriyi sızdırabilir
- Önem: low
- Güven: medium
- Dosyalar: `config/settings.py:27-30`
- Açıklama: `DJANGO_DEBUG` verilmezse `DEBUG=1` olur; hata ayıklama sayfası yerel değişkenlerdeki (çalışan adı, mesaj gövdesi, izin sebebi) verileri gösterir. `ALLOWED_HOSTS` boşsa DEBUG ile çalışır. Güvenli varsayılan değil ("fail-open").
- Kanıt: `DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'`.
- Öneri: Varsayılanı kapalı yapın veya `SECRET_KEY` ayarlıyken DEBUG'ı reddedin.

### 08-11 - HR kişisel verisinin okunması (erişim) kaydı yok; günlük yalnız değişiklikleri tutuyor
- Önem: low
- Güven: medium
- Dosyalar: `hr/services.py:33-362` (yalnız yazma yolları `audit.record*`), `core/audit.py`, `hr/resources/leave.py`, `hr/resources/attendance.py`
- Açıklama: Kimin hangi çalışanın izin/yoklama/izin türü (sick = sağlık verisi) bilgisini okuduğu hiçbir yerde kaydedilmez; `audit.record` çağrıları yalnız create/update/delete'tir. HR "Everyone" sahiplerinin tüm kişilere erişimi vardır; kötüye kullanımın sonradan tespiti mümkün değildir (KVKK m.12 veri güvenliği, erişim izlenebilirliği).
- Kanıt: `hr/services.py` içinde yalnız yazma sonrası `audit.record_*` çağrıları; okuma akışlarında (`hr/read.py`, resource detail) çağrı yok.
- Öneri: Hassas HR alanlarının (izin türü/sebebi detay sayfaları, dışa aktarımlar) okunması için ayrı, kısıtlı erişim kaydı düşünün.

### 08-12 - Rapor anlık görüntüsü/kontak bilgisi kişisel veriyi kopyalayıp sürdürüyor
- Önem: info
- Güven: medium
- Dosyalar: `reports/models.py:85-87,265`, `reports/resources.py:132`, `reports/exports.py:28`
- Açıklama: Yeni rapor formu, oturumdaki kullanıcının adı ve e-postasını `contact_*` alanlarına önceden doldurur; dosyalandığında dondurulmuş `ReportSnapshot` içinde ve Mattilsynet JSON/CSV dışa aktarımında (`navn`, `epost`, `telefonnummer`) taşınır. Yasal bildirim için meşru olabilir, ancak kullanıcı pasifleştirilse/silme istese bile kopya kalır ve saklama süresi tanımlı değildir (08-3).
- Kanıt: `initial = {'contact_name': user.get_full_name() or user.get_username(), 'contact_email': user.email}`; `{'navn': report.contact_name, 'epost': report.contact_email, 'telefonnummer': report.contact_phone}`.
- Öneri: Hukuki dayanağı ve saklama süresini belgeleyin; kişisel kontak yerine rol/ortak posta kutusu kullanımını önerin.

## Olumlu gözlemler (bulgu değil)

- `Employee` modelinde maaş/banka/kimlik/adres/iletişim kolonu yok; `hr/tests/test_boundary.py` `FORBIDDEN` desenleriyle korunuyor (`hr/models/employee.py:28-34`).
- `Message.__str__` metni asla göstermiyor (`messaging/models.py` ~160), mesaj gövdesi DB görüntüleyicide maskeli, mesaj sayfaları `Cache-Control: no-store` (`messaging/views.py:49`).
- HR günlük kayıtları `hr.all_employee` ile sınırlı (`hr/apps.py:14`); izin türü yalnız kişi/karar vericiye açık (`hr/resources/leave.py`).
- Kodda PII içeren `logger`/`print` çağrısı yok (yalnız monitoring/placements istisna logları).
