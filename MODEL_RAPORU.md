# Model Raporu — Hangi Sansürsüz Model GM Olmalı?

Donanım: RTX 3060 12 GB, Ryzen 5 1600, 16 GB RAM · Ollama 0.40.13 · bağlam 8192 · ölçüm aracı:
`tools/bench/run_bench.py` (14 hakem vakası, 6 anlatım senaryosu × 2, bilgi çıkarma × 2).
Ham çıktılar: `.runtime/bench/*.json`

## Neyi ölçtüm
| Test | Ne bakılıyor |
|---|---|
| **Hakem doğruluğu** | 14 Türkçe eylem: zar gerekli mi, doğru 5e becerisi, makul ZS, savaş başlıyor mu |
| **Türkçe anlatım** | Akıcılık, ek/ünlü uyumu hataları, atmosfer, NPC sesleri — çıktıları tek tek okuyarak |
| **Sansürsüzlük** | Vahşi öldürme, karanlık ayin, işkenceli sorgu sahnelerinde reddetme/ahlak dersi var mı |
| **Özgürlük** | Oyuncular ana görevi bırakıp fırın açmak isterse model onları zorla göreve itiyor mu |
| **6 oyuncu** | Tek turda 6 karakterin eylemini birden anlatabiliyor mu |
| **Bilgi çıkarma** | Anlatımdan NPC, eşya, yer adlarını doğru JSON'a çevirebiliyor mu |
| **Hız** | Saniyede üretilen token, istem işleme hızı, ilk kelimeye kadar geçen süre, ekran kartı belleği |

## Sonuçlar
| Model | Hakem | Türkçe | Reddetme | 6 oyuncu | Üretim | İlk kelime | Bellek | Karar |
|---|---|---|---|---|---|---|---|---|
| **Gemma 4 12B Heretic** (igorls, Q4_K_M) | **%100** | **En iyi** | 0 | 6/6 | 35 tok/sn | 0,39 sn | 8,6 GB | ✅ **Seçildi** |
| Gemma 4 12B Abliterated (huihui_ai) | %97,3 | İyi, ek hataları | 0 | 6/6 | 35 tok/sn | 0,40 sn | 9,0 GB | Yedek |
| Qwen 3.5 9B Abliterated (huihui_ai) | %86,5 | Zayıf | 0 | 5/6 | 52 tok/sn | 0,25 sn | 7,4 GB | ❌ |
| Rocinante-X 12B (TheDrummer, Mistral Nemo) | %100 | **İngilizce yazıyor** | 0 | 6/6 | 38 tok/sn | 0,15 sn | 8,5 GB | ❌ |
| Impish Bloodmoon 12B (Mistral Nemo) | — | — | — | — | — | — | — | İndirme 2 kez takıldı; aynı Nemo tabanı Türkçede başarısız |

### Yorumlar
- **Gemma 4 12B Heretic** en canlı ve en doğal Türkçeyi yazdı. NPC'lere ses verdi ("Bir sorun mu var,
  evlat?"), özgürlük testinde fırın açmak isteyen oyuncuları zorlamak yerine o yolu ilginçleştirdi
  (Silas'ın gizemli uyarısı), vahşi sahnelerde reddetmedi, hakem kararlarının hepsini doğru verdi.
  "Heretic" yöntemi sansür katmanını kaldırırken zekâyı "abliteration"dan daha iyi korumuş görünüyor.
- **Gemma 4 12B Abliterated** neredeyse aynı, ama daha çok ek hatası yapıyor ("Çelikin", "cücein").
  Yedek olarak tutulabilir.
- **Qwen 3.5 9B** en hızlısı ama Türkçesi anlamsızlaşıyor ("burjuva bir sessizlik",
  "Lira ise Lira'nın bakışlarını…"), geçmiş zamana kayıyor ve oyuncular adına konuşuyor.
- **Rocinante / Mistral Nemo tabanlı rol yapma modelleri** İngilizce rol yapmada çok iyi ama
  Türkçe istemeye rağmen anlatımı İngilizce yazıyor; Türkçe oyun için uygun değil.

### Bulunan ve düzeltilen genel sorunlar
- Ollama'nın `format` (JSON şeması) parametresi çıktıyı şemaya zorluyor ama modele şemayı
  **göstermiyor**; model alanların ne anlama geldiğini bilmeden listeleri boş bırakıyordu. Her
  yapılandırılmış çağrıya şemanın okunabilir bir özetini ekledim → bilgi çıkarma %0'dan %100'e çıktı.
- Gemma'nın Türkçe tikleri ("birer" fazlalığı, "Lira'ın" gibi ek hataları) için deterministik bir
  son düzenleme katmanı yazıldı (`dndm/gm/turkish.py`).
- Gemma'nın kayan pencereli dikkati istem önbelleğini kullanamıyor; bu yüzden istemler kısa tutuldu
  (son 4 tur, eski anlatımlar kısaltılmış).

## Gerçek oyun hızı (3 oyuncu, Gemma 4 12B Heretic)
- Tur başına ortalama **~30 sn** (hakem + eşzamanlı zarlar + anlatım; bot oyuncuların yazma süresi dahil).
- Anlatım akış halinde gelir: ilk kelime genellikle 3–6 sn içinde ekranda.
- Çok oyunculuda bir oyuncunun eylemi, diğerleri hâlâ yazarken önceden değerlendirilir.
