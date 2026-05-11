"""
Switchyard — Code Track Starter
=================================
This is your file. Change anything you like.

The only rules:
  - Do not modify anything under src/railtracks_shipyard/game_engine/
  - Your agent must use the tools defined below to interact with the game
  - Set TEAM_NAME before running

Run with:
    python competition/code_track/agent.py
"""
from __future__ import annotations

import json

import railtracks as rt
from railtracks_shipyard import GameDashboard, SwitchyardEngine


# ── Configuration ─────────────────────────────────────────────────────────────

TEAM_NAME = "My Team"           # Set this to your team name
MODEL     = "gpt-4.1-mini"     # Any OpenAI-compatible model
SEED      = None                # None = random. Set to COMPETITIVE_SEED for the ranked board.
TIME_BUDGET = 300


# ── System prompt ─────────────────────────────────────────────────────────────
#
# This is the baseline prompt. Improve it — or throw it away entirely and
# build something more sophisticated below in main().
#
# CHALLENGES (roughly in order of difficulty):
#
#   1. PROMPTING       Can you write a better strategy than this baseline?
#
#   2. PLANNING        Can the agent form an explicit plan at game start
#                      and refer back to it throughout the game?
#
#   3. SHORT-TERM      Can it learn within a single run? E.g. remember which
#      LEARNING        NPCs gave the best prices and prefer them next time.
#
#   4. LONG-TERM       Can it try different strategies across runs and converge
#      LEARNING        on the best one? Think RL-style: explore, evaluate, exploit.
#
#   5. CONTEXT         A long game fills the context window. Can you get the
#      COMPRESSION     agent to summarise its own history to stay efficient?

SYSTEM_PROMPT = """
You are a trading agent playing the Switchyard commodity market simulation.

GOAL: Maximise final score = cash + item net worth at your final market + bonus points.

═══════════════════════════════════════════════════════
PHASE 1 — OPENING (do this once, right at game start)
═══════════════════════════════════════════════════════
1. Call get_news. Identify which categories have bullish news (prices rising) and
   bearish news (prices falling).
2. Call get_historical_trends (no item argument — fetch all). Identify 2–3 items
   that were already trending upward before the game started.
3. Call get_market_dashboard to see what is available right now.
4. Call get_buzz to hear what NPCs are saying.
5. Review your bonus_objectives. Plan around them:
   - "visit_all_markets" → move to all three markets before time runs out.
   - "sell_luxury"       → prioritise black_market.
   - "buy_energy"        → visit frontier_post for Energy items.

═══════════════════════════════════════════════════════
PHASE 2 — TRADING LOOP (repeat until time runs low)
═══════════════════════════════════════════════════════
Each iteration, pick ONE action:

A) SELL first if you hold items and the dashboard shows a bid for them.
   → negotiate(npc_id, item, "sell", bid_price, quantity)
   → If outcome="counter", respond immediately with the counter_price.

B) BUY an item from a category your news/trends analysis flagged as bullish.
   → negotiate(npc_id, item, "buy", ask_price, 1)
   → If outcome="counter", accept by calling negotiate again with action="respond".

C) MOVE to a market you haven't visited (required for visit_all_markets bonus).
   After moving, call get_market_dashboard before trading.

D) READ news or buzz again if significant time has passed (every ~50 time units).

═══════════════════════════════════════════════════════
PHASE 3 — ENDGAME (when time_remaining < 40)
═══════════════════════════════════════════════════════
1. Sell items you don't want to hold — cash is always worth face value.
2. Move to the market with the best rates for items you are holding.
3. Stop trading when time_remaining < 15 or you receive GAME_OVER.

═══════════════════════════════════════════════════════
HARD RULES
═══════════════════════════════════════════════════════
- proposed_price must always be > 0. quantity must always be >= 1.
- Only use npc_id values that appear in the CURRENT market's dashboard.
- After move_to_market, always call get_market_dashboard before trading.
""".strip()


# ── Tools ─────────────────────────────────────────────────────────────────────
#
# These wrap the game engine API. You can add pre/post processing here,
# cache results, build your own abstractions on top — go wild.

def build_tools(engine: SwitchyardEngine) -> list:

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
            Envelope with data.market and data.items (list of {name, market_rate, asks, bids}).
            asks: NPCs willing to sell to you. bids: NPCs willing to buy from you.
        """
        return engine.get_market_dashboard()

    @rt.function_node
    def get_historical_trends(item: str = "") -> dict:
        """Return pre-game price trend summary for all items, or a single item if specified.
        Args:
            item: Optional item name (e.g. 'prairie_wheat'). Leave empty for all items.
        Returns:
            Envelope with data.items (list of {name, category, trend, start_price,
            current_price, min_price, max_price, recent}).
        """
        return engine.get_historical_trends(item if item else None)

    @rt.function_node
    def get_news() -> dict:
        """Return recent news reports that have affected category prices.
        Returns:
            Envelope with data.reports (list of {timestamp, headline, body, affected_categories}).
        """
        return engine.get_news()

    @rt.function_node
    def get_buzz() -> dict:
        """Return recent NPC chatter from your current market.
        Reliability varies — some NPCs are honest, some deliberately mislead.
        Returns:
            Envelope with data.messages (list of {npc_id, npc_name, message, timestamp}).
        """
        return engine.get_buzz()

    @rt.function_node
    def get_move_history() -> dict:
        """Return your recent action log (last 15 actions).
        Returns:
            Envelope with data.actions (list of {timestamp, type, details, time_consumed}).
        """
        return engine.get_move_history()

    @rt.function_node
    def get_time_remaining() -> dict:
        """Return the remaining time budget.
        Returns:
            Envelope with data.time_remaining, data.time_total, data.time_consumed.
        """
        return engine.get_time_remaining()

    @rt.function_node
    def negotiate(npc_id: str, item: str, action: str, proposed_price: float, quantity: int) -> dict:
        """Negotiate with an NPC to buy or sell an item.
        Args:
            npc_id: NPC identifier shown on the market dashboard (e.g. 'npc_03').
            item: Item name to trade (e.g. 'prairie_wheat').
            action: 'buy', 'sell', or 'respond' (to accept/counter a counter-offer).
            proposed_price: Your price per unit (must be > 0).
            quantity: Number of units (must be >= 1).
        Returns:
            Envelope with data.outcome ('accepted', 'rejected', or 'counter').
            If 'counter': data.counter_price is set — respond or walk away.
            If 'accepted': data.price and data.total_cost (buy) or data.total_proceeds (sell).
        """
        return engine.negotiate(npc_id, item, action, proposed_price, quantity)

    @rt.function_node
    def move_to_market(destination: str) -> dict:
        """Move to a different market. You can only trade in your current market.
        Markets: 'exchange' (Agriculture & Tech), 'frontier_post' (Energy),
                 'black_market' (Luxury & rare Tech).
        Args:
            destination: One of 'exchange', 'frontier_post', or 'black_market'.
        Returns:
            Envelope with data.market, data.npcs_present, data.items_available.
        """
        return engine.move_to_market(destination)

    @rt.function_node
    def wait(duration: int) -> dict:
        """Wait for a number of time units. Prices move while you wait.
        Args:
            duration: Time units to wait (1–50).
        Returns:
            Envelope with data.time_consumed, data.time_remaining, data.market_summary.
        """
        return engine.wait(duration)

    return [
        get_score, get_inventory, get_market_dashboard, get_historical_trends,
        get_news, get_buzz, get_move_history, get_time_remaining,
        negotiate, move_to_market, wait,
    ]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{'='*60}")
    print(f"  SWITCHYARD — CODE TRACK")
    print(f"  Team: {TEAM_NAME}  |  Model: {MODEL}  |  Seed: {SEED or 'random'}")
    print(f"{'='*60}\n")

    engine = SwitchyardEngine()
    game_info = engine.new_game(seed=SEED, time_budget=TIME_BUDGET, team_name=TEAM_NAME)
    actual_seed: int = game_info.get("seed", 0)

    if SEED is None:
        print(f"  Random seed this run: {actual_seed}")
    print()

    dashboard = GameDashboard(engine)
    dashboard.start()

    # Build tools and agent
    tools = build_tools(engine)

    llm = rt.llm.OpenAILLM(MODEL)

    agent = rt.agent_node(
        f"{TEAM_NAME} Agent",
        tool_nodes=tools,
        llm=llm,
        system_message=SYSTEM_PROMPT,
    )

    flow = rt.Flow(name=f"{TEAM_NAME} Flow", entry_point=agent)

    initial_message = (
        "A new game of Switchyard has started. Here is your starting information:\n\n"
        + json.dumps(game_info, indent=2)
        + "\n\nBegin trading. Use the tools available to you to maximise your final score."
    )

    try:
        flow.invoke(initial_message)
    finally:
        dashboard.stop()
        score = engine.final_score()

        print(f"\n{'='*60}")
        print(f"  FINAL SCORE — {TEAM_NAME}")
        print(f"{'='*60}")
        print(f"  Cash:         ${score['cash']:>10,.2f}")
        print(f"  Item worth:   ${score['item_worth']:>10,.2f}")
        print(f"  Bonus points: ${score['bonus_points']:>10,.2f}")
        print(f"  TOTAL:        ${score['total_score']:>10,.2f}")
        print()
        print("  Objectives:")
        for obj in score["objectives"]:
            status = "✓" if obj["completed"] else "✗"
            print(f"    {status} {obj['description']} (+{obj['points']})")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
