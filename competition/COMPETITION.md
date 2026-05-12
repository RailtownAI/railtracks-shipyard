# Switchyard — Competition Brief

A commodity trading simulation set across three Alberta markets. Your agent buys and sells goods within a 300-unit time budget. Score = **cash + item net worth at your final market + bonus points**.

Each action costs time. News events shift prices mid-game. NPC chatter gives hints — some reliable, some not.

---

## Tracks

### Prompt Track
Edit one YAML file. No code.

```
competition/prompt_track/config.yaml   ← yours
competition/prompt_track/run.py        ← do not touch
```

```bash
python competition/prompt_track/run.py
```

### Code Track
Edit the agent file. Do whatever you want with it.

```
competition/code_track/agent.py        ← yours
src/railtracks_shipyard/               ← do not touch
```

```bash
python competition/code_track/agent.py
```

---

## Tools

| Tool | Time cost | What it returns |
|---|---|---|
| `get_market_dashboard` | 3–5 | All NPC asks and bids in your current market |
| `get_historical_trends` | 3–5 | Pre-game price trend summary (call once) |
| `get_news` | 3–5 | News reports that have moved category prices |
| `get_buzz` | 3–5 | NPC chatter — reliability varies |
| `negotiate` | 6–10 | Buy or sell with an NPC; counter-offers supported |
| `move_to_market` | 8–12 | Travel to a different market |
| `get_inventory` | 1–2 | Current cash and held items |
| `get_score` | 1–2 | Score breakdown |
| `get_time_remaining` | 1–2 | Time left |
| `wait` | exact | Sit out N time units; prices move |

---

## Markets

| Market | Primary categories |
|---|---|
| `exchange` | Agriculture, Tech & AI |
| `frontier_post` | Energy, Agriculture |
| `black_market` | Luxury & Local, Tech & AI |

Item net worth at game end is calculated using rates in **your final market** — positioning matters.

---

## Challenges

These are roughly ordered by difficulty. The baseline prompt solves none of them well.

1. **Prompting** — Write a better strategy. The default is a starting point, not a ceiling.
2. **Planning** — Get the agent to commit to a plan before its first trade and track it.
3. **Short-term learning** — Can it remember which NPCs gave good prices this run and prefer them?
4. **Long-term learning** — Can it try different strategies across runs and exploit what works?
5. **Context compression** — Tool results fill the context window fast. Can the agent summarise its history to stay sharp late-game?
6. **Multi-agent coordination** — Run multiple agents to maximize performance and minimize token use. Can they leverage their shared info to maximize team score?

---

## Leaderboard

Scores post automatically at the end of every run. 
You may want to use a consistent seed for reproducibility, but it's not required.

---

## Rules

- Do not modify anything under `src/railtracks_shipyard/game_engine/`
- Both tracks use the same engine, scoring, and markets
- Any OpenAI-compatible model is allowed
- Set your team name before running — it's how you appear on the board
- `OPENAI_API_KEY` must be in your environment or a `.env` file at the repo root

---

## Setup

```bash
pip install -e ".[competition]"
cp .env.example .env          # add your OPENAI_API_KEY
python competition/prompt_track/run.py    # prompt track
python competition/code_track/agent.py   # code track
```
