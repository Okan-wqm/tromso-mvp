# Çapraz görüş: privacy-pii (08)

## Doğrulananlar
- 01-2 / 05-1 / 05-2 / 02-2: config/settings.py:25 (sabit SECRET_KEY) ve :28 (DEBUG varsayılan '1') doğrulandı. KVKK açısından DEBUG hata sayfaları (08-10) ve audit özeti (08-8) ile birleşiyor.
- 05-6 / 01-5: e-posta console backend; sıfırlama bağlantısı stdout'a düşer (08-9 ile aynı kök).
- 04-1 / 03-4: _field.html:20 `help_text|safe`; tasks/forms.py:80-81 yer etiketi kaçışsız gömülüyor. Doğrulandı.
- 02-5: aktivite günlüğünde yalnız HR türleri kısıtlı; 08-1/08-5 (kontak, görev notu düz metin) ile birleşince yetkisiz okuma yolu.
- 01-9: giriş/çıkış olayları audit'te yok; KVKK erişim izi eksikliği (08-11) ile aynı boşluk.
- 24-1/24-6: seri silme/geri yükleme ve sert silme; saklama/silme politikası (08-3) yokluğunu pekiştirir.
- 03-12: autoescape off yalnız düz metin e-postada; kabul edilebilir, fakat kullanıcı adı PII'dir ve loga düz yazılır.

## Önem derecesi
- 01-2 ve 05-2 high: PII açısından da uygun. 02-5 medium: PII açısından high'a yakın (düz metin not/kontak okunabiliyor).
- 03-12 info uygun.

## Yeni bulgular
Bkz. StructuredOutput 08-X1..08-X3.

## Sorular
- authn/secrets: SECRET_KEY rotasyonu audit 'rev' özetlerini geçersiz kılar mı, geçmiş kayıt doğrulanabilir mi?
- authz: Aktivite günlüğü görünümü hangi izinle açılıyor; kontak/görev notu içeren kayıtlar filtreleniyor mu?
- biz-tasks: Sert silinen planlı görevlerin audit izi kalıyor mu?
- timeseries: Retention eksikliği PII içermeyen ölçümler için mi, yoksa operatör/kullanıcı alanları da var mı?
- injection/csrf-xss: Parola sıfırlama e-postasındaki kullanıcı adı kaçışsız; başlık/satır enjeksiyonu için kontrol edildi mi?
