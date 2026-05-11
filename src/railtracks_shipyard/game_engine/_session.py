from __future__ import annotations

import random
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Optional

from ._models import (
    BONUS_OBJECTIVE_POOL,
    ITEM_CATALOG,
    MARKET_PRIMARY_CATEGORIES,
    STARTING_ITEM_POOL,
    BonusObjectiveDef,
    Category,
    ItemName,
    MarketName,
)
from ._npc import NPC
from ._price_engine import PriceEngine

# Target total starting portfolio value (cash + items at baseline)
_TARGET_START_VALUE = 300.0
_MIN_CASH = 60.0
# How many bonus objectives to select per game
_NUM_OBJECTIVES = 3


@dataclass
class ActiveObjective:
    id: str
    description: str
    points: int
    completed: bool = False
    # Running counter for objectives that track progress mid-game
    _progress: int = field(default=0, repr=False)


@dataclass
class PendingNegotiation:
    npc_id: str
    item: ItemName
    action: str   # "buy" or "sell" from agent perspective
    counter_price: float
    quantity: int
    round_num: int


class GameSession:
    """All mutable game state for a single run."""

    def __init__(self, seed: int, time_budget: int, team_name: str = "") -> None:
        self.seed = seed
        self.time_budget = time_budget
        self.team_name = team_name
        self.time_consumed: int = 0
        self.game_clock: int = 0

        self.cash: float = 0.0
        self.inventory: dict[ItemName, int] = {}

        self.current_market: MarketName = MarketName.EXCHANGE
        self.markets_visited: set[MarketName] = set()
        self.successful_trades: int = 0
        self.below_market_buys: int = 0

        self.npcs: list[NPC] = []
        self.objectives: list[ActiveObjective] = []
        self.action_log: list[dict] = []
        self.pending_negotiations: dict[tuple[str, str], PendingNegotiation] = {}

        # Shock schedule: mechanical params pre-seeded, text generated on-demand
        self.shock_schedule: list[dict] = []
        # On-demand LLM content buffers
        self.available_news: list[dict] = []   # accumulates; never cleared
        self.available_buzz: list[dict] = []   # cleared after each get_buzz call
        self.buzz_log: list[dict] = []         # permanent history for dashboard
        self._pending_futures: list[tuple[str, Future, dict]] = []

        self.rng = random.Random(seed)
        self.price_engine = PriceEngine(seed)

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def time_remaining(self) -> int:
        return self.time_budget - self.time_consumed

    # ── NPC helpers ───────────────────────────────────────────────────────────

    def get_npcs_in_market(self, market: MarketName) -> list[NPC]:
        return [n for n in self.npcs if n.market == market]

    def get_npc_by_id(self, npc_id: str) -> Optional[NPC]:
        for n in self.npcs:
            if n.npc_id == npc_id:
                return n
        return None

    # ── Action logging ────────────────────────────────────────────────────────

    def log_action(self, action_type: str, details: dict, time_consumed: int) -> None:
        self.action_log.append({
            "timestamp": self.game_clock,
            "type": action_type,
            "details": details,
            "time_consumed": time_consumed,
        })

    # ── State updates ─────────────────────────────────────────────────────────

    def record_market_visit(self, market: MarketName) -> None:
        self.markets_visited.add(market)
        self._check_objectives()

    def record_trade(self, item: ItemName, price: float) -> None:
        self.successful_trades += 1
        market_rate = self.price_engine.get_market_rate(item)
        if price <= market_rate:
            self.below_market_buys += 1
        self._check_objectives()

    # ── LLM content helpers ───────────────────────────────────────────────────

    def collect_ready_content(self) -> None:
        """Drain completed LLM futures into available_news / available_buzz."""
        still_pending = []
        for kind, future, meta in self._pending_futures:
            if future.done():
                try:
                    result = future.result()
                    if kind == "news" and isinstance(result, dict) and result:
                        self.available_news.append({**meta, **result})
                    elif kind == "buzz" and isinstance(result, list):
                        self.available_buzz.extend(result)
                        self.buzz_log.extend(result)
                except Exception:
                    pass
            else:
                still_pending.append((kind, future, meta))
        self._pending_futures = still_pending

    # ── Scoring ───────────────────────────────────────────────────────────────

    def compute_bonus_points(self) -> float:
        self._check_objectives()
        # End-of-game inventory-based objectives
        for obj in self.objectives:
            if obj.completed:
                continue
            if obj.id == "bonus_collector":
                cats = {ITEM_CATALOG[item].category for item, qty in self.inventory.items() if qty > 0}
                if len(cats) >= 4:
                    obj.completed = True
            elif obj.id == "bonus_luxury":
                luxury = sum(qty for item, qty in self.inventory.items()
                             if ITEM_CATALOG[item].category == Category.LUXURY_LOCAL and qty > 0)
                if luxury >= 2:
                    obj.completed = True
            elif obj.id == "bonus_energy":
                energy = sum(qty for item, qty in self.inventory.items()
                             if ITEM_CATALOG[item].category == Category.ENERGY and qty > 0)
                if energy >= 3:
                    obj.completed = True
        return sum(obj.points for obj in self.objectives if obj.completed)

    def compute_item_worth(self) -> float:
        return sum(
            qty * self.price_engine.get_market_rate(item)
            for item, qty in self.inventory.items()
            if qty > 0
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _check_objectives(self) -> None:
        for obj in self.objectives:
            if obj.completed:
                continue
            if obj.id == "bonus_traveller" and len(self.markets_visited) >= 3:
                obj.completed = True
            elif obj.id == "bonus_trader" and self.successful_trades >= 10:
                obj.completed = True
            elif obj.id == "bonus_frugal" and self.below_market_buys >= 5:
                obj.completed = True


# ── Session factory ───────────────────────────────────────────────────────────

def build_starting_inventory(
    rng: random.Random,
    price_engine: PriceEngine,
) -> tuple[float, dict[ItemName, int]]:
    """
    Build a randomised starting inventory with total portfolio value ≈ TARGET.
    Cash is adjusted so that cash + item_value == _TARGET_START_VALUE.
    """
    for _ in range(50):  # retry loop in case cash < MIN_CASH
        n_items = rng.randint(2, 4)
        chosen = rng.sample(STARTING_ITEM_POOL, min(n_items, len(STARTING_ITEM_POOL)))
        inventory: dict[ItemName, int] = {}
        item_value = 0.0
        for item in chosen:
            qty = rng.randint(1, 4)
            inventory[item] = qty
            item_value += qty * ITEM_CATALOG[item].baseline_price

        cash = round(_TARGET_START_VALUE - item_value, 2)
        if cash >= _MIN_CASH:
            return cash, inventory

    # Fallback: cash-only start
    return _TARGET_START_VALUE, {}


def select_objectives(rng: random.Random) -> list[ActiveObjective]:
    chosen: list[BonusObjectiveDef] = rng.sample(BONUS_OBJECTIVE_POOL, _NUM_OBJECTIVES)
    return [ActiveObjective(id=o.id, description=o.description, points=o.points) for o in chosen]
