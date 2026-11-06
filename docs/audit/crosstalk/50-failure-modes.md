# 50 failure-modes: komşu bulguların çapraz değerlendirmesi

Kapsam: data-read (09), data-write (10), data-modify (11), backup-restore (12), audit-log (13), biz-water (22), permissions-matrix (49). Yalnızca okuma; kodda doğrulananlar yazıldı.

## Doğrulananlar
- 09-8 / 09-16: core/dbgrid.py:146 `isdecimal()` + `int()`; messaging/views.py:72,74,113 `isdigit()` + `int()`. Aşırı uzun veya '²' gibi girdide ValueError, yani 500. Bozuk girdi senaryosu olarak 50-12 ile aynı sınıfta.
- 09-13: farm/water/views.py:214-216 `_day` içinde `parse_date(...)` geçersiz ama biçimi doğru tarihte (2026-13-45) ValueError fırlatır. Yakalama yok.
- 12-5 / 12-15 / 11-7: core/softdelete.py:189-203 `restore` kilitsiz, yalnızca doğrudan FK kontrol eder, yalnızca kaydın kendisini döndürür; 50-6 ile örtüşür.
- 10-1 / 11-6: 50-7 ile aynı kök neden.
- 10-2: 50-1 ile aynı.
- 10-5 / 13-10: GET ile yazma; 50-4 ile aynı.
- 10-13: close_due / copy_template ön kontrol sonra yaz; 50-10 ile aynı.
- 11-15 / 12-3 / 13-16: PDF yetimi; 50-9 ile aynı.
- 12-1, 12-2: yedek yok; 50-13 ile aynı. Önem yüksek kalmalı.
- 12-11: ATOMIC_REQUESTS yok; audit+yazma atomikliği çağırana bırakılmış, hata kurtarma açısından önemli.

## Önem derecesi itirazları
- 09-11 (high): performans bulgusu; felaket senaryosu değil, ancak zaman aşımı yokluğu (50-3) ile birleşince tüm sayfayı kilitleme riski taşır. high makul.
- 09-13 (medium): düz kullanıcı girdisi 500; 09-8 low iken bu medium: tutarsız. Aynı sınıf, low/medium olmalı (kimlik doğrulanmış kullanıcı, veri kaybı yok).
- 09-2 (medium): statement_timeout yokluğu (50-3) ile birlikte düşünülürse tek kullanıcı DB'yi uzun süre meşgul edebilir; medium korunmalı, 50-3 ile çapraz bağlanmalı.
- 13-7 (medium): alarm eksikliği bir işletim/izleme bulgusu; failure-modes açısından kritik uyarı okuyan kimse yok, medium makul.
- 22-5 (medium): bayat kritik değerde alarmın kalkması fail-open davranıştır; failure-modes açısından high'a yakın değerlendirilebilir (sensör kopması = alarm kapanır).

## Yeni bulgular
Bkz. StructuredOutput 50-X1 ... 50-X4.

## Komşulara sorular
- data-write (10): 10-3 izin kotası için select_for_update hangi satır üzerinde olmalı (Employee satırı) ve 50-16 kilit sırası ile çakışır mı?
- backup-restore (12): hypertable restore sonrası audit trigger ve frozen-report trigger'ları kurtarma sırasında nasıl devre dışı bırakılacak?
- audit-log (13): audit.record transaction dışında çağrılırsa (13-8) hata durumunda log satırı mı yoksa değişiklik mi kaybolur; test var mı?
- biz-water (22): sensör verisi kesildiğinde (stale) kart OK mi gösteriyor, yoksa 'veri yok' mu; 22-12 yalnızca sıcaklık/oksijen için mi?
- permissions-matrix (49): 49-7 özel 500 şablonu yokluğu, 50-14 (DEBUG varsayılanı açık) ile birleşince yığın izi sızdırır mı?
- data-read (09): 09-17 okundu işaretçisi GET ile yazılıyor; replica/salt-okunur DB senaryosunda sayfa düşer mi?
