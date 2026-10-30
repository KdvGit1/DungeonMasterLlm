"""
Condition catalogue: Turkish names, icons and the mechanical flags the
combat engine reads. Conditions are stored on characters/enemies as
``Condition`` objects (id + rounds + save info).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CondInfo:
    name: str
    icon: str
    desc: str
    incapacitated: bool = False      # loses action & reaction
    attacks_have_adv: bool = False   # attacks against it have advantage
    melee_auto_crit: bool = False    # melee hits within 5 ft are crits
    attacker_dis: bool = False       # its own attacks have disadvantage
    ranged_against_dis: bool = False # ranged attacks against it have disadvantage (prone)
    melee_against_adv: bool = False  # melee attacks against it have advantage (prone)
    attacks_adv: bool = False        # its own attacks have advantage
    ends_on_damage: bool = False
    no_reactions: bool = False
    dex_save_fail: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


CONDITIONS: dict[str, CondInfo] = {
    "prone": CondInfo("Yere Serilmiş", "🔻", "Saldırıları dezavantajlı; yakın saldırılar ona avantajlı, uzaktan saldırılar dezavantajlı.",
                      attacker_dis=True, melee_against_adv=True, ranged_against_dis=True),
    "restrained": CondInfo("Bağlanmış", "🕸️", "Hareket edemez, saldırıları dezavantajlı, ona yapılan saldırılar avantajlı.",
                           attacker_dis=True, attacks_have_adv=True, dex_save_fail=False),
    "grappled": CondInfo("Tutulmuş", "✊", "Yer değiştiremez."),
    "paralyzed": CondInfo("Felçli", "⚡", "Hiçbir şey yapamaz; ona yakın vuruşlar kritik.",
                          incapacitated=True, attacks_have_adv=True, melee_auto_crit=True, dex_save_fail=True),
    "asleep": CondInfo("Uyuyor", "💤", "Hasar alınca uyanır; ona yakın vuruşlar kritik.",
                       incapacitated=True, attacks_have_adv=True, melee_auto_crit=True, ends_on_damage=True),
    "stunned": CondInfo("Sersemlemiş", "💫", "Hiçbir şey yapamaz; ona saldırılar avantajlı.",
                        incapacitated=True, attacks_have_adv=True, dex_save_fail=True),
    "frightened": CondInfo("Korkmuş", "😱", "Saldırıları ve becerileri dezavantajlı.", attacker_dis=True),
    "poisoned": CondInfo("Zehirlenmiş", "🤢", "Saldırıları ve becerileri dezavantajlı.", attacker_dis=True),
    "blinded": CondInfo("Kör", "🙈", "Saldırıları dezavantajlı, ona saldırılar avantajlı.",
                        attacker_dis=True, attacks_have_adv=True),
    "charmed": CondInfo("Büyülenmiş", "💗", "Büyüleyene saldıramaz."),
    "charmed_incapacitated": CondInfo("Hipnoz", "🌀", "Kendinden geçmiş; hasar alınca uyanır.",
                                      incapacitated=True, ends_on_damage=True),
    "incapacitated": CondInfo("Etkisiz", "⛔", "Eylem yapamaz.", incapacitated=True),
    "invisible": CondInfo("Görünmez", "👻", "Saldırıları avantajlı, ona saldırılar dezavantajlı.", attacks_adv=True),
    "hidden": CondInfo("Saklanmış", "🌑", "Bir sonraki saldırısı avantajlı.", attacks_adv=True),
    "dodging": CondInfo("Savunmada", "🛡️", "Ona yapılan saldırılar dezavantajlı."),
    "raging": CondInfo("Öfkeli", "🔥", "+2 hasar, fiziksel hasara direnç."),
    "blessed": CondInfo("Kutsanmış", "✨", "Saldırı ve kurtarma zarlarına +1d4."),
    "illuminated": CondInfo("Işıkla İşaretli", "🌟", "Bir sonraki saldırı avantajlı.", attacks_have_adv=True),
    "outlined": CondInfo("Peri Ateşi", "🧚", "Ona saldırılar avantajlı.", attacks_have_adv=True),
    "mocked": CondInfo("Aşağılanmış", "🤡", "Bir sonraki saldırısı dezavantajlı.", attacker_dis=True),
    "slowed": CondInfo("Yavaşlamış", "🧊", "Hızı azaldı."),
    "no_reactions": CondInfo("Sarsılmış", "⚡", "Reaksiyon kullanamaz.", no_reactions=True),
    "helped": CondInfo("Yardım Aldı", "🤝", "Bir sonraki saldırısı avantajlı.", attacks_adv=True),
    "reckless": CondInfo("Pervasız", "😤", "Saldırıları avantajlı, ona saldırılar da avantajlı.",
                         attacks_adv=True, attacks_have_adv=True),
    "marked": CondInfo("Avcının İşareti", "🎯", "Avcı ona ek hasar verir."),
    "engulfed": CondInfo("Yutulmuş", "🟩", "Küpün içinde, asitle eriyor.", attacker_dis=True, attacks_have_adv=True),
    "restrained_petrifying": CondInfo("Taşlaşıyor", "🗿", "Bedeni taşa dönüşüyor.", attacker_dis=True,
                                      attacks_have_adv=True),
    "petrified": CondInfo("Taşlaşmış", "🪨", "Taşa dönüştü.", incapacitated=True),
    "shield_spell": CondInfo("Kalkan Büyüsü", "🔷", "+5 Zırh Sınıfı."),
    "shield_of_faith": CondInfo("İnanç Kalkanı", "🔰", "+2 Zırh Sınıfı."),
    "mage_armor": CondInfo("Büyü Zırhı", "🔮", "Zırh Sınıfı 13 + Çeviklik."),
    "heroism": CondInfo("Kahramanlık", "🦸", "Her tur geçici can, korkuya bağışık."),
    "spirit_guardians": CondInfo("Ruh Muhafızları", "👼", "Ön saftaki düşmanlar her tur ışık hasarı alır."),
    "spiritual_weapon": CondInfo("Ruhani Silah", "🗡️", "Her tur ek saldırı."),
    "hunters_mark": CondInfo("Avcı Odağı", "🏹", "İşaretli hedefe ek 1d6."),
    "ensnaring_ready": CondInfo("Dolayan Vuruş Hazır", "🌿", "Sonraki isabet hedefi bağlar."),
    "smite_ready": CondInfo("Gürleyen Darbe Hazır", "⚡", "Sonraki isabet ek gök gürültüsü hasarı verir."),
    "sacred_weapon": CondInfo("Kutsal Silah", "⚔️", "Saldırılara Karizma bonusu."),
    "inspired": CondInfo("İlham", "🎵", "Bir zarına ilham zarı ekleyebilir."),
    "fleeing": CondInfo("Kaçıyor", "🏃", "Savaştan kaçmaya çalışıyor."),
    "surrendered": CondInfo("Teslim Oldu", "🏳️", "Silahını bıraktı.", incapacitated=True),
}


def info(cid: str) -> CondInfo:
    return CONDITIONS.get(cid) or CondInfo(cid, "❔", cid)


def name_tr(cid: str) -> str:
    return info(cid).name
