# Məhsulu özünüz əlavə edin

1. Saytınızda `/admin` səhifəsinə keçin və öz istifadəçi adınız/şifrənizlə daxil olun. Vercel-də ilk hesab şəxsi `INITIAL_ADMIN_*` parametrləri ilə ilk girişdə yaradılır; sonra hər iki parametr silinir. Standart şifrə və açıq qeydiyyat yoxdur. İlkin quraşdırma üçün [Vercel təlimatına](VERCEL_SUPABASE.md) baxın.
2. **Məhsullar → + Yeni məhsul** düyməsini basın.
3. Adı, Azərbaycanca təsviri, AZN ilə satış qiymətini, şəxsi maya dəyərini və kateqoriyanı daxil edin. Kateqoriya yoxdursa, **Kateqoriyalar** bölməsində yaradın.
4. Hər ölçü/rəng üçün **Variant** əlavə edin və real stok sayını yazın. Variantın qiyməti/maya dəyəri boş qalsa, əsas məhsulun dəyəri istifadə edilir. Adi məhsul üçün bir standart variant kifayətdir.
5. Statusu **Qaralama** saxlayıb **Məhsulu saxla** basın. Aşağıdakı bölmədə bir neçə şəkil seçib **Şəkilləri yüklə** basın. İlk şəkil üz qabığıdır. JPG, PNG və WebP qəbul olunur; seçimdə hər biri ən çox 20 MB / 24 MP, məhsulda ən çox 10 şəkil. Brauzer şəkilləri kiçildib ayrı-ayrı yükləyir.
6. **Saxla və önbaxış** ilə görünüşü yoxlayın. Ön baxış şəxsidir və sifariş qəbul etmir.
7. **Sifariş üçün aktivdir** xanasını işarələyin, stokun sıfırdan böyük olduğunu yoxlayın, statusu **Yayımlanıb** seçin və saxlayın. Məhsul saytda görünəcək.

Qiymət və stok üçün **Redaktə et → Saxla** kifayətdir. Köhnə sifariş qiymətləri və qazanılmış komissiyalar dəyişmir. Digər əməliyyat məlumatı dəyişibsə, sistem üzərinə yazmaq əvəzinə səhifəni yeniləməyi istəyəcək.

**Gizlət** məhsulu kataloqdan çıxarır. **Arxivlə** onu arxiv statusunda saxlayır; tarixçə silinmir. **Surətini yarat** şəkilləri və təsviri kopyalayır, amma fiziki stok iki dəfə hesablanmasın deyə yeni surəti sıfır stoklu qaralama kimi yaradır.

Əvvəlki dəsmalı və üç şəklini gətirmək üçün **Orijinal dəsmalı idxal et** düyməsini basın; təkrar basmaq məlumatı çoxaltmır və dəyişmir. Stok məlum deyil və əvvəlcə bağlıdır. Hər ölçünün real stokunu, maya dəyərini və mövcudluğunu yoxlayın. Bu dəsmalda əvvəlki paket endirimləri qorunub: 2 ədəd −10%, 3 və daha çox −15%.

## WhatsApp sorğusunu satışa çevirin

- Müştərinin sorğusu əvvəl serverdə saxlanılır və unikal `MF-…` istinadı alır. Sonra WhatsApp açılır. Açılmasa, müştəri saxlanılmış sorğudakı keçiddən istifadə edə bilər.
- **Sorğu** təsdiqlənmiş satış, çatdırılma və ya ödəniş demək deyil. WhatsApp mesajının göndərilib-göndərilmədiyini sistem bilmir.
- **Sifariş sorğuları** bölməsində müştəri ilə razılaşdırın. Səbəb/istinad yazıb **Satışı təsdiqlə** basın. Stok yalnız bu addımda çıxılır; stok çatmırsa, təsdiq alınmır.
- Məhsul təhvil veriləndə **Çatdırıldı**, pul alınanda **Ödəniş alındı** seçin. Bu faktları real əməliyyata əsasən qeyd edin.
- Çatdırılmamış, ödənilməmiş sifarişi ləğv etmək stoku bərpa edir. Pul qaytarılması və məhsulun fiziki geri alınması ayrı əməliyyatlardır; hər birini ayrıca qeyd edin.

## Referal işçilər və komissiya

**Partnyorlar və QR** bölməsində işçini, unikal kodu və bir uyğun sifarişə sabit AZN komissiyasını yaradın. QR-ni yükləyib işçiyə verin. QR sizin konfiqurasiya edilmiş sayt ünvanınıza `?ref=KOD` keçidi verir.

Aktiv kod serverdə yoxlanır və sorğuya yazılır. Kod brauzerdə 30 gün yadda qala bilər. Təsdiqlənməyən kod komissiya qazandırmır. Hər uyğun sifariş yalnız **təsdiqləndikdən, çatdırıldıqdan və ödənildikdən sonra** sabit komissiya qazanır. Uyğunluğu lazım olduqda səbəb yazaraq dəyişə bilərsiniz.

Komissiyanı işçiyə ayrıca ödədikdən sonra **Komissiya ödənişini qeydə al** seçin; düymə pul köçürmür. Məhsul/pul geri qayıdarsa, qazanılmış komissiya əks qeyd ilə geri alınır. Artıq ödənilmiş komissiya üçün mənfi qalıq yarana bilər; işçi ilə ayrıca hesablaşın. Keçmiş qeydlər silinmir.

## Ehtiyat nüsxə

Serveri idarə edən şəxs [quraşdırma təlimatındakı](DEPLOYMENT.md) gündəlik ehtiyat nüsxə cədvəlini aktiv etməli, nüsxələri ayrıca təhlükəsiz yerə köçürməli və bərpanı yoxlamalıdır. Bu paneldə müştəri məlumatları və maya dəyərləri var; şifrənizi paylaşmayın.
