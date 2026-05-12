from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


BASE_TIMESTAMP = 1_700_000_000  # Unix epoch anchor for all in-game timestamps


class ItemName(str, Enum):
    # Energy (8)
    OIL_SANDS_CRUDE = "oil_sands_crude"
    NATURAL_GAS = "natural_gas"
    REFINED_BITUMEN = "refined_bitumen"
    SOLAR_PANELS = "solar_panels"
    WIND_TURBINE_PARTS = "wind_turbine_parts"
    HYDROGEN_CELLS = "hydrogen_cells"
    GEOTHERMAL_CREDITS = "geothermal_credits"
    CARBON_OFFSETS = "carbon_offsets"
    # Agriculture (8)
    PRAIRIE_WHEAT = "prairie_wheat"
    CANOLA_OIL = "canola_oil"
    BARLEY = "barley"
    HONEY = "honey"
    BISON_MEAT = "bison_meat"
    LENTILS = "lentils"
    PEA_PROTEIN = "pea_protein"
    MUSTARD_SEED = "mustard_seed"
    # Tech & AI (8)
    GPU_CHIPS = "gpu_chips"
    TRAINING_DATA = "training_data"
    AI_MODEL_WEIGHTS = "ai_model_weights"
    ROBOTICS_PARTS = "robotics_parts"
    CLOUD_CREDITS = "cloud_credits"
    QUANTUM_ACCESS = "quantum_access"
    DRONE_COMPONENTS = "drone_components"
    SENSOR_ARRAYS = "sensor_arrays"
    # Luxury & Local (8)
    ALBERTA_BEEF = "alberta_beef"
    CRAFT_WHISKY = "craft_whisky"
    ICE_HOTEL_TICKETS = "ice_hotel_tickets"
    NORTHERN_LIGHTS_TOURS = "northern_lights_tours"
    HOCKEY_MEMORABILIA = "hockey_memorabilia"
    WILD_GAME_LICENSES = "wild_game_licenses"
    BUFFALO_HIDE = "buffalo_hide"
    MAPLE_SPIRITS = "maple_spirits"


class Category(str, Enum):
    ENERGY = "energy"
    AGRICULTURE = "agriculture"
    TECH_AI = "tech_ai"
    LUXURY_LOCAL = "luxury_local"


class MarketName(str, Enum):
    EXCHANGE = "exchange"
    FRONTIER_POST = "frontier_post"
    BLACK_MARKET = "black_market"


class NPCArchetype(str, Enum):
    RELIABLE_TRADER = "reliable_trader"
    OPTIMIST = "optimist"
    PESSIMIST = "pessimist"
    MANIPULATOR = "manipulator"
    NOISE_TRADER = "noise_trader"


class ErrorCode(str, Enum):
    GAME_OVER = "GAME_OVER"
    INVALID_ITEM = "INVALID_ITEM"
    INVALID_MARKET = "INVALID_MARKET"
    INVALID_NPC = "INVALID_NPC"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    NPC_UNAVAILABLE = "NPC_UNAVAILABLE"
    ALREADY_HERE = "ALREADY_HERE"
    INVALID_DURATION = "INVALID_DURATION"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_PRICE = "INVALID_PRICE"


@dataclass(frozen=True)
class ItemConfig:
    name: ItemName
    category: Category
    baseline_price: float
    volatility: float           # σ as fraction of baseline per tick
    mean_reversion_speed: float  # κ: how fast price returns to baseline
    news_sensitivity: float      # multiplier applied to news shocks


ITEM_CATALOG: dict[ItemName, ItemConfig] = {
    # ── Energy: high volatility, strongly news-sensitive ──────────────────────
    ItemName.OIL_SANDS_CRUDE:    ItemConfig(ItemName.OIL_SANDS_CRUDE,    Category.ENERGY,  80.0, 0.0080, 0.04, 1.50),
    ItemName.NATURAL_GAS:        ItemConfig(ItemName.NATURAL_GAS,        Category.ENERGY,  45.0, 0.0090, 0.04, 1.60),
    ItemName.REFINED_BITUMEN:    ItemConfig(ItemName.REFINED_BITUMEN,    Category.ENERGY,  95.0, 0.0070, 0.03, 1.40),
    ItemName.SOLAR_PANELS:       ItemConfig(ItemName.SOLAR_PANELS,       Category.ENERGY, 120.0, 0.0060, 0.03, 1.20),
    ItemName.WIND_TURBINE_PARTS: ItemConfig(ItemName.WIND_TURBINE_PARTS, Category.ENERGY, 110.0, 0.0060, 0.03, 1.20),
    ItemName.HYDROGEN_CELLS:     ItemConfig(ItemName.HYDROGEN_CELLS,     Category.ENERGY, 155.0, 0.0085, 0.04, 1.45),
    ItemName.GEOTHERMAL_CREDITS: ItemConfig(ItemName.GEOTHERMAL_CREDITS, Category.ENERGY,  60.0, 0.0055, 0.04, 1.10),
    ItemName.CARBON_OFFSETS:     ItemConfig(ItemName.CARBON_OFFSETS,     Category.ENERGY,  38.0, 0.0065, 0.05, 1.35),

    # ── Agriculture: stable, seasonal drift, modest news response ─────────────
    ItemName.PRAIRIE_WHEAT: ItemConfig(ItemName.PRAIRIE_WHEAT, Category.AGRICULTURE, 22.0, 0.0020, 0.06, 0.80),
    ItemName.CANOLA_OIL:    ItemConfig(ItemName.CANOLA_OIL,    Category.AGRICULTURE, 28.0, 0.0020, 0.06, 0.80),
    ItemName.BARLEY:        ItemConfig(ItemName.BARLEY,        Category.AGRICULTURE, 18.0, 0.0020, 0.06, 0.80),
    ItemName.HONEY:         ItemConfig(ItemName.HONEY,         Category.AGRICULTURE, 35.0, 0.0025, 0.05, 0.70),
    ItemName.BISON_MEAT:    ItemConfig(ItemName.BISON_MEAT,    Category.AGRICULTURE, 42.0, 0.0030, 0.05, 0.90),
    ItemName.LENTILS:       ItemConfig(ItemName.LENTILS,       Category.AGRICULTURE, 20.0, 0.0018, 0.06, 0.75),
    ItemName.PEA_PROTEIN:   ItemConfig(ItemName.PEA_PROTEIN,   Category.AGRICULTURE, 50.0, 0.0030, 0.05, 0.85),
    ItemName.MUSTARD_SEED:  ItemConfig(ItemName.MUSTARD_SEED,  Category.AGRICULTURE, 24.0, 0.0022, 0.06, 0.75),

    # ── Tech & AI: trend-driven, strong news correlation ──────────────────────
    ItemName.GPU_CHIPS:        ItemConfig(ItemName.GPU_CHIPS,        Category.TECH_AI, 200.0, 0.0070, 0.03, 1.40),
    ItemName.TRAINING_DATA:    ItemConfig(ItemName.TRAINING_DATA,    Category.TECH_AI,  75.0, 0.0050, 0.04, 1.20),
    ItemName.AI_MODEL_WEIGHTS: ItemConfig(ItemName.AI_MODEL_WEIGHTS, Category.TECH_AI, 150.0, 0.0060, 0.03, 1.30),
    ItemName.ROBOTICS_PARTS:   ItemConfig(ItemName.ROBOTICS_PARTS,   Category.TECH_AI, 180.0, 0.0060, 0.03, 1.30),
    ItemName.CLOUD_CREDITS:    ItemConfig(ItemName.CLOUD_CREDITS,    Category.TECH_AI,  55.0, 0.0050, 0.04, 1.10),
    ItemName.QUANTUM_ACCESS:   ItemConfig(ItemName.QUANTUM_ACCESS,   Category.TECH_AI, 320.0, 0.0090, 0.03, 1.50),
    ItemName.DRONE_COMPONENTS: ItemConfig(ItemName.DRONE_COMPONENTS, Category.TECH_AI, 165.0, 0.0065, 0.03, 1.25),
    ItemName.SENSOR_ARRAYS:    ItemConfig(ItemName.SENSOR_ARRAYS,    Category.TECH_AI,  90.0, 0.0055, 0.04, 1.15),

    # ── Luxury & Local: illiquid, low drift, premium when available ───────────
    ItemName.ALBERTA_BEEF:          ItemConfig(ItemName.ALBERTA_BEEF,          Category.LUXURY_LOCAL,  65.0, 0.0015, 0.02, 0.60),
    ItemName.CRAFT_WHISKY:          ItemConfig(ItemName.CRAFT_WHISKY,          Category.LUXURY_LOCAL,  90.0, 0.0015, 0.02, 0.50),
    ItemName.ICE_HOTEL_TICKETS:     ItemConfig(ItemName.ICE_HOTEL_TICKETS,     Category.LUXURY_LOCAL, 250.0, 0.0020, 0.02, 0.60),
    ItemName.NORTHERN_LIGHTS_TOURS: ItemConfig(ItemName.NORTHERN_LIGHTS_TOURS, Category.LUXURY_LOCAL, 200.0, 0.0020, 0.02, 0.60),
    ItemName.HOCKEY_MEMORABILIA:    ItemConfig(ItemName.HOCKEY_MEMORABILIA,    Category.LUXURY_LOCAL, 140.0, 0.0020, 0.02, 0.60),
    ItemName.WILD_GAME_LICENSES:    ItemConfig(ItemName.WILD_GAME_LICENSES,    Category.LUXURY_LOCAL, 185.0, 0.0018, 0.02, 0.55),
    ItemName.BUFFALO_HIDE:          ItemConfig(ItemName.BUFFALO_HIDE,          Category.LUXURY_LOCAL, 115.0, 0.0018, 0.02, 0.55),
    ItemName.MAPLE_SPIRITS:         ItemConfig(ItemName.MAPLE_SPIRITS,         Category.LUXURY_LOCAL,  78.0, 0.0015, 0.02, 0.50),
}


# Items that can appear in the agent's randomised starting inventory
STARTING_ITEM_POOL: list[ItemName] = [
    ItemName.PRAIRIE_WHEAT,
    ItemName.CANOLA_OIL,
    ItemName.BARLEY,
    ItemName.LENTILS,
    ItemName.MUSTARD_SEED,
    ItemName.NATURAL_GAS,
    ItemName.OIL_SANDS_CRUDE,
    ItemName.CARBON_OFFSETS,
    ItemName.TRAINING_DATA,
    ItemName.CLOUD_CREDITS,
    ItemName.SENSOR_ARRAYS,
]

# Primary categories traded in each market (affects NPC inventory and prices)
MARKET_PRIMARY_CATEGORIES: dict[MarketName, list[Category]] = {
    MarketName.EXCHANGE:     [Category.AGRICULTURE, Category.TECH_AI],
    MarketName.FRONTIER_POST: [Category.ENERGY, Category.AGRICULTURE],
    MarketName.BLACK_MARKET: [Category.LUXURY_LOCAL, Category.TECH_AI],
}

MARKET_DESCRIPTIONS: dict[MarketName, str] = {
    MarketName.EXCHANGE: (
        "High liquidity. Stable, well-priced commodities. "
        "Transparent traders dealing primarily in Agriculture and Tech & AI."
    ),
    MarketName.FRONTIER_POST: (
        "Raw resource focus. Higher volatility. "
        "Mix of honest and unreliable traders dealing in Energy and raw materials."
    ),
    MarketName.BLACK_MARKET: (
        "Rare items appear here. High risk, high reward. "
        "Mostly deceptive traders dealing in Luxury items and rare Tech."
    ),
}

# NPC archetype distribution per market — 8 NPCs each
MARKET_NPC_ARCHETYPES: dict[MarketName, list[NPCArchetype]] = {
    MarketName.EXCHANGE: [
        NPCArchetype.RELIABLE_TRADER,
        NPCArchetype.RELIABLE_TRADER,
        NPCArchetype.RELIABLE_TRADER,
        NPCArchetype.OPTIMIST,
        NPCArchetype.OPTIMIST,
        NPCArchetype.PESSIMIST,
        NPCArchetype.PESSIMIST,
        NPCArchetype.NOISE_TRADER,
    ],
    MarketName.FRONTIER_POST: [
        NPCArchetype.RELIABLE_TRADER,
        NPCArchetype.RELIABLE_TRADER,
        NPCArchetype.OPTIMIST,
        NPCArchetype.OPTIMIST,
        NPCArchetype.PESSIMIST,
        NPCArchetype.PESSIMIST,
        NPCArchetype.NOISE_TRADER,
        NPCArchetype.MANIPULATOR,
    ],
    MarketName.BLACK_MARKET: [
        NPCArchetype.MANIPULATOR,
        NPCArchetype.MANIPULATOR,
        NPCArchetype.MANIPULATOR,
        NPCArchetype.NOISE_TRADER,
        NPCArchetype.NOISE_TRADER,
        NPCArchetype.PESSIMIST,
        NPCArchetype.PESSIMIST,
        NPCArchetype.OPTIMIST,
    ],
}

NPC_FIRST_NAMES: list[str] = [
    "Marlene", "Dutch", "Kovacs", "Sable", "Rex", "Ingrid", "Boris",
    "Fatima", "Clint", "Vera", "Jasper", "Nadia", "Buck", "Greta",
    "Silas", "Petra", "Raul", "Esther", "Finn", "Dolores",
    "Hank", "Yuki", "Cormac", "Lena", "Dex", "Wren", "Tomas",
    "Opal", "Reid", "Zara",
]

NPC_LAST_NAMES: list[str] = [
    "Harwick", "Strand", "Okafor", "Vance", "Thorn", "Bauer", "Reyes",
    "Novak", "Calloway", "Decker", "Frost", "Ibarra", "Kane", "Olsen",
    "Mercer", "Dunbar", "Sousa", "Yuen", "Breckenridge", "Farrow",
    "Allard", "Dubois", "Tran", "MacLeod", "Patel", "Woźniak", "Ferreira",
    "Lindqvist", "Kowalski", "Ito",
]


@dataclass
class BonusObjectiveDef:
    id: str
    description: str
    points: int


BONUS_OBJECTIVE_POOL: list[BonusObjectiveDef] = [
    BonusObjectiveDef(
        "bonus_traveller",
        "Visit all three markets at least once during the game.",
        50,
    ),
    BonusObjectiveDef(
        "bonus_collector",
        "Hold at least one item from each of the four categories at game end.",
        75,
    ),
    BonusObjectiveDef(
        "bonus_trader",
        "Complete 10 or more successful trades during the game.",
        60,
    ),
    BonusObjectiveDef(
        "bonus_luxury",
        "Hold at least 2 units of any Luxury & Local item at game end.",
        80,
    ),
    BonusObjectiveDef(
        "bonus_energy",
        "Hold at least 3 units of Energy items in total at game end.",
        55,
    ),
    BonusObjectiveDef(
        "bonus_frugal",
        "Execute 5 or more buy trades at a price at or below the market rate.",
        65,
    ),
]
