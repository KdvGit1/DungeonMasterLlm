# Fikirler ve Öneriler

Geliştirirken aklıma gelen, senin onayını/görüşünü bekleyen ekstra fikirler.
Geldiğinde sorarsan buradan anlatırım. ✅ = yaptım, 💬 = karar senin, 🕓 = sonraya.

## Oyun deneyimi

- 💬 **GM'in sesli anlatımı (TTS):** Piper adlı çevrimdışı ses motorunun Türkçe sesleri var (~80 MB).
  PC masası anlatımı yüksek sesle okuyabilir; telefondan bakmadan dinleyerek oynanır. Çok sürükleyici olur.
  İnternet gerektirmez, ekran kartına yük bindirmez (işlemcide çalışır).
- 💬 **Ortam müziği ve sesleri:** Sahneye göre (meyhane, orman, savaş, mağara) arka plan ambiyansı.
  Telifsiz (CC0) ses paketleriyle ya da tamamen kod üretimiyle yapılabilir.
- 💬 **Masa ekranında harita:** Bilinen yerlerin grafiği, grubun konumu, keşfedilmemiş "?" yerler.
- 💬 **Kampanya modu:** Bir senaryo bitince karakterler seviyeleri ve eşyalarıyla yeni senaryoya geçer.
- 💬 **Grup oylaması:** "Köprüyü mü geçelim, nehri mi?" gibi anlarda telefonlardan hızlı oylama.
- 💬 **Kişisel gizli hedefler:** Her oyuncuya senaryodan gizli bir kişisel amaç (ör. "Muhtardan intikam al").
  Oyun içi entrika ve rol yapmayı çok artırır.
- 💬 **"Önceki bölümde" özeti:** Kayıtlı oyun açılınca GM'in sesli/yazılı kısa bir özetle başlaması.
- 💬 **Oyuncu başına "kader zarı" / ilham puanı:** İyi rol yapana GM'in verdiği, bir zarı yeniden attıran
  jeton. 5e'deki "Inspiration" kuralı; oyuncuları rol yapmaya teşvik eder.
- 💬 **Masa ekranında "Önceki Turda" kutusu:** Geç katılan ya da dikkati dağılan için son olayların
  3 maddelik özeti (GM zaten özet çıkarıyor).
- 💬 **Daha fazla sınıf:** Şu an 8 sınıf var (Savaşçı, Barbar, Düzenbaz, Korucu, Paladin, Rahip,
  Büyücü, Ozan). Druid, Keşiş, Sihirbaz (Sorcerer) ve Cadı (Warlock) eklenebilir.
- 💬 **Senaryo editörü:** Senaryoları YAML yerine masa ekranından form ile yazmak; ya da GM'e bir
  fikir verip tüm senaryoyu (mekânlar, NPC'ler, tehditler) yapay zekâya taslak olarak ürettirmek.
- 💬 **Savaş repliği:** Telefonda saldırı seçerken isteğe bağlı tek satırlık bir söz ("Bu köy için!")
  yazılabilsin; GM o vuruşu anlatırken repliği karakterin ağzından aktarsın. Savaşta rol yapmayı artırır.
- 💬 **Savaş anlatım temposu ayarı:** Ayarlara "her vuruşu anlat / sadece önemli anları anlat (öldürme,
  kritik, yere düşme)" seçeneği. Kalabalık savaşlarda bekleme süresini yarıya indirir.
- 🕓 **Karakter portresi üretimi:** Yerel görsel modelle (ör. SDXL Turbo) karakter ve NPC resimleri.
  12 GB ekran kartında LLM ile aynı anda zor; sadece savaş dışında üretilebilir. Ağır, sonraya.

## Teknik

- 💬 **İsteğe bağlı bulut model:** OpenRouter/Claude gibi güçlü bir modelle çok daha iyi anlatım (ücretli, internet gerekir).
  Varsayılan yine yerel ve sansürsüz model kalır.
- 💬 **Daha büyük yerel model:** Ekran kartı yükseltilirse (16-24 GB) 26-31B modeller belirgin şekilde daha iyi Türkçe yazar.
- 💬 **Kurulum dosyasını imzalamak:** Kendi yazdığım kurulum sihirbazı imzasız; Windows SmartScreen
  "tanınmayan uygulama" uyarısı gösterebilir ("Ek bilgi → Yine de çalıştır"). Kod imzalama sertifikası
  (yıllık ücretli) bunu kaldırır. (Not: Inno Setup ile kurulum yapmayı denedim ama internetten indirilen
  kurulum programını çalıştırmam otomatik izin denetimince engellendi; bu yüzden kendi sihirbazımızı yazdım.)
- 🕓 **Telefonu PWA yapmak:** "Ana ekrana ekle" ile uygulama gibi açılır, tam ekran.
