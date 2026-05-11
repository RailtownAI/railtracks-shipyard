from __future__ import annotations

import math
import random
from typing import Optional

from ._models import BASE_TIMESTAMP, Category, ItemConfig, ItemName, ITEM_CATALOG

# Number of ticks to simulate before game start for historical data
_WARMUP_TICKS = 60


class PriceEngine:
    """
    Stochastic price simulation.

    Each tick applies four components to every item's true value:
      1. Mean reversion  — pulls toward long-run baseline
      2. Cyclical drift  — slow sine oscillation over the game session
      3. Random walk     — Gaussian noise scaled by category volatility
      4. News shocks     — large temporary deviations that decay each tick

    The engine also records price history (every 5 ticks) for agents to query.
    """

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self.clock: int = 0
        self.true_values: dict[ItemName, float] = {}
        self.price_history: dict[ItemName, list[dict]] = {}
        self._active_shocks: dict[ItemName, list[tuple[float, float]]] = {}
        self._run_warmup()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _run_warmup(self) -> None:
        for name, config in ITEM_CATALOG.items():
            initial = config.baseline_price * (1.0 + self._rng.gauss(0, 0.04))
            initial = max(initial, config.baseline_price * 0.15)
            self.true_values[name] = initial
            self.price_history[name] = []
            self._active_shocks[name] = []

        # Simulate pre-game history so agents have trends to analyse
        for t in range(_WARMUP_TICKS):
            for name, config in ITEM_CATALOG.items():
                self._step(name, config, warmup_clock=t - _WARMUP_TICKS)

            if t % 5 == 0:
                ts = BASE_TIMESTAMP + (t - _WARMUP_TICKS) * 60
                for name in ITEM_CATALOG:
                    self.price_history[name].append(
                        {"timestamp": ts, "price": round(self.true_values[name], 2)}
                    )

        self.clock = 0

    # ── Public interface ──────────────────────────────────────────────────────

    def advance(self, ticks: int) -> None:
        """Advance the game clock by `ticks` units, updating all prices."""
        for _ in range(ticks):
            self.clock += 1
            for name, config in ITEM_CATALOG.items():
                self._step(name, config, warmup_clock=None)
            if self.clock % 5 == 0:
                ts = BASE_TIMESTAMP + self.clock * 60
                for name in ITEM_CATALOG:
                    self.price_history[name].append(
                        {"timestamp": ts, "price": round(self.true_values[name], 2)}
                    )

    def apply_shock(
        self,
        categories: list[Category],
        direction: float,       # +1 = bullish, -1 = bearish
        magnitude_pct: float,   # fraction of baseline, e.g. 0.10
        decay_rate: float = 0.08,
    ) -> None:
        """Apply a news-driven price shock to all items in the affected categories."""
        for name, config in ITEM_CATALOG.items():
            if config.category in categories:
                mag = (
                    config.baseline_price
                    * magnitude_pct
                    * direction
                    * config.news_sensitivity
                )
                self._active_shocks[name].append((mag, decay_rate))

    def apply_demand_pressure(self, item: ItemName, units: int) -> None:
        """Buying `units` of `item` nudges its price upward."""
        config = ITEM_CATALOG[item]
        mag = config.baseline_price * 0.004 * units
        self._active_shocks[item].append((mag, 0.20))

    def apply_supply_pressure(self, item: ItemName, units: int) -> None:
        """Selling `units` of `item` nudges its price downward."""
        config = ITEM_CATALOG[item]
        mag = -config.baseline_price * 0.004 * units
        self._active_shocks[item].append((mag, 0.20))

    def get_market_rate(self, item: ItemName) -> float:
        return round(self.true_values[item], 2)

    def get_all_rates(self) -> dict[ItemName, float]:
        return {name: round(v, 2) for name, v in self.true_values.items()}

    def get_history(self, item: Optional[ItemName] = None) -> list[dict]:
        if item is not None:
            return list(self.price_history.get(item, []))
        return list(self.price_history.values())

    # ── Internal mechanics ────────────────────────────────────────────────────

    def _step(self, name: ItemName, config: ItemConfig, warmup_clock: Optional[int]) -> None:
        clock = warmup_clock if warmup_clock is not None else self.clock
        v = self.true_values[name]

        # 1. Mean reversion
        mean_rev = config.mean_reversion_speed * (config.baseline_price - v)

        # 2. Cyclical component — period ≈ 200 ticks
        amplitude = config.baseline_price * 0.04
        cycle = amplitude * math.sin(2 * math.pi * clock / 200)

        # 3. Random walk
        dw = self._rng.gauss(0, config.volatility * config.baseline_price)

        # 4. Decaying news shocks
        shock_total = 0.0
        surviving: list[tuple[float, float]] = []
        for magnitude, decay in self._active_shocks[name]:
            shock_total += magnitude
            remaining = magnitude * (1.0 - decay)
            if abs(remaining) > config.baseline_price * 0.003:
                surviving.append((remaining, decay))
        self._active_shocks[name] = surviving

        new_v = v + mean_rev + cycle + dw + shock_total
        new_v = max(new_v, config.baseline_price * 0.15)
        self.true_values[name] = new_v
