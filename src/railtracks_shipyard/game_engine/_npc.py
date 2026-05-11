from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from ._models import (
    Category,
    ItemName,
    ITEM_CATALOG,
    MARKET_NPC_ARCHETYPES,
    MARKET_PRIMARY_CATEGORIES,
    MarketName,
    NPC_FIRST_NAMES,
    NPC_LAST_NAMES,
    NPCArchetype,
)


# ── Price deviation parameters per archetype ──────────────────────────────────
# (ask_low, ask_high): NPC sell-to-agent multiplier range
# (bid_low, bid_high): NPC buy-from-agent multiplier range
_ASK_RANGE: dict[NPCArchetype, tuple[float, float]] = {
    NPCArchetype.RELIABLE_TRADER: (0.97, 1.03),
    NPCArchetype.OPTIMIST:        (1.08, 1.18),
    NPCArchetype.PESSIMIST:       (0.97, 1.04),
    NPCArchetype.MANIPULATOR:     (1.15, 1.30),  # overprices, sometimes deceptively low
    NPCArchetype.NOISE_TRADER:    (0.75, 1.28),
}

_BID_RANGE: dict[NPCArchetype, tuple[float, float]] = {
    NPCArchetype.RELIABLE_TRADER: (0.97, 1.03),
    NPCArchetype.OPTIMIST:        (0.98, 1.05),
    NPCArchetype.PESSIMIST:       (0.82, 0.92),
    NPCArchetype.MANIPULATOR:     (0.70, 0.85),  # lowballs
    NPCArchetype.NOISE_TRADER:    (0.70, 1.25),
}

# How far below ask the NPC will accept (for buy negotiation)
_ACCEPT_THRESHOLD_BUY: dict[NPCArchetype, float] = {
    NPCArchetype.RELIABLE_TRADER: 0.94,
    NPCArchetype.OPTIMIST:        0.96,
    NPCArchetype.PESSIMIST:       0.88,
    NPCArchetype.MANIPULATOR:     0.97,
    NPCArchetype.NOISE_TRADER:    0.70,
}

# How far above bid the NPC will accept (for sell negotiation)
_ACCEPT_THRESHOLD_SELL: dict[NPCArchetype, float] = {
    NPCArchetype.RELIABLE_TRADER: 1.06,
    NPCArchetype.OPTIMIST:        1.08,
    NPCArchetype.PESSIMIST:       1.03,
    NPCArchetype.MANIPULATOR:     1.04,
    NPCArchetype.NOISE_TRADER:    1.30,
}

_COUNTER_TEMPLATES = [
    "Best I can do is {price:.2f}.",
    "I can do {price:.2f} per unit — take it or leave it.",
    "How about {price:.2f}? That's fair and you know it.",
    "Meet me at {price:.2f}.",
    "{price:.2f}. Final offer.",
]

_REJECT_TEMPLATES = [
    "Not interested at that price.",
    "You're wasting my time.",
    "Come back when you're serious.",
    "That's not going to work for me.",
    "No deal.",
]


@dataclass
class NPC:
    npc_id: str
    name: str
    archetype: NPCArchetype
    market: MarketName
    inventory: dict[ItemName, int] = field(default_factory=dict)
    wanted_items: list[ItemName] = field(default_factory=list)
    # Cached prices refreshed on every price advance
    _ask_cache: dict[ItemName, float] = field(default_factory=dict, repr=False)
    _bid_cache: dict[ItemName, float] = field(default_factory=dict, repr=False)

    # ── Cached price access ───────────────────────────────────────────────────

    def refresh_prices(self, market_rates: dict[ItemName, float], rng: random.Random) -> None:
        """Re-compute and cache ask/bid prices based on current market rates."""
        all_items = set(self.inventory) | set(self.wanted_items)
        for item in all_items:
            rate = market_rates.get(item, 0.0)
            if rate <= 0:
                continue
            lo, hi = _ASK_RANGE[self.archetype]
            # Manipulator occasionally flips to a deceptively low ask
            if self.archetype == NPCArchetype.MANIPULATOR and rng.random() < 0.35:
                lo, hi = 0.82, 0.94
            self._ask_cache[item] = round(rate * rng.uniform(lo, hi), 2)

            blo, bhi = _BID_RANGE[self.archetype]
            if self.archetype == NPCArchetype.MANIPULATOR and rng.random() < 0.35:
                blo, bhi = 1.05, 1.18
            self._bid_cache[item] = round(rate * rng.uniform(blo, bhi), 2)

    def get_ask(self, item: ItemName) -> float:
        return self._ask_cache.get(item, 0.0)

    def get_bid(self, item: ItemName) -> float:
        return self._bid_cache.get(item, 0.0)

    def accept_threshold_buy(self) -> float:
        return _ACCEPT_THRESHOLD_BUY[self.archetype]

    def accept_threshold_sell(self) -> float:
        return _ACCEPT_THRESHOLD_SELL[self.archetype]


# ── Negotiation logic ─────────────────────────────────────────────────────────

def negotiate_round(
    npc: NPC,
    action: str,          # "buy" or "sell" from agent's perspective
    proposed_price: float,
    round_num: int,
    rng: random.Random,
) -> tuple[str, float, str]:
    """
    Evaluate one round of negotiation.

    Returns (outcome, price, message):
      outcome: "accepted" | "rejected" | "counter"
      price:   agreed/counter price (0.0 if rejected)
      message: NPC dialogue string
    """
    if action == "buy":
        ask = npc.get_ask(None)  # cached; item not needed here
        return _evaluate_buy(npc, ask, proposed_price, round_num, rng)
    else:
        bid = npc.get_bid(None)
        return _evaluate_sell(npc, bid, proposed_price, round_num, rng)


def negotiate_round_for_item(
    npc: NPC,
    item: ItemName,
    action: str,
    proposed_price: float,
    round_num: int,
    rng: random.Random,
) -> tuple[str, float, str]:
    """Same as negotiate_round but resolves cached price by item."""
    if action == "buy":
        ask = npc.get_ask(item)
        if ask <= 0:
            # Fallback if cache is cold
            rate_fallback = proposed_price * 1.05
            ask = rate_fallback
        return _evaluate_buy(npc, ask, proposed_price, round_num, rng)
    else:
        bid = npc.get_bid(item)
        if bid <= 0:
            bid = proposed_price * 0.95
        return _evaluate_sell(npc, bid, proposed_price, round_num, rng)


def _evaluate_buy(
    npc: NPC,
    ask: float,
    proposed: float,
    round_num: int,
    rng: random.Random,
) -> tuple[str, float, str]:
    if npc.archetype == NPCArchetype.NOISE_TRADER:
        roll = rng.random()
        if roll < 0.40:
            return "accepted", proposed, ""
        if roll < 0.70:
            counter = round(ask * rng.uniform(0.90, 1.05), 2)
            return "counter", counter, _counter_msg(counter, rng)
        return "rejected", 0.0, _reject_msg(rng)

    threshold = npc.accept_threshold_buy()
    if proposed >= ask * threshold:
        return "accepted", proposed, ""

    # Concession zone: [ask*(threshold-0.15), ask*threshold)
    min_concede = ask * max(threshold - 0.15, 0.70)
    if proposed >= min_concede:
        concession_frac = 0.30 if round_num == 1 else 0.55
        counter = round(ask - (ask - proposed) * concession_frac, 2)
        counter = max(counter, ask * (threshold - 0.03))
        return "counter", counter, _counter_msg(counter, rng)

    return "rejected", 0.0, _reject_msg(rng)


def _evaluate_sell(
    npc: NPC,
    bid: float,
    proposed: float,
    round_num: int,
    rng: random.Random,
) -> tuple[str, float, str]:
    if npc.archetype == NPCArchetype.NOISE_TRADER:
        roll = rng.random()
        if roll < 0.40:
            return "accepted", proposed, ""
        if roll < 0.70:
            counter = round(bid * rng.uniform(0.95, 1.10), 2)
            return "counter", counter, _counter_msg(counter, rng)
        return "rejected", 0.0, _reject_msg(rng)

    threshold = npc.accept_threshold_sell()
    if proposed <= bid * threshold:
        return "accepted", proposed, ""

    max_concede = bid * min(threshold + 0.15, 1.40)
    if proposed <= max_concede:
        concession_frac = 0.30 if round_num == 1 else 0.55
        counter = round(bid + (proposed - bid) * concession_frac, 2)
        counter = min(counter, bid * (threshold + 0.03))
        return "counter", counter, _counter_msg(counter, rng)

    return "rejected", 0.0, _reject_msg(rng)


def _counter_msg(price: float, rng: random.Random) -> str:
    return rng.choice(_COUNTER_TEMPLATES).format(price=price)


def _reject_msg(rng: random.Random) -> str:
    return rng.choice(_REJECT_TEMPLATES)


# ── Factory ───────────────────────────────────────────────────────────────────

def create_npcs(seed: int) -> list[NPC]:
    """
    Create all 15 NPCs (5 per market) with seeded-random names and inventory.
    Archetypes match each market's character.
    """
    rng = random.Random(seed + 10)
    first_names = list(NPC_FIRST_NAMES)
    last_names = list(NPC_LAST_NAMES)
    rng.shuffle(first_names)
    rng.shuffle(last_names)

    npcs: list[NPC] = []
    npc_counter = 1

    for market in (MarketName.EXCHANGE, MarketName.FRONTIER_POST, MarketName.BLACK_MARKET):
        archetypes = list(MARKET_NPC_ARCHETYPES[market])
        rng.shuffle(archetypes)
        primary_cats = MARKET_PRIMARY_CATEGORIES[market]
        market_items = [n for n, cfg in ITEM_CATALOG.items() if cfg.category in primary_cats]

        for archetype in archetypes:
            npc_id = f"npc_{npc_counter:02d}"
            name = f"{first_names.pop()}{' ' if last_names else ''}{last_names.pop() if last_names else ''}".strip()

            # Give each NPC 2–3 items to sell and 1–2 to buy
            sell_count = rng.randint(2, min(3, len(market_items)))
            buy_count = rng.randint(1, min(2, len(market_items)))
            sell_items = rng.sample(market_items, sell_count)
            buy_items = rng.sample(market_items, buy_count)

            inventory = {item: rng.randint(8, 20) for item in sell_items}

            npc = NPC(
                npc_id=npc_id,
                name=name,
                archetype=archetype,
                market=market,
                inventory=inventory,
                wanted_items=buy_items,
            )
            npcs.append(npc)
            npc_counter += 1

    return npcs
