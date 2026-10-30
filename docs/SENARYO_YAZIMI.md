# Senaryo Yazım Kılavuzu

Senaryolar `scenarios/<klasör_adı>/scenario.yaml` dosyasında durur. Bir senaryo bir **hikâye
değil, bir dünyadır**: oyuncular istedikleri yere gider, GM dünyayı onlara göre canlandırır.
Örnekler: `scenarios/degirmenkoyun_golgesi`, `kul_kalesinin_laneti`, `tuzlukiyida_gumus_ve_kan`.

## İskelet
```yaml
title: "Başlık"
pitch: "Lobide görünen 1-2 cümlelik kanca."
tone: "Ton (GM'e ipucu)."
players: [1, 6]
level_range: [1, 3]
premise: |            # SADECE GM görür: dünyanın gerçeği, kim neyi neden yapıyor
truths: ["GM'in asla unutmaması gereken gerçekler"]
start_location: baslangic_yeri
opening: "Açılış sahnesi için GM'e yönlendirme."
style_notes: |        # anlatım tarzı ipuçları
factions: {...}       # grupların amaçları
fronts: {...}         # TEHDİT SAATLERİ: oyuncular oyalandıkça ilerler
quests: {...}         # görevler (optional: false olanlar baştan aktif)
npcs: {...}           # kişiler: görünüş, kişilik, ses, istek, SIR, bildikleri
locations: {...}      # mekânlar
endings: [...]        # olası sonlar (2+)
random_events: [...]  # durgunlukta GM'in kullanabileceği küçük olaylar
```

## Mekân
```yaml
locations:
  meyhane:
    name: Paslı Testi Meyhanesi
    description: "Oyuncuların gördüğü sahne."
    gm_notes: "Sadece GM: burada neler dönüyor."
    exits: [meydan, mahzen]        # İKİ YÖNLÜ olmalı (meydan'ın exits'inde de 'meyhane' olmalı)
    npcs: [borin]
    hidden: false                  # true: keşfedilene kadar haritada görünmez
    safe_rest: true                # burada uzun dinlenme yapılabilir
    travel_hours: 1                # buraya gitmek kaç saat sürer
    shop: [{id: potion_healing, price: 50}]        # dükkân (eşya id'leri dndm/data/items.yaml'da)
    items: [{id: dagger}, {name: "Eski Mektup", kind: quest}]   # yerde duran, alınabilir eşyalar
    discoveries:                   # KEŞİFLER: keşfin ödülü
      - id: gizli_defter
        hint: "Tezgâhın altında bir şey parlıyor."     # GM bunu sahnede fark edilir kılar
        check: {skill: investigation, dc: 13}          # yoksa zar gerekmez (göze çarpan şey)
        reveals: "Bulunan bilgi."
        item: {name: "Kara Defter", kind: quest, description: "..."}   # ya da {id: katalog_id}
        gold: 10
        leads_to: [gizli_mahzen]   # keşfedilince haritada açılan yerler
        xp: 50
    encounters:                    # olası savaşlar (GM uygun anda başlatır)
      - id: kavga
        when: "Oyuncular hancıyı tehdit ederse"
        enemies: [{monster: thug, count: 2, name: "Sarhoş"}]   # canavar id'leri: dndm/data/monsters.yaml
        boss: false
        features:                  # savaş alanında kullanılabilir şeyler
          - {name: "Avize", description: "...", effect: hazard, damage: 2d6, damage_type: bludgeoning, rank: front}
```
`effect`: `hazard` (hasar), `push_hazard` (itilince hasar), `trap` (yere serer), `cover` (siper),
`obscure` (görüşü kapatır), `high_ground`. Patron için `hp_factor: 0.6` (yaralı) ya da `2.5` (güçlendirilmiş).

## Tehdit saati
```yaml
fronts:
  ayin:
    name: Yükseliş Ayini
    description: "Oyuncular durdurmazsa ne olacak."
    clock: 6          # toplam adım
    per_day: 2        # oyun içi günde kaç adım ilerler (zaman geçtikçe)
    stages: {2: "2. adımda dünyada görülen değişiklik", 4: "..."}
    on_complete: "Saat dolunca olan."
```

## İyi senaryo için ipuçları
- **Her önemli ipucuna en az üç yol** olsun (bir NPC, bir eşya, bir yer). Tek zara bağlı kalmasın.
- Her NPC'nin bir **isteği** ve bir **sırrı** olsun; GM onları buna göre oynar.
- Zarsız keşifler (göze çarpan şeyler) mekânı canlı kılar; zorlu bilgi için `check` ekle.
- Zorunlu sıra koyma; tehdit saatleri ve sonuçlar dünyayı ilerletsin.
- Yalnızca klasik fantastik öğeler: modern teknoloji yok, yayınlanmış ticari dünyaların
  isimleri (Faerûn, Waterdeep, Strahd…) yok — özgün isimler kullan.

## Kontrol
```bash
python -m tools.yaml_quote_fix scenarios/*/scenario.yaml   # ": " içeren değerleri tırnağa alır
python -m pytest -q tests/test_scenarios.py                # yapı + klasik D&D denetimi
python -m tools.playtest --scenario <klasör_adı> --players 3 --rounds 10   # otonom deneme
```
