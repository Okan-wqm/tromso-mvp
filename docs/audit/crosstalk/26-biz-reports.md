# 26-biz-reports: komşu bulgu çapraz denetimi

Kapsam: biz-feeding (19), biz-health (20), biz-stock-prod (21), biz-water (22), biz-inventory (23), docs-consistency (39), csrf-xss (03). Yalnızca okuma; test çalıştırılmadı.

## Doğrulananlar
- 20-2 (doğrulandı): reports/compute/lice.py:44-49 `week_treatments` yalnızca `reason=SEA_LICE` olan tedavileri alıyor; farm/health/services.py:97-116 `_check_medicine` ilaç türü ile nedeni sadece aşı/ilaç-aşı ilişkisi için bağlıyor. Bit ilacı başka nedenle girilirse haftalık bit raporundan düşer. Önem medium uygun (düzenleyici rapor eksik kalır).
- 21-3 (doğrulandı, kısmen): reports/compute/slaughter.py:37-63 plan kalemleri `item.date` haftasına göre, plansız kesimler `operation.date` haftasına göre seçiliyor; `unplanned_of` yalnızca bu haftanın kalemlerinin operation_id'lerini hariç tutuyor. Bir plan kalemi A haftasında, gerçek harvest B haftasında ise A'da planlı, B'de plansız sayılır (çift sayım). Tesis değişimi için de aynı mantık (facility filtresi iki sorguda ayrı).
- 21-4 (ilgili): reports/compute/biomass.py:88-89 yalnızca round ağırlıkla çalışıyor (21-4 ile uyumlu; ayrıntı doğrulaması düşük güven).
- 20-14 (doğrulandı): reports/due.py:365-396 hastalık bildirimi yalnızca NOTIFIABLE teşhisli olaydan, refah bildirimi ise teşhissiz ve kapanmamış MORTALITY olayından 14 gün sonra doğuyor; kendi 26-19 ile birleşik okunmalı (olay bildirimleri gecikmiş sayılmıyor).
- 22-15 (doğrulandı): reports/compute/lice.py:52-73 `depth_samples` site genelinde tüm DEPTH noktalarını (depth_m=3) ortalıyor; ünite türü/su tipi filtresi yok. Sınıflandırma 26 tarafından da kabul edilir, low uygun.
- 19-6 (ilgili, doğrulanamadı tam): geçmiş gün oran/tahminlerinin sonradan değişmesi biyokütle raporuna (reports/compute/biomass.py `_biomass`) yansıyor; 26-3/26-4 ile aynı kök neden (parmak izi bu girdileri kapsamıyor olabilir). Confidence medium.

## Önem derecesi itirazları
- 21-3: medium yerine yüksek (high) düşünülmeli; düzenleyiciye giden planlı kesim bildirimi çift sayılıyor ve 26-1 ile birleşince tarih kuralı da farklı.
- 20-2: medium yerine high olabilir; sessiz eksik beyan (zorunlu haftalık bit raporu).

## Yeni bulgular
Bkz. StructuredOutput: 26-X1 (planlı/plansız kesim çift sayımı mekanizması ve haftalık sınır), 26-X2 (bit raporu tedavi nedeni filtresi ile sağlık servisinin bağsızlığı), 26-X3 (plansız kesim ağırlığı measured_weight_kg None olabilir).

## Komşulara sorular
- biz-stock-prod: bir plan kalemi başka haftada gerçekleşince plan-operasyon bağı (operation_id) kalem tarihini güncelliyor mu?
- biz-health: ilaç türü ile tedavi nedenini bağlamak planlanıyor mu (20-2)?
- biz-water: bit raporu sıcaklığı için DEPTH noktası zorunluluğu saha tarafından nasıl karşılanıyor?
