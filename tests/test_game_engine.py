"""
Smoke tests for the Switchyard game engine.

These tests use a fixed seed and do not make LLM calls (the LLM layer falls
back to templates automatically when no API key is present). They verify the
complete tool API without network access.
"""
import unittest

from railtracks_shipyard import SwitchyardEngine, GameEngine


SEED = 42


class TestEngineInit(unittest.TestCase):
    def setUp(self):
        self.engine = SwitchyardEngine()
        self.payload = self.engine.new_game(seed=SEED, time_budget=300)

    def test_game_start_shape(self):
        p = self.payload
        self.assertEqual(p["event"], "game_start")
        self.assertIn("rules", p)
        self.assertIn("starting_inventory", p)
        self.assertIn("starting_market", p)
        self.assertIn("bonus_objectives", p)
        self.assertIn("npcs", p)

    def test_starting_inventory_value(self):
        inv = self.payload["starting_inventory"]
        self.assertGreater(inv["cash"], 0)
        # 3 objectives always selected
        self.assertEqual(len(self.payload["bonus_objectives"]), 3)

    def test_npc_count(self):
        # 8 NPCs per market × 3 markets = 24 total
        self.assertEqual(len(self.payload["npcs"]), 24)

    def test_backward_compat_alias(self):
        self.assertIs(GameEngine, SwitchyardEngine)


class TestStateTools(unittest.TestCase):
    def setUp(self):
        self.engine = SwitchyardEngine()
        self.engine.new_game(seed=SEED, time_budget=300)

    def _assert_envelope(self, result):
        self.assertIn("ok", result)
        self.assertIn("time_consumed", result)
        self.assertIn("time_remaining", result)
        if result["ok"]:
            self.assertIn("data", result)
        else:
            self.assertIn("error", result)

    def test_get_score(self):
        r = self.engine.get_score()
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        d = r["data"]
        self.assertIn("cash", d)
        self.assertIn("item_worth", d)
        self.assertIn("bonus_points", d)
        self.assertIn("total_score", d)

    def test_get_inventory(self):
        r = self.engine.get_inventory()
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        self.assertIn("cash", r["data"])
        self.assertIn("items", r["data"])

    def test_get_market_dashboard(self):
        r = self.engine.get_market_dashboard()
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        self.assertIn("market", r["data"])
        self.assertIn("items", r["data"])

    def test_get_historical_trends_all(self):
        r = self.engine.get_historical_trends()
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        items = r["data"]["items"]
        self.assertEqual(len(items), 32)

    def test_get_historical_trends_single(self):
        r = self.engine.get_historical_trends("prairie_wheat")
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["data"]["items"]), 1)
        self.assertEqual(r["data"]["items"][0]["name"], "prairie_wheat")

    def test_get_historical_trends_invalid(self):
        r = self.engine.get_historical_trends("not_a_real_item")
        self._assert_envelope(r)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "INVALID_ITEM")

    def test_get_news(self):
        r = self.engine.get_news()
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        self.assertIn("reports", r["data"])

    def test_get_buzz(self):
        r = self.engine.get_buzz()
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        self.assertIn("messages", r["data"])

    def test_get_move_history(self):
        r = self.engine.get_move_history()
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        self.assertIn("actions", r["data"])

    def test_get_time_remaining(self):
        r = self.engine.get_time_remaining()
        self._assert_envelope(r)
        self.assertTrue(r["ok"])
        d = r["data"]
        self.assertIn("time_remaining", d)
        self.assertIn("time_total", d)
        self.assertEqual(d["time_total"], 300)


class TestActionTools(unittest.TestCase):
    def setUp(self):
        self.engine = SwitchyardEngine()
        self.engine.new_game(seed=SEED, time_budget=300)

    def test_wait_basic(self):
        r = self.engine.wait(5)
        self.assertTrue(r["ok"])
        self.assertEqual(r["time_consumed"], 5)
        self.assertIn("market_summary", r["data"])

    def test_wait_invalid_duration(self):
        r = self.engine.wait(0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "INVALID_DURATION")

        r = self.engine.wait(51)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "INVALID_DURATION")

    def test_move_to_market(self):
        current = self.engine._session.current_market.value
        others = [m for m in ("exchange", "frontier_post", "black_market") if m != current]
        r = self.engine.move_to_market(others[0])
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["market"], others[0])

    def test_already_here(self):
        current = self.engine._session.current_market.value
        r = self.engine.move_to_market(current)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "ALREADY_HERE")

    def test_invalid_market(self):
        r = self.engine.move_to_market("fake_market")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "INVALID_MARKET")

    def test_negotiate_invalid_item(self):
        session = self.engine._session
        npc_id = session.get_npcs_in_market(session.current_market)[0].npc_id
        r = self.engine.negotiate(npc_id, "not_an_item", "buy", 10.0, 1)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "INVALID_ITEM")

    def test_negotiate_invalid_price(self):
        session = self.engine._session
        npc = session.get_npcs_in_market(session.current_market)[0]
        item = list(npc.inventory.keys())[0].value if npc.inventory else "prairie_wheat"
        r = self.engine.negotiate(npc.npc_id, item, "buy", -5.0, 1)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "INVALID_PRICE")

    def test_negotiate_invalid_quantity(self):
        session = self.engine._session
        npc = session.get_npcs_in_market(session.current_market)[0]
        item = list(npc.inventory.keys())[0].value if npc.inventory else "prairie_wheat"
        r = self.engine.negotiate(npc.npc_id, item, "buy", 50.0, 0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "INVALID_QUANTITY")

    def test_negotiate_npc_not_in_market(self):
        session = self.engine._session
        # Find an NPC in a different market
        current = session.current_market
        other_npc = next(n for n in session.npcs if n.market != current)
        r = self.engine.negotiate(other_npc.npc_id, "prairie_wheat", "buy", 20.0, 1)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "INVALID_NPC")

    def test_time_budget_exhaustion(self):
        self.engine._session.time_consumed = self.engine._session.time_budget
        r = self.engine.get_score()
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "GAME_OVER")

    def test_no_session_raises(self):
        engine = SwitchyardEngine()
        with self.assertRaises(RuntimeError):
            engine.get_score()


class TestNegotiationFlow(unittest.TestCase):
    """Verify a full buy negotiation through to completion."""

    def setUp(self):
        self.engine = SwitchyardEngine()
        self.engine.new_game(seed=SEED, time_budget=300)
        session = self.engine._session

        # Find an NPC in the starting market that has inventory
        self.npc = next(
            n for n in session.get_npcs_in_market(session.current_market)
            if n.inventory
        )
        self.item = list(self.npc.inventory.keys())[0]
        # Ensure agent has enough cash for any reasonable price
        session.cash = 10_000.0

    def test_buy_above_ask_accepted(self):
        ask = self.npc.get_ask(self.item)
        if ask <= 0:
            self.skipTest("NPC has no cached ask for this item")
        # Offer well above ask — should be accepted immediately
        r = self.engine.negotiate(
            self.npc.npc_id, self.item.value, "buy", ask * 1.20, 1
        )
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["outcome"], "accepted")

    def test_sell_below_bid_accepted(self):
        bid = self.npc.get_bid(self.item)
        if bid <= 0:
            self.skipTest("NPC has no cached bid for this item")
        # Give agent the item to sell
        session = self.engine._session
        session.inventory[self.item] = 5
        # Offer well below bid — should be accepted
        r = self.engine.negotiate(
            self.npc.npc_id, self.item.value, "sell", bid * 0.80, 1
        )
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["outcome"], "accepted")

    def test_final_score_structure(self):
        score = self.engine.final_score()
        self.assertIn("cash", score)
        self.assertIn("item_worth", score)
        self.assertIn("bonus_points", score)
        self.assertIn("total_score", score)
        self.assertIn("objectives", score)


if __name__ == "__main__":
    unittest.main()
