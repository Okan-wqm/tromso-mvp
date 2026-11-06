# 24-biz-tasks capraz degerlendirme

Komsu bulgulardan (19, 20, 21, 22, 23, 37) gorev alanini ilgilendiren tek nokta 37-8 (zamanlanmis isler). Diger bulgular gorev/recurrence kodunu etkilemiyor.

## Dogrulama
- 37-8 DOGRULANDI: tasks/management/commands/generate_tasks.py:5-12 "for a cron job" der, ama repo'da scheduler tanimi yok. Uretim su an yalnizca sayfa gorüntulemesine bagli: tasks/views.py:142 ve tasks/resources.py:92,226 icinde services.materialise_due() cagrisi var. Bu, 24-3 (GET sirasinda yazma) ile dogrudan baglantili: cron olmayinca GET yazmasi tek uretim yolu, kaldirilamaz.

## Onem derecesi
- 37-8 medium yeterli; ancak 24-3 duzeltilirse (GET'te yazma kaldirilirsa) scheduler yoklugu high'a yukselir, cunku planli gorevler hic uretilmez.

## Komsulara sorular
- ci-devops: cron/scheduler eklenirse generate_tasks tek bir calisma icinde birden cok kez (cok dugum) calisabilir; materialise_due kilitsiz (24-5) oldugundan cift uretim riski var. Kilit/idempotency onlemi dusunuldu mu?
- biz-inventory / biz-health: check_* komutlari ile generate_tasks ayni scheduler'da toplanacaksa hata yalitimi (24-2 tek bozuk seri tumunu dusurur) nasil ele alinacak?
