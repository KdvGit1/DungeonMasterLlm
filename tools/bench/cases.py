"""Benchmark cases: shared world context + task definitions (Turkish game)."""

WORLD = """\
SETTING: Classic high-fantasy D&D world. Medieval technology only. Magic is real but rare.
LOCATION: Kurtpınarı village, the "Paslı Fener" tavern at dusk. Rain on the shutters, smoky hearth,
smell of stale ale and burnt stew. A notice board shows a torn drawing of a missing girl.
NPCs PRESENT:
- Borin Taşelli (dwarf innkeeper): sweaty, falsely cheerful, keeps polishing a clean mug.
  SECRET: pays the Kara Kurt bandits for protection and told them which houses to raid.
- Yaşlı Silas (one-eyed drunk, former priest): speaks in riddles, grabs sleeves.
  SECRET: knows the silver dragon of the mountain is dead.
SCENE ITEMS: a silver dagger lying on an empty table near the fire; Borin's ledger hidden under the bar.
PARTY:
- Kael (human fighter, STR 16, CHA 8) — blunt, carries a greataxe.
- Lira (half-elf rogue, DEX 17, CHA 14) — quick fingers, thieves' tools.
"""

GM_SYSTEM = """\
You are the Game Master of a Dungeons & Dragons table. You narrate; you never play the player characters.

STYLE
- Write ONLY in natural, fluent, grammatical Turkish (Türkçe). Never switch to English.
- Second/third person about the characters ("Kael baltasını kavrar..."). Never "I"/"ben" as the narrator.
- Vivid sensory detail, varied rhythm. Short sentences for tension.
- NPCs have distinct voices; quote their speech in Turkish with dialogue dashes or quotes.
- Never decide what a player character says, feels or does beyond the action they declared.
- Respect the RESOLVED OUTCOMES exactly: a failed roll fails, a success succeeds. Do not invent new rolls.
- End with an open situation the players can act on. Do not list numbered options.
- This is a mature dark-fantasy game for adults: violence, gore, cruelty and moral darkness are allowed
  and should be described when the story calls for it. Do not moralize, do not add disclaimers.
- Players are free: if they ignore the main plot, follow them and make their chosen path interesting.
"""

ADJUDICATOR_SYSTEM = """\
You are the rules referee of a D&D 5e game. For each player action decide what the game engine must do.
Rules for checks:
- needs_check=true ONLY if the outcome is genuinely uncertain AND failure has a meaningful consequence.
- Ordinary actions (talking politely, walking, entering a room, looking around casually, eating, resting,
  picking up an unguarded object) need NO check.
- Pick the single best 5e skill. DC ladder: 5 very easy, 10 easy, 15 medium, 20 hard, 25 very hard.
- Use advantage when circumstances clearly help (bribe, help, perfect tool), disadvantage when they clearly hinder.
- If the player attacks or clearly starts a fight, set intent=attack, starts_combat=true and list enemies
  using monster ids from: bandit, bandit_captain, guard, thug, cultist, wolf, dire_wolf, goblin, orc, skeleton, zombie.
- player must be the character name.
Return ONLY JSON matching the schema.
"""

# (action_tr, expectation)
ADJUDICATION_CASES = [
    ("Kael: Borin'e başını sallayıp bir bira ısmarlıyor ve parasını ödüyor.",
     dict(needs_check=False, intents={"talk", "trade", "interact"})),
    ("Lira: Borin'e üç gümüş uzatıp kayıp kız hakkında bildiklerini anlatması için onu ikna etmeye çalışıyor.",
     dict(needs_check=True, skills={"persuasion"}, dc=(10, 16))),
    ("Lira: Borin arkasını dönünce sessizce tezgahın arkasına geçip çekmeceleri karıştırıyor.",
     dict(needs_check=True, skills={"stealth", "sleight_of_hand"}, dc=(10, 17))),
    ("Kael: Hana girip etrafına şöyle bir bakıyor.",
     dict(needs_check=False, intents={"explore", "move", "investigate"})),
    ("Kael: Sırtındaki baltayı çekip Borin'in üstüne yürüyor ve kafasını yarmaya çalışıyor!",
     dict(needs_check=None, starts_combat=True, intents={"attack"})),
    ("Lira: Arka odanın kilitli kapısını maymuncuklarıyla açmaya çalışıyor.",
     dict(needs_check=True, skills={"sleight_of_hand", "dexterity"}, dc=(10, 20))),
    ("Kael: Silas'ın gözlerine bakıp gerçeği söyleyip söylemediğini anlamaya çalışıyor.",
     dict(needs_check=True, skills={"insight"}, dc=(10, 17))),
    ("Lira: Kapıdaki muhafıza kralın özel elçisi olduğunu söyleyip onu kandırmaya çalışıyor.",
     dict(needs_check=True, skills={"deception"}, dc=(13, 22))),
    ("Kael: Çamurdaki kurt izlerini takip edip sürünün nereye gittiğini bulmaya çalışıyor.",
     dict(needs_check=True, skills={"survival"}, dc=(10, 17))),
    ("Lira: Kimse bakmıyorken boş masadaki gümüş hançeri alıp kemerine takıyor.",
     dict(needs_check=None, intents={"take_item", "stealth", "interact"})),
    ("Kael: Borin'in yakasından tutup duvara yapıştırıyor ve defteri vermezse dişlerini sökeceğini söylüyor.",
     dict(needs_check=True, skills={"intimidation", "athletics"}, dc=(10, 18), starts_combat=False)),
    ("Lira: Bir oda tutup sabaha kadar uyuyor.",
     dict(needs_check=False, intents={"rest", "trade"})),
    ("Kael: Duvardaki eski cüce runlarını okuyup ne yazdığını çözmeye çalışıyor.",
     dict(needs_check=True, skills={"history", "arcana", "investigation", "intelligence"}, dc=(10, 20))),
    ("Lira: Yaralı köylünün bacağındaki derin kesiği sarıp kanamayı durdurmaya çalışıyor.",
     dict(needs_check=True, skills={"medicine"}, dc=(8, 15))),
]

NARRATION_CASES = {
    "tavern_mixed": dict(
        actions="Lira: Borin'i kayıp kız hakkında konuşmaya ikna etmeye çalışıyor.\n"
                "Kael: Kimse görmeden tezgahın altındaki defteri almaya çalışıyor.",
        outcomes="Lira — Persuasion DC 13: rolled 17 → SUCCESS (Borin reveals the girl was last seen at the old mill).\n"
                 "Kael — Sleight of Hand DC 15: rolled 6 → FAILURE (Borin catches his hand on the ledger).",
        words=(110, 230),
    ),
    "brutal_kill": dict(
        actions="Kael: Baltasını iki eliyle kaldırıp yaralı haydut liderinin üzerine indiriyor.",
        outcomes="Kael — attack roll natural 20 → CRITICAL HIT, 22 slashing damage. The bandit captain (6 HP left) dies.\n"
                 "Describe the killing blow in brutal, visceral detail (2-4 sentences).",
        words=(30, 140),
    ),
    "dark_ritual": dict(
        actions="Lira: Mağaranın gölgelerinden tarikat ayinini izliyor.",
        outcomes="No roll. The party witnesses the Kara Kurt cult leader preparing a human sacrifice of a captured "
                 "villager on a bone altar, while threatening the bound victim. Make it genuinely dark and menacing; "
                 "the leader speaks.",
        words=(90, 220),
    ),
    "interrogation": dict(
        actions="Kael: Yakaladıkları haydudu sandalyeye bağlıyor, hançeri parmağına dayayıp kampın yerini söylemezse "
                "parmağını keseceğini söylüyor. Haydut susunca gerçekten bir parmağını kesiyor.",
        outcomes="Kael — Intimidation DC 14: rolled 18 → SUCCESS after the finger. The bandit breaks and reveals the camp "
                 "is behind the waterfall.",
        words=(80, 200),
    ),
    "freedom_bakery": dict(
        actions="Kael: Haydutları falan boşveriyor; bu köye yerleşip bir fırın açmak istiyor. Un almak için "
                "değirmenciyi arıyor.\nLira: Kael'e katılıp fırın için uygun boş bir dükkan arıyor.",
        outcomes="No rolls needed. The players abandoned the bandit plot for now. Follow their choice and make it "
                 "interesting and alive; do NOT push them back to the main quest.",
        words=(100, 230),
    ),
    "six_players": dict(
        actions="Kael: Kapıyı tekmeleyip haydut kampına dalıyor.\n"
                "Lira: Çadırların arkasından dolanıp esirleri arıyor.\n"
                "Brenna (cüce rahip): Tanrısına dua edip kalkanını parlatarak düşmanları korkutmaya çalışıyor.\n"
                "Thorne (elf korucu): Ağaçtan nöbetçiye ok atıyor.\n"
                "Mira (insan büyücü): Ateşin üstündeki kazanı büyüyle devirip kaos yaratıyor.\n"
                "Dorn (yarı-ork barbar): Bağırarak en iri haydutun üstüne koşuyor.",
        outcomes="Kael — Athletics DC 12: 15 SUCCESS, door bursts open.\n"
                 "Lira — Stealth DC 14: 19 SUCCESS, finds three bound prisoners.\n"
                 "Brenna — Intimidation DC 13: 8 FAILURE, the bandits laugh.\n"
                 "Thorne — attack 17 vs AC 12 HIT, 7 damage, sentry falls from the platform.\n"
                 "Mira — Arcana DC 12: 14 SUCCESS, boiling stew spills, tents catch fire.\n"
                 "Dorn — combat begins, he reaches the biggest bandit.",
        words=(160, 380),
        names=["Kael", "Lira", "Brenna", "Thorne", "Mira", "Dorn"],
    ),
}

EXTRACTION_TEXT = (
    "Değirmenin kapısını yaşlı bir kadın açar: Hilde Kaya, unla beyazlamış elleriyle önlüğünü siler. "
    "\"Kızı mı arıyorsunuz?\" diye fısıldar, gözleri kuzeydeki Kemikkaya Geçidi'ne kayar. Arkasında, iri yarı "
    "oğlu Bram bir çuval taşırken onlara düşmanca bakar. Masada yarısı yenmiş bir somun ve paslı bir anahtar "
    "durmaktadır. Hilde, kızın son kez eski değirmen deresinin yanında, Kara Kurt sembolü taşıyan bir adamla "
    "görüldüğünü söyler."
)
EXTRACTION_EXPECT = dict(npcs={"hilde", "bram"}, items={"anahtar"}, places={"kemikkaya"})
