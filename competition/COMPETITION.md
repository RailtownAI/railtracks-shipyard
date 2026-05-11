# Switchyard — Competition Brief

Switchyard is a commodity trading simulation set in an Alberta market. An AI agent
controls a trader who buys and sells goods across three markets within a fixed time
budget. Your job is to build the best agent you can.

---

## How it works

Each game run:
- Your agent starts with a random portfolio of cash and items
- It has 300 time units to trade across three markets: **Exchange**, **Frontier Post**, and **Black Market**
- Every action costs time — the clock ticks whether you trade well or badly
- News events fire during the game and shift prices; NPC chatter gives hints (some reliable, some not)
- At the end, your score is: **cash + item net worth at your final market + bonus points**

---

## The two tracks

### Track 1 — Prompt Track
Edit a single YAML file. No coding required.

```
competition/prompt_track/config.yaml   ← your file
competition/prompt_track/run.py        ← do not modify
```

You control:
- **system_prompt** — the strategy instructions your agent follows
- **model** — which LLM to use
- **initial_message** — how the game state is framed to the agent at the start

Run with:
```bash
python competition/prompt_track/run.py
```

### Track 2 — Code Track
Fork the repo and do whatever you want in your agent file.

```
competition/code_track/agent.py   ← your file
src/railtracks_shipyard/          ← do not modify
```

Run with:
```bash
python competition/code_track/agent.py
```

---

## Tools available to your agent

| Tool | Cost | Description |
|---|---|---|
| `get_market_dashboard` | 3–5 | All asks and bids in your current market |
| `get_historical_trends` | 3–5 | Pre-game price trend summary for items |
| `get_news` | 3–5 | Recent news reports affecting category prices |
| `get_buzz` | 3–5 | NPC chatter (reliability varies) |
| `negotiate` | 6–10 | Buy or sell with an NPC (counter-offers supported) |
| `move_to_market` | 8–12 | Travel to a different market |
| `get_inventory` | 1–2 | Your current cash and items |
| `get_score` | 1–2 | Your current score breakdown |
| `get_move_history` | 1–2 | Your last 15 actions |
| `get_time_remaining` | 1–2 | How much time you have left |
| `wait` | exact | Wait N time units for prices to shift |

---

## Challenges

These are the dimensions we are watching. You don't have to solve all of them —
but the teams that do will score highest.

**1. Prompting**
Can you write a better baseline strategy than the default? Start here.

**2. Planning**
Can the agent form an explicit plan at game start and stick to it?
Try prompting it to write out a strategy before it makes its first trade.

**3. Short-term learning**
Can the agent learn *within a single game*? For example: remember which NPCs
accepted fair prices and trade with them again; avoid NPCs who rejected you.

**4. Long-term learning**
Can it try different strategies across multiple runs and converge on the best one?
Think of it like reinforcement learning: explore different approaches, evaluate
the outcomes, and exploit what works.

**5. Context compression**
A long game fills the context window with tool results. Can you get the agent
to periodically summarise its own history so it stays efficient and doesn't
lose track of early information?

---

## Leaderboard

All scores are posted publicly after every run. Leaderboard submission is
handled automatically by the engine at the end of each game — you don't need
to do anything extra.

One seed (`42`) is the **competitive seed** — teams get one entry on the ranked
leaderboard. All other seeds go on the open leaderboard where you can run as
many times as you like.

Set `seed: 42` in your config (prompt track) or `SEED = 42` in your agent
(code track) when you are ready to submit your competitive entry.

---

## Rules

- Do not modify anything under `src/railtracks_shipyard/game_engine/`
- Both tracks use the same engine, same scoring, same markets
- You may use any LLM available via the OpenAI-compatible API
- Set your `TEAM_NAME` / `team_name` before running — this is how you appear on the leaderboard
- The `OPENAI_API_KEY` environment variable must be set (or a `.env` file in the repo root)

---

## Setup

```bash
pip install -e ".[competition]"
cp .env.example .env          # add your OPENAI_API_KEY
python competition/prompt_track/run.py    # prompt track
python competition/code_track/agent.py   # code track
```
