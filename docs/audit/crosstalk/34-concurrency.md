# Eşzamanlılık uzmanı (34) - çapraz değerlendirme

Kapsam: architecture (31), code-quality (32), error-handling (33), performance (35), testing (36), i18n (45), permissions-matrix (49) bulguları.

## Doğrulananlar
- [33-6] / [32-12] / [31-11]: monitoring/read.py:86 `FAILED_AT = {}` süreç-yereli sözlük; kilitsiz, çok worker'da her worker ayrı log atar (34-13 ile aynı). Throttle yarışı zararsız (en kötü iki log).
- [35-15]: config/settings.py:121 `CONN_MAX_AGE` varsayılan 0; 15 sn poll ile her istekte yeni bağlantı. Dağıtım tanımı yok (34-11).
- [35-8]: yazma yolu kilit altında tüm geçmişi katlıyor; kilit tutma süresi geçmişle doğrusal büyür, aynı birim/parti üzerinde yazma serileşmesi uzar (eşzamanlılık etkisi eklendi).
- [35-12]: knowledge/models/document.py:222 `save()` içinde `extraction.read_pdf` (senkron, CPU ağır); CRUD'un atomic bloğu (core/crud.py) içinden çağrılırsa satır kilidi/bağlantı PDF okuma süresince tutulur.
- [35-6]: farm/management/commands/check_withdrawal.py:16 listede `read.stock_of(units)` her eleman için çağrılıyor (O(n^2)); salt okunur, eşzamanlılık riski yok.
- [33-11]: hr/views.py:86 ve experiments/services.py:451,666,883 IntegrityError'ı tek "yarış" mesajına çeviriyor; kısıt ayrımı yok. Yarış tespiti doğru yönde ama yanlış mesaj üretebilir.

## Reddedilen/düzeltilen
- [33-4] "kayıt edilmeden": monitoring/read.py:272-278'de `_optional` throttle'lı logger.exception var; zorunlu kaynaklar için ayrıca doğrulanmalı (error-handling kendi içinde 'olumlu' diyor, tutarsız).
- [35-2] severity high: okuma-only sorgu, yazma/kilit etkisi yok; eşzamanlılık açısından high değil (yük açısından geçerli).

## Önem derecesi
- [35-12] medium kalsın; açık işlem içinde ağır iş olduğu için eşzamanlılık açısından medium-high.
- [36-x] testing: yarış testleri var deniyor (36 özeti) ama 34-1/34-2 senaryoları (withdraw bayat liste, çocuk ekleme yarışı) için eşzamanlı test yok.

## Yeni bulgular
- 34-X1: [35-12] ile birleşik: PDF okuma + sayfa bulk_create + dosya silme (on_commit) tek save içinde; yarım kalan upload'da dosya depolamada yetim kalabilir (depolamaya yazma, DB rollback'ten önce).
- 34-X2: Test altyapısı tek DB + MD5 (36-13): TransactionTestCase/thread tabanlı gerçek yarış testi ile kilit sırası (34-8) doğrulanmıyor.
- 34-X3: Süreç-içi önbellek/durum (FAILED_AT) ile 31-11 "hatalar yutuluyor" deseni aynı kök: worker başına durum; metrik yok.

## Komşulara sorular
- error-handling: [33-4] zorunlu kaynak hatası için log yok mu, yoksa yalnız Unavailable'a mı çevriliyor; teyit eder misiniz?
- performance: [35-8] kilit altında katlama süresi ölçüldü mü; kilit bekleme zaman aşımı (lock_timeout) tanımlı mı?
- testing: eşzamanlı (thread) yarış testi var mı; 34-1/34-2 için?
- architecture: worker/dağıtım tanımı (gunicorn, çoklu süreç) neden yok (34-11, 35-23)?
