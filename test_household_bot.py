import unittest
import sys
import types
from datetime import date

# The production image installs Flask and requests from requirements.txt.  The
# lightweight repository test runner only exercises storage/analytics logic.
sys.modules.setdefault("requests", types.SimpleNamespace(post=None))
sys.modules.setdefault(
    "flask",
    types.SimpleNamespace(jsonify=None, request=types.SimpleNamespace()),
)

from household_bot import HouseholdStore, consumption_stats


class HouseholdBotTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tempdir.name) / "household.json"

    def tearDown(self):
        self._tempdir.cleanup()

    def test_store_add_remove_and_purchase(self):
        store = HouseholdStore(self.path)
        store.add_to_list("dairy-0")
        store.add_to_list("dairy-0")
        self.assertEqual(store.load()["shopping"]["dairy-0"]["quantity"], 2)

        store.record_purchase("dairy-0", 2)
        payload = store.load()
        self.assertNotIn("dairy-0", payload["shopping"])
        self.assertEqual(payload["purchases"][0]["name"], "شیر")
        self.assertEqual(payload["purchases"][0]["quantity"], 2)

    def test_consumption_interval_and_due_date(self):
        payload = {
            "shopping": {},
            "purchases": [
                {"item_id": "dairy-0", "purchased_at": "2026-08-16T10:00:00+00:00"},
                {"item_id": "dairy-0", "purchased_at": "2026-08-31T10:00:00+00:00"},
                {"item_id": "dairy-0", "purchased_at": "2026-09-15T10:00:00+00:00"},
            ],
        }
        stats = consumption_stats(payload, today=date(2026, 9, 27))
        self.assertEqual(stats["dairy-0"]["average_days"], 15)
        self.assertEqual(stats["dairy-0"]["next_date"], date(2026, 9, 30))
        self.assertTrue(stats["dairy-0"]["due"])

    def test_store_recovers_from_invalid_json(self):
        self.path.write_text("not-json", encoding="utf-8")
        self.assertEqual(HouseholdStore(self.path).load(), {
            "shopping": {}, "purchases": [], "sessions": {}
        })


if __name__ == "__main__":
    unittest.main()
