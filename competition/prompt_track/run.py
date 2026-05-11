"""
Switchyard — Prompt Track Runner
=================================
Loads config.yaml and runs a game. Do not modify this file.
Edit config.yaml instead.
"""
from __future__ import annotations

import json

import yaml  # type: ignore

import railtracks as rt
from railtracks_shipyard import GameDashboard, SwitchyardEngine



def main() -> None:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    team_name: str = cfg.get("team_name", "unnamed")
    model: str = cfg.get("model", "gpt-4.1-mini")
    seed: int | None = cfg.get("seed")
    time_budget: int = cfg.get("time_budget", 300)
    system_prompt: str = cfg["system_prompt"].strip()
    initial_message_template: str = cfg.get(
        "initial_message",
        "A new game of Switchyard has started.\n\n{game_info}\n\nBegin trading.",
    ).strip()

    print(f"\n{'='*60}")
    print(f"  SWITCHYARD — PROMPT TRACK")
    print(f"  Team: {team_name}  |  Model: {model}  |  Seed: {seed or 'random'}")
    print(f"{'='*60}\n")

    # ── Start game ────────────────────────────────────────────────────────────
    engine = SwitchyardEngine()
    game_info = engine.new_game(seed=seed, time_budget=time_budget, team_name=team_name)
    actual_seed: int = game_info.get("seed", 0)

    if seed is None:
        print(f"  Random seed this run: {actual_seed}")
    print()

    dashboard = GameDashboard(engine)
    dashboard.start()

    # ── Wire tools (do not modify) ────────────────────────────────────────────

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
        """
        return engine.negotiate(npc_id, item, action, proposed_price, quantity)

    @rt.function_node
    def move_to_market(destination: str) -> dict:
        """Move to a different market.
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

    # ── Build agent ───────────────────────────────────────────────────────────
    llm = rt.llm.OpenAILLM(model)

    agent = rt.agent_node(
        f"{team_name} Agent",
        tool_nodes=[
            get_score, get_inventory, get_market_dashboard, get_historical_trends,
            get_news, get_buzz, get_move_history, get_time_remaining,
            negotiate, move_to_market, wait,
        ],
        llm=llm,
        system_message=system_prompt,
    )

    flow = rt.Flow(name=f"{team_name} Flow", entry_point=agent)

    # ── Run ───────────────────────────────────────────────────────────────────
    initial_message = initial_message_template.replace(
        "{game_info}", json.dumps(game_info, indent=2)
    )

    try:
        flow.invoke(initial_message)
    finally:
        dashboard.stop()
        score = engine.final_score()

        print(f"\n{'='*60}")
        print(f"  FINAL SCORE — {team_name}")
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
