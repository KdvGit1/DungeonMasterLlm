"""
Inventory: the single source of truth for what a character owns.

Nothing enters an inventory except through these methods, which are called by
the engine — never directly from free model text. Every stack has a unique
``uid`` so equipping, giving and dropping are unambiguous.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from dndm.rules import data
from dndm.text import norm_key, similar

Slot = Literal["main_hand", "off_hand", "armor", "cloak", "neck", "ring1", "ring2", "boots", "hands"]
SLOT_TR = {
    "main_hand": "Ana El", "off_hand": "Yan El", "armor": "Zırh", "cloak": "Pelerin", "neck": "Boyun",
    "ring1": "Yüzük", "ring2": "Yüzük", "boots": "Çizme", "hands": "Eldiven",
}
RARITY_TR = {"common": "Sıradan", "uncommon": "Nadir Olmayan", "rare": "Nadir",
             "very_rare": "Çok Nadir", "legendary": "Efsanevi", "quest": "Görev Eşyası"}


class InventoryError(ValueError):
    """User-facing (Turkish) reason why an inventory operation was refused."""


def _uid() -> str:
    return uuid.uuid4().hex[:10]


class ItemStack(BaseModel):
    uid: str = Field(default_factory=_uid)
    item_id: str | None = None          # catalog id; None for custom/story items
    name: str
    qty: int = 1
    kind: str = "gear"                  # catalog type, or quest / trinket for custom items
    description: str = ""
    value: float = 0
    rarity: str = "common"
    magic_bonus: int = 0                # +1/+2/+3 weapons & armor
    base: str | None = None             # catalog base for magic variants (e.g. longsword)
    charges: int | None = None

    @property
    def definition(self):
        return data.items().get(self.item_id) if self.item_id else None

    @property
    def weapon_def(self):
        """Catalog definition that carries the weapon stats (base for magic weapons)."""
        if self.base:
            return data.items().get(self.base)
        d = self.definition
        if d and d.type == "weapon":
            return d
        if d and getattr(d, "base", None):
            return data.items().get(d.base)
        return None

    @property
    def stackable(self) -> bool:
        d = self.definition
        return bool(d and d.stack) and not self.magic_bonus

    def display_name(self) -> str:
        n = self.name
        if self.magic_bonus and not n.startswith("+"):
            n = f"+{self.magic_bonus} {n}"
        return f"{n} ×{self.qty}" if self.qty > 1 else n

    def to_public(self) -> dict:
        d = self.definition
        return {
            "uid": self.uid, "item_id": self.item_id, "name": self.display_name(), "qty": self.qty,
            "kind": self.kind, "description": self.description, "value": self.value,
            "rarity": self.rarity, "rarity_tr": RARITY_TR.get(self.rarity, self.rarity),
            "magic_bonus": self.magic_bonus, "charges": self.charges,
            "usable": bool(d and d.type == "consumable"),
            "equippable": slot_for(self) is not None,
            "damage": (self.weapon_def.damage if self.weapon_def else None),
        }


def slot_for(stack: ItemStack) -> Slot | None:
    d = stack.definition
    if stack.weapon_def is not None:
        return "main_hand"
    if d is None:
        return None
    if d.type == "armor":
        return "armor"
    if d.type == "shield" or (d.type == "magic" and d.slot == "off_hand"):
        return "off_hand"
    if d.type == "magic" and d.slot in ("cloak", "neck", "boots", "hands"):
        return d.slot  # type: ignore[return-value]
    if d.type == "magic" and d.slot == "ring":
        return "ring1"
    return None


class Inventory(BaseModel):
    items: list[ItemStack] = Field(default_factory=list)
    equipped: dict[str, str] = Field(default_factory=dict)  # slot -> uid
    copper: int = 0                                         # all coins stored as copper

    # ── coins ───────────────────────────────────────────────────
    @property
    def gold(self) -> float:
        return self.copper / 100

    def coins_tr(self) -> str:
        gp, rest = divmod(self.copper, 100)
        sp, cp = divmod(rest, 10)
        parts = []
        if gp:
            parts.append(f"{gp} altın")
        if sp:
            parts.append(f"{sp} gümüş")
        if cp or not parts:
            parts.append(f"{cp} bakır")
        return ", ".join(parts)

    def add_coins(self, gp: float = 0, sp: int = 0, cp: int = 0) -> int:
        delta = int(round(gp * 100)) + sp * 10 + cp
        if self.copper + delta < 0:
            raise InventoryError("Yeterli paran yok.")
        self.copper += delta
        return delta

    def can_afford(self, gp: float) -> bool:
        return self.copper >= int(round(gp * 100))

    # ── lookup ──────────────────────────────────────────────────
    def get(self, uid: str) -> ItemStack:
        for s in self.items:
            if s.uid == uid:
                return s
        raise InventoryError("Bu eşya envanterinde yok.")

    def find(self, query: str) -> ItemStack | None:
        """Fuzzy lookup by catalog id or (Turkish) name — used to map spoken item names."""
        q = norm_key(query)
        if not q:
            return None
        for s in self.items:
            if s.item_id == query.strip() or norm_key(s.name) == q:
                return s
        for s in self.items:
            if similar(s.name, query) or (s.item_id and similar(s.item_id.replace("_", " "), query)):
                return s
        return None

    def count(self, item_id: str) -> int:
        return sum(s.qty for s in self.items if s.item_id == item_id)

    def is_equipped(self, uid: str) -> bool:
        return uid in self.equipped.values()

    def equipped_stack(self, slot: str) -> ItemStack | None:
        uid = self.equipped.get(slot)
        if not uid:
            return None
        try:
            return self.get(uid)
        except InventoryError:
            self.equipped.pop(slot, None)
            return None

    # ── add / remove ────────────────────────────────────────────
    def add(self, item_id: str, qty: int = 1, **overrides) -> ItemStack:
        """Add a catalog item. Stackables merge into an existing stack."""
        if item_id not in data.items():
            raise InventoryError(f"Bilinmeyen eşya: {item_id}")
        d = data.item(item_id)
        if qty < 1:
            raise InventoryError("Miktar en az 1 olmalı.")
        if d.stack and not overrides.get("magic_bonus"):
            for s in self.items:
                if s.item_id == item_id and not s.magic_bonus:
                    s.qty += qty
                    return s
            stack = ItemStack(item_id=item_id, name=d.name, qty=qty, kind=d.type, value=d.value,
                              rarity=d.rarity, **overrides)
            self.items.append(stack)
            return stack
        # non-stackable: one stack per copy (each can be equipped/given separately)
        name = overrides.pop("name", d.name)
        overrides.setdefault("charges", getattr(d, "charges", None))
        first: ItemStack | None = None
        for _ in range(qty):
            stack = ItemStack(item_id=item_id, name=name, qty=1, kind=d.type, value=d.value,
                              rarity=d.rarity, **overrides)
            self.items.append(stack)
            first = first or stack
        assert first is not None
        return first

    def add_custom(self, name: str, *, kind: str = "trinket", description: str = "",
                   value: float = 0, rarity: str = "common", qty: int = 1) -> ItemStack:
        """Story items with no mechanics (letters, keys, idols). Kind: quest | trinket | treasure."""
        name = name.strip()[:60]
        if not name:
            raise InventoryError("Eşyanın adı boş olamaz.")
        for s in self.items:
            if s.item_id is None and norm_key(s.name) == norm_key(name) and kind != "quest":
                s.qty += qty
                return s
        stack = ItemStack(item_id=None, name=name, qty=qty, kind=kind, description=description[:300],
                          value=value, rarity="quest" if kind == "quest" else rarity)
        self.items.append(stack)
        return stack

    def add_stack(self, stack: ItemStack) -> ItemStack:
        """Insert an existing stack object (from another inventory or the scene)."""
        if stack.stackable:
            for s in self.items:
                if s.item_id == stack.item_id and not s.magic_bonus:
                    s.qty += stack.qty
                    return s
        stack.uid = _uid()
        self.items.append(stack)
        return stack

    def remove(self, uid: str, qty: int = 1) -> ItemStack:
        """Remove qty from a stack; returns the removed portion as its own stack."""
        s = self.get(uid)
        if qty < 1 or qty > s.qty:
            raise InventoryError(f"Elinde sadece {s.qty} adet {s.name} var.")
        if s.qty == qty:
            self.unequip_uid(uid)
            self.items.remove(s)
            return s
        s.qty -= qty
        return s.model_copy(update={"uid": _uid(), "qty": qty})

    def consume(self, item_id: str, qty: int = 1) -> bool:
        """Spend ammunition/rations etc. by catalog id. Returns False if not enough."""
        have = self.count(item_id)
        if have < qty:
            return False
        for s in list(self.items):
            if s.item_id != item_id or qty == 0:
                continue
            take = min(qty, s.qty)
            self.remove(s.uid, take)
            qty -= take
        return True

    # ── equipment ───────────────────────────────────────────────
    def equip(self, uid: str, *, strength: int = 10) -> str:
        s = self.get(uid)
        slot = slot_for(s)
        if slot is None:
            raise InventoryError(f"{s.name} kuşanılabilecek bir eşya değil.")
        d = s.definition
        w = s.weapon_def
        if slot == "main_hand" and w and "two_handed" in w.properties:
            self.equipped.pop("off_hand", None)
        if slot == "off_hand":
            main = self.equipped_stack("main_hand")
            if main and main.weapon_def and "two_handed" in main.weapon_def.properties:
                raise InventoryError("İki elli silah tutarken kalkan kuşanamazsın.")
        if slot == "main_hand" and self.equipped.get("main_hand") and w and "light" in w.properties:
            current = self.equipped_stack("main_hand")
            if current and current.weapon_def and "light" in current.weapon_def.properties and \
                    "off_hand" not in self.equipped:
                slot = "off_hand"  # dual wield two light weapons
        if slot == "ring1" and self.equipped.get("ring1"):
            slot = "ring2"
        msg = ""
        if d and d.type == "armor" and d.str_req and strength < d.str_req:
            msg = f" (Güç {d.str_req} gerekli — hareketin yavaşlar)"
        self.unequip_uid(uid)
        self.equipped[slot] = uid
        return f"{s.name} kuşanıldı ({SLOT_TR[slot]}).{msg}"

    def unequip_uid(self, uid: str) -> None:
        for slot, u in list(self.equipped.items()):
            if u == uid:
                del self.equipped[slot]

    def unequip(self, slot: str) -> None:
        self.equipped.pop(slot, None)

    # ── derived ─────────────────────────────────────────────────
    def weapon(self) -> ItemStack | None:
        return self.equipped_stack("main_hand")

    def off_hand(self) -> ItemStack | None:
        return self.equipped_stack("off_hand")

    def armor(self) -> ItemStack | None:
        return self.equipped_stack("armor")

    def weight(self) -> float:
        total = 0.0
        for s in self.items:
            d = s.definition
            total += (d.weight if d else 0.5) * s.qty
        return round(total, 1)

    def to_public(self) -> dict:
        return {
            "items": [dict(s.to_public(), equipped_slot=next((k for k, v in self.equipped.items()
                                                              if v == s.uid), None))
                      for s in self.items],
            "coins": self.coins_tr(),
            "copper": self.copper,
            "weight": self.weight(),
        }

    def summary_for_llm(self) -> str:
        if not self.items:
            return f"(empty) — coins: {self.coins_tr()}"
        eq = {v for v in self.equipped.values()}
        parts = [f"{s.display_name()}{' [equipped]' if s.uid in eq else ''}" for s in self.items]
        return ", ".join(parts) + f" — coins: {self.coins_tr()}"
