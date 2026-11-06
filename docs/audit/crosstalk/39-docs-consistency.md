# 39 docs-consistency capraz degerlendirme

Dogrulananlar:
- 33-1 / 33-2 / 35-23 / 50-14: config/settings.py:28 `DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'` (varsayilan acik); LOGGING tanimi yok. README bunu belgelemiyor (bkz. 39-11). Dokumantasyon eksigi olarak da gecerli.
- 34-11 / 50-13: README.md:2991 DB_CONN_MAX_AGE'i "gunicorn icin" diye anlatiyor ama repoda gunicorn/dagitim tanimi yok; README'de yedekleme/DR bolumu yok (README.md:2384 yalniz "sunucunun yedekleri" diye geciyor).
- 33-4: monitoring/read.py:335-336 `except Exception as error: raise Unavailable(str(error)) from error` kayitsiz; ayni dosyada :272-277 opsiyonel kaynaklar logger.exception ile kayitli. Tutarsizlik dogru.

Onem derecesi:
- 33-1 (high/medium) belgeleme acisindan: README'de uretim yapilandirmasi hic anlatilmadigi icin fail-open DEBUG riskinin ciddiyeti artiyor; severity korunabilir.

Yeni bulgular: 39-X1 (README uretim/dagitim ve yedekleme yok, DEBUG varsayilani belgesiz), 39-X2 (README CONN_MAX_AGE "gunicorn" ifadesi dagitim olmayan bir sunucuya atif).

Sorular: architecture'a: README Layout tablosu ile gercek app listesi (hr, monitoring) farkini mimari rapor da kayda aldi mi? error-handling'e: 400/403/404/500 sablonlarinin yoklugu README'de iddia ediliyor mu?
