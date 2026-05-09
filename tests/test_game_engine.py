import unittest

from railtracks_shipyard import GameEngine


class TestGameEngineScaffold(unittest.TestCase):
    def test_status_message(self) -> None:
        engine = GameEngine()
        self.assertEqual(engine.status(), "game-engine scaffold ready")


if __name__ == "__main__":
    unittest.main()
