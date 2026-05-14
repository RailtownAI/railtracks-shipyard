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


def _is_colab() -> bool:
    try:
        import google.colab  # noqa: F401
        return True
    except ImportError:
        return False


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
        if _is_colab():
            self._run_colab()
            return
        with Live(
            self._render(),
            refresh_per_second=4,
            screen=True,
        ) as live:
            while not self._stop.is_set():
                live.update(self._render())
                time.sleep(0.25)
            live.update(self._render())  # final frame before exit

    def _run_colab(self) -> None:
        from IPython.display import display, HTML, clear_output  # type: ignore
        while not self._stop.is_set():
            clear_output(wait=True)
            display(HTML(self._render_html()))
            time.sleep(0.5)
        clear_output(wait=True)
        display(HTML(self._render_html()))

    # ── Colab HTML renderer ───────────────────────────────────────────────────

    def _render_html(self) -> str:
        session = self.engine._session
        if session is None:
            return '<div style="font-family:monospace;background:#0f0f1a;color:#888;padding:16px;border-radius:8px;">Waiting for game session…</div>'

        _MC = {"exchange": "#00bcd4", "frontier_post": "#ffc107", "black_market": "#f44336"}
        _OC = {"accepted": "#4caf50", "counter": "#ff9800", "rejected": "#f44336"}

        market = session.current_market.value
        mc = _MC.get(market, "#ffffff")
        tr = session.time_remaining
        tt = session.time_budget
        pct = max(0, round(100 * tr / tt))
        bar_col = "#4caf50" if tr > tt * 0.5 else "#ff9800" if tr > tt * 0.2 else "#f44336"

        cash = round(session.cash, 2)
        items_val = round(session.compute_item_worth(), 2)
        bonus = round(session.compute_bonus_points(), 2)
        total = cash + items_val + bonus

        # Objectives
        obj_rows = ""
        for obj in session.objectives:
            icon, col = ("✓", "#4caf50") if obj.completed else ("○", "#555")
            pts_col = "#4caf50" if obj.completed else "#444"
            obj_rows += f'<div style="color:{col};padding:2px 0;">{icon} {obj.id} <span style="color:{pts_col};">+{obj.points}</span></div>'

        # Inventory
        inv_rows = ""
        items = [(item, qty) for item, qty in session.inventory.items() if qty > 0]
        if items:
            for item, qty in sorted(items, key=lambda x: -x[1]):
                rate = session.price_engine.get_market_rate(item)
                val = rate * qty
                inv_rows += (
                    f'<tr>'
                    f'<td style="padding:3px 8px;color:#e0e0e0;">{item.value.replace("_", " ")}</td>'
                    f'<td style="padding:3px 8px;color:#ffc107;text-align:right;">×{qty}</td>'
                    f'<td style="padding:3px 8px;color:#888;text-align:right;">${rate:.2f}</td>'
                    f'<td style="padding:3px 8px;color:#00bcd4;text-align:right;">${val:.2f}</td>'
                    f'</tr>'
                )
        else:
            inv_rows = '<tr><td colspan="4" style="padding:3px 8px;color:#555;">empty</td></tr>'

        # Actions
        action_rows = ""
        for entry in reversed(session.action_log[-12:]):
            ts = entry["timestamp"]
            action = entry["type"]
            details = entry.get("details", {})
            if action == "negotiate":
                item = details.get("item", "?").replace("_", " ")
                act = details.get("action", "?")
                outcome = details.get("outcome", "?")
                price = details.get("price") or details.get("counter_price")
                price_str = f" ${price:.2f}" if isinstance(price, (int, float)) else ""
                qty_str = f" ×{details['quantity']}" if details.get("quantity") else ""
                ocol = _OC.get(outcome, "#e0e0e0")
                action_rows += (
                    f'<div style="padding:2px 0;">'
                    f'<span style="color:#555;">[{ts:>4}]</span> '
                    f'<span style="color:#888;">negotiate</span> '
                    f'<span style="color:#00bcd4;">{item[:20]}</span> '
                    f'<span style="color:#666;">{act}</span> '
                    f'<span style="color:{ocol};">{outcome}{price_str}{qty_str}</span>'
                    f'</div>'
                )
            elif action == "move_to_market":
                dest = details.get("destination", "?")
                dcol = _MC.get(dest, "#fff")
                action_rows += (
                    f'<div style="padding:2px 0;">'
                    f'<span style="color:#555;">[{ts:>4}]</span> '
                    f'<span style="color:#888;">move</span> '
                    f'<span style="color:{dcol};">→ {dest}</span>'
                    f'</div>'
                )
            else:
                action_rows += (
                    f'<div style="padding:2px 0;">'
                    f'<span style="color:#555;">[{ts:>4}] {action}</span>'
                    f'</div>'
                )
        if not action_rows:
            action_rows = '<div style="color:#555;">No actions yet…</div>'

        visited = ", ".join(m.value for m in session.markets_visited) or "—"
        card = "background:#1a1a2e;padding:12px;border-radius:6px;"
        label = "color:#555;font-size:0.75em;letter-spacing:1px;margin-bottom:8px;"

        return f"""
<div style="font-family:'Courier New',monospace;background:#0f0f1a;color:#e0e0e0;padding:16px;border-radius:10px;max-width:860px;margin:8px 0;">
  <div style="background:#16213e;padding:10px 16px;border-radius:6px;margin-bottom:12px;display:flex;align-items:center;gap:12px;">
    <span style="color:white;font-weight:bold;font-size:1.1em;letter-spacing:2px;">SWITCHYARD</span>
    <span style="color:#555;font-size:0.85em;">seed={session.seed}</span>
    <div style="flex:1;background:#2a2a3e;height:10px;border-radius:5px;overflow:hidden;">
      <div style="background:{bar_col};width:{pct}%;height:100%;"></div>
    </div>
    <span style="color:#888;font-size:0.9em;">{tr} / {tt} units</span>
  </div>

  <div style="display:flex;gap:10px;margin-bottom:10px;">
    <div style="{card}border-left:3px solid {mc};flex:1;">
      <div style="{label}">STATE</div>
      <div style="color:{mc};font-weight:bold;font-size:1.05em;">{market.upper()}</div>
      <div style="color:#4caf50;font-size:1.05em;margin:4px 0;">${cash:,.2f}</div>
      <div style="color:#888;font-size:0.85em;">clock {session.game_clock}</div>
      <div style="color:#888;font-size:0.85em;">trades {session.successful_trades}</div>
      <div style="color:#444;font-size:0.8em;margin-top:4px;">{visited}</div>
    </div>
    <div style="{card}flex:1;">
      <div style="{label}">SCORE</div>
      <div style="display:flex;justify-content:space-between;color:#4caf50;padding:2px 0;"><span>Cash</span><span>${cash:,.2f}</span></div>
      <div style="display:flex;justify-content:space-between;color:#00bcd4;padding:2px 0;"><span>Items</span><span>${items_val:,.2f}</span></div>
      <div style="display:flex;justify-content:space-between;color:#ffc107;padding:2px 0;"><span>Bonus</span><span>${bonus:,.2f}</span></div>
      <div style="border-top:1px solid #333;margin:6px 0;"></div>
      <div style="display:flex;justify-content:space-between;color:white;font-weight:bold;padding:2px 0;"><span>TOTAL</span><span>${total:,.2f}</span></div>
    </div>
    <div style="{card}flex:1.5;">
      <div style="{label}">OBJECTIVES</div>
      {obj_rows or '<div style="color:#555;">none</div>'}
    </div>
  </div>

  <div style="{card}margin-bottom:10px;">
    <div style="{label}">INVENTORY</div>
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr style="color:#555;font-size:0.8em;">
        <th style="text-align:left;padding:2px 8px;">Item</th>
        <th style="text-align:right;padding:2px 8px;">Qty</th>
        <th style="text-align:right;padding:2px 8px;">Rate</th>
        <th style="text-align:right;padding:2px 8px;">Value</th>
      </tr></thead>
      <tbody>{inv_rows}</tbody>
    </table>
  </div>

  <div style="{card}">
    <div style="{label}">RECENT ACTIONS</div>
    <div style="font-size:0.85em;line-height:1.7;">{action_rows}</div>
  </div>
</div>"""

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

