# DnD Master

Yapay zekâ anlatıcılı (GM), yerel ağda **1–6 kişilik** masa başı Dungeons & Dragons macerası.
PC masanın ortak ekranı olur (anlatım, 3D zarlar, savaş takibi); oyuncular aynı Wi-Fi'deki
telefonlarından tarayıcıyla bağlanır. Her şey bilgisayarında, internetsiz çalışır.

## Kurulum
1. `DnDMaster-Setup.exe`'yi çalıştır, klasörü seç (varsayılan `D:\DnDMaster`).
2. "Telefonların bağlanabilmesi için güvenlik duvarı izni" kutusunu işaretli bırak ve Windows
   onay penceresini kabul et.
3. İlk açılışta yapay zekâ motoru (~1,6 GB) ve anlatıcı model (~7,4 GB) indirilir. Bir kez yapılır.

Önerilen donanım: 10 GB+ belleği olan ekran kartı (12 GB ideal), 16 GB RAM, ~12 GB boş disk.
Daha küçük kartlarda (6–8 GB) ya da ekran kartı yoksa başlatıcı otomatik olarak daha hızlı ama daha
basit Türkçe yazan **hafif modeli** (~6,3 GB) seçer. Ayrıntılar: [MODEL_RAPORU.md](MODEL_RAPORU.md).

## Nasıl oynanır
- **DnD Master**'ı aç → masa ekranı tarayıcıda açılır. Ekrandaki QR kodu telefonla okut
  (ya da `http://<bilgisayarın-IP'si>:8765/play` adresine gir).
- Her oyuncu adını yazar, hazır bir kahraman seçer ya da kendi karakterini oluşturur.
- Masadan senaryoyu seç (ya da "Serbest Macera"ya bir fikir yaz) ve başlat.
- **Keşif:** herkes telefonuna ne yaptığını yazar ("Hancıya kayıp kızı soruyorum").
  🤫 *Gizli* işaretlenirse sadece GM görür. Herkes hazır olunca GM tur sonucunu anlatır.
- **Zarlar:** gerektiğinde telefonda büyük **ZAR AT** düğmesi çıkar; zar PC ekranında
  3D olarak yuvarlanır, sonuç sunucuda belirlenir (hile yok).
- **Savaş:** sıra sana gelince telefonunda eylem menüsü açılır: saldır, büyü, yetenek,
  eşya, ön/arka saf, savun, saklan, kaç… veya **🎭 Yaratıcı** ile serbest bir hamle yaz
  ("Avizenin ipini kesip üstlerine düşürüyorum").
- **Çanta:** kuşan, kullan, arkadaşına ver, yere bırak, yerdekini al.
- Oyun her turda otomatik kaydedilir; masadan "Kayıtlı oyunlar"la devam edilir.

## Senaryolar
| Senaryo | Seviye | Ton |
|---|---|---|
| Değirmenköy'ün Gölgesi | 1–4 | Kayıp çocuklar, haydut tarikatı, yeşil ejderha |
| Kül Kalesi'nin Laneti | 2–5 | Gotik korku, karlı dağ köyü, uyanan ölüler |
| Tuzlukıyı'nda Gümüş ve Kan | 1–3 | Liman şehri entrikası, kurtadam, hırsızlar loncası |

Senaryolar açık dünyadır: zorunlu bir yol yoktur; tehditler siz oyalandıkça kendi kendine ilerler.
Yeni senaryo eklemek için `scenarios/<isim>/scenario.yaml` yaz; `python -m pytest tests/test_scenarios.py`
yapıyı ve klasik D&D dünyasına uygunluğu denetler.

## Geliştirme
```bash
source scripts/devenv.sh            # tüm indirmeler/önbellekler D:\dndmaster\.runtime altında
python -m dndm                      # sunucu (gerçek model)
python -m dndm --port 8766 --fake-llm   # GPU'suz arayüz geliştirme
python -m pytest -q                 # testler
python -m tools.playtest --players 3 --rounds 10   # yapay zekâ oyuncularla otonom oyun testi
python -m tools.bench.run_bench MODEL              # model karşılaştırma
python -m tools.sim_balance 150                    # savaş dengesi simülasyonu
python -m tools.build_release                      # dist/DnDMaster-Setup.exe
```

Mimari: `dndm/rules` (zar, kurallar, SRD verisi) · `dndm/game` (karakter, envanter, savaş, oturum) ·
`dndm/gm` (yapay zekâ GM: hakem, anlatıcı, çıkarıcı) · `dndm/world` (senaryo ve dünya durumu) ·
`dndm/server` (FastAPI + WebSocket) · `web/` (masa ve telefon arayüzleri).

Lisanslar ve atıflar: [docs/LICENSES.md](docs/LICENSES.md) · Fikirler: [FIKIRLER.md](FIKIRLER.md)
