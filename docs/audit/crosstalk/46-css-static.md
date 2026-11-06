# 46 css-static - capraz denetim

## Dogrulananlar
- 44-3 (girdi kenarligi 1.68:1): kendi 46-11 bulgumla ayni; dogrulandi.
- 44-1 (mobil menu): static/css/app.css:370-385 rail yalniz transform ile gizleniyor; visibility/inert yok. Dogrulandi.
- 44-7 / 41-17 (izleme duvari uyarisi): static/css/monitor.css:5-21 uyari ::before content: attr() ile basiliyor; canli bolge yok. Dogrulandi.
- 41-6: static/css/monitor.css:231 `[aria-invalid]` ozniteligin varligina bakiyor; bos deger 'true' gibi isleniyor, CSS tarafi tutarli.
- 42-8: templates/app_base.html:8-10 ve auth_base.html:7-9 Google Fonts; 46-4 ile ayni.
- 44-12: cekmece CSS'te (components.css:1129) z-index 45; odak yonetimi CSS ile cozulemez, dogru.

## Onem derecesi
- 44-7 high: CSS tarafindan bakinca 'high' abartili, medium daha uygun (veri kaybi yok, yalniz duyuru eksik).

## Yeni bulgular
- 46-X1: z-index olcegi 5 dosyaya dagilmis (app.css 25/30/40/50/60/100, components.css 2-3/45, monitor.css 40) ve yorumlarla elle senkron.
