# Switchyard

**Market simulation game engine for the Railtracks Workshop · Upper Bound 2025**

Agents trade Alberta-themed commodities across three markets, racing against a time budget to maximise score. The engine rewards agents that read trends, interpret noisy signals, time their moves, and manage their action budget — not ones that follow hardcoded rules.

---

## Installation

```bash
# Clone the repo, then:
pip install -e .
```

Requires Python 3.9+. The `OPENAI_API_KEY` environment variable must be set to generate LLM-powered news and NPC buzz at game start (falls back to built-in templates if not set).

```bash
# .env file (or export in shell)
OPENAI_API_KEY=sk-...
```

---

## Quick start — run the example agent

```bash
python examples/naive_agent.py
```

This runs a simple trading agent against a random-seed game. Set a fixed seed for a reproducible run:

```python
# in examples/naive_agent.py, change:
main(seed=42)
```

---

## The game

### Time budget

The game has no turn count. Each tool call consumes time (with ±20% variance). The game ends when the budget hits zero. Agents must balance gathering information against taking action.

| Tool category | Cost |
|---|---|
| State reads (score, inventory, time) | Low — 1–2 units |
| Market reads (dashboard, news, buzz, trends, history) | Medium — 3–5 units |
| Negotiate (buy or sell) | High — 6–10 units base, +2–4 per round |
| Move to market | High — 8–12 units |
| Wait | Exactly `duration` units (1–50) |

### Scoring

```
final_score = cash
            + sum(quantity × end_market_rate  for each held item)
            + sum(bonus_points for each completed objective)
```

Item net worth is calculated using the market rate in the agent's **final market** when time runs out.

### Markets

| Market | Character | Primary items | NPC trust |
|---|---|---|---|
| `exchange` | High liquidity. Stable prices. | Agriculture, Tech & AI | Mostly honest |
| `frontier_post` | Volatile. Raw resource focus. | Energy, Agriculture | Mixed — calibrate carefully |
| `black_market` | High risk, high reward. Rare items. | Luxury & Local, rare Tech | Mostly deceptive |

Agents start in a random market. Moving costs time but unlocks different trading opportunities and NPC pools.

### Items

| Category | Items | Price behaviour |
|---|---|---|
| **Energy** | Oil sands crude, Natural gas, Refined bitumen, Solar panels, Wind turbine parts | High volatility. News-sensitive. Can spike or crash quickly. |
| **Agriculture** | Prairie wheat, Canola oil, Barley, Honey, Bison meat | Stable with seasonal drift. Reliable signal from trends. |
| **Tech & AI** | GPU chips, Training data, AI model weights, Robotics parts, Cloud credits | Trend-driven. Strong news correlation. |
| **Luxury & Local** | Alberta beef, Craft whisky, Ice hotel tickets, Northern lights tours, Hockey memorabilia | Illiquid. Rare appearances. High margin when available. |

### Price model

Each item has an underlying true value that evolves each game tick via:
1. **Mean reversion** — drifts back toward a long-run baseline
2. **Cyclical component** — slow sine oscillation over the session
3. **Random walk** — Gaussian noise scaled by category volatility
4. **News shocks** — large temporary deviations triggered by news events, decaying over time

Energy items are the most volatile; luxury items are the most stable but illiquid.

### NPCs

~15 NPCs (5 per market) are assigned one of five personality archetypes at game start:

| Archetype | Pricing | Buzz truthfulness |
|---|---|---|
| **Reliable Trader** | Close to market rate. Accepts fair offers. | High — correlates with actual trades |
| **Optimist** | Asks above market. Slow to sell, quick to buy. | Honest but overly bullish |
| **Pessimist** | Bids below market. Offloads cheaply. | Honest but tends negative |
| **Manipulator** | Prices designed to mislead. | Low — buzz intentionally decoupled from behaviour |
| **Noise Trader** | Semi-random prices. No strategy. | Random — not a reliable signal |

Archetypes are **not revealed** at game start. Agents that calibrate NPC trust over time will consistently outperform those that don't.

### Information channels

| Channel | Source | Reliability |
|---|---|---|
| `get_news` | Engine-generated events | Always factually accurate, but requires interpretation |
| `get_buzz` | NPC-generated chatter | Varies by personality — may be truthful, misleading, or noise |

---

## Tool API reference

All tools return a standard response envelope:

```json
{
  "ok": true,
  "time_consumed": 4,
  "time_remaining": 238,
  "data": { ... }
}
```

On error (`ok: false`), `data` is replaced by `error: { code, message }`. Failed calls consume no time, **except** `negotiate` which charges for rounds already played.

### State tools

#### `get_score()`
Returns `{ cash, item_worth, bonus_points, total_score }`.

#### `get_inventory()`
Returns `{ cash, items: [{ name, quantity, current_market_rate }] }`.

#### `get_market_dashboard()`
Returns all current asks and bids in the agent's current market.
```json
{
  "market": "exchange",
  "items": [
    {
      "name": "prairie_wheat",
      "category": "agriculture",
      "market_rate": 22.00,
      "asks": [{ "npc_id": "npc_02", "price": 21.50, "quantity": 8 }],
      "bids": [{ "npc_id": "npc_05", "price": 19.00, "quantity": 10 }]
    }
  ]
}
```

#### `get_historical_trends(item="")`
Returns pre-game price history. Pass an item name to filter, or omit for all 20 items.

#### `get_news()`
Returns news reports that have fired at or before the current game time.

#### `get_buzz()`
Returns recent NPC chatter from the current market. Trust varies by NPC.

#### `get_move_history()`
Returns the agent's own action log for this session.

#### `get_time_remaining()`
Returns `{ time_remaining, time_total, time_consumed }`.

### Action tools

#### `negotiate(npc_id, item, action, proposed_price, quantity)`

Opens or continues a price negotiation with a specific NPC.

| Parameter | Type | Notes |
|---|---|---|
| `npc_id` | str | Must be in your current market |
| `item` | str | Item name, e.g. `"prairie_wheat"` |
| `action` | str | `"buy"`, `"sell"`, or `"respond"` |
| `proposed_price` | float | Per unit, must be > 0 |
| `quantity` | int | Must be >= 1 |

Possible outcomes:

```json
{ "outcome": "accepted", "price": 21.50, "quantity": 2, "total_cost": 43.00, "rounds": 1 }
{ "outcome": "rejected", "message": "Not interested at that price.", "rounds": 1 }
{ "outcome": "counter", "counter_price": 22.00, "message": "Best I can do is 22.00.", "rounds": 1 }
```

To accept a counter-offer, call `negotiate` again with `action="respond"` and `proposed_price` equal to the `counter_price`. To walk away, simply don't respond.

#### `move_to_market(destination)`

Moves to a different market. Returns `{ market, description, npcs_present, items_available }`.

Error codes: `ALREADY_HERE`, `INVALID_MARKET`.

#### `wait(duration)`

Explicitly idles for `duration` time units (1–50). Returns `{ time_consumed, time_remaining, market_summary }`.

---

## Writing your own agent

The engine is a plain Python library. Any agent framework can call it directly. The [example agent](examples/naive_agent.py) shows the full railtracks pattern — all 11 tools wrapped as `@rt.function_node` and passed to `rt.agent_node`.

```python
from railtracks_shipyard import SwitchyardEngine
import railtracks as rt

engine = SwitchyardEngine()
game_info = engine.new_game()   # random seed (test mode)

@rt.function_node
def get_market_dashboard() -> dict:
    """Return all current asks and bids in your current market.
    Returns:
        Envelope with data.market and data.items (asks and bids per item).
    """
    return engine.get_market_dashboard()

# ... wrap remaining tools the same way ...

MyAgent = rt.agent_node(
    "My Agent",
    tool_nodes=[get_market_dashboard, ...],
    llm=rt.llm.OpenAILLM("gpt-4o-mini"),
    system_message="Your strategy here...",
)

flow = rt.Flow(name="My Game", entry_point=MyAgent)
result = flow.invoke(f"Game info: {game_info}. Start trading.")
print(engine.final_score())
```

### Tips for a stronger strategy

- **Cross-reference buzz with dashboards** — Manipulators lie; Noise Traders are random. A Reliable Trader's buzz is worth acting on.
- **Read news before buying** — News affects entire categories. A bullish energy shock ripples across all five energy items.
- **Shop around** — The same item has different NPC prices. Optimists price high; Pessimists offload cheap.
- **Historical trends are pre-game data** — Use them to identify items already in uptrends at game start.
- **Time is the scarce resource** — A single `move_to_market` costs as much as 6 score reads. Budget it.
- **End in a good market** — Item net worth is calculated using prices in your *final* market. Plan your last market move.

---

## Game environments

| Mode | How to start | Behaviour |
|---|---|---|
| **Test** (default) | `engine.new_game()` | New random seed each run. Everything varies. |
| **Reproducible** | `engine.new_game(seed=42)` | Same NPCs, same prices, same news every run. |
| **Competition** | `engine.new_game(seed=COMPETITION_SEED)` | Fixed seed shared across all participants. Level playing field. |

---

## Project structure

```
src/railtracks_shipyard/
├── __init__.py                      # Exports SwitchyardEngine
└── game_engine/
    ├── __init__.py                  # SwitchyardEngine public API
    ├── _models.py                   # Enums, item catalog, constants
    ├── _price_engine.py             # Stochastic price simulation
    ├── _npc.py                      # NPC archetypes and negotiation logic
    ├── _session.py                  # Game session state
    ├── _llm.py                      # LLM-generated news and buzz (railtracks)
    └── _tools.py                    # All 11 tool implementations

examples/
└── naive_agent.py                   # Simple railtracks agent example

tests/
└── test_game_engine.py              # Engine unit tests
```
