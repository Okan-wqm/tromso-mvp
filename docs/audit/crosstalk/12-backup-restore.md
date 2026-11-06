# Capraz Gorusme: backup-restore (12)

Kapsam: data-read (09), data-write (10), data-modify (11), audit-log (13), migrations (14), biz-inventory (23), deps-supply (07). Salt-okunur dogrulama.

## Onaylar
- 11-7 / 12-15: `core/softdelete.py:189-203` restore kilitsiz ve surumsuz; yalnizca dogrudan FK ve `full_clean` kontrol eder, `version += 1` yapar ama kilit/`select_for_update` yok.
- 11-8 / 11-3 (12-5, 12-6): `restore` docstring'i "Only the record itself returns" der; cocuklar ve SET_NULL ile koparilan baglar geri gelmez.
- 11-15 / 13-16 (12-4): `knowledge/models/document.py:239-240` eski dosya `on_commit` ile silinir; geri alinamaz, yedek yoksa kalici kayip.
- 13-1 / 14-6 (12-8, 12-14): append-only yalnizca satir tetikleyicisi; yedekten geri yukleme sirasinda tetikleyici/TRUNCATE yolu belgesiz.
- 14-4 (12-13): noop geri almalar dogru; geri alma veri kaybi riski tasir.
- 14-13 (12-12): TimescaleDB surum dogrulamasi yok; `docker-compose.yml:5` 2.17.2-pg17 sabit ama restore icin surum eslesmesi belgesiz.
- 07-9 / 07-8 (12-17): `docker-compose.yml:9` varsayilan parola `balik`, ayni imaj digest'siz.
- 13-4 / 13-17 (12-10, 12-8): hard delete audit'ten kurtarilamaz, saklama politikasi yok.
- 11-16: onay ekrani "admin'den geri alinabilir" vaadi; deney parcalari/stok icin dogru degil, yedekle iliskili beklenti hatasi.

## Itirazlar
Yok.

## Siddet degisiklikleri
- 11-7 low -> medium: restore, yedek disi tek geri alma yoludur; kilitsiz/surumsuz olmasi esen yazimla ezilebilir.
- 11-15 low -> medium: yetim dosya iyi huylu, ama ters yon (silinen eski PDF) 12-4 ile birlikte yedeksiz kalici veri kaybi.
- 14-12 medium: CI/migrate yonergesi yok; migrate oncesi yedek adimi da yok (yeni bulgu 12-X1 ile birlestirilmeli).

## Yeni bulgular
- 12-X1 (medium/high): Migrate oncesi yedek/geri donus adimi yok; migration'lar (14-4, 14-9) kayipli/engelli geri alma icerirken README/compose'ta dagitim oncesi snapshot onerilmiyor. Kanit: `docker-compose.yml:1-17` (yalniz dev DB), 14-12.
- 12-X2 (medium/medium): `knowledge/models/document.py:239-240` `on_commit` ile eski dosya siliniyor; commit sonrasi hata/yedek geri yuklemesi sonrasi DB eski dosya adini gosterir ama dosya yok. DB ve MEDIA_ROOT yedek tutarsizligi (12-3) bu yolla kalici "kirik baglanti" uretir.
- 12-X3 (low/high): `docker-compose.yml:12-14` `restart: unless-stopped` + tek `pgdata` volume; `docker compose down -v` tek komutla tum veriyi siler, uyari/yedek yok (12-2 ile iliskili, 09/10/11 bulgularinda gorulmedi).
- 12-X4 (low/medium): `restore` (core/softdelete.py:189-203) audit'e degisiklik icerigi yazmaz (13-5); yedekten kismi geri yukleme sonrasi audit ile DB arasi tutarsizlik tespit edilemez.

## Komsulara sorular
- 14 (migrations): `makemigrations`/`migrate` oncesi yedek veya `--plan` adimi var mi? reports 0005 ve farm 0019-0023 IrreversibleError durumunda geri donus yolu nedir?
- 13 (audit-log): pg_dump/restore'da `audit_log` append-only tetikleyicisi geri yuklemeyi engeller mi; restore proseduru nasil olmali?
- 07 (deps-supply): Dockerfile/prod imaji olmadan `pg_dump` istemci surumu (pg17) nerede garanti ediliyor?
- 11 (data-modify): restore'un kilitsiz olmasi esen soft-delete ile cakisirsa version ne olur?
- 10 (data-write): ATOMIC_REQUESTS yok (12-11); audit yazimi atomik olmayan yollar tam liste mi?
