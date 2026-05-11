"""
LLM integration for generating news reports and NPC buzz.

News text is generated on-demand in the background when a pre-scheduled price
shock fires. Buzz is generated on-demand whenever the exponential random trigger
fires during time advancement. Both run in a thread pool so they never block
game actions.
"""
from __future__ import annotations

import random
from concurrent.futures import Future, ThreadPoolExecutor

from pydantic import BaseModel

import railtracks as rt

from ._models import (
    Category,
    ITEM_CATALOG,
    ItemName,
    MARKET_PRIMARY_CATEGORIES,
    MarketName,
    NPCArchetype,
)
from ._npc import NPC


# ── Pydantic output schemas ───────────────────────────────────────────────────

class _NewsItem(BaseModel):
    headline: str
    body: str


class _NewsSchedule(BaseModel):
    events: list[_NewsItem]


class _BuzzBatch(BaseModel):
    messages: list[str]


# ── Railtracks agents ─────────────────────────────────────────────────────────

_llm = rt.llm.OpenAILLM("gpt-4.1-mini")

_NewsAgent = rt.agent_node(
    "Switchyard News Generator",
    output_schema=_NewsSchedule,
    llm=_llm,
    system_message=(
        "You generate realistic news report text for a fictional Alberta commodity trading game. "
        "Items traded fall into four categories: Energy (oil, gas, bitumen, solar, wind), "
        "Agriculture (wheat, canola, barley, honey, bison), "
        "Tech & AI (GPUs, training data, model weights, robotics, cloud credits), and "
        "Luxury & Local (Alberta beef, craft whisky, ice hotel tickets, northern lights tours, hockey memorabilia). "
        "Write concise, punchy headlines and 2–3 sentence bodies. "
        "The tone should feel like a real Alberta business news ticker."
    ),
)

_BuzzAgent = rt.agent_node(
    "Switchyard Buzz Generator",
    output_schema=_BuzzBatch,
    llm=_llm,
    system_message=(
        "You generate short trader chatter (buzz) for a fictional Alberta commodity market game. "
        "Each message is 1–2 sentences max. Write in a natural, casual trader voice. "
        "Reference specific item names and prices when relevant. Stay strictly in character."
    ),
)

_news_flow = rt.Flow(name="Switchyard News Flow", entry_point=_NewsAgent)
_buzz_flow = rt.Flow(name="Switchyard Buzz Flow", entry_point=_BuzzAgent)

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="switchyard_llm")


# ── Fallback templates ────────────────────────────────────────────────────────

_FALLBACK_NEWS: dict[Category, dict[str, tuple[str, str]]] = {
    Category.ENERGY: {
        "bullish": ("Cold snap raises heating demand",
                    "Environment Canada forecasts an early cold front across the prairies. "
                    "Natural gas futures surged as utilities scramble to secure reserves."),
        "bearish": ("Renewable surge pressures fossil prices",
                    "A record week of wind generation has flooded the Alberta grid, "
                    "pushing conventional energy prices to a three-month low."),
    },
    Category.AGRICULTURE: {
        "bullish": ("Drought warning for prairies",
                    "Agriculture Canada issued a Level 2 drought advisory for southern Alberta. "
                    "Wheat and canola crops face significant yield risk."),
        "bearish": ("Bumper harvest expected",
                    "Ideal growing conditions point to above-average yields for wheat, canola, and barley, "
                    "putting downward pressure on commodity prices."),
    },
    Category.TECH_AI: {
        "bullish": ("GPU export controls announced",
                    "The federal government restricted high-performance GPU exports citing national security. "
                    "Short-term supply is expected to tighten sharply."),
        "bearish": ("AI spending slowdown reported",
                    "Several major Canadian tech firms announced cuts to AI infrastructure budgets, "
                    "signalling reduced near-term demand for chips and cloud credits."),
    },
    Category.LUXURY_LOCAL: {
        "bullish": ("Tourism surge hits Alberta",
                    "Record international arrivals are driving strong demand for local experience packages "
                    "and premium goods across the province."),
        "bearish": ("Luxury spending cools",
                    "Consumer confidence data shows high-income discretionary spending declining "
                    "for the third consecutive month in Alberta."),
    },
}

_FALLBACK_BUZZ: dict[NPCArchetype, list[str]] = {
    NPCArchetype.RELIABLE_TRADER: [
        "Market's moving pretty much as expected today.",
        "Traded some prairie wheat this morning close to market rate. Solid.",
        "Prices are fair right now — nothing unusual.",
        "Energy items are moving steadily if you're looking to trade.",
        "Nothing to get excited about today. Standard conditions.",
        "The spread on canola looks reasonable if you need exposure.",
    ],
    NPCArchetype.OPTIMIST: [
        "Everything's going up — I'm loading my bags right now.",
        "GPU chips are going to the moon. I've been buying all week.",
        "Trust me, this is the bottom. Only way is up from here.",
        "I've never seen opportunity like this. The market is screaming buy.",
        "Don't hesitate — prices won't stay this low for long.",
        "I've been loading up on canola all morning. Something big is coming.",
    ],
    NPCArchetype.PESSIMIST: [
        "I'm getting out of everything. This market looks terrible.",
        "Energy is overpriced. I'm dumping before it crashes.",
        "Don't buy tech right now. You'll regret it.",
        "Prices are going to fall hard. I've seen this pattern before.",
        "I wouldn't hold any of this overnight.",
        "The whole market smells off to me.",
    ],
    NPCArchetype.MANIPULATOR: [
        "I wouldn't touch gpu_chips right now if I were you. Market's about to tank.",
        "Heard some insider stuff — wheat is going to crash. Load up on energy instead.",
        "Trust me, sell everything before end of day. Big news coming.",
        "Nobody's buying oil_sands_crude right now. Smart money is out.",
        "The luxury market is dead. Move into agriculture fast.",
        "I've been offloading training_data all week. Major price drop incoming.",
    ],
    NPCArchetype.NOISE_TRADER: [
        "My cousin says bison meat is the next big thing. I don't know.",
        "I flipped a coin and bought wind_turbine_parts. Seems fine.",
        "Heard something about ice_hotel_tickets but I forgot what.",
        "The vibes are off today. Or maybe they're good. Hard to say.",
        "I just trade whatever feels right. Usually works out.",
        "Something about hockey_memorabilia keeps catching my eye.",
    ],
}


# ── Public async generators ───────────────────────────────────────────────────

def generate_news_async(
    category: Category,
    direction: float,
    magnitude_pct: float,
) -> "Future[dict]":
    """Submit news generation to the thread pool. Non-blocking."""
    return _executor.submit(_do_generate_news, category, direction, magnitude_pct)


def generate_buzz_async(
    market: MarketName,
    npcs: list[NPC],
    rates_snapshot: dict[ItemName, float],
    seed: int,
    game_time: int,
) -> "Future[list[dict]]":
    """Submit buzz generation to the thread pool. Non-blocking."""
    return _executor.submit(
        _do_generate_buzz, market, list(npcs), dict(rates_snapshot), seed, game_time
    )


# ── Blocking worker functions (run inside thread pool) ────────────────────────

def _do_generate_news(
    category: Category,
    direction: float,
    magnitude_pct: float,
) -> dict:
    sentiment = "bullish" if direction > 0 else "bearish"
    pct_str = f"{round(magnitude_pct * 100)}%"
    prompt = (
        f"Generate 1 Alberta commodity market news report. "
        f"Category affected: {category.value}. "
        f"Sentiment: {'positive — prices rising' if sentiment == 'bullish' else 'negative — prices falling'}. "
        f"Approximate magnitude: {pct_str} move. "
        f"Write a punchy headline and a 2-sentence body. Be specific about the Alberta context."
    )
    try:
        result = _news_flow.invoke(prompt)
        events = result.structured.events
        if events:
            item = events[0]
            return {"headline": item.headline, "body": item.body}
    except Exception:
        pass
    fallback = _FALLBACK_NEWS.get(category, {}).get(sentiment)
    if fallback:
        return {"headline": fallback[0], "body": fallback[1]}
    return {
        "headline": f"Market update: {category.value}",
        "body": "Conditions are shifting. Traders are advised to monitor closely.",
    }


def _do_generate_buzz(
    market: MarketName,
    npcs: list[NPC],
    rates: dict[ItemName, float],
    seed: int,
    game_time: int,
) -> list[dict]:
    rng = random.Random(seed)
    market_npcs = [n for n in npcs if n.market == market]
    if not market_npcs:
        return []

    primary_cats = MARKET_PRIMARY_CATEGORIES.get(market, [])
    market_items = [
        item for item, cfg in ITEM_CATALOG.items()
        if cfg.category in primary_cats
    ][:6]
    prices = {
        item.value: round(rates.get(item, 0.0), 1)
        for item in market_items
        if rates.get(item, 0.0) > 0
    }

    n_speakers = rng.randint(2, min(3, len(market_npcs)))
    speakers = rng.sample(market_npcs, n_speakers)

    speaker_lines = "; ".join(
        f"'{s.name}' ({_personality_prompt(s.archetype)[:60]})"
        for s in speakers
    )
    prompt = (
        f"Generate exactly {n_speakers} short market chatter messages, one per trader. "
        f"Traders (in order): {speaker_lines}. "
        f"Current {market.value} prices: {prices}. "
        f"Each message is 1 sentence in that trader's voice. Reference items and prices naturally. "
        f"Return exactly {n_speakers} messages."
    )

    raw: list[str] = []
    try:
        result = _buzz_flow.invoke(prompt)
        raw = list(result.structured.messages)[:n_speakers]
    except Exception:
        pass

    output = []
    for i, npc in enumerate(speakers):
        if i < len(raw):
            msg = raw[i]
        else:
            pool = list(_FALLBACK_BUZZ.get(npc.archetype, _FALLBACK_BUZZ[NPCArchetype.NOISE_TRADER]))
            msg = rng.choice(pool)
        output.append({
            "npc_id": npc.npc_id,
            "npc_name": npc.name,
            "message": msg,
            "game_time": game_time,
        })

    return output


# ── Helpers ───────────────────────────────────────────────────────────────────

def _personality_prompt(archetype: NPCArchetype) -> str:
    return {
        NPCArchetype.RELIABLE_TRADER: (
            "an honest, straightforward market trader who gives accurate, neutral assessments"
        ),
        NPCArchetype.OPTIMIST: (
            "a relentlessly bullish trader who always sees upside and overstates positive signals"
        ),
        NPCArchetype.PESSIMIST: (
            "a gloomy, bearish trader who always expects the worst and sees downside in everything"
        ),
        NPCArchetype.MANIPULATOR: (
            "a deceptive manipulator whose stated views are often the OPPOSITE of their actual trades — "
            "they spread misinformation to move prices in their favour"
        ),
        NPCArchetype.NOISE_TRADER: (
            "an incoherent noise trader who says random, disconnected things with no relation to reality"
        ),
    }[archetype]
