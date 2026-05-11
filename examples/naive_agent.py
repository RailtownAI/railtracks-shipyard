"""
Naive Trading Agent — Switchyard example
=========================================

This is the simplest possible agent that plays the Switchyard game.

Strategy:
  - Check the market dashboard and accept the first ask/bid prices it sees
  - No price negotiation — just post the NPC's listed price
  - Sell inventory items whenever it finds a buyer
  - Visit all three markets to earn the traveller bonus
  - Keep trading until the time budget runs out

Run this file directly:
    python examples/naive_agent.py

Set ANTHROPIC_API_KEY in your environment (or a .env file) before running.
"""

import json

import railtracks as rt

from railtracks_shipyard import GameDashboard, SwitchyardEngine


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a trading agent playing the Switchyard commodity market simulation.

GOAL: Maximise final score = cash + item net worth at your final market + bonus points.

═══════════════════════════════════════════════════════
PHASE 1 — OPENING (do this once, right at game start)
═══════════════════════════════════════════════════════
1. Call get_news. Identify which categories have bullish news (prices rising) and
   bearish news (prices falling). Write down your findings with share_progress.
2. Call get_historical_trends (no item argument — fetch all). Identify 2–3 items
   that were already trending upward before the game started. Prefer those for buying.
3. Call get_market_dashboard to see what is available right now.
4. Call get_buzz to hear what NPCs are saying. Note which items they mention.
5. Review your bonus_objectives from the game_start payload. Plan around them:
   - "visit_all_markets" → you MUST move to all three markets before time runs out.
   - "profit_10pct" / "profit_20pct" → track your starting total worth and aim to beat it.
   - "sell_luxury" → prioritise visiting black_market where luxury items appear.
   - "buy_energy" → visit frontier_post for Energy items.
   - "hold_X_items" → make sure you hold the right count at game end.
   - "no_rejections" → only offer at or above the ask / at or below the bid.
   Use share_progress to record your objective plan before you start trading.

═══════════════════════════════════════════════════════
PHASE 2 — TRADING LOOP (repeat until time runs low)
═══════════════════════════════════════════════════════
Each iteration, pick ONE of the following actions:

A) SELL first if you hold items and the dashboard shows a bid for them.
   → negotiate(npc_id, item, "sell", bid_price, quantity)
   → If outcome="counter", respond immediately with the counter_price.

B) BUY an item from a category that your news/trends analysis flagged as bullish.
   → negotiate(npc_id, item, "buy", ask_price, 1)
   → If outcome="counter", accept by calling negotiate again with action="respond".

C) MOVE to a market you haven't visited yet (required for visit_all_markets bonus
   and to access different item categories). After moving, call get_market_dashboard.

D) READ news or buzz again if significant time has passed (every ~50 time units).
   New news events fire during the game — catching them early is an edge.

Do NOT: call get_market_dashboard twice in a row without acting on it. Do NOT call
get_historical_trends more than once (it shows pre-game data that never changes).

═══════════════════════════════════════════════════════
PHASE 3 — ENDGAME (when time_remaining < 40)
═══════════════════════════════════════════════════════
1. Sell any items you don't want to hold — cash is always worth face value.
2. Make sure you're in the market with the best rates for items you are holding,
   because item net worth is calculated at your FINAL market when time runs out.
3. Call share_progress with a final summary of your score estimate.
4. Stop trading when time_remaining < 15 or you receive GAME_OVER.

═══════════════════════════════════════════════════════
PROGRESS LOGGING
═══════════════════════════════════════════════════════
Call share_progress freely — it costs zero game time. Use it to:
- Record your news/trend interpretation after the opening phase.
- Log each trade: item, price, quantity, and why.
- Note when you move markets and what objective that serves.
- Flag new news events and how they change your plan.
- Write a final summary when you stop.

═══════════════════════════════════════════════════════
HARD RULES
═══════════════════════════════════════════════════════
- proposed_price must always be > 0. quantity must always be >= 1.
- Only use npc_id values that appear in the CURRENT market's dashboard.
- After move_to_market, always call get_market_dashboard before trading.
- share_progress costs no time — use it freely.
""".strip()


# ── Main ──────────────────────────────────────────────────────────────────────

def main(seed: int | None = None, time_budget: int = 300) -> None:
    """Run one game with the naive agent."""

    # ── 1. Start the game and dashboard ──────────────────────────────────────
    engine = SwitchyardEngine()
    game_info = engine.new_game(seed=seed, time_budget=time_budget)

    dashboard = GameDashboard(engine)
    dashboard.start()

    # ── 2. Wrap every engine method as a railtracks tool ─────────────────────
    #
    # The @rt.function_node decorator turns a plain Python function into a
    # railtracks tool node. Type hints define the parameter schema; the
    # docstring (Args / Returns sections) is what the LLM reads.

    @rt.function_node
    def get_score() -> dict:
        """Return the current score: cash, item_worth, bonus_points, total_score.
        Returns:
            Envelope with data.cash, data.item_worth, data.bonus_points, data.total_score.
        """
        return engine.get_score()

    @rt.function_node
    def get_inventory() -> dict:
        """Return cash on hand and all items currently held.
        Returns:
            Envelope with data.cash and data.items (list of {name, quantity, current_market_rate}).
        """
        return engine.get_inventory()

    @rt.function_node
    def get_market_dashboard() -> dict:
        """Return all current asks and bids in your current market.
        Shows the aggregate market_rate per item plus each NPC's individual ask/bid price.
        Use this to find what NPCs are willing to buy and sell, and at what prices.
        Returns:
            Envelope with data.market and data.items (list of {name, market_rate, asks, bids}).
            asks: NPCs willing to sell to you. bids: NPCs willing to buy from you.
        """
        return engine.get_market_dashboard()

    @rt.function_node
    def get_historical_trends(item: str = "") -> dict:
        """Return pre-game price history for all items, or a single item if specified.
        Args:
            item: Optional item name (e.g. 'prairie_wheat'). Leave empty for all items.
        Returns:
            Envelope with data.items (list of {name, category, history: [{timestamp, price}]}).
        """
        return engine.get_historical_trends(item if item else None)

    @rt.function_node
    def get_news() -> dict:
        """Return recent news reports that have affected category prices.
        Reports are factually accurate but require interpretation to determine price direction.
        Returns:
            Envelope with data.reports (list of {timestamp, headline, body, affected_categories}).
        """
        return engine.get_news()

    @rt.function_node
    def get_buzz() -> dict:
        """Return recent NPC chatter from your current market.
        Reliability varies — some NPCs are honest, some deliberately mislead.
        Returns:
            Envelope with data.messages (list of {npc_id, message, timestamp}).
        """
        return engine.get_buzz()

    @rt.function_node
    def get_move_history() -> dict:
        """Return your own action log for this game session.
        Returns:
            Envelope with data.actions (list of {timestamp, type, details, time_consumed}).
        """
        return engine.get_move_history()

    @rt.function_node
    def get_time_remaining() -> dict:
        """Return the remaining time budget. Call this to decide when to stop trading.
        Returns:
            Envelope with data.time_remaining, data.time_total, data.time_consumed.
        """
        return engine.get_time_remaining()

    @rt.function_node
    def negotiate(npc_id: str, item: str, action: str, proposed_price: float, quantity: int) -> dict:
        """Negotiate with an NPC to buy or sell an item.
        Args:
            npc_id: NPC identifier shown on the market dashboard (e.g. 'npc_03').
            item: Item name to trade (e.g. 'prairie_wheat', 'gpu_chips', 'canola_oil').
            action: 'buy' to purchase from the NPC, 'sell' to sell to the NPC,
                    'respond' to accept or counter a counter-offer you received.
            proposed_price: Your price per unit (must be > 0).
                For a new negotiation: use the ask/bid price from the dashboard.
                To accept a counter-offer: set this to the counter_price from the previous response.
                To make a new counter: set this to any price between your offer and their counter.
            quantity: Number of units to trade (must be >= 1).
        Returns:
            Envelope with data.outcome ('accepted', 'rejected', or 'counter').
            If 'counter': data.counter_price and data.message are set — respond or walk away.
            If 'accepted': data.price and data.total_cost (buy) or data.total_proceeds (sell).
        """
        return engine.negotiate(npc_id, item, action, proposed_price, quantity)

    @rt.function_node
    def move_to_market(destination: str) -> dict:
        """Move to a different market. You can only trade in your current market.
        Markets: 'exchange' (stable, Agriculture & Tech), 'frontier_post' (volatile, Energy),
        'black_market' (high-risk, Luxury & rare Tech).
        Args:
            destination: One of 'exchange', 'frontier_post', or 'black_market'.
        Returns:
            Envelope with data.market, data.description, data.npcs_present, data.items_available.
        """
        return engine.move_to_market(destination)

    @rt.function_node
    def wait(duration: int) -> dict:
        """Wait for a specified number of time units. Prices move while you wait.
        Useful for timing entry after a news event. Costs exactly 'duration' time.
        Args:
            duration: Time units to wait (1–50).
        Returns:
            Envelope with data.time_consumed, data.time_remaining, data.market_summary.
        """
        return engine.wait(duration)
    

    # ── 3. Build the railtracks agent ─────────────────────────────────────────

    llm = rt.llm.OpenAILLM("gpt-4.1-mini")

    NaiveTrader = rt.agent_node(
        "Naive Trader",
        tool_nodes=[
            get_score,
            get_inventory,
            get_market_dashboard,
            get_historical_trends,
            get_news,
            get_buzz,
            get_move_history,
            get_time_remaining,
            negotiate,
            move_to_market,
            wait,
        ],
        llm=llm,
        system_message=SYSTEM_PROMPT,
    )


    flow = rt.Flow(
        name="Naive Trader Flow",
        entry_point=NaiveTrader,
    )

    # ── 4. Run the agent ──────────────────────────────────────────────────────
    initial_message = (
        "A new game of Switchyard has started. Here is your game information:\n\n"
        + json.dumps(game_info, indent=2)
        + "\n\nBegin trading. Use the tools to play the game."
    )
    try:
        flow.invoke(initial_message)
    finally:

        dashboard.stop()

        score = engine.final_score()
        print("\n" + "=" * 60)
        print("FINAL SCORE")
        print("=" * 60)
        print(f"Cash:          ${score['cash']:.2f}")
        print(f"Item worth:    ${score['item_worth']:.2f}")
        print(f"Bonus points:  ${score['bonus_points']:.2f}")
        print(f"TOTAL:         ${score['total_score']:.2f}")
        print()
        print("Objectives:")
        for obj in score["objectives"]:
            status = "✓" if obj["completed"] else "✗"
            print(f"  {status} {obj['description']} (+{obj['points']})")
        print("=" * 60)


if __name__ == "__main__":
    # Use seed=None for a random game, or seed=42 for a reproducible run.
    main(seed=None)
