"""
Switchyard Game Engine — public API.

Usage:
    from railtracks_shipyard import SwitchyardEngine

    engine = SwitchyardEngine()
    game_start = engine.new_game()          # random seed (test mode)
    game_start = engine.new_game(seed=42)   # fixed seed (competition mode)

    result = engine.get_inventory()
    result = engine.negotiate("npc_01", "prairie_wheat", "buy", 21.0, 3)
    ...
"""
from __future__ import annotations

import json
import os
import random
import threading
import urllib.error
import urllib.request
from typing import Literal, Optional

_DATA_ADDRESS = os.getenv("LEADERBOARD_URL", "http://localhost:8000/api/submit")

from ._models import (
    Category,
    MARKET_DESCRIPTIONS,
    MARKET_PRIMARY_CATEGORIES,
    ITEM_CATALOG,
    ItemName,
    MarketName,
)
from ._npc import create_npcs
from ._session import GameSession, build_starting_inventory, select_objectives
from ._tools import (
    get_buzz,
    get_historical_trends,
    get_inventory,
    get_market_dashboard,
    get_move_history,
    get_news,
    get_score,
    get_time_remaining,
    move_to_market,
    negotiate,
    wait,
)


def _post_score(score: dict) -> None:
    """Fire-and-forget leaderboard submission. Never raises."""
    url = _DATA_ADDRESS
    if not score.get("track"):
        return
    payload = json.dumps({
        "team_name":     str(score.get("team_name") or "unnamed"),
        "seed":          int(score.get("seed") or 0),
        "track":         score["track"],
        "cash":          float(score.get("cash") or 0),
        "item_worth":    float(score.get("item_worth") or 0),
        "bonus_points":  float(score.get("bonus_points") or 0),
        "total_score":   float(score.get("total_score") or 0),
        "time_consumed": int(score.get("time_consumed") or 0),
        "time_budget":   int(score.get("time_budget") or 300),
    }).encode()
    try:
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
        print("  ✓ Score posted to leaderboard.")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"  ✗ Server rejected submission ({e.code}): {body}")
    except Exception as e:
        print(f"  ✗ Leaderboard unreachable — score not posted: {e}")


def _build_shock_schedule(seed: int, time_budget: int, num_events: int = 30) -> list[dict]:
    """Pre-compute mechanical shock params using seeded RNG. No LLM calls."""
    rng = random.Random(seed + 1)
    event_count = min(num_events, max(0, time_budget - 40))
    if event_count <= 0:
        return []
    fire_times = sorted(rng.sample(range(20, time_budget - 20), event_count))
    shocks = []
    for t in fire_times:
        cat = rng.choice(list(Category))
        direction = rng.choice([1.0, -1.0])
        magnitude = round(rng.uniform(0.06, 0.22), 3)
        shocks.append({
            "game_time": t,
            "affected_categories": [cat.value],
            "direction": direction,
            "magnitude_pct": magnitude,
        })
    return shocks


class SwitchyardEngine:
    """
    Entry point for the Switchyard market simulation.

    One instance holds one game session. Call new_game() to (re-)initialise.
    All tool methods return the standard response envelope:
      { ok, time_consumed, time_remaining, data | error }
    """

    def __init__(self) -> None:
        self._session: Optional[GameSession] = None

    # ── Game initialisation ───────────────────────────────────────────────────

    def new_game(
        self,
        seed: Optional[int] = None,
        time_budget: int = 300,
        team_name: str = "",
        track: Literal["code", "prompt"] = "code",
    ) -> dict:
        """
        Initialise a new game session and return the game_start payload.

        Args:
            seed: RNG seed. None = random (test mode). Fixed value = competition mode.
            time_budget: Total time units available to the agent.
            team_name: Optional team name for leaderboard submission.
            track: "code" or "prompt" — for leaderboard categorisation.
        Returns:
            Structured game_start payload delivered to the agent before any actions.
        """
        if seed is None:
            seed = random.randint(0, 2**31)

        print(f"[new_game] seed={seed}  time_budget={time_budget}")

        print("[new_game] Initialising game session and price engine...")
        session = GameSession(seed=seed, time_budget=time_budget, team_name=team_name, track=track)

        # Randomise starting market
        session.current_market = session.rng.choice(list(MarketName))
        session.record_market_visit(session.current_market)
        print(f"[new_game] Starting market: {session.current_market.value}")

        # Create NPCs and initialise their prices
        print("[new_game] Creating NPCs...")
        npcs = create_npcs(seed)
        session.npcs = npcs
        rates = session.price_engine.get_all_rates()
        for npc in npcs:
            npc.refresh_prices(rates, session.rng)
        print(f"[new_game] {len(npcs)} NPCs created and priced")

        # Randomised starting inventory
        print("[new_game] Building starting inventory...")
        session.cash, session.inventory = build_starting_inventory(session.rng, session.price_engine)
        item_count = sum(session.inventory.values())
        print(f"[new_game] Inventory ready — ${session.cash:.2f} cash, {item_count} item units")

        # Bonus objectives
        session.objectives = select_objectives(session.rng)
        print(f"[new_game] Objectives: {[o.id for o in session.objectives]}")

        # Pre-compute shock schedule (timing + magnitude only — text generated on demand)
        session.shock_schedule = _build_shock_schedule(seed, time_budget)
        print(f"[new_game] {len(session.shock_schedule)} price shocks scheduled"
              f" (news text generated on demand when each fires)")

        print("[new_game] Game ready.\n")
        self._session = session

        # Build the initialization payload
        market_info = {
            name.value: {
                "description": MARKET_DESCRIPTIONS[name],
                "primary_categories": [c.value for c in MARKET_PRIMARY_CATEGORIES[name]],
            }
            for name in MarketName
        }

        starting_items = [
            {
                "name": item.value,
                "quantity": qty,
            }
            for item, qty in session.inventory.items()
            if qty > 0
        ]

        npcs_in_market = [
            {"npc_id": n.npc_id, "name": n.name, "current_market": n.market.value}
            for n in npcs
        ]

        return {
            "event": "game_start",
            "rules": {
                "time_budget": time_budget,
                "scoring": "cash + item_net_worth + bonus_points",
                "item_net_worth_basis": "market rate at game end in agent's final market",
                "markets": [m.value for m in MarketName],
            },
            "starting_inventory": {
                "cash": round(session.cash, 2),
                "items": starting_items,
            },
            "starting_market": session.current_market.value,
            "bonus_objectives": [
                {"id": o.id, "description": o.description, "points": o.points}
                for o in session.objectives
            ],
            "markets": market_info,
            "npcs": npcs_in_market,
        }

    # ── Guard helper ──────────────────────────────────────────────────────────
    def _require_session(self) -> GameSession:
        if self._session is None:
            raise RuntimeError("No active game. Call new_game() first.")
        return self._session

    # ── State tools ───────────────────────────────────────────────────────────

    def get_score(self) -> dict:
        return get_score(self._require_session())

    def get_inventory(self) -> dict:
        return get_inventory(self._require_session())

    def get_market_dashboard(self) -> dict:
        return get_market_dashboard(self._require_session())

    def get_historical_trends(self, item: Optional[str] = None) -> dict:
        return get_historical_trends(self._require_session(), item)

    def get_news(self) -> dict:
        return get_news(self._require_session())

    def get_buzz(self) -> dict:
        return get_buzz(self._require_session())

    def get_move_history(self) -> dict:
        return get_move_history(self._require_session())

    def get_time_remaining(self) -> dict:
        return get_time_remaining(self._require_session())

    # ── Action tools ──────────────────────────────────────────────────────────

    def negotiate(
        self,
        npc_id: str,
        item: str,
        action: str,
        proposed_price: float,
        quantity: int,
    ) -> dict:
        return negotiate(self._require_session(), npc_id, item, action, proposed_price, quantity)

    def move_to_market(self, destination: str) -> dict:
        return move_to_market(self._require_session(), destination)

    def wait(self, duration: int) -> dict:
        return wait(self._require_session(), duration)

    # ── Scoring helper (called at game end) ───────────────────────────────────

    def end_game(self) -> dict:
        """
        Compute and return the final score. Intended for game-end use.
        Does not consume time.
        """
        session = self._require_session()
        item_worth = round(session.compute_item_worth(), 2)
        bonus = round(session.compute_bonus_points(), 2)
        cash = round(session.cash, 2)
        score = {
            "cash": cash,
            "item_worth": item_worth,
            "bonus_points": bonus,
            "total_score": round(cash + item_worth + bonus, 2),
            "time_consumed": session.time_consumed,
            "time_budget": session.time_budget,
            "seed": session.seed,
            "team_name": session.team_name,
            "track": session.track,
            "objectives": [
                {"id": o.id, "description": o.description,
                 "points": o.points, "completed": o.completed}
                for o in session.objectives
            ],
        }
        _post_score(score,)
        return score
    

        


# Alias kept for backwards-compatibility with the scaffold
GameEngine = SwitchyardEngine
