"""
Switchyard — Code Track
========================
This is your file. Change anything you like.

Rules:
  - Do not modify anything under src/railtracks_shipyard/game_engine/
  - OPENAI_API_KEY must be set in your environment or a .env file

Run:
    python competition/code_track/agent.py
"""
from __future__ import annotations

import json

import railtracks as rt
from railtracks_shipyard import GameDashboard, SwitchyardEngine


# ── Config ────────────────────────────────────────────────────────────────────

TEAM_NAME   = "My Team"       # shown on the leaderboard
MODEL       = "gpt-4.1-mini"  # any OpenAI-compatible model
SEED        = None             # None = random  |  42 = competitive entry
TIME_BUDGET = 300


# ── System prompt ─────────────────────────────────────────────────────────────
#
# The baseline below is a starting point. Improving it is the whole game.
#
# Things worth trying (roughly in order of difficulty):
#   1. Better strategy instructions
#   2. Explicit planning before the first trade
#   3. Tracking which NPCs gave good prices and preferring them
#   4. Multi-run strategy that evolves across games
#   5. Context compression so late-game reasoning stays sharp

SYSTEM_PROMPT = """
You are a trading agent in Switchyard, a commodity market simulation.
GOAL: maximise cash + item net worth at your final market + bonus points.

━━━ TURN STRUCTURE — FOLLOW EXACTLY ━━━
Each turn has exactly two steps:
  1. Call ONE tool.
  2. Write the handoff block below. Then stop. Do not call another tool.

Your turn ends the moment you finish writing the handoff block.
Do NOT call a second tool "just to confirm" or "to get started on the next step."
A second tool call in the same turn is an error.

Another agent reads your handoff and continues. You will not see what happens next.
Do not explain what you are about to do — just call the tool and write the handoff.
Do not restate tool results — extract only what changes your plan.

━━━ HANDOFF BLOCK (write this after every tool call, then stop) ━━━

  NEXT: <tool> — <one-line reason>
  STATE: <market> | $<cash> | <item×qty …or "none"> | <time> left
  EDGE: <one sentence — the sharpest insight driving your current strategy>

Under 40 words total. This block ends your turn — nothing comes after it.

━━━ OPENING SEQUENCE (steps, not loops — do each once) ━━━
1. get_news          → which categories are bullish / bearish
2. get_historical_trends (no arg) → 2-3 rising items to target
3. get_market_dashboard  → best immediate buy or sell
4. get_buzz          → any tips worth acting on
After step 4, write a single PLAN line summarising your trade targets and
any objectives that constrain routing (visit_all_markets, sell_luxury, etc.).

━━━ TRADING ━━━
Priority order each turn:
  1. Sell held items if dashboard shows a bid  (action="sell")
  2. Buy a bullish-category item at ask price  (action="buy")
  3. Move to an unvisited market if needed for objectives or better rates
  4. Read news/buzz if ~50 time units have passed since last read
Counter-offers: always respond with action="respond" and the counter_price.
get_historical_trends never changes — call it once only.

━━━ ENDGAME (time < 40) ━━━
Sell anything you don't want held. Move to the market with the best rate for
your held items — net worth is calculated at your FINAL market. Stop at time < 15.

━━━ RULES ━━━
- proposed_price > 0 · quantity ≥ 1
- Only use npc_id values from the CURRENT market dashboard
- After move_to_market, call get_market_dashboard before trading
""".strip()


# ── Game setup ────────────────────────────────────────────────────────────────

engine    = SwitchyardEngine()
game_info = engine.new_game(seed=SEED, time_budget=TIME_BUDGET, team_name=TEAM_NAME, track="code")

dashboard = GameDashboard(engine)
dashboard.start()


# ── Tools ─────────────────────────────────────────────────────────────────────

@rt.function_node
def get_score() -> dict:
    """Return current score: cash, item_worth, bonus_points, total_score."""
    return engine.get_score()

@rt.function_node
def get_inventory() -> dict:
    """Return cash on hand and all items currently held."""
    return engine.get_inventory()

@rt.function_node
def get_market_dashboard() -> dict:
    """Return all current asks and bids in your current market.
    Returns:
        data.market and data.items (list of {name, market_rate, asks, bids}).
        asks: NPCs willing to sell to you. bids: NPCs willing to buy from you.
    """
    return engine.get_market_dashboard()

@rt.function_node
def get_historical_trends(item: str = "") -> dict:
    """Return pre-game price trend summary. Call once with no argument for all items.
    Args:
        item: Optional item name (e.g. 'prairie_wheat'). Empty = all items.
    Returns:
        data.items (list of {name, category, trend, start_price, current_price}).
    """
    return engine.get_historical_trends(item if item else None)

@rt.function_node
def get_news() -> dict:
    """Return news reports that have moved category prices.
    Returns:
        data.reports (list of {timestamp, headline, body, affected_categories}).
    """
    return engine.get_news()

@rt.function_node
def get_buzz() -> dict:
    """Return NPC chatter from your current market. Reliability varies.
    Returns:
        data.messages (list of {npc_id, npc_name, message, timestamp}).
    """
    return engine.get_buzz()

@rt.function_node
def get_move_history() -> dict:
    """Return your last 15 actions.
    Returns:
        data.actions (list of {timestamp, type, details, time_consumed}).
    """
    return engine.get_move_history()

@rt.function_node
def get_time_remaining() -> dict:
    """Return remaining time budget.
    Returns:
        data.time_remaining, data.time_total, data.time_consumed.
    """
    return engine.get_time_remaining()

@rt.function_node
def negotiate(npc_id: str, item: str, action: str, proposed_price: float, quantity: int) -> dict:
    """Negotiate with an NPC to buy or sell an item.
    Args:
        npc_id: NPC identifier from the market dashboard (e.g. 'npc_03').
        item: Item name (e.g. 'prairie_wheat').
        action: 'buy', 'sell', or 'respond' (to answer a counter-offer).
        proposed_price: Your price per unit (must be > 0).
        quantity: Number of units (must be >= 1).
    Returns:
        data.outcome ('accepted', 'rejected', or 'counter').
        If 'counter': data.counter_price — respond with action='respond'.
        If 'accepted': data.total_cost (buy) or data.total_proceeds (sell).
    """
    return engine.negotiate(npc_id, item, action, proposed_price, quantity)

@rt.function_node
def move_to_market(destination: str) -> dict:
    """Move to a different market. You can only trade in your current market.
    Args:
        destination: 'exchange', 'frontier_post', or 'black_market'.
    Returns:
        data.market, data.npcs_present, data.items_available.
    """
    return engine.move_to_market(destination)

@rt.function_node
def wait(duration: int) -> dict:
    """Wait N time units. Prices move while you wait.
    Args:
        duration: 1–50 time units.
    Returns:
        data.time_consumed, data.time_remaining, data.market_summary.
    """
    return engine.wait(duration)


# ── Agent ─────────────────────────────────────────────────────────────────────

agent = rt.agent_node(
    f"{TEAM_NAME} Agent",
    tool_nodes=[
        get_score, get_inventory, get_market_dashboard, get_historical_trends,
        get_news, get_buzz, get_move_history, get_time_remaining,
        negotiate, move_to_market, wait,
    ],
    llm=rt.llm.OpenAILLM(MODEL),
    system_message=SYSTEM_PROMPT,
)

flow = rt.Flow(name=f"{TEAM_NAME} Flow", entry_point=agent)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    initial_message = (
        "A new Switchyard game has started. Your starting state:\n\n"
        + json.dumps(game_info, indent=2)
        + "\n\nBegin trading."
    )

    try:
        flow.invoke(initial_message)
    finally:
        dashboard.stop()
        score = engine.end_game()

        print(f"\n{'='*60}")
        print(f"  FINAL SCORE — {TEAM_NAME}")
        print(f"{'='*60}")
        print(f"  Cash:         ${score['cash']:>10,.2f}")
        print(f"  Item worth:   ${score['item_worth']:>10,.2f}")
        print(f"  Bonus points: ${score['bonus_points']:>10,.2f}")
        print(f"  TOTAL:        ${score['total_score']:>10,.2f}")
        print()
        for obj in score["objectives"]:
            status = "✓" if obj["completed"] else "✗"
            print(f"  {status} {obj['description']} (+{obj['points']})")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
