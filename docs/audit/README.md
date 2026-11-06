# Tromso MVP: uzman denetimi özeti

Tarih: 2026-11-06. Kapsam: `tromso-mvp` deposu (Django 6.1, PostgreSQL + TimescaleDB, TypeScript frontend; farm, hr, inventory, knowledge, messaging, monitoring, reports, tasks, experiments, core). Denetim yalnızca okuma ile yapılmıştır; kod ve veri değiştirilmemiştir.

## Yönetici özeti

- 50 uzman 831 bulgu, çapraz görüş aşaması 126 yeni bulgu üretti (toplam 957 ham kayıt). Aynı kök nedenler birleştirilince **838 tekil kayıt** kaldı: 826 bulgu, 10 olumlu doğrulama, 2 meta not.
- Nihai önem dağılımı (tekil bulgular): Yüksek 0, Orta 244, Düşük 421, Bilgi 161. Uzmanların "yüksek" dediği 20 kayıt ve çapraz görüşteki 1 kayıt (toplam 21) doğrulama sonrası Orta veya altına indirildi; **doğrulanmış kritik/yüksek bulgu yoktur**. Bu, riskin olmadığı anlamına gelmez: birçok orta bulgu üretim sertleştirmesi eksiğidir ve repo bugün yerel geliştirme düzeyindedir.
- Baskın örüntü: yetki modeli ve servis katmanı bilinçli kurulmuş (bkz. 02 özeti); zayıf alanlar üretime hazırlık (güvensiz varsayılanlar, dağıtım/CI/yedek yok), geri alma/silme-geri yükleme tutarlılığı, GET ile yazma, bellekte katlayıp sayfalayan okuma yolları ve hata sayfaları/erişilebilirliktir.
- En çok tekrarlanan kök neden: `config/settings.py` içindeki fail-open varsayılanlar (SECRET_KEY, DEBUG, cookie/HTTPS, e-posta) 10 farklı kayıtta, 8 uzmanın raporunda görünür (F-001, F-004, F-014).
- Doğrulama: seçilen 24 kayıttan 23'ü doğrulandı, 1'i (35-2, menü rozeti sorgu maliyeti) doğrulanamadı ve çürütüldü/şüpheli işaretlendi. Ayrıca 4 kayda çapraz görüşte kısmi itiraz geldi (38-2, 31-11, 33-4, 44-11); ayrıntı `MASTER-FINDINGS.md` içindedir.
- Denetimin sınırları ciddidir: kayıtların yaklaşık %97,5'i (957 ham kaydın 933'ü) ikinci bir doğrulamadan geçmemiştir, uygulama canlı çalıştırılmamış, birçok uzman testleri çalıştıramamıştır. Bkz. `coverage-gaps.md`.

## Metodoloji

Dört faz:

1. **Bağımsız uzman denetimi**: 50 uzman, her biri kendi alanında depoyu salt-okunur inceledi ve `findings/NN-alan.md` yazdı (özet, incelenen/incelenmeyen alanlar, kimlikli bulgular; önem ve güven etiketli, dosya:satır kanıtlı).
2. **Çapraz konuşma**: uzmanlar komşu alanların bulgularını okuyup doğruladı, önem itirazı yazdı, tekrarları işaretledi ve yeni bulgular ekledi (`crosstalk/NN-alan.md`; 126 yeni kayıt, 4 kısmi itiraz).
3. **Doğrulama**: 24 seçilmiş kayıt (çoğu yüksek işaretli veya tartışmalı) iki bağımsız doğrulayıcı tarafından kodda yeniden kontrol edildi; önem ve güven düzeltildi (23 doğrulandı, 1 doğrulanamadı).
4. **Konsolidasyon** (bu belgeler): tüm kayıtlar ayrıştırıldı, mükerrerler elle seçilmiş 62 kümede birleştirildi, doğrulama ve itirazlar uygulandı, temalar ve boşluklar çıkarıldı.

Birleştirme yöntemi: yalnızca aynı kök nedeni ve aynı kodu anlatan kayıtlar birleştirildi (uzmanların kendi "X ile aynı" notları ve dosya/başlık örtüşmesi esas alındı). Benzer ama farklı sonuç doğuran kayıtlar ayrı bırakıldı; bu nedenle tekil sayı hâlâ bir miktar tekrar içerebilir. Önem: doğrulanmış kayıt varsa onun nihai önemi, yoksa kümedeki en yüksek önem.

### İstatistikler

| Ölçü | Değer |
|---|---|
| Uzman | 50 |
| Ham uzman bulgusu | 831 |
| Çapraz görüşten yeni kayıt | 126 |
| Doğrulamaya alınan / doğrulanan | 24 / 23 |
| Tekil kayıt (birleştirme sonrası) | 838 (826 bulgu) |
| Birleştirilen küme | 62 |
| Ham önem (uzman, 831) | Yüksek 20, Orta 237, Düşük 411, Bilgi 163 |
| Ham önem (çapraz görüş, 126) | Yüksek 1, Orta 24, Düşük 76, Bilgi 25 |
| Nihai önem (tekil bulgu) | Yüksek 0, Orta 244, Düşük 421, Bilgi 161 |

### Önem x alan dağılımı (tekil bulgular)

| Alan | Yüksek | Orta | Düşük | Bilgi | Toplam |
|---|---:|---:|---:|---:|---:|
| Güvenlik | 0 | 29 | 47 | 24 | 100 |
| Gizlilik/KVKK | 0 | 6 | 4 | 1 | 11 |
| Veri okuma/yazma/değiştirme | 0 | 15 | 24 | 5 | 44 |
| Yedekleme ve denetim izi | 0 | 16 | 19 | 3 | 38 |
| Veritabanı ve veri bütünlüğü | 0 | 17 | 42 | 13 | 72 |
| İş mantığı (alan modülleri) | 0 | 60 | 106 | 43 | 209 |
| Mimari ve kod kalitesi | 0 | 7 | 16 | 10 | 33 |
| Hata yönetimi ve eşzamanlılık | 0 | 8 | 13 | 6 | 27 |
| Performans ve test | 0 | 16 | 21 | 3 | 40 |
| DevOps, API ve dokümantasyon | 0 | 23 | 33 | 10 | 66 |
| Frontend, UX, erişilebilirlik, i18n | 0 | 29 | 75 | 29 | 133 |
| Uçtan uca akış, durum ve dayanıklılık | 0 | 18 | 21 | 14 | 53 |
| **Toplam** | 0 | 244 | 421 | 161 | 826 |

Alan, kaydın birincil kaynağı olan uzmanın alanına göre atanmıştır (01-07 güvenlik, 08 gizlilik, 09-11 veri okuma/yazma/değiştirme, 12-13 yedek/denetim izi, 14-18 veritabanı/bütünlük, 19-30 iş mantığı, 31-32 mimari/kod, 33-34 hata/eşzamanlılık, 35-36 performans/test, 37-40 devops/api/dokümantasyon, 41-46 frontend/UX, 47-50 uçtan uca).

### Uzman listesi

| No | Uzman | Bulgu | Y | O | D | B | Çapraz yeni | Dosyalar |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 01 | authn | 15 | 2 | 4 | 5 | 4 | 5 | [bulgular](findings/01-authn.md), [çapraz](crosstalk/01-authn.md) |
| 02 | authz | 17 | 0 | 6 | 9 | 2 | 3 | [bulgular](findings/02-authz.md), [çapraz](crosstalk/02-authz.md) |
| 03 | csrf-xss | 14 | 0 | 2 | 7 | 5 | 3 | [bulgular](findings/03-csrf-xss.md), [çapraz](crosstalk/03-csrf-xss.md) |
| 04 | injection | 12 | 0 | 1 | 6 | 5 | 3 | [bulgular](findings/04-injection.md), [çapraz](crosstalk/04-injection.md) |
| 05 | secrets-config | 15 | 2 | 6 | 4 | 3 | 4 | [bulgular](findings/05-secrets-config.md), [çapraz](crosstalk/05-secrets-config.md) |
| 06 | file-upload | 15 | 0 | 4 | 9 | 2 | 3 | [bulgular](findings/06-file-upload.md), [çapraz](crosstalk/06-file-upload.md) |
| 07 | deps-supply | 16 | 0 | 7 | 6 | 3 | 4 | [bulgular](findings/07-deps-supply.md), [çapraz](crosstalk/07-deps-supply.md) |
| 08 | privacy-pii | 12 | 0 | 5 | 6 | 1 | 3 | [bulgular](findings/08-privacy-pii.md), [çapraz](crosstalk/08-privacy-pii.md) |
| 09 | data-read | 23 | 1 | 8 | 9 | 5 | 3 | [bulgular](findings/09-data-read.md), [çapraz](crosstalk/09-data-read.md) |
| 10 | data-write | 14 | 0 | 5 | 8 | 1 | 2 | [bulgular](findings/10-data-write.md), [çapraz](crosstalk/10-data-write.md) |
| 11 | data-modify | 16 | 0 | 4 | 10 | 2 | 4 | [bulgular](findings/11-data-modify.md), [çapraz](crosstalk/11-data-modify.md) |
| 12 | backup-restore | 17 | 3 | 6 | 6 | 2 | 4 | [bulgular](findings/12-backup-restore.md), [çapraz](crosstalk/12-backup-restore.md) |
| 13 | audit-log | 18 | 0 | 6 | 11 | 1 | 4 | [bulgular](findings/13-audit-log.md), [çapraz](crosstalk/13-audit-log.md) |
| 14 | migrations | 16 | 0 | 6 | 7 | 3 | 1 | [bulgular](findings/14-migrations.md), [çapraz](crosstalk/14-migrations.md) |
| 15 | db-schema | 15 | 0 | 3 | 11 | 1 | 1 | [bulgular](findings/15-db-schema.md), [çapraz](crosstalk/15-db-schema.md) |
| 16 | transactions | 14 | 0 | 5 | 7 | 2 | 2 | [bulgular](findings/16-transactions.md), [çapraz](crosstalk/16-transactions.md) |
| 17 | timeseries | 13 | 0 | 0 | 9 | 4 | 2 | [bulgular](findings/17-timeseries.md), [çapraz](crosstalk/17-timeseries.md) |
| 18 | data-integrity | 16 | 0 | 4 | 9 | 3 | 4 | [bulgular](findings/18-data-integrity.md), [çapraz](crosstalk/18-data-integrity.md) |
| 19 | biz-feeding | 15 | 0 | 4 | 8 | 3 | 1 | [bulgular](findings/19-biz-feeding.md), [çapraz](crosstalk/19-biz-feeding.md) |
| 20 | biz-health | 16 | 0 | 4 | 7 | 5 | 1 | [bulgular](findings/20-biz-health.md), [çapraz](crosstalk/20-biz-health.md) |
| 21 | biz-stock-prod | 14 | 0 | 6 | 6 | 2 | 1 | [bulgular](findings/21-biz-stock-prod.md), [çapraz](crosstalk/21-biz-stock-prod.md) |
| 22 | biz-water | 16 | 0 | 4 | 9 | 3 | 1 | [bulgular](findings/22-biz-water.md), [çapraz](crosstalk/22-biz-water.md) |
| 23 | biz-inventory | 18 | 0 | 5 | 8 | 5 | 1 | [bulgular](findings/23-biz-inventory.md), [çapraz](crosstalk/23-biz-inventory.md) |
| 24 | biz-tasks | 17 | 0 | 3 | 8 | 6 | 1 | [bulgular](findings/24-biz-tasks.md), [çapraz](crosstalk/24-biz-tasks.md) |
| 25 | biz-hr | 18 | 1 | 8 | 7 | 2 | 1 | [bulgular](findings/25-biz-hr.md), [çapraz](crosstalk/25-biz-hr.md) |
| 26 | biz-reports | 20 | 0 | 4 | 12 | 4 | 3 | [bulgular](findings/26-biz-reports.md), [çapraz](crosstalk/26-biz-reports.md) |
| 27 | biz-experiments | 17 | 0 | 4 | 9 | 4 | 2 | [bulgular](findings/27-biz-experiments.md), [çapraz](crosstalk/27-biz-experiments.md) |
| 28 | biz-knowledge | 17 | 0 | 7 | 9 | 1 | 2 | [bulgular](findings/28-biz-knowledge.md), [çapraz](crosstalk/28-biz-knowledge.md) |
| 29 | biz-messaging | 19 | 0 | 6 | 8 | 5 | 2 | [bulgular](findings/29-biz-messaging.md), [çapraz](crosstalk/29-biz-messaging.md) |
| 30 | biz-core-facility | 16 | 0 | 5 | 9 | 2 | 2 | [bulgular](findings/30-biz-core-facility.md), [çapraz](crosstalk/30-biz-core-facility.md) |
| 31 | architecture | 13 | 0 | 4 | 6 | 3 | 3 | [bulgular](findings/31-architecture.md), [çapraz](crosstalk/31-architecture.md) |
| 32 | code-quality | 15 | 0 | 2 | 8 | 5 | 2 | [bulgular](findings/32-code-quality.md), [çapraz](crosstalk/32-code-quality.md) |
| 33 | error-handling | 15 | 2 | 5 | 6 | 2 | 3 | [bulgular](findings/33-error-handling.md), [çapraz](crosstalk/33-error-handling.md) |
| 34 | concurrency | 14 | 0 | 2 | 7 | 5 | 3 | [bulgular](findings/34-concurrency.md), [çapraz](crosstalk/34-concurrency.md) |
| 35 | performance | 24 | 4 | 10 | 9 | 1 | 3 | [bulgular](findings/35-performance.md), [çapraz](crosstalk/35-performance.md) |
| 36 | testing | 15 | 0 | 4 | 7 | 4 | 3 | [bulgular](findings/36-testing.md), [çapraz](crosstalk/36-testing.md) |
| 37 | ci-devops | 18 | 3 | 10 | 4 | 1 | 3 | [bulgular](findings/37-ci-devops.md), [çapraz](crosstalk/37-ci-devops.md) |
| 38 | api-contracts | 18 | 0 | 1 | 13 | 4 | 1 | [bulgular](findings/38-api-contracts.md), [çapraz](crosstalk/38-api-contracts.md) |
| 39 | docs-consistency | 16 | 0 | 7 | 7 | 2 | 2 | [bulgular](findings/39-docs-consistency.md), [çapraz](crosstalk/39-docs-consistency.md) |
| 40 | git-hygiene | 15 | 0 | 3 | 8 | 4 | 2 | [bulgular](findings/40-git-hygiene.md), [çapraz](crosstalk/40-git-hygiene.md) |
| 41 | frontend-ts | 29 | 0 | 9 | 15 | 5 | 4 | [bulgular](findings/41-frontend-ts.md), [çapraz](crosstalk/41-frontend-ts.md) |
| 42 | templates | 20 | 0 | 3 | 14 | 3 | 4 | [bulgular](findings/42-templates.md), [çapraz](crosstalk/42-templates.md) |
| 43 | ux-flows | 19 | 0 | 7 | 8 | 4 | 3 | [bulgular](findings/43-ux-flows.md), [çapraz](crosstalk/43-ux-flows.md) |
| 44 | accessibility | 20 | 1 | 4 | 11 | 4 | 4 | [bulgular](findings/44-accessibility.md), [çapraz](crosstalk/44-accessibility.md) |
| 45 | i18n | 16 | 0 | 1 | 8 | 7 | 2 | [bulgular](findings/45-i18n.md), [çapraz](crosstalk/45-i18n.md) |
| 46 | css-static | 25 | 0 | 5 | 16 | 4 | 1 | [bulgular](findings/46-css-static.md), [çapraz](crosstalk/46-css-static.md) |
| 47 | workflows-e2e | 13 | 0 | 4 | 5 | 4 | 1 | [bulgular](findings/47-workflows-e2e.md), [çapraz](crosstalk/47-workflows-e2e.md) |
| 48 | state-machines | 15 | 1 | 3 | 5 | 6 | 3 | [bulgular](findings/48-state-machines.md), [çapraz](crosstalk/48-state-machines.md) |
| 49 | permissions-matrix | 14 | 0 | 4 | 8 | 2 | 2 | [bulgular](findings/49-permissions-matrix.md), [çapraz](crosstalk/49-permissions-matrix.md) |
| 50 | failure-modes | 16 | 0 | 7 | 7 | 2 | 4 | [bulgular](findings/50-failure-modes.md), [çapraz](crosstalk/50-failure-modes.md) |

## En kritik 20 bulgu

Sıralama: nihai önem, ardından bağımsız uzman sayısı, güven ve doğrulama. Doğrulanmış yüksek bulgu olmadığından hepsi Orta düzeydedir; sıralama öncelik önerisidir.

| # | Kimlik | Önem | Başlık | Alan | Kaynak sayısı | Doğrulama |
|---:|---|---|---|---|---:|---|
| 1 | [F-001](MASTER-FINDINGS.md#f-001) | Orta | SECRET_KEY ve DEBUG güvensiz varsayılanları (fail-open) | Güvenlik | 10 | doğrulandı |
| 2 | [F-002](MASTER-FINDINGS.md#f-002) | Orta | GET isteklerinde materialise_due yazması | Hata yönetimi ve eşzamanlılık | 9 | doğrulanmadı |
| 3 | [F-003](MASTER-FINDINGS.md#f-003) | Orta | restore() kilitsiz/sürümsüz/kısmi | Uçtan uca akış, durum ve dayanıklılık | 8 | doğrulanmadı |
| 4 | [F-004](MASTER-FINDINGS.md#f-004) | Orta | Cookie/HTTPS/HSTS sertleştirme ayarları yok | Güvenlik | 5 | doğrulanmadı |
| 5 | [F-005](MASTER-FINDINGS.md#f-005) | Orta | help_text \|safe ile kaçışsız basılıyor | Güvenlik | 5 | doğrulanmadı |
| 6 | [F-006](MASTER-FINDINGS.md#f-006) | Orta | isdigit() Unicode rakamda 500 | İş mantığı (alan modülleri) | 5 | doğrulanmadı |
| 7 | [F-007](MASTER-FINDINGS.md#f-007) | Orta | MEDIA_ROOT/yüklenen dosyalar için kalıcılık ve yedek yok | Yedekleme ve denetim izi | 3 | doğrulandı |
| 8 | [F-008](MASTER-FINDINGS.md#f-008) | Orta | PDF yükleme rollback sonrası yetim dosya | Güvenlik | 4 | doğrulanmadı |
| 9 | [F-009](MASTER-FINDINGS.md#f-009) | Orta | UpdateView/RowListView kilit altında kayıt bulunamama (500) | Veri okuma/yazma/değiştirme | 4 | doğrulanmadı |
| 10 | [F-010](MASTER-FINDINGS.md#f-010) | Orta | Modal istemcisi ağ/HTTP hataları ele alınmıyor | Frontend, UX, erişilebilirlik, i18n | 4 | doğrulanmadı |
| 11 | [F-011](MASTER-FINDINGS.md#f-011) | Orta | Dockerfile/üretim imajı yok | DevOps, API ve dokümantasyon | 2 | doğrulandı |
| 12 | [F-012](MASTER-FINDINGS.md#f-012) | Orta | Statik dosya üretim hattı yok | DevOps, API ve dokümantasyon | 2 | doğrulandı |
| 13 | [F-013](MASTER-FINDINGS.md#f-013) | Orta | Çalışan deney kapatılamıyor (running->closed) | Uçtan uca akış, durum ve dayanıklılık | 2 | doğrulandı |
| 14 | [F-014](MASTER-FINDINGS.md#f-014) | Orta | E-posta konsol backend (davet/parola sıfırlama üretime hazır değil) | Güvenlik | 4 | doğrulanmadı |
| 15 | [F-015](MASTER-FINDINGS.md#f-015) | Orta | PDF metin çıkarımı istek içinde, sınırsız | Güvenlik | 4 | doğrulanmadı |
| 16 | [F-016](MASTER-FINDINGS.md#f-016) | Orta | Append-only audit log ile silme/KVKK talebi çelişkisi | Gizlilik/KVKK | 3 | doğrulanmadı |
| 17 | [F-017](MASTER-FINDINGS.md#f-017) | Orta | Silinen mesaj gövdesi DB'de duruyor | Gizlilik/KVKK | 3 | doğrulanmadı |
| 18 | [F-018](MASTER-FINDINGS.md#f-018) | Orta | Belge dosyası değişince eski dosya geri dönülemez | Yedekleme ve denetim izi | 3 | doğrulanmadı |
| 19 | [F-019](MASTER-FINDINGS.md#f-019) | Orta | Su geçmişi tarih aralığı sınırsız | Performans ve test | 3 | doğrulanmadı |
| 20 | [F-020](MASTER-FINDINGS.md#f-020) | Orta | Sitesiz üretim bölümü yemlemesi yem stoğuna yansımıyor | Uçtan uca akış, durum ve dayanıklılık | 3 | doğrulanmadı |

## Doğrulama ile önemi değişen kayıtlar

| Kayıt | Uzman önemi | Doğrulayıcılar | Nihai | Sonuç |
|---|---|---|---|---|
| 01-1 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 01-2 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 05-1 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 05-2 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 08-X1 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 09-11 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 12-1 | Yüksek | Düşük/Orta | Orta | doğrulandı |
| 12-2 | Yüksek | Düşük/Bilgi | Düşük | doğrulandı |
| 12-3 | Yüksek | Orta/Düşük | Orta | doğrulandı |
| 25-1 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 31-11 | Bilgi | Bilgi/Bilgi | Bilgi | doğrulandı |
| 33-1 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 33-4 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 35-1 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 35-2 | Yüksek | Düşük/Düşük | Düşük | çürütüldü/şüpheli |
| 35-3 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 35-5 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 37-1 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 37-2 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 37-4 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 38-2 | Orta | Düşük/Düşük | Düşük | doğrulandı |
| 44-11 | Düşük | Düşük/Düşük | Düşük | doğrulandı |
| 44-7 | Yüksek | Orta/Orta | Orta | doğrulandı |
| 48-1 | Yüksek | Orta/Düşük | Orta | doğrulandı |

## Dosya dizini

| Dosya | İçerik |
|---|---|
| [README.md](README.md) | Bu özet |
| [MASTER-FINDINGS.md](MASTER-FINDINGS.md) | Tüm tekil bulgular, önem sırasıyla, kaynak kimlikleri ve doğrulama durumu |
| [findings.json](findings.json) | Aynı bulguların makine-okunur listesi |
| [themes.md](themes.md) | Tekrar eden kök nedenler ve öncelikli yol haritası |
| [coverage-gaps.md](coverage-gaps.md) | İncelenmeyen alanlar ve denetimin sınırları |
| `findings/NN-*.md` | 50 uzmanın ham bulgu dosyaları (değiştirilmedi) |
| `crosstalk/NN-*.md` | 50 çapraz görüş dosyası (değiştirilmedi) |
