# 19-biz-feeding çapraz değerlendirme

Doğrulananlar: 20-15 (withdrawal.py:263-268 covers() yalnızca yöntem+tarih+birim bakar, ilaç/yem eşlemez; 19-12 ile ilişkili), 23-15 (inventory/fold.py:237-252 _feed site havuzundan çeker; 19-10 ile ilişkili), 23-13, 24-1 (19-8 ile aynı soft-delete geri yükleme deseni), 22-3 (kısmen: degree_days belgesi gün sıcaklığı yoksa 0 °C kullanıyor; yem tarafı SFR için sıcaklık yoksa 19-5).
Yeni bulgu 19-X1: yemleme -> stok defteri tüketimi ile yemleme ekranları farklı toplam tanımı kullanıyor (21-7 ve 23-15 ile birlikte okunmalı).
Sorular: biz-inventory'ye (23-15) ve biz-health'e (20-15).
