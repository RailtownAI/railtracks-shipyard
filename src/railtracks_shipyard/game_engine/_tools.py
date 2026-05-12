"""
All tool implementations for the Switchyard game engine.

Each function receives a GameSession and returns a plain dict in the response
envelope format:
  { ok, time_consumed, time_remaining, data }   on success
  { ok, time_consumed, time_remaining, error }  on failure

Failed calls consume no time (except negotiate, which charges for rounds played).
"""
from __future__ import annotations

import random
from typing import Optional

from ._llm import generate_buzz_async, generate_news_async
from ._models import (
    BASE_TIMESTAMP,
    Category,
    ErrorCode,
    ITEM_CATALOG,
    ItemName,
    MARKET_PRIMARY_CATEGORIES,
    MarketName,
)
from ._npc import negotiate_round_for_item
from ._session import GameSession, PendingNegotiation



# ── Response helpers ──────────────────────────────────────────────────────────

def _ok(session: GameSession, data: dict, time_consumed: int) -> dict:
    return {
        "ok": True,
        "time_consumed": time_consumed,
        "time_remaining": session.time_remaining,
        "data": data,
    }


def _error(session: GameSession, code: ErrorCode, message: str, time_consumed: int = 0) -> dict:
    return {
        "ok": False,
        "time_consumed": time_consumed,
        "time_remaining": session.time_remaining,
        "error": {"code": code.value, "message": message},
    }


def _game_over(session: GameSession) -> dict:
    return _error(session, ErrorCode.GAME_OVER, "Time budget exhausted.", 0)


# ── Time advancement ──────────────────────────────────────────────────────────

def _consume_time(session: GameSession, low: int, high: int) -> int:
    """Roll a time cost, advance clocks and prices, fire shocks and trigger LLM content."""
    base = session.rng.randint(low, high)
    variance = session.rng.uniform(0.80, 1.20)
    cost = max(1, round(base * variance))
    cost = min(cost, session.time_remaining)

    old_clock = session.game_clock
    session.time_consumed += cost
    session.game_clock += cost

    session.price_engine.advance(cost)

    # Apply mechanical shocks and kick off background news-text generation
    for shock in session.shock_schedule:
        if old_clock < shock["game_time"] <= session.game_clock:
            cats = [Category(c) for c in shock["affected_categories"]]
            session.price_engine.apply_shock(cats, shock["direction"], shock["magnitude_pct"])
            meta = {
                "game_time": shock["game_time"],
                "affected_categories": shock["affected_categories"],
            }
            future = generate_news_async(cats[0], shock["direction"], shock["magnitude_pct"])
            session._pending_futures.append(("news", future, meta))

    # Refresh NPC cached prices
    rates = session.price_engine.get_all_rates()
    for npc in session.npcs:
        npc.refresh_prices(rates, session.rng)

    # Pre-computed buzz schedule
    for buzz_event in session.buzz_schedule:
        if old_clock < buzz_event["game_time"] <= session.game_clock:
            future = generate_buzz_async(
                session.current_market, session.npcs, rates,
                buzz_event["buzz_seed"], session.game_clock,
            )
            session._pending_futures.append(("buzz", future, {}))

    # Drain any completed LLM futures so the dashboard always sees fresh content
    session.collect_ready_content()

    return cost


# ── State tools ───────────────────────────────────────────────────────────────

def get_score(session: GameSession) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    cost = _consume_time(session, 1, 2)
    item_worth = round(session.compute_item_worth(), 2)
    bonus = round(session.compute_bonus_points(), 2)
    cash = round(session.cash, 2)
    total = round(cash + item_worth + bonus, 2)

    session.log_action("get_score", {}, cost)
    return _ok(session, {
        "cash": cash,
        "item_worth": item_worth,
        "bonus_points": bonus,
        "total_score": total,
    }, cost)


def get_inventory(session: GameSession) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    cost = _consume_time(session, 1, 2)
    items = [
        {
            "name": item.value,
            "quantity": qty,
            "current_market_rate": session.price_engine.get_market_rate(item),
        }
        for item, qty in session.inventory.items()
        if qty > 0
    ]
    session.log_action("get_inventory", {}, cost)
    return _ok(session, {"cash": round(session.cash, 2), "items": items}, cost)


def get_market_dashboard(session: GameSession) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    cost = _consume_time(session, 3, 5)
    market_npcs = session.get_npcs_in_market(session.current_market)

    items_map: dict[str, dict] = {}

    for npc in market_npcs:
        # Asks: items the NPC holds
        for item, qty in npc.inventory.items():
            if qty <= 0:
                continue
            ask = npc.get_ask(item)
            if ask <= 0:
                continue
            key = item.value
            if key not in items_map:
                items_map[key] = {
                    "name": key,
                    "category": ITEM_CATALOG[item].category.value,
                    "market_rate": session.price_engine.get_market_rate(item),
                    "asks": [],
                    "bids": [],
                }
            items_map[key]["asks"].append({"npc_id": npc.npc_id, "price": ask, "quantity": qty})

        # Bids: items the NPC wants to buy
        for item in npc.wanted_items:
            bid = npc.get_bid(item)
            if bid <= 0:
                continue
            key = item.value
            if key not in items_map:
                items_map[key] = {
                    "name": key,
                    "category": ITEM_CATALOG[item].category.value,
                    "market_rate": session.price_engine.get_market_rate(item),
                    "asks": [],
                    "bids": [],
                }
            items_map[key]["bids"].append({"npc_id": npc.npc_id, "price": bid, "quantity": 10})

    # Keep only the 3 best-priced offers per item to limit response size
    for entry in items_map.values():
        entry["asks"] = sorted(entry["asks"], key=lambda x: x["price"])[:3]
        entry["bids"] = sorted(entry["bids"], key=lambda x: -x["price"])[:3]

    session.log_action("get_market_dashboard", {"market": session.current_market.value}, cost)
    return _ok(session, {
        "market": session.current_market.value,
        "items": list(items_map.values()),
    }, cost)


def get_historical_trends(session: GameSession, item_name: Optional[str] = None) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    item: Optional[ItemName] = None
    if item_name is not None:
        try:
            item = ItemName(item_name)
        except ValueError:
            return _error(session, ErrorCode.INVALID_ITEM, f"Unknown item: {item_name!r}")

    cost = _consume_time(session, 3, 5)

    def _summarise(name: ItemName) -> dict:
        history = session.price_engine.get_history(name)
        prices = [h["price"] for h in history]
        if prices:
            start_p = prices[0]
            current_p = prices[-1]
            delta = current_p - start_p
            pct = delta / start_p if start_p else 0
            trend = "rising" if pct > 0.03 else "falling" if pct < -0.03 else "flat"
        else:
            start_p = current_p = session.price_engine.get_market_rate(name)
            trend = "flat"
            prices = [current_p]
        return {
            "name": name.value,
            "category": ITEM_CATALOG[name].category.value,
            "trend": trend,
            "start_price": round(start_p, 2),
            "current_price": round(current_p, 2),
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "recent": history[-5:],
        }

    if item is not None:
        items_out = [_summarise(item)]
    else:
        items_out = [_summarise(name) for name in ItemName]

    session.log_action("get_historical_trends", {"item": item_name}, cost)
    return _ok(session, {"items": items_out}, cost)


def get_news(session: GameSession) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    cost = _consume_time(session, 3, 5)
    session.collect_ready_content()
    reports = [
        {
            "timestamp": BASE_TIMESTAMP + e["game_time"] * 60,
            "headline": e["headline"],
            "body": e["body"],
            "affected_categories": e["affected_categories"],
        }
        for e in session.available_news[-8:]
    ]
    session.log_action("get_news", {}, cost)
    return _ok(session, {"reports": reports}, cost)


def get_buzz(session: GameSession) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    cost = _consume_time(session, 3, 5)
    session.collect_ready_content()
    messages = [
        {
            "npc_id": m["npc_id"],
            "npc_name": m.get("npc_name", m["npc_id"]),
            "message": m["message"],
            "timestamp": BASE_TIMESTAMP + m["game_time"] * 60,
        }
        for m in session.available_buzz
    ]
    session.available_buzz.clear()
    session.log_action("get_buzz", {}, cost)
    return _ok(session, {"messages": messages}, cost)


def get_move_history(session: GameSession) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    cost = _consume_time(session, 1, 2)
    actions = [
        {
            "timestamp": BASE_TIMESTAMP + a["timestamp"] * 60,
            "type": a["type"],
            "details": a["details"],
            "time_consumed": a["time_consumed"],
        }
        for a in session.action_log[-15:]
    ]
    session.log_action("get_move_history", {}, cost)
    return _ok(session, {"actions": actions}, cost)


def get_time_remaining(session: GameSession) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    cost = 0
    session.log_action("get_time_remaining", {}, cost)
    return _ok(session, {
        "time_remaining": session.time_remaining,
        "time_total": session.time_budget,
        "time_consumed": session.time_consumed,
    }, cost)


# ── Action tools ──────────────────────────────────────────────────────────────

def negotiate(
    session: GameSession,
    npc_id: str,
    item_name: str,
    action: str,
    proposed_price: float,
    quantity: int,
) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    # ── Input validation (no time consumed on error) ──────────────────────────
    if action not in ("buy", "sell", "respond"):
        return _error(session, ErrorCode.INVALID_ITEM,
                      f"action must be 'buy', 'sell', or 'respond'.")

    if proposed_price <= 0:
        return _error(session, ErrorCode.INVALID_PRICE, "price must be > 0.")

    if quantity < 1:
        return _error(session, ErrorCode.INVALID_QUANTITY, "quantity must be >= 1.")

    try:
        item = ItemName(item_name)
    except ValueError:
        return _error(session, ErrorCode.INVALID_ITEM, f"Unknown item: {item_name!r}")

    npc = session.get_npc_by_id(npc_id)
    if npc is None:
        return _error(session, ErrorCode.INVALID_NPC, f"NPC '{npc_id}' not found.")

    if npc.market != session.current_market:
        return _error(session, ErrorCode.INVALID_NPC,
                      f"NPC '{npc_id}' is not in your current market.")

    pending_key = (npc_id, item_name)
    has_pending = pending_key in session.pending_negotiations

    # "respond" requires a pending counter-offer
    if action == "respond" and not has_pending:
        return _error(session, ErrorCode.INVALID_NPC, "No pending negotiation to respond to.")

    # Determine the real action direction
    if action == "respond":
        actual_action = session.pending_negotiations[pending_key].action
    else:
        actual_action = action

    # ── Round tracking ────────────────────────────────────────────────────────
    if has_pending:
        pending = session.pending_negotiations[pending_key]
        round_num = pending.round_num
    else:
        round_num = 1

    # ── Responding to a counter-offer ────────────────────────────────────────
    if has_pending:
        pending = session.pending_negotiations[pending_key]

        # Check if agent is accepting the counter
        is_accepting = (
            (actual_action == "buy"  and proposed_price >= pending.counter_price * 0.99) or
            (actual_action == "sell" and proposed_price <= pending.counter_price * 1.01)
        )

        if is_accepting or round_num > 3:
            if round_num > 3:
                # Max rounds hit — force rejection
                cost = _consume_time(session, 2, 4)
                del session.pending_negotiations[pending_key]
                session.log_action("negotiate", {
                    "npc_id": npc_id, "item": item_name,
                    "action": actual_action, "outcome": "rejected", "rounds": round_num,
                }, cost)
                return _ok(session, {
                    "outcome": "rejected", "npc_id": npc_id, "item": item_name,
                    "message": "We've been going back and forth too long. No deal.",
                    "rounds": round_num,
                }, cost)

            # Accept at the counter price
            trade_price = pending.counter_price
            if actual_action == "buy":
                total_cost = round(trade_price * quantity, 2)
                if session.cash < total_cost:
                    cost = _consume_time(session, 2, 4)
                    del session.pending_negotiations[pending_key]
                    return _error(session, ErrorCode.INSUFFICIENT_FUNDS,
                                  f"You have {session.cash:.2f} cash but total is {total_cost:.2f}.", cost)
                if npc.inventory.get(item, 0) < quantity:
                    cost = _consume_time(session, 2, 4)
                    del session.pending_negotiations[pending_key]
                    return _error(session, ErrorCode.INSUFFICIENT_STOCK,
                                  f"NPC only has {npc.inventory.get(item, 0)} units.", cost)
                session.cash -= total_cost
                session.inventory[item] = session.inventory.get(item, 0) + quantity
                npc.inventory[item] -= quantity
                session.price_engine.apply_demand_pressure(item, quantity)
                session.record_trade(item, trade_price)
            else:  # sell
                if session.inventory.get(item, 0) < quantity:
                    cost = _consume_time(session, 2, 4)
                    del session.pending_negotiations[pending_key]
                    return _error(session, ErrorCode.INSUFFICIENT_STOCK,
                                  f"You only have {session.inventory.get(item, 0)} units.")
                total_proceeds = round(trade_price * quantity, 2)
                session.inventory[item] = session.inventory.get(item, 0) - quantity
                session.cash += total_proceeds
                session.price_engine.apply_supply_pressure(item, quantity)
                session.record_trade(item, trade_price)

            cost = _consume_time(session, 2, 4)
            del session.pending_negotiations[pending_key]
            total_value = round(trade_price * quantity, 2)
            session.log_action("negotiate", {
                "npc_id": npc_id, "item": item_name, "action": actual_action,
                "outcome": "accepted", "price": trade_price,
                "quantity": quantity, "rounds": round_num,
            }, cost)
            return _ok(session, {
                "outcome": "accepted", "npc_id": npc_id,
                "item": item_name, "action": actual_action,
                "price": trade_price, "quantity": quantity,
                "total_cost" if actual_action == "buy" else "total_proceeds": total_value,
                "rounds": round_num,
            }, cost)

    # ── New negotiation or counter-counter ────────────────────────────────────
    outcome, counter_price, message = negotiate_round_for_item(
        npc, item, actual_action, proposed_price, round_num, session.rng
    )

    base_lo = 6 if round_num == 1 else 2
    base_hi = 10 if round_num == 1 else 4

    if outcome == "accepted":
        # Validate and execute trade
        if actual_action == "buy":
            total_cost = round(proposed_price * quantity, 2)
            if session.cash < total_cost:
                cost = _consume_time(session, base_lo, base_hi)
                return _error(session, ErrorCode.INSUFFICIENT_FUNDS,
                              f"You have {session.cash:.2f} but need {total_cost:.2f}.", cost)
            if npc.inventory.get(item, 0) < quantity:
                cost = _consume_time(session, base_lo, base_hi)
                return _error(session, ErrorCode.INSUFFICIENT_STOCK,
                              f"NPC only has {npc.inventory.get(item, 0)} units.", cost)
            session.cash -= total_cost
            session.inventory[item] = session.inventory.get(item, 0) + quantity
            npc.inventory[item] -= quantity
            session.price_engine.apply_demand_pressure(item, quantity)
            session.record_trade(item, proposed_price)
            cost = _consume_time(session, base_lo, base_hi)
            session.log_action("negotiate", {
                "npc_id": npc_id, "item": item_name, "action": actual_action,
                "outcome": "accepted", "price": proposed_price,
                "quantity": quantity, "rounds": round_num,
            }, cost)
            return _ok(session, {
                "outcome": "accepted", "npc_id": npc_id,
                "item": item_name, "action": "buy",
                "price": proposed_price, "quantity": quantity,
                "total_cost": total_cost, "rounds": round_num,
            }, cost)
        else:  # sell
            if session.inventory.get(item, 0) < quantity:
                cost = _consume_time(session, base_lo, base_hi)
                return _error(session, ErrorCode.INSUFFICIENT_STOCK,
                              f"You only have {session.inventory.get(item, 0)} units.", cost)
            total_proceeds = round(proposed_price * quantity, 2)
            session.inventory[item] = session.inventory.get(item, 0) - quantity
            session.cash += total_proceeds
            session.price_engine.apply_supply_pressure(item, quantity)
            session.record_trade(item, proposed_price)
            cost = _consume_time(session, base_lo, base_hi)
            session.log_action("negotiate", {
                "npc_id": npc_id, "item": item_name, "action": actual_action,
                "outcome": "accepted", "price": proposed_price,
                "quantity": quantity, "rounds": round_num,
            }, cost)
            return _ok(session, {
                "outcome": "accepted", "npc_id": npc_id,
                "item": item_name, "action": "sell",
                "price": proposed_price, "quantity": quantity,
                "total_proceeds": total_proceeds, "rounds": round_num,
            }, cost)

    elif outcome == "rejected":
        cost = _consume_time(session, base_lo, base_hi)
        # Clear any stale pending for this pair
        session.pending_negotiations.pop(pending_key, None)
        session.log_action("negotiate", {
            "npc_id": npc_id, "item": item_name, "action": actual_action,
            "outcome": "rejected", "rounds": round_num,
        }, cost)
        return _ok(session, {
            "outcome": "rejected", "npc_id": npc_id,
            "item": item_name, "message": message, "rounds": round_num,
        }, cost)

    else:  # counter
        cost = _consume_time(session, base_lo, base_hi)
        session.pending_negotiations[pending_key] = PendingNegotiation(
            npc_id=npc_id,
            item=item,
            action=actual_action,
            counter_price=counter_price,
            quantity=quantity,
            round_num=round_num + 1,
        )
        session.log_action("negotiate", {
            "npc_id": npc_id, "item": item_name, "action": actual_action,
            "outcome": "counter", "counter_price": counter_price,
            "quantity": quantity, "rounds": round_num,
        }, cost)
        return _ok(session, {
            "outcome": "counter", "npc_id": npc_id,
            "item": item_name, "action": actual_action,
            "counter_price": counter_price, "quantity": quantity,
            "message": message, "rounds": round_num,
        }, cost)


def move_to_market(session: GameSession, destination: str) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    try:
        dest = MarketName(destination)
    except ValueError:
        return _error(session, ErrorCode.INVALID_MARKET, f"Unknown market: {destination!r}")

    if dest == session.current_market:
        return _error(session, ErrorCode.ALREADY_HERE,
                      f"You are already at {destination}.")

    cost = _consume_time(session, 8, 12)
    session.current_market = dest
    session.record_market_visit(dest)

    npcs_present = [n.npc_id for n in session.get_npcs_in_market(dest)]

    from ._models import MARKET_DESCRIPTIONS
    primary_items = [
        item.value
        for item, cfg in ITEM_CATALOG.items()
        if cfg.category in MARKET_PRIMARY_CATEGORIES.get(dest, [])
    ]

    session.log_action("move_to_market", {"destination": destination}, cost)
    return _ok(session, {
        "market": destination,
        "description": MARKET_DESCRIPTIONS.get(dest, ""),
        "npcs_present": npcs_present,
        "items_available": primary_items,
    }, cost)


def wait(session: GameSession, duration: int) -> dict:
    if session.time_remaining <= 0:
        return _game_over(session)

    if duration < 1 or duration > 50:
        return _error(session, ErrorCode.INVALID_DURATION,
                      "wait duration must be between 1 and 50.")

    # wait costs exactly duration (capped at remaining time)
    actual = min(duration, session.time_remaining)
    old_clock = session.game_clock
    session.time_consumed += actual
    session.game_clock += actual

    session.price_engine.advance(actual)
    for shock in session.shock_schedule:
        if old_clock < shock["game_time"] <= session.game_clock:
            cats = [Category(c) for c in shock["affected_categories"]]
            session.price_engine.apply_shock(cats, shock["direction"], shock["magnitude_pct"])
            meta = {
                "game_time": shock["game_time"],
                "affected_categories": shock["affected_categories"],
            }
            future = generate_news_async(cats[0], shock["direction"], shock["magnitude_pct"])
            session._pending_futures.append(("news", future, meta))

    rates = session.price_engine.get_all_rates()
    for npc in session.npcs:
        npc.refresh_prices(rates, session.rng)

    # Pre-computed buzz schedule
    for buzz_event in session.buzz_schedule:
        if old_clock < buzz_event["game_time"] <= session.game_clock:
            future = generate_buzz_async(
                session.current_market, session.npcs, rates,
                buzz_event["buzz_seed"], session.game_clock,
            )
            session._pending_futures.append(("buzz", future, {}))

    # Build a brief market summary by checking how primary items moved
    primary_cats = MARKET_PRIMARY_CATEGORIES.get(session.current_market, [])
    moved_up = []
    moved_down = []
    for item, cfg in ITEM_CATALOG.items():
        if cfg.category not in primary_cats:
            continue
        history = session.price_engine.get_history(item)
        if len(history) >= 2:
            delta = history[-1]["price"] - history[-2]["price"]
            if delta > cfg.baseline_price * 0.02:
                moved_up.append(item.value)
            elif delta < -cfg.baseline_price * 0.02:
                moved_down.append(item.value)

    parts = []
    if moved_up:
        parts.append(f"{', '.join(moved_up[:3])} rose")
    if moved_down:
        parts.append(f"{', '.join(moved_down[:3])} fell")
    if parts:
        summary = f"Prices in {session.current_market.value} shifted. " + "; ".join(parts) + "."
    else:
        summary = f"Prices in {session.current_market.value} were relatively stable."

    session.collect_ready_content()
    session.log_action("wait", {"duration": actual}, actual)
    return _ok(session, {
        "time_consumed": actual,
        "time_remaining": session.time_remaining,
        "market_summary": summary,
    }, actual)
