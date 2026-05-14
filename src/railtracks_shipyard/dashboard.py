"""
Live terminal dashboard for a Switchyard game session.

Usage:
    dashboard = GameDashboard(engine)
    dashboard.start()          # takes over the terminal
    ...                        # run your agent
    dashboard.stop()           # releases the terminal

"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Optional


from rich import box
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .game_engine._models import ITEM_CATALOG, MARKET_PRIMARY_CATEGORIES

if TYPE_CHECKING:
    from .game_engine import SwitchyardEngine


_MARKET_COLORS = {
    "exchange": "cyan",
    "frontier_post": "yellow",
    "black_market": "red",
}

_ACTION_COLORS = {
    "accepted": "green",
    "counter":  "yellow",
    "rejected": "red",
}

_MAX_ACTIONS = 20
_MAX_FEED = 20


class GameDashboard:
    """Full-screen live dashboard that reflects game state in real time."""

    def __init__(self, engine: "SwitchyardEngine") -> None:
        self.engine = engine
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the dashboard in a background thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the dashboard to exit and wait for the thread to finish."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    # ── Background thread ─────────────────────────────────────────────────────

    def _run(self) -> None:
        with Live(
            self._render(),
            refresh_per_second=4,
            screen=True,
        ) as live:
            while not self._stop.is_set():
                live.update(self._render())
                time.sleep(0.25)
            live.update(self._render())  # final frame before exit

    # ── Layout assembly ───────────────────────────────────────────────────────

    def _render(self):
        session = self.engine._session
        if session is None:
            return Panel("[dim]Waiting for game session…[/dim]", title="SWITCHYARD")

        root = Layout()
        root.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
        )
        root["body"].split_row(
            Layout(name="left", ratio=5),
            Layout(name="right", ratio=7),
        )
        root["left"].split_column(
            Layout(name="state",      size=7),
            Layout(name="inventory",  ratio=1),
            Layout(name="score",      size=7),
            Layout(name="objectives", size=7),
        )
        root["right"].split_column(
            Layout(name="prices",  ratio=3),
            Layout(name="actions", ratio=2),
            Layout(name="feed",    ratio=2),
        )

        root["header"].update(self._header(session))
        root["state"].update(self._state_panel(session))
        root["inventory"].update(self._inventory_panel(session))
        root["prices"].update(self._prices_panel(session))
        root["score"].update(self._score_panel(session))
        root["objectives"].update(self._objectives_panel(session))
        root["actions"].update(self._actions_panel(session))
        root["feed"].update(self._feed_panel(session))

        return root

    # ── Individual panels ─────────────────────────────────────────────────────

    def _header(self, session) -> Panel:
        tr = session.time_remaining
        tt = session.time_budget
        bar_w = 50
        filled = max(0, round(bar_w * tr / tt))
        color = "green" if tr > tt * 0.5 else "yellow" if tr > tt * 0.2 else "red"
        t = Text()
        t.append("  SWITCHYARD  ", style="bold white on dark_blue")
        t.append(f"  seed={session.seed}  │  ")
        t.append("█" * filled, style=color)
        t.append("░" * (bar_w - filled), style="dim")
        t.append(f"  {tr}/{tt} units remaining")
        return Panel(t, style="bold")

    def _state_panel(self, session) -> Panel:
        market = session.current_market.value
        color = _MARKET_COLORS.get(market, "white")
        t = Text()
        t.append("Market  ", style="dim")
        t.append(f"{market.upper()}\n", style=f"bold {color}")
        t.append("Cash    ", style="dim")
        t.append(f"${session.cash:,.2f}\n", style="bold green")
        t.append("Clock   ", style="dim")
        t.append(f"{session.game_clock}\n", style="white")
        t.append("Markets ", style="dim")
        visited = ", ".join(m.value for m in session.markets_visited) or "—"
        t.append(f"{visited}\n", style="white")
        t.append("Trades  ", style="dim")
        t.append(f"{session.successful_trades}", style="white")
        return Panel(t, title="[bold]STATE[/bold]", box=box.SIMPLE_HEAD)

    def _inventory_panel(self, session) -> Panel:
        tbl = Table(box=None, show_header=True, header_style="bold dim", padding=(0, 1))
        tbl.add_column("Item",     style="white")
        tbl.add_column("Qty",      justify="right", style="bold yellow")
        tbl.add_column("Rate",     justify="right", style="dim")
        tbl.add_column("Value",    justify="right", style="cyan")

        items = [(item, qty) for item, qty in session.inventory.items() if qty > 0]
        if items:
            for item, qty in sorted(items, key=lambda x: -x[1]):
                rate = session.price_engine.get_market_rate(item)
                val = rate * qty
                tbl.add_row(
                    item.value.replace("_", " "),
                    str(qty),
                    f"${rate:.1f}",
                    f"${val:.0f}",
                )
        else:
            tbl.add_row("[dim]empty[/dim]", "", "", "")

        return Panel(tbl, title="[bold]INVENTORY[/bold]", box=box.SIMPLE_HEAD)

    def _prices_panel(self, session) -> Panel:
        primary_cats = set(MARKET_PRIMARY_CATEGORIES.get(session.current_market, []))
        rates = session.price_engine.get_all_rates()

        def _row(item, cfg):
            rate = rates.get(item, cfg.baseline_price)
            history = session.price_engine.get_history(item)
            if len(history) >= 2:
                delta = history[-1]["price"] - history[-2]["price"]
                if delta > cfg.baseline_price * 0.01:
                    trend, tcol = "▲", "green"
                elif delta < -cfg.baseline_price * 0.01:
                    trend, tcol = "▼", "red"
                else:
                    trend, tcol = "─", "dim"
            else:
                trend, tcol = "─", "dim"
            return (item.value.replace("_", " "), f"${rate:.1f}", trend, tcol,
                    cfg.category in primary_cats)

        rows = [_row(i, c) for i, c in ITEM_CATALOG.items()]

        mid = (len(rows) + 1) // 2
        left_col, right_col = rows[:mid], rows[mid:]

        tbl = Table(box=None, show_header=True, header_style="bold dim",
                    padding=(0, 1), expand=True)
        for _ in range(2):
            tbl.add_column("Item",  style="white",   ratio=3)
            tbl.add_column("Rate",  justify="right",  ratio=2)
            tbl.add_column("",      justify="left",   ratio=1, no_wrap=True)

        for i, (name, rate_str, trend, tcol, primary) in enumerate(left_col):
            fmt = "bold" if primary else "dim"
            name_l  = f"[{fmt}]{name}[/{fmt}]"
            rate_l  = f"[{fmt}]{rate_str}[/{fmt}]"
            trend_l = f"[{tcol}]{trend}[/{tcol}]"
            if i < len(right_col):
                rn, rr, rt, rc, rp = right_col[i]
                rfmt = "bold" if rp else "dim"
                tbl.add_row(name_l, rate_l, trend_l,
                            f"[{rfmt}]{rn}[/{rfmt}]",
                            f"[{rfmt}]{rr}[/{rfmt}]",
                            f"[{rc}]{rt}[/{rc}]")
            else:
                tbl.add_row(name_l, rate_l, trend_l, "", "", "")

        market = session.current_market.value
        color = _MARKET_COLORS.get(market, "white")
        return Panel(tbl,
                     title=f"[bold]PRICES[/bold] [dim](bold = {market})[/dim]",
                     border_style=color,
                     box=box.SIMPLE_HEAD)

    def _score_panel(self, session) -> Panel:
        cash = round(session.cash, 2)
        items_val = round(session.compute_item_worth(), 2)
        bonus = round(session.compute_bonus_points(), 2)
        total = cash + items_val + bonus
        t = Text()
        t.append(f"Cash   ${cash:>10,.2f}\n",      style="green")
        t.append(f"Items  ${items_val:>10,.2f}\n",  style="cyan")
        t.append(f"Bonus  ${bonus:>10,.2f}\n",      style="yellow")
        t.append(f"TOTAL  ${total:>10,.2f}",        style="bold white")
        return Panel(t, title="[bold]SCORE[/bold]", box=box.SIMPLE_HEAD)

    def _objectives_panel(self, session) -> Panel:
        t = Text()
        for obj in session.objectives:
            done = obj.completed
            icon = "✓" if done else "○"
            style = "bold green" if done else "dim"
            t.append(f"{icon} ", style=style)
            t.append(f"{obj.id}", style=style)
            t.append(f"  +{obj.points}\n", style="green" if done else "dim")
        return Panel(t, title="[bold]OBJECTIVES[/bold]", box=box.SIMPLE_HEAD)

    def _actions_panel(self, session) -> Panel:
        log = list(reversed(session.action_log[-_MAX_ACTIONS:]))
        t = Text()
        for entry in log:
            ts = entry["timestamp"]
            action = entry["type"]
            details = entry.get("details", {})

            t.append(f"[{ts:>4}] ", style="dim")

            if action == "negotiate":
                item = details.get("item", "?").replace("_", " ")
                act = details.get("action", "?")
                outcome = details.get("outcome", "?")
                price = details.get("price") or details.get("counter_price")
                price_str = f" ${price:.2f}" if isinstance(price, (int, float)) else ""
                qty = details.get("quantity", "")
                qty_str = f" ×{qty}" if qty else ""
                t.append("negotiate  ", style="white")
                t.append(f"{item[:18]:<18} ", style="cyan")
                t.append(f"{act:<4} ", style="dim")
                t.append(f"{outcome}{price_str}{qty_str}\n",
                         style=_ACTION_COLORS.get(outcome, "white"))

            elif action == "move_to_market":
                dest = details.get("destination", "?")
                color = _MARKET_COLORS.get(dest, "white")
                t.append("move       ", style="white")
                t.append(f"→ {dest}\n", style=f"bold {color}")

            elif action == "get_market_dashboard":
                market = details.get("market", "")
                t.append("dashboard  ", style="dim white")
                t.append(f"{market}\n", style="dim")

            else:
                t.append(f"{action}\n", style="dim white")

        return Panel(t, title="[bold]RECENT ACTIONS[/bold]", box=box.SIMPLE_HEAD)

    def _feed_panel(self, session) -> Panel:
        # Merge news and buzz into a single list sorted newest-first
        entries = []
        for n in session.available_news:
            entries.append(("news", n.get("game_time", 0), n))
        for b in session.buzz_log:
            entries.append(("buzz", b.get("game_time", 0), b))
        entries.sort(key=lambda x: -x[1])

        t = Text()
        for kind, game_time, item in entries[:_MAX_FEED]:
            t.append(f"[{game_time:>4}] ", style="dim")
            if kind == "news":
                cats = ", ".join(item.get("affected_categories", []))
                headline = item.get("headline", "")
                t.append("NEWS  ", style="bold magenta")
                t.append(f"{cats}  ", style="dim magenta")
                t.append(f"{headline}\n", style="white")
            else:
                npc = item.get("npc_name", item.get("npc_id", "?"))
                msg = item.get("message", "")
                t.append("BUZZ  ", style="bold blue")
                t.append(f"{npc}  ", style="dim blue")
                t.append(f"{msg}\n", style="dim white")

        if not entries:
            t.append("No news or buzz yet…", style="dim")

        return Panel(t, title="[bold]LIVE FEED[/bold]", box=box.SIMPLE_HEAD)

