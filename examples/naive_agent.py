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
import random
import railtracks as rt

from railtracks_shipyard import GameDashboard, SwitchyardEngine


# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT_DO_NOTHING = """
You are a trading agent playing the Switchyard commodity market simulation. You will use the wait tool to pass the time until the game ends. Do not attempt to buy or sell any items, or move to other markets. Your final score will be based on your starting cash and any bonus points from objectives."""
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
# you can customize the seed for consistent results during development
seed = random.randint(1, 2**31)
engine = SwitchyardEngine()

game_info = engine.new_game(seed=seed, team_name="Logan's Agent Almighty", track="code")

dashboard = GameDashboard(engine)
dashboard.start()


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

@rt.function_node
async def trader_flow(user_input: str) -> str:
    original_input = user_input
    new_input = original_input

    while get_time_remaining()["ok"]:
        result = await rt.call(NaiveTrader, new_input)
        new_input = f"""
Intial message: {original_input}
Agent response: {result.text}        
"""
    
    return new_input
    

flow = rt.Flow(
    name="Naive Trader Flow",
    entry_point=trader_flow,
)

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run one game with the naive agent."""
    

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

        score = engine.end_game()
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
    main()
