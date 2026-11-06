# 11 - Veri değiştirme/silme denetimi (data-modify)

## Özet
Değiştirme tarafı genel olarak bilinçli kurulmuş: tüm çiftleştirilmiş kayıtlar `AuditedModel` (soft delete + `version`), jenerik `UpdateView`/`RowListView` kayıt kilidi altında `version` karşılaştırır, `DeleteView` kilit altında `plan_delete` ile `on_delete` semantiğini soft delete'e uygular, defter benzeri kayıtlar (stok, envanter, besleme, su, sağlık) hard delete/restore yerine "void" ile geri alınır ve admin restore'u bu modellerde bilerek kapalıdır. Servis katmanında (hr, tasks, messaging, inventory, farm/stock) satır kilitleri tutarlı kullanılıyor. Bulunanlar ağırlıkla: (1) soft delete zincirinde kilitsiz alt kayıtlara tam-satır `save()` (kayıp güncelleme), (2) kilit sonrası `.get()` ile 500, (3) tekrarlayan görevlerde kilitsiz hard delete yarışı ve restore sonrası boşluk, (4) Rol/Kullanıcı kayıtlarında iyimser kilit yokluğu ve rol silmenin etki göstermemesi, (5) restore'un kilitsiz/versiyonsuz oluşu, (6) SET_NULL ayırmanın restore ile geri alınamaması, (7) RowList "hepsini sil, yeniden yaz" modelinin kimlik/iz kaybı. Kritik bulgu yok. Testler çalıştırılmadı (salt-okunur inceleme).

## İncelenen alanlar
core/models.py (AuditedModel, soft_delete, detach), core/softdelete.py (plan/execute/restore), core/crud.py (UpdateView, DeleteView, RowList, RowListView), core/admin.py (restore), core/resources.py + core/forms.py (Rol/Kullanıcı), farm/admin.py, inventory/admin.py, experiments/admin.py, hr/services.py (move, leave_company, align_placements, izin, yoklama), hr/resources/employee.py, tasks/services.py + tasks/models.py (durum geçişleri, materialise, withdraw, replan, planned), messaging/services.py + models.py, inventory/services.py (_commit, void), farm/stock/services.py (locked, voided), farm/forms/equipment.py + farm/models/equipment.py, knowledge/models/document.py, experiments/services.py (save_design/_apply/_touch/_park), reports/services.py, tüm `on_delete=` kullanımları ve `delete_blockers` tanımları, koşulsuz UniqueConstraint taraması, migrasyonlardaki tetikleyici listesi.

## İncelenmeyen / sınırlı incelenen alanlar
Gerçek eşzamanlılık testi yapılmadı (yarışlar kod okumasına dayanır; PostgreSQL READ COMMITTED varsayıldı). farm/health, farm/handling, farm/water/services (void akışı yalnızca başlık düzeyi), farm/feeding projeksiyonları, reports/compute, monitoring views (kart kopyalama), knowledge/entry iş akışı, TypeScript frontend (sürüm alanını gönderme), migrasyon tetikleyicilerinin SQL gövdeleri tek tek incelenmedi. Yetki konuları 02, SQL enjeksiyonu 04, veri yazma yolları 10 numaralı uzmanların alanıdır.

## Bulgular

### 11-1 | Orta | Güven: yüksek
**Soft delete zincirinde kilitsiz alt kayıtlara tam-satır `save()`: eşzamanlı düzenleme sessizce ezilir, `version` çakışır**
- Dosyalar: core/softdelete.py:174-185, core/models.py:53-59, core/softdelete.py:99-115, core/crud.py:775-780
- Açıklama: `DeleteView.post` yalnızca silinen kökü `select_for_update` ile kilitler. `plan_delete` alt kayıtları (CASCADE ve `deleted_with` ile planlanan DO_NOTHING çocukları) kilitsiz `model.objects.filter(...)` ile okur; `execute` bunları `record.soft_delete(user)` ile siler. `soft_delete` `self.save()` (tüm sütunlar) yazar ve `version += 1`'i bellekteki eski değerden hesaplar. Plan ile yürütme arasında başka bir işlem alt kaydı değiştirirse (ör. görev başlatma/tamamlama, formdan düzenleme) bu değişiklik eski değerlerle ezilir ve versiyon sayacı geri/çakışık gider. `detach` ise `update_fields` kullandığı için bu sorun yok; yalnızca soft_delete yolu etkilenir.
- Kanıt: `record.soft_delete(user)` (softdelete.py:180) → `self.version += 1; self.save()` (models.py:57-59); çocuklar `list(model.objects.filter(**{link: obj}))` (softdelete.py:110), kilit yok.
- Öneri: Plan çocuklarını yürütmeden önce `select_for_update` ile yeniden oku (pk sırasıyla) ya da `soft_delete`'i `update_fields=['is_deleted','deleted_at','deleted_by','updated_by','version','updated_at']` ile yaz ve versiyonu `F('version')+1` ile artır.

### 11-2 | Orta | Güven: orta
**Tekrarlayan görev `withdraw`, planlı görevleri kilitlemeden ve yeniden doğrulamadan hard delete eder**
- Dosyalar: tasks/services.py:265-271, tasks/models.py:424-436, tasks/services.py:107-117
- Açıklama: `replan` yalnızca `TaskSeries` satırını kilitler. `withdraw`, `Task.planned(...)` ile (open, version=1, not ticked, no note) adayları kilitsiz okur, sonra tek tek `task.delete()` yapar. Arada biri `start()/complete()/add_note()` (görev satırını kilitleyerek) çalıştırırsa, dokunulmuş görev DB'den fiilen silinir; CASCADE ile notlar (`TaskNote`, "kalıcı iş kaydı"), checklist ve atamalar da gider. Satır kilidi veya `WHERE version=1` doğrulaması yok.
- Kanıt: `for task in Task.planned(Task.objects.filter(series=series)): ... task.delete()` (services.py:270-271); `planned` bir `list(...)` döndürür (models.py:432).
- Öneri: Planlı görevleri `select_for_update()` altında seç (veya `Task.objects.filter(pk__in=..., version=1, status=OPEN).delete()` ile koşulu silme anında yinele) ve silinenleri döndürülen satırlardan logla.

### 11-3 | Orta | Güven: orta
**Silinen tekrarlayan görev geri getirilince onunla silinen planlı görevler geri gelmez ve `materialise` o günleri sonsuza dek atlar**
- Dosyalar: tasks/services.py:238-241, core/softdelete.py:189-203, tasks/models.py:434-440
- Açıklama: Seri silinince dokunulmamış planlı görevleri `deleted_with` ile soft delete olur. `restore` yalnızca serinin kendisini döndürür. `materialise` "bir gün zaten görevi varsa, canlı ya da silinmiş, atla" kuralıyla `Task.all_objects` kullanır; böylece seri geri geldiğinde cascade ile silinmiş günler `taken` sayılır, bu günler yeniden üretilmez. `generated_until` değeri de ilerlediği için kalıcı boşluk (eksik görev) oluşur. Dokümanın "kişinin sildiği görev silik kalır" gerekçesi cascade ile silinenler için geçerli değil.
- Kanıt: `taken = set(Task.all_objects.filter(series=series, occurrence_date__in=days)...)` (services.py:240); restore yalnızca `record` üzerinde çalışır (softdelete.py:198-203).
- Öneri: Cascade ile silinen planlı görevleri `deleted_by`/zaman damgasıyla ayırt edip seri restore'unda geri getir ya da `taken` hesabını yalnızca kullanıcı tarafından silinenlerle sınırla.

### 11-4 | Orta | Güven: yüksek
**Rol (Group) ve Kullanıcı düzenlemesinde iyimser kilit yok: son yazan kazanır, izin kümesi tamamen ezilir**
- Dosyalar: core/crud.py:158-164, 725-737, core/resources.py:14-47
- Açıklama: `TabbedForm.version` alanı model `version` alanı yoksa silinir; `Group` ve `User` Django modelleridir. `UpdateView` `versioned = 'version' in form.fields` olmadığı için sürüm kontrolü atlanır, yalnızca satır kilidi alınır. İki yönetici aynı rolü açıp farklı izinler işaretlerse ikincisi birincinin izin değişikliğini uyarısız ezer (`permissions` m2m tamamen `set` edilir); aynı durum kullanıcının `groups`/`is_active` alanı için geçerli. Güvenlik açısından izin matrisi sessizce geri alınabilir.
- Kanıt: `if not any(f.name == 'version' ...): del self.fields['version']` (crud.py:161-162); `versioned = 'version' in form.fields` (crud.py:725).
- Öneri: Rol/Kullanıcı formuna bir gizli sürüm (ör. `updated_at` damgası veya Profile üzerinde sayaç) ekleyip kilit altında karşılaştır.

### 11-5 | Düşük | Güven: yüksek
**Rol silme hard delete'tir; onay ekranı üyeleri ve kaybedilecek izinleri göstermez, geri alma yolu yok**
- Dosyalar: core/crud.py:781-785, templates/crud/confirm_delete.html:51-52, core/resources.py:14-31
- Açıklama: `RoleResource` `AuditedModel` olmadığı için `DeleteView` doğrudan `obj.delete()` çağırır (kalıcı). Onay ekranı `plan=None` iken yalnızca genel "kalıcı silinir" metni gösterir; role bağlı kullanıcı sayısı/adı ve bunların kaybedeceği izinler gösterilmez (liste şablonu sayıyı gösteriyor ama silme diyaloğu göstermiyor). Silinen rolün izinleri audit'te `snapshot` ile kayıtlıdır ama restore mekanizması yok; son izinli rol silinirse kullanıcılar yetkisiz kalır.
- Kanıt: `audit.record_delete(...); obj.delete()` (crud.py:784-785); şablonda `{% else %}<p>This removes it permanently...` (confirm_delete.html:51).
- Öneri: Rol silme için bloklayıcı/uyarı (üyesi olan rol silinemez veya üye listesi gösterilir) ekle.

### 11-6 | Düşük | Güven: yüksek
**`UpdateView` kilit altındaki `.get(pk=pk)` kayıt bu arada silinmişse 500 üretir**
- Dosyalar: core/crud.py:721-723, 811-814, 773-774
- Açıklama: Düzenleme formu açıldıktan sonra kayıt başkası tarafından soft delete edilirse, `r.visible(request)` canlı kayıtlarla sınırlı olduğundan `select_for_update(...).get(pk=pk)` `DoesNotExist` fırlatır; `get_object_or_404` yalnızca kilit öncesi okumada vardır. Kullanıcı 404 yerine sunucu hatası alır. `RowListView.post` (crud.py:813) aynı kalıpta. (`DeleteView.post` doğru şekilde `get_object_or_404` kullanıyor.)
- Kanıt: `current = r.visible(request).select_for_update(of=('self',)).get(pk=pk)` (crud.py:722).
- Öneri: `get_object_or_404(...)` kullan veya `DoesNotExist`'ı yakalayıp "kayıt silindi" mesajıyla listeye yönlendir.

### 11-7 | Düşük | Güven: yüksek
**`restore` kilitsiz, sürümsüz ve yalnızca `ValidationError` yakalar; eşzamanlı restore/çakışmada `IntegrityError` 500'e düşer**
- Dosyalar: core/softdelete.py:189-203, core/admin.py:38-52
- Açıklama: Admin eylemi kayıtları `queryset` ile okur, `restore` satırı kilitlemez ve `version` doğrulamaz. İki yönetici aynı kaydı restore ederse çift RESTORE audit satırı ve çift sürüm artışı oluşur. `full_clean()` canlı koşullu kısıtları kontrol eder ama arada oluşan çakışma (eş zamanlı kod alma, hariç tutma/exclusion kısıtı: attendance, leave, posting) veritabanında `IntegrityError` olarak patlar; admin eylemi sadece `ValidationError` yakalar. Ayrıca restore, `delete_blockers`/alan kurallarının tersini (ör. kapalı bir lokasyonun, silinmiş bir lokasyonun stok tutması) denetlemez; bu yalnızca stok/envanter/sağlık kayıtları için admin eylemi kapatılarak çözülmüş.
- Kanıt: `record.is_deleted, ... = False, None, None; record.version += 1; record.full_clean(); record.save()` (softdelete.py:197-203); `except ValidationError` (admin.py:46).
- Öneri: `select_for_update` ile yeniden oku, `is_deleted` hâlâ True mu doğrula, `IntegrityError`'ı da yakala.

### 11-8 | Düşük | Güven: yüksek
**SET_NULL ayırma (`detach`) geri alınamaz: restore bağı geri koymaz**
- Dosyalar: core/softdelete.py:7-8, 99-123, 174-179, core/models.py:61-66, farm/models/tank.py:329-331, farm/models/production_department.py:46
- Açıklama: Silinen sistemin tankları `system`, silinen sitenin üretim bölümleri `site` bağını kaybeder (`detach` ile `NULL`). Restore yalnızca kaydın kendisini döndürür; ayrılmış kayıtlar eski bağlarına dönmez. Bağ yalnızca audit_log'daki "önceki değer"de kalır. Onay ekranı bunu "lose their link" olarak gösterir ama "restore bunu geri getirmez" demez; DO_NOTHING için "restore ile geri gelir" notu varken SET_NULL için tersi geçerlidir, kullanıcı beklentisi tutarsızdır.
- Kanıt: `record.detach(link, user)` (softdelete.py:178); `restore` hiçbir ayrılmış bağı işlemez (softdelete.py:189-203).
- Öneri: Onay ve restore mesajında bunu açıkça belirt veya ayrılan bağlar için restore sırasında audit'ten geri yükleme sun.

### 11-9 | Düşük | Güven: yüksek
**`RowList.save` "hepsini sil, yeniden oluştur" yapar: satır kimlikleri, `created_at/created_by` her kayıtta sıfırlanır**
- Dosyalar: core/crud.py:357-371, farm/models/equipment.py:259-270, farm/models/site.py:198
- Açıklama: Site iletişimleri, besleyici kalibrasyonları vb. her kayıtta `rows(obj).delete()` + `bulk_create` ile komple yenilenir. Değişmemiş satırlar da yeni pk alır ve `created_by` o anki kullanıcı, `created_at` şimdi olur; asıl oluşturan ve ilk giriş zamanı kaybolur. Bu satırlara dışarıdan pk ile bağlanan bir şey (şu an yok) kırılırdı. Log yalnızca özet önce/sonra karşılaştırması tutar. İyimser kilit kayıt düzeyinde var (iyi).
- Kanıt: `cls.rows(obj).delete(); model.objects.bulk_create([... 'created_by': user ...])` (crud.py:364-367).
- Öneri: Satırları pk ile eşleştirip yalnızca değişeni güncelle/ekle/sil.

### 11-10 | Düşük | Güven: yüksek
**Ekipman kaydedilince silinmiş sistemlere olan bağlar hard delete edilir; modelin ve onay ekranının "restore bağı geri getirir" vaadiyle çelişir**
- Dosyalar: farm/forms/equipment.py:104-117, 181-190, farm/models/equipment.py:216-222, templates/crud/confirm_delete.html:41-43, core/softdelete.py:19-21
- Açıklama: `EquipmentSystem` düz satırdır; `EquipmentForm._save_m2m` `system_links.all().delete()` ile silinmiş sistemlere olan bağları da siler (form bunu yardım metninde açıklıyor). Ama `core/softdelete` ve onay ekranı "bağ satırı kalır, restore bağı geri getirir" der. Sistem silinip ekipman düzenlendikten sonra sistem restore edilirse bağ kayıptır. Davranış bilinçli ama iki belgeyle tutarsız; ayrıca kayıp bağlar audit'te yer almıyor.
- Kanıt: `self.instance.system_links.all().delete()` (equipment.py:186); `"restoring the system brings the link back"` (equipment.py:221).
- Öneri: Silinmiş sistem bağlarını silme (yalnızca formda görünenleri değiştir) ya da dokümanı güncelle.

### 11-11 | Düşük | Güven: düşük
**Soft delete düz (AuditedModel olmayan) satırlardan gelen PROTECT bağlarını izlemez; yalnızca elle yazılan `delete_blockers` korur**
- Dosyalar: core/softdelete.py:99-123, farm/models/site.py:116-122, reports/models.py:356, 388, farm/models/health.py:219
- Açıklama: `_collect` yalnızca `AuditedModel` ilişkilerini izler. `OutsideDutyDone.site`, `DueClosure.site` (PROTECT) ve `MedicineWithdrawal.species` (PROTECT) düz modellerdir; `Site.delete_blockers` yalnızca stok hareketini, `Species` için blokaj yok. Dolayısıyla beyan edilmiş yıllık görevi/kapatması olan site soft delete edilebilir; veri kalır ama listelerden (ve `Site.objects` ile okunan yerlerden) kaybolur, DB'nin PROTECT'i soft delete'te zaten devreye girmez. Her model için blocker yazma yükü geliştiriciye bırakılmış, yeni düz satırda unutma riski var.
- Kanıt: `if not relation.one_to_many or not issubclass(model, AuditedModel): continue` (softdelete.py:99-101).
- Öneri: PROTECT için düz satırları da say (canlılık filtresi olmadan) ya da sistematik test ekle.

### 11-12 | Düşük | Güven: yüksek
**Mesaj silme audit log'a yazılmaz ve metin DB'de kalır**
- Dosyalar: messaging/services.py:267-275, messaging/models.py:127-158
- Açıklama: `delete_message` yalnızca `is_deleted/deleted_at/deleted_by` yazar (`update_fields`), `audit.record_*` çağrısı ve `version` yok; oysa üyelik/rol değişiklikleri loglanıyor. `body` silinmiş mesajda da durur ("metin gösterilmez" yalnızca sunum katmanı). Silme talebi (ör. KVKK/GDPR) fiilen yerine getirilmez; ayrıca silinmiş mesajın geri alınması için yol da yok (ama DB'den okunabilir).
- Kanıt: `message.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])` (services.py:274); `body` temizlenmez.
- Öneri: Silmede `body`'yi boşalt/anonimleştir (kontrol kısıtı `chk` ile uyumlu) ve gerekiyorsa log yaz.

### 11-13 | Düşük | Güven: orta
**`align_placements` yalnızca bekleyen izinleri iptal eder; işten ayrılış tarihini aşan onaylı izin/yoklama dokunulmaz, tarih geri alınınca kesilen yerleşimler geri gelmez**
- Dosyalar: hr/services.py:112-138, hr/resources/employee.py:90-96, hr/services.py:91-109
- Açıklama: `left_on` verilince `Posting` ve `ShiftAssignment` (day > left_on) silinir/kısalır; `LeaveRequest` için yalnızca `PENDING` ve `first_day > left_on` iptal edilir. `left_on`'u aşan onaylı izin ve `left_on` sonrası yoklama/`left_on`'u kesen bekleyen izin aynen kalır. Çalışan `left_on` sonradan temizlenirse (yanlış girildiyse) silinen/kesilen yerleşimler ve vardiya planları otomatik geri gelmez (restore ayrı ve elle). Etkisi raporlama tutarsızlığı.
- Kanıt: `LeaveRequest.objects.filter(employee=employee, status=LeaveStatus.PENDING, first_day__gt=employee.left_on)` (services.py:131).
- Öneri: Kuralı belgeleyip tutarlı hale getir (onaylı izinleri de uyar/işaretle), `left_on` geri alma akışı için uyarı ekle.

### 11-14 | Bilgi | Güven: yüksek
**Deney tasarımı `_touch`/`_park` `queryset.update()` ile yazar: `version` artmaz, `AuditedModel` sözleşmesi dışında kalır**
- Dosyalar: experiments/services.py:193-200, 245, 266-270
- Açıklama: `Factor` ve `ExperimentGroup` kayıtları yeniden adlandırma/sıra değişiminde `update(updated_by, updated_at, ...)` ile yazılır; `version` sabit kalır, `updated_at` elle atanır. Kayıtlar bu yüzden doğrudan düzenlenmez (tasarım Experiment sürümüyle kilitlenir ve loglanır), dolayısıyla pratik etki yok; ancak `AuditedModel`'in "her değişiklik version artırır" invariantı bu modeller için geçerli değil, ileride bu satırlar için ayrı bir form eklenirse kilit çalışmaz. `_park` geçici `~uuid` adları yalnızca işlem içinde görünür.
- Kanıt: `model.objects.filter(pk=record.pk).update(updated_by=user, updated_at=timezone.now(), **values)` (services.py:200).
- Öneri: Sözleşmeyi dokümante et veya `version=F('version')+1` ekle.

### 11-15 | Düşük | Güven: orta
**Belge dosyası yüklemesi işlem geri alınınca depoda yetim kalır**
- Dosyalar: knowledge/models/document.py:215-241
- Açıklama: `Document.save` yeni PDF'i `super().save` sırasında depoya yazar; yalnızca eski dosyanın silinmesi `transaction.on_commit` ile yapılır. `UpdateView` işlemi geri alınırsa (örn. sonraki bir hata, `audit` hatası) yeni yazılan dosya silinmez; ayrıca eski dosya doğru biçimde korunur. Yetim dosya birikir. `pages.all().delete()` + `bulk_create` ise işlem içinde (atomik) olduğundan tutarlıdır.
- Kanıt: `transaction.on_commit(partial(self.file.storage.delete, stored))` yalnızca `stored` için (document.py:241).
- Öneri: Yeni dosya için `transaction.on_rollback` benzeri temizlik (`on_commit` ile başarısızlık denetimi) veya yetim dosya süpürücüsü.

### 11-16 | Bilgi | Güven: orta
**Onay ekranı "admin'den geri alınabilir" der; deney tasarım parçaları ve stok/envanter benzeri kayıtlar için bu doğru değil**
- Dosyalar: templates/crud/confirm_delete.html:49, experiments/admin.py:17-25, farm/admin.py:21-28
- Açıklama: Soft delete onayı tüm `AuditedModel`'ler için "restore edilebilir" sözü verir. `DesignRecordAdmin` ve `StockRecordAdmin` `actions = []` ile restore'u bilerek kapatır; bu kayıtlar için metin yanıltıcı olabilir (ör. deney taslağı restore edilir ama tasarımı yeniden girilir; parçalar tek başına dönmez). Ayrıca restore eylemi `has_change_` iznine bağlı iken admin sitesine yalnızca platform yöneticisi girer.
- Kanıt: confirm_delete.html:49; `actions = []` (farm/admin.py:27, experiments/admin.py:20).
- Öneri: Metni modele göre özelleştir (`restorable` bayrağı).
