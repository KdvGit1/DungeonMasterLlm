# DnD Master v2 — İlerleme Günlüğü

Bu dosya otonom geliştirme sırasında nerede kalındığını takip eder.
Fikir/öneri notları için: [FIKIRLER.md](FIKIRLER.md)

## Ortam (her şey D:'de)
- Kaynak: `D:\dndmaster` (git, dal: `v2`)
- Çalışma zamanı: `D:\dndmaster\.runtime\` (git dışı)
  - `venv\` geliştirme Python 3.12 ortamı
  - `ollama\` taşınabilir Ollama v0.40.13, `models\` model dosyaları, `ollama-home\`
  - `pip-cache\`, `hf-cache\`, `tmp\`, `downloads\`
- Her kabukta: `source scripts/devenv.sh`
- Ollama başlatma: `USERPROFILE=<.runtime\ollama-home> OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 .runtime/ollama/ollama.exe serve`
- Donanım: RTX 3060 12GB, Ryzen 5 1600, 16GB RAM

## Dallar
- `main` — orijinal (bozuk merge 8d40b8b dahil)
- `legacy-fix` — merge doğru yapıldı (eb75b47), eski sürüm açılıyor, 28 test geçiyor
- `v2` — yeni sürüm geliştirmesi

## Aşamalar
- [x] 0. Hazırlık (klasör düzeni, venv, Ollama)
- [x] 1. Bozuk merge kurtarıldı → `legacy-fix`
- [ ] 2. Model araştırması, benchmark, seçim → `MODEL_RAPORU.md`
- [ ] 3. Oyun motoru çekirdeği (kurallar, karakter, zar)
- [ ] 4. Envanter
- [ ] 5. AI GM katmanı
- [ ] 6. Savaş
- [ ] 7. Sunucu + çok oyunculu
- [ ] 8. Arayüzler (PC masa ekranı + telefon) + 3D zar
- [ ] 9. Senaryolar + doğrulama
- [ ] 10. Uçtan uca testler
- [ ] 11. Kurulum exe
- [ ] 12. Cilalama

## Günlük
- 2026-10-30: Repo klonlandı, analiz yapıldı, plan onaylandı. Merge düzeltildi (`legacy-fix`). v2 dalı açıldı.
