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
- 🕓 **Karakter portresi üretimi:** Yerel görsel modelle (ör. SDXL Turbo) karakter ve NPC resimleri.
  12 GB ekran kartında LLM ile aynı anda zor; sadece savaş dışında üretilebilir. Ağır, sonraya.

## Teknik

- 💬 **İsteğe bağlı bulut model:** OpenRouter/Claude gibi güçlü bir modelle çok daha iyi anlatım (ücretli, internet gerekir).
  Varsayılan yine yerel ve sansürsüz model kalır.
- 💬 **Daha büyük yerel model:** Ekran kartı yükseltilirse (16-24 GB) 26-31B modeller belirgin şekilde daha iyi Türkçe yazar.
- 🕓 **Telefonu PWA yapmak:** "Ana ekrana ekle" ile uygulama gibi açılır, tam ekran.
