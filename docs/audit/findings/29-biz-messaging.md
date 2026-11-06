# 29 - biz-messaging: Mesajlaşma denetimi

## Özet
Alan: konuşmalar, kanallar, okunmamış sayacı, yetki, AI asistan katılımı tasarımı, gerçek zamanlılık (`messaging/` uygulaması, `templates/messaging/`, `frontend/poll.ts`).
Genel tablo: yazma yolu tek (`services.py`), üyelik 404 modeli, `direct_key` benzersizliği, konuşma kilidiyle sıralı mesaj no ve ileri-yönlü okundu işaretçisi sağlam kurulmuş; DB'de bileşik FK'ler var. Bulgular çoğunlukla kenar durumlar: yetim kanal, silinen mesajın açık sayfada kalması, `isdigit()` kaynaklı 500, olay dinleyicisi hatasının isteği bozması, GET ile okundu işaretleme, asistan tasarımındaki boşluklar. Testler çalıştırılmadı; yalnızca kod okundu.

## İncelenen alanlar
messaging/models.py, services.py, read.py, views.py, forms.py, events.py, screens.py, urls.py, migrations/0001, tests/*, templates/messaging/*, frontend/poll.ts (başlık), config/access.py, navigation.py, database.py, README "Messages" bölümü, core/navigation.py badge, docs/audit/findings (çakışma kontrolü).

## İncelenmeyen alanlar
Gerçek PostgreSQL çalışma planları (EXPLAIN), testlerin çalıştırılması, poll.ts'nin tamamı/CSS, mobil API (yok), çeviri katalogları, yük testi.

## Bulgular

### 29-1 (orta, güven yüksek) Son üye ayrılınca yetim kanal: ad sonsuza dek kilitli, geçmişe kimse ulaşamaz
Dosyalar: messaging/services.py:176-182, 202-208; messaging/models.py:62-64; messaging/tests/test_services.py:242-243
Açıklama: `_keep_an_owner` yalnızca başka üye kaldıkça son sahibin ayrılmasını engeller; tek kalan üye ayrılabilir. Kanalın katılımcısı kalmaz, ama kanal `is_deleted=False` kalır; `channel_name_unique` kısmi indeksi adı canlı kanal sayılarak tutmaya devam eder. Geri getirme/silme sayfası yok (screens.py: delete=gap), `add_members` sahip gerektirir, yani kimse kanala dönemez.
Kanıt: `if owners == [target] and (len(live) > 1 if leaving else True)`; test "the last one may go" sonrası `assertFalse(channel.participants.exists())`.
Öneri: Son üye ayrılınca kanalı soft-delete edin (adı serbest bırakır) veya son üyenin ayrılmasını engelleyip silme akışı sunun; yönetici için yetim kanal onarımı.

### 29-2 (orta, güven yüksek) Silinen mesaj, açık sayfalarda yeniden yüklenene dek görünür; olay/poll tasarımı silme ve üyelik değişikliğini taşımıyor
Dosyalar: messaging/views.py:108-121; frontend/poll.ts (data-poll-append); messaging/events.py:1-14; messaging/services.py:268-275
Açıklama: Poll yalnızca `id > after` mesajları ekler; silme ya da başkasının sayfasındaki mevcut satırın değişmesi hiçbir yoldan taşınmıyor. Planlanan push için tek olay `message_posted`; silme/üyelik olayı yok. README bunu kabul ediyor ("stays on an open page"), ancak "text is never shown again" sözüyle çelişir (hassas mesaj yanlışlıkla yazılıp silinse bile diğer üyelerde kalır). Kullanıcı kanaldan çıkarılınca sayfası bir sonraki poll'da 404 ile `gone` olur (iyi), ama mesajların DOM'da kalması sürer.
Kanıt: `new = read.after(participant, last_id)` yalnızca yeni id; `events.py` yalnızca `message_posted` tanımlar.
Öneri: `message_deleted`/`membership_changed` olayları ekleyin; o zamana dek poll'a `deleted_since` benzeri bir tazeleme ya da kısa aralıklı liste yenilemesi.

### 29-3 (orta, güven yüksek) Silinen mesajın metni veritabanında durur
Dosyalar: messaging/services.py:268-275; messaging/models.py:127-158 (CHECK message_has_text)
Açıklama: `delete_message` yalnızca bayrak yazar, `body` temizlenmez; CHECK `\S` boş gövdeye izin vermez, tombstone yazmak şu an mümkün değil. Maske (`config/database.py:27`) yalnız viewer'ı korur, yedekte metin kalır. (08-privacy-pii ile örtüşür.)
Kanıt: `message.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])`.
Öneri: Silmede gövdeyi tombstone ile değiştirin (CHECK'i `is_deleted OR \S` yapın) ya da saklama süresi sonunda temizleyin.

### 29-4 (düşük, güven yüksek) Silme etkinlik günlüğü/sürüm izi bırakmaz; kanal sahibi için moderasyon yok
Dosyalar: messaging/services.py:256-275; messaging/models.py:127
Açıklama: Mesaj `AuditedModel` değil; silme `version`/`updated_by` yazmaz, `audit.record_*` çağrısı yok (tasarım gereği, ama silen = yazar zaten). Yalnızca yazar silebilir (`own_message`: başkasınınsa PermissionDenied); kanal sahibi ya da yönetici uygunsuz mesajı kaldıramaz, ayrılan üye de kendi eski mesajını silemez (`member` canlı üyelik ister).
Kanıt: `if message.author_id != actor.pk: raise PermissionDenied`.
Öneri: Kanal sahibine moderatör silmesi (deleted_by ayrımıyla) düşünün; ürün kararı olarak belgeleyin.

### 29-5 (orta, güven yüksek) `?before=` / `?after=` üst simge rakamla 500 verir
Dosyalar: messaging/views.py:72, 74, 113
Açıklama: `str.isdigit()` '²' için True, `int('²')` ValueError (Python'da doğrulandı). Yetkili bir kullanıcı `/messages/<id>/?before=²` veya `/new/?after=²` ile 500 üretir. Testlerde kötü parametre denemesi yok.
Kanıt: `int(before) if before.isdigit() else None`; `int(after) if after.isdigit() else 0`.
Öneri: `isdecimal()`+`isascii()` ya da try/except ile ayrıştırın; üst sınır koyun.

### 29-6 (orta, güven orta) `message_posted.send` dinleyici hatasında istek 500 olur, ileti kaydedilmiş kalır
Dosyalar: messaging/services.py:246-247; messaging/events.py:10-11
Açıklama: `on_commit` içinde `Signal.send` (robust değil) kullanılıyor; bir dinleyici (planlanan push/AI dağıtıcı) istisna atarsa istisna, commit'ten sonra istek yoluna çıkar: mesaj yazılı ama kullanıcı 500 görür ve yeniden gönderince tekrar mesaj oluşur. events.py "must not fail the request" der ama kod bunu zorlamaz. Şu an dinleyici yok, bu yüzden gizli.
Kanıt: `transaction.on_commit(lambda: events.message_posted.send(...))`.
Öneri: `send_robust` + loglama ya da on_commit(robust=True).

### 29-7 (düşük, güven yüksek) GET ile okundu işaretleme; 50'den fazla okunmamış varsa görünmeyenler de okunmuş olur
Dosyalar: messaging/views.py:70-76; messaging/read.py:19-21, 98-105
Açıklama: Konuşmayı açan GET, gösterilen son mesaja işaretçiyi ilerletir. Okunmamış sayısı PAGE=50'yi aşarsa daha eski okunmamışlar sayfada yok ama "okundu" olur; "New" çizgisi de (`first_unread` yalnızca gösterilenlerde arar) çıkmaz. Ayrıca ön-getirme/ikinci sekme GET'i de okundu yapar.
Kanıt: `services.mark_read(participant, shown[-1].pk)` ve `shown` en fazla 50 mesaj.
Öneri: Okunmamış sayısı PAGE'i aşarsa işaretçiyi ilk okunmamışın hemen öncesine veya gösterilen sayfanın sonuna göre ayarlayın; işaretlemeyi POST/poll'a taşıyın.

### 29-8 (düşük, güven orta) Form uzunluk sınırı `\r\n` ile servis sınırından farklı sayar
Dosyalar: messaging/forms.py:31; messaging/services.py:237-241
Açıklama: Tarayıcı textarea satır sonlarını `\r\n` gönderir; form `max_length=4000`'i bunlarla sayar, servis ise `\r\n`'i `\n`'e çevirip sonra sınar. Çok satırlı ~3990 karakterlik mesaj serviste geçerken formda reddedilir.
Kanıt: `max_length=MAX_BODY` (form) / `text = body.replace('\r\n', '\n').strip()`; `len(text) > MAX_BODY`.
Öneri: Form sınırını kaldırıp servise bırakın ya da normalleştirmeyi `clean_body`da yapın.

### 29-9 (düşük, güven orta) `services.post` NUL karakteri ve tür doğrulamasını yapmaz; API/asistan yolu 500 üretebilir
Dosyalar: messaging/services.py:232-248
Açıklama: Docstring servisi API ve asistanlar için tek kural yeri sayar, ama NUL (`\x00`) denetimi yalnız Django form alanında (ProhibitNullCharactersValidator) var; servis doğrudan çağrılırsa PostgreSQL DataError (500). `body` str değilse AttributeError.
Kanıt: `text = body.replace(...).strip()`; hiçbir NUL kontrolü yok.
Öneri: Kuralı servise taşıyın.

### 29-10 (düşük, güven yüksek) `direct_key` asistanı desteklemiyor, docstring ile uyumsuz
Dosyalar: messaging/services.py:63-67; messaging/models.py:48-51
Açıklama: Docstring "An assistant's part will read 'assistant:<id>'" der, ama kod her tarafı `user:{pk}` yazar; asistan geçirilirse yanlış anahtar (`user:<uuid>`) oluşur ve kullanıcıyla çakışma/yanlış eşleşme riski. `start_direct`/`contacts` yalnız kullanıcıyı kabul eder, yani asistanla doğrudan konuşma yolu henüz yok.
Kanıt: `' '.join(sorted(f'user:{party.pk}' for party in parties))`.
Öneri: Parti türüne göre önek; asistan için ayrı `start_direct` yolunu tasarlayın.

### 29-11 (düşük, güven orta) Doğrudan konuşmanın iki katılımcı kuralı DB'de yok; `title()` `.get()` ile 500 verebilir
Dosyalar: messaging/models.py:56-68, 82-103; messaging/read.py:86-92, 66-69
Açıklama: CHECK yalnızca kind/direct_key/name şeklini zorlar; direct konuşmada katılımcı sayısı kodla korunur (`owner()` kanal ister). Tutarsız veri (elle/asistan akışı) olursa `title()`'daki `.get(conversation=...)` MultipleObjectsReturned fırlatır; `inbox` `others` sözlüğü ikinci katılımcıyı sessizce ezer.
Kanıt: `str(Participant.all_objects....exclude(pk=participant.pk).get(conversation=conversation))`.
Öneri: Dayanıklı yazım (`.first()`) ve yalnız servis yolundan katılımcı ekleme kuralı + test.

### 29-12 (düşük, güven yüksek) `start_direct` silinmiş konuşmayı döndürür
Dosyalar: messaging/services.py:102-103, 114; messaging/services.py:81-87
Açıklama: `Conversation.all_objects` kullanımı yüzünden soft-delete edilmiş doğrudan konuşma döner; `member()` canlı filtre uyguladığı için sayfa 404 verir. Şu an hiçbir şey konuşma silmiyor, ama silme eklendiğinde çift taraflı kalıcı 404. (02-authz ile örtüşür.)
Kanıt: `Conversation.all_objects.filter(direct_key=key).first()`.
Öneri: Silinmişi geri getirin ya da anahtarı serbest bırakacak şekilde silin.

### 29-13 (orta/tasarım, güven orta) AI asistan katılımı: yazma yolunda asistan yetki/etkinlik denetimi yok
Dosyalar: messaging/services.py:232-248; messaging/models.py:27-43, 82-103; README "AI assistants"
Açıklama: `post(author, body)` herhangi bir Participant'ı kabul eder; asistanın silinmiş olup olmadığına, sahibinin hâlâ aktif/`USE` iznine sahip olup olmadığına bakmaz (README: "worker checks the owner's permissions" - kural kodda değil, ileride dışarıda). Asistan katılımcısı eklemek için hizmet fonksiyonu yok; `_reachable` yalnız kullanıcıları denetler. Asistan kanala eklendiğinde kanalın tüm geçmişini okuyacak mı (add_members `last_read` ayarlıyor ama okuma sınırı yok) belirsiz; platform yöneticisinin okuyamadığı mesajları asistanın okuyabilmesi gizlilik modelini zayıflatır. `message_posted` yükü yazarın türünü/asistan olduğunu taşımıyor (dinleyicinin yeniden sorgulaması gerekir; asistan-asistan döngüsü koruması tasarlanmamış).
Kanıt: `post` yalnızca `Participant.objects.filter(pk=author.pk).first()` kontrolü; `Assistant` için `is_deleted`/`owner.is_active` denetimi yok.
Öneri: `post`ta yazar türüne göre yetki kuralı (asistan etkin + sahip izni), katılma/okuma kapsamı (`visible_from`), olay yüküne `author_kind`, döngü/hız sınırı tasarımı.

### 29-14 (düşük, güven orta) Okunmamış rozeti her render'da hesaplanır; sorgu Message tablosundan başlar
Dosyalar: messaging/read.py:25-31; core/navigation.py:69, 182; config/navigation.py:172-173
Açıklama: Rozet, kenar çubuğu her çizildiğinde ve her 30 sn'de ayrıca `Message.objects...Exists(...)count()` ile hesaplanır; sorgu kullanıcıdan değil mesajlar tablosundan başlar, planlayıcıya bağlı olarak tüm mesajlar taranabilir. Ek olarak `inbox` 15 sn'de bir, kullanıcı başına konuşma başı 3 ilişkili alt sorgu çalıştırır. Büyük mesaj hacminde pahalı olabilir (ölçülmedi). (09-data-read ile örtüşür.)
Kanıt: `Message.objects.filter(is_deleted=False).filter(Exists(mine)).count()`.
Öneri: Katılımcıdan başlayan (veya sayaç sütunlu) sorgu; EXPLAIN ile doğrulayın.

### 29-15 (info, güven yüksek) Mesaj gönderme için hız sınırı / spam koruması yok
Dosyalar: messaging/views.py:92-103; messaging/services.py:232-248
Açıklama: Her kullanıcı sınırsız sıklıkta mesaj yazabilir; poll 5 sn, tek mesaj 4000 karakter. Asistanlar eklendiğinde taşma riski artar.
Kanıt: Sınırlama kodu yok.
Öneri: Kişi/konuşma başına oran sınırı.

### 29-16 (info, güven orta) İzni düşen/pasifleşen karşı taraf sessizce birikim yapar
Dosyalar: messaging/services.py:47-60, 70-75, 90-104
Açıklama: `_reachable` yalnız konuşma/üye eklerken çalışır. Sonradan hesabı pasif veya izni kalkan kişi doğrudan konuşmada ve kanallarda katılımcı kalır; gönderen bunu görmez, mesajlar okunmadan birikir ve kişi geri dönerse tümü "okunmamış" olur. Rozet/okunmamış yalnızca canlı üyelik arar, kişinin etkinliğine bakmaz (kapsam dışı olabilir).
Kanıt: `_reachable` çağrıları yalnız `start_direct`, `create_channel`, `add_members`.
Öneri: Karşı tarafın durumunu konuşma başlığında göstermek; pasif kullanıcıları roster'dan ayıklamak.

### 29-17 (info, güven orta) `leave` içinde kilit, üyelik denetiminden önce alınıyor
Dosyalar: messaging/services.py:77-79, 201-208
Açıklama: `_locked(conversation_id)` `member()`'dan önce çağrılır: Messages iznine sahip herhangi biri bir konuşmanın UUID'sini bilirse üyesi olmadan satır kilidi alıp işlem süresince tutabilir (kısa). UUID tahmin edilemez, risk düşük; kural "üye olmayan için konuşma yoktur" ile tutarsızlık.
Kanıt: `_locked(conversation_id); actor = member(user, conversation_id)`.
Öneri: Önce `member()`, sonra kilit (tutarlı sırayla; `owner()` de aynı).

### 29-18 (info, güven yüksek) Test boşlukları
Dosyalar: messaging/tests/test_pages.py, test_services.py
Açıklama: Bulunmayan testler: bozuk `before/after` parametreleri (29-5), POLL_LIMIT=200 taşması, >50 okunmamışta işaretçi (29-7), son üye ayrılınca yetim kanal davranışı yalnızca "izin verilir" olarak sabitlenmiş (29-1), olay dinleyicisi istisnası (29-6), eşzamanlı remove/leave yarışı, asistan katılımcısı ile `post`/`title`. Eşzamanlı `start_direct` testi var (iyi).
Kanıt: grep sonucu: POLL_LIMIT ve kötü parametre testi yok.
Öneri: Yukarıdaki durumlar için test ekleyin.

### 29-19 (info, güven yüksek) Olumlu doğrulamalar
Dosyalar: messaging/models.py, migrations/0001_initial.py, services.py
Açıklama: Yazar-konuşma ve okundu işaretçisi-konuşma bileşik FK'leri DB'de; `direct_key` benzersiz, kanal adı büyük/küçük harf duyarsız benzersiz; post konuşma satırını kilitler (mesaj numaraları commit sırasıyla artar); mark_read tek UPDATE ile yalnız ileri; şablonlar otomatik kaçışla (linebreaksbr) XSS'e karşı güvenli; yanıtlar `no-store`; silme ve ayrılma POST+CSRF.
Kanıt: migrations/0001_initial.py:14-22; services.py:236; views.py:62-64; templates/messaging/_messages.html.
Öneri: Yok.
