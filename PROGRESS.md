# DnD Master v2 — İlerleme Günlüğü

Fikir/öneri notları: [FIKIRLER.md](FIKIRLER.md)

## Ortam (her şey D:'de)
- Kaynak: `D:\dndmaster` (git dalı `v2`); çalışma zamanı `D:\dndmaster\.runtime\` (venv, Ollama, modeller, önbellekler)
- Her kabukta: `source scripts/devenv.sh`
- Sunucu: `python -m dndm` (gerçek model) / `python -m dndm --port 8766 --fake-llm` (GPU'suz arayüz testi)
- Testler: `python -m pytest -q` (125 test)
- Otonom oyun testi: `python -m tools.playtest --players 3 --rounds 10 --personas investigator,thief,free_spirit`
- Model karşılaştırma: `python -m tools.bench.run_bench MODEL...` → `.runtime/bench/`
- Savaş dengesi: `python -m tools.sim_balance 150`
- Gerçek modelle savaş denemesi: `python -m tools.combat_demo 2` (ya da `3 bandit_captain:1 bandit:2`)
- Sürüm: `python -m tools.build_release` → `dist/DnDMaster-Setup.exe` (32,8 MB)

## Dallar
- `main` orijinal · `legacy-fix` merge düzeltilmiş eski sürüm · `v2` yeni sürüm

## Bitenler
- [x] Bozuk merge kurtarıldı (`legacy-fix`)
- [x] Model karşılaştırması: Gemma4-12B heretic önde (hakem %100, en iyi Türkçe); Qwen3.5-9B ve Rocinante elendi
- [x] Kural motoru, zar, karakter, 8 sınıf/9 ırk, 98 eşya, 42 büyü, 51 canavar (SRD 5.1)
- [x] Envanter (kuşanma, yığın, ver/al/bırak/yerden al, para, dükkân)
- [x] Savaş motoru + düşman yapay zekâsı + denge simülasyonu
- [x] Açık dünya senaryo formatı + doğrulayıcı (yapı + klasik D&D/çağ dışı kontrolü)
- [x] GM katmanı (hakem / anlatıcı / çıkarıcı / özet), Türkçe ek düzeltici, durgunluk kırıcı
- [x] Oturum: eşzamanlı zarlar, erken hakemlik, kayıt/yükleme
- [x] FastAPI + WebSocket sunucu, PC masa ekranı (3D zar), telefon arayüzü (savaş menüsü dahil)
- [x] Senaryolar: Değirmenköy'ün Gölgesi (eski senaryonun uyarlaması), Kül Kalesi'nin Laneti (özgün)
- [x] Başlatıcı (DnDMaster.exe) + kendi kurulum sihirbazımız (DnDMaster-Setup.exe)

- [x] 3. senaryo: Tuzlukıyı'nda Gümüş ve Kan (kurtadam, lonca, gümüş silahlar)
- [x] Paketlenmiş exe gerçek modelle uçtan uca denendi (`tools/ws_smoke.py`)
- [x] Gizli eylemler gerçekten gizli (özel zar + "sen" diliyle özel anlatım)
- [x] Durgunluk kırıcı en kolay ipucunu NPC/olay ile veriyor; anlatıcı senaryo dışı mekân uydurmuyor
- [x] Masa: sahne başlığı; telefon: hikâye özeti, standart yetenek sırası; README
- [x] Gerçek modelle savaş testi: anlatıcıya ham Türkçe kayıt yerine net olgular (kim, kime, hangi silahla,
      isabet/ıska) veriliyor; düşmanların silahları açılışta bildiriliyor; ölüm zarı vuruşu sadece yerdeki
      karakteri anlatıyor. Vuruş başına ~3,8 sn, 3 kişilik seviye 2–3 savaşlar 75–90 sn

## Sıradakiler
- [ ] Hafif model (e4b-qat) + 26B MoE ölçümü → MODEL_RAPORU.md'ye ekle
- [ ] Not: Inno Setup'ı çalıştırmak otomatik izin denetimince engellendi → kendi kurulum sihirbazımızı yazdık
