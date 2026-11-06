# 17 timeseries - capraz denetim

## Dogrulananlar
- 09-1: core/database.py:115-122 `counts()` `Count('pk')` ile water_measurements hypertable'inin tum chunk'larini her genel bakista tarar (zaman kosulu yok). Onaylandi; 17-2 (retention/aggregate yok) ile birlikte buyudukce yavaslar.
- 09-12: farm/water/views.py:220-229 ve farm/water/read.py:469-505; `list(samples)` tum araligi bellege alir, `history()` Context'i min(measured_at) ile kurar; sayfalama sonra (views.py:229). Onaylandi (17-8/17-9 ile ayni aile).
- 09-13: farm/water/views.py:214-216 `parse_date` gecersiz tarihte ValueError verir; onaylandi.
- 12-12: farm/migrations/0014_water.py:91-103 hypertable olusturur; dump/restore belgesi yok. Onaylandi (17-10/17-11 ile ayni).
- 13-17: etkinlik logu hypertable degil, ayri konu; zaman serisi acisindan tavsiye: retention.

## Yeni bulgu
- 17-X1: `?to=9999-12-31` -> `end + timedelta(days=1)` OverflowError (500) (farm/water/views.py:221-225); ayrica `from > to` bos sonuc sessizce doner.
- 17-X2: Su gecmisi araligi ust sinirsiz oldugundan hypertable'da cok sayida chunk taranir; 09-12 ve 17-3 ile birlesik risk (farm/water/views.py:216).
