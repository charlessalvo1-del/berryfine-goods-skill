import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "berryfine-goods-skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pricing_replay import summarize_search_budget  # noqa: E402


class PricingReplayBudgetTests(unittest.TestCase):
    def population(self, ten_count):
        research = {}
        results = []
        for index in range(115):
            count = 10 if index < ten_count else 8
            item_id = f"item-{index:03d}"
            research[item_id] = {
                "search_attempts": [
                    {"opened_urls": [f"https://example.com/{item_id}/{attempt}"]}
                    for attempt in range(count)
                ]
            }
            results.append({"search_attempts": count, "included_prices": 1})
        return research, results

    def test_rothschild_baseline_passes_without_growth(self):
        research, results = self.population(26)
        summary = summarize_search_budget(research, results)
        self.assertEqual(summary["total_search_attempts"], 972)
        self.assertEqual(summary["average_search_attempts"], 8.45)
        self.assertTrue(summary["within_rothschild_baseline"])

    def test_extra_ten_search_item_fails_regression_guard(self):
        research, results = self.population(27)
        summary = summarize_search_budget(research, results)
        self.assertEqual(summary["total_search_attempts"], 974)
        self.assertFalse(summary["within_rothschild_baseline"])


if __name__ == "__main__":
    unittest.main()
