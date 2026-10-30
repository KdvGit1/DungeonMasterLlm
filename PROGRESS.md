# DnD Master v2 — İlerleme Günlüğü

Fikir/öneri notları: [FIKIRLER.md](FIKIRLER.md)

## Ortam (her şey D:'de)
- Kaynak: `D:\dndmaster` (git dalı `v2`); çalışma zamanı `D:\dndmaster\.runtime\` (venv, Ollama, modeller, önbellekler)
- Her kabukta: `source scripts/devenv.sh`
- Sunucu: `python -m dndm` (gerçek model) / `python -m dndm --port 8766 --fake-llm` (GPU'suz arayüz testi)
- Testler: `python -m pytest -q` (117 test)
- Otonom oyun testi: `python -m tools.playtest --players 3 --rounds 10 --personas investigator,thief,free_spirit`
- Model karşılaştırma: `python -m tools.bench.run_bench MODEL...` → `.runtime/bench/`
- Savaş dengesi: `python -m tools.sim_balance 150`
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

## Sıradakiler
- [ ] Son oyun testinin (20261030_05xx) transkriptini incele; Kül Kalesi'ni oyun testinden geçir
- [ ] Paketlenmiş exe'nin gerçek denemesi (DNDM_OLLAMA_PORT=11434 ile), sonra temiz kurulum testi
- [ ] Impish Bloodmoon + Gemma4-26B MoE + hafif model (e4b-qat) ölçümü → MODEL_RAPORU.md
- [ ] 3. senaryo (liman şehri entrikası), PC masa ekranında görsel cilalama, özel karakter oluşturma testi
- [ ] Not: Inno Setup'ı çalıştırmak otomatik izin denetimince engellendi → kendi kurulum sihirbazımızı yazdık
