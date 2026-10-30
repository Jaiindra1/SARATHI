"""SQLite contract checks using isolated temporary database files; no browsers."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services import search_service
from services.product_normalizer import normalize_price
from services.product_repository import ProductRepository, product_identity
from services.price_tracking_service import track_search
from services.sqlite_client import connection


def listing(price=100, retailer="Amazon", **overrides):
    product = {
        "name": "Example phone", "retailer": retailer, "price": price,
        "original_price": 150, "image_url": None,
        "url": ("https://www.amazon.in/phone/dp/B012345678?tag=example" if retailer == "Amazon"
                else "https://www.flipkart.com/phone/p/itm123?pid=MOB123&lid=tracking"),
    }
    return dict(product, **overrides)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "products.sqlite3"
        self.repo = ProductRepository(self.path)
        self.now = datetime.now(timezone.utc)

    def save(self, price=100, search_id="search1", **overrides):
        return self.repo.save_observation(listing(price, **overrides), search_id, self.now)

    def history(self):
        with connection(self.path, write=True) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM price_history ORDER BY rowid")]

    def test_first_product_and_initial_history(self):
        identity = self.save()
        self.assertEqual(self.repo.get_product(identity)["current_price"], 100)
        self.assertEqual(self.history()[0]["change_type"], "initial")
        self.assertEqual(self.history()[0]["search_id"], "search1")

    def test_unchanged_price_only_updates_last_checked(self):
        identity = self.save()
        before = self.repo.get_product(identity)
        self.now += timedelta(seconds=1)
        self.save("Rs. 100.00", "search2")
        after = self.repo.get_product(identity)
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(after, dict(before, last_checked=self.now))

    def test_decrease_and_increase_create_history(self):
        identity = self.save()
        self.save(80, "decrease")
        self.save(120, "increase")
        self.assertEqual([h["price"] for h in self.history()], [100, 80, 120])
        self.assertEqual([h["change_type"] for h in self.history()], ["initial", "changed", "changed"])
        self.assertEqual(self.repo.get_product(identity)["current_price"], 120)

    def test_missing_invalid_zero_price_preserves_valid_price(self):
        identity = self.save()
        for i, value in enumerate([None, 0, -2, "invalid", "NaN", float("inf"), True, "12.345"]):
            self.save(value, str(i))
        self.assertEqual(self.repo.get_product(identity)["current_price"], 100)
        self.assertEqual(len(self.history()), 1)

    def test_initial_missing_price_later_becomes_valid(self):
        identity = self.save(None)
        self.assertEqual(len(self.history()), 0)
        self.assertIsNone(self.repo.get_product(identity)["current_price"])
        self.save(90, "later")
        self.assertEqual(self.history()[0]["change_type"], "initial")

    def test_retailers_separate_and_url_variations_deduplicated(self):
        identity = self.save()
        other = self.repo.save_observation(listing(retailer="Flipkart"), "search1", self.now)
        self.assertNotEqual(identity, other)
        self.save(url="https://amazon.in/gp/product/B012345678?ref=other")
        self.assertEqual(len(self.history()), 2)
        with connection(self.path, write=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM products").fetchone()[0], 2)

    def test_pid_variants_do_not_merge(self):
        first = product_identity(listing(retailer="Flipkart"))[0]
        second = product_identity(listing(retailer="Flipkart", url="https://flipkart.com/phone/p/itm123?pid=MOB456"))[0]
        self.assertNotEqual(first, second)

    def test_fallback_preserves_variant_but_removes_tracking(self):
        def identity(query):
            return product_identity(listing(url="https://amazon.in/listing?" + query))[0]
        self.assertEqual(identity("variant=a&utm_source=x"), identity("variant=a&utm_source=y"))
        self.assertNotEqual(identity("variant=a"), identity("variant=b"))

    def test_no_name_only_identity(self):
        with self.assertRaises(ValueError):
            product_identity(listing(url=None))

    def test_simultaneous_same_price_has_single_history(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: self.save(100, str(i)), range(20)))
        self.assertEqual(len(self.history()), 1)

    def test_older_observation_does_not_revert_price(self):
        identity = self.save(100)
        self.repo.save_observation(listing(80), "old", self.now - timedelta(seconds=1))
        self.assertEqual(self.repo.get_product(identity)["current_price"], 100)
        self.assertEqual(len(self.history()), 1)

    def test_search_records_separate_and_failed_retailer_untouched(self):
        other_id = self.repo.save_observation(listing(200, "Flipkart"), "old", self.now)
        before = self.repo.get_product(other_id)
        report = track_search("phone", [listing()], ["Flipkart"], repository=self.repo)
        with connection(self.path, write=True) as db:
            record = json.loads(db.execute("SELECT data FROM searches WHERE search_id = ?",
                                           (report["search_id"],)).fetchone()[0])
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["products_found"], 1)
        self.assertEqual(len(record["product_ids"]), 1)
        self.assertEqual(self.repo.get_product(other_id), before)

    def test_one_product_failure_does_not_block_other_saves(self):
        report = track_search("phone", [listing(url=None), listing()], repository=self.repo)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["saved_count"], 1)
        self.assertIn("warning", report)

    def test_reopening_preserves_records_and_all_source_fields(self):
        product = listing(rating="4.5", specifications={"ram": "8GB"}, highlights=["8GB RAM"], availability="In stock")
        identity = self.repo.save_observation(product, "first", self.now)
        before = self.repo.get_product(identity)
        reopened = ProductRepository(self.path)
        self.assertEqual(reopened.get_product(identity), before)
        with connection(self.path, write=True) as db:
            stored = json.loads(db.execute("SELECT product_data FROM products WHERE product_id = ?", (identity,)).fetchone()[0])
        self.assertEqual(stored, product)
        self.assertEqual(len(self.history()), 1)

    def test_observation_rolls_back_if_history_write_fails(self):
        with connection(self.path, write=True) as db:
            db.execute("""CREATE TRIGGER fail_history BEFORE INSERT ON price_history
                          BEGIN SELECT RAISE(ABORT, 'controlled failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save()
        with connection(self.path, write=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM products").fetchone()[0], 0)

    def test_search_merges_preserve_earlier_fields(self):
        self.repo.save_search("search", {"query": "phone", "status": "processing"})
        self.repo.save_search("search", {"status": "completed"})
        with connection(self.path, write=True) as db:
            record = json.loads(db.execute("SELECT data FROM searches WHERE search_id = 'search'").fetchone()[0])
        self.assertEqual(record, {"query": "phone", "status": "completed"})


class ConnectionAndSearchTests(unittest.TestCase):
    def test_retailer_default_and_strict_failure_modes(self):
        from retailers import amazon, flipkart
        for module, search in [(amazon, amazon.search_amazon), (flipkart, flipkart.search_flipkart)]:
            with self.subTest(module=module.__name__), \
                 patch.object(module, "browser_session", side_effect=RuntimeError("Browser unavailable")):
                with self.assertRaises(RuntimeError):
                    search("phone")
                with self.assertRaises(RuntimeError):
                    search("phone", raise_on_error=True)


    def test_same_path_different_flipkart_pid_survives_search_deduplication(self):
        variants = [listing(retailer="Flipkart"), listing(retailer="Flipkart", url="https://flipkart.com/phone/p/itm123?pid=MOB456")]
        with patch.object(search_service, "search_flipkart", return_value=variants), \
             patch.object(search_service, "search_amazon", return_value=[]), \
             patch.object(search_service, "track_search", return_value={"status": "saved"}):
            self.assertEqual(len(search_service.search_products("phone")), 2)

    def test_price_validation(self):
        self.assertEqual(normalize_price("INR 1,09,999.50"), 109999.5)
        for value in ["100-200", "1,2,3", "USD 50", "0", "-1", "NaN"]:
            self.assertIsNone(normalize_price(value))

    def test_connection_failure_reported(self):
        with patch("services.price_tracking_service.ProductRepository", side_effect=RuntimeError):
            report = track_search("phone", [listing()])
        self.assertEqual(report["status"], "failed")
        self.assertIn("warning", report)


    def test_search_preserves_list_and_frontend_fields_on_persistence_failure(self):
        with patch.object(search_service, "search_amazon", return_value=[listing()]), \
             patch.object(search_service, "search_flipkart", side_effect=RuntimeError), \
             patch.object(search_service, "track_search", return_value={"status": "failed", "warning": "Save failed"}) as track:
            products = search_service.search_products("phone")
        self.assertIsInstance(products, list)
        self.assertEqual(products[0]["name"], "Example phone")
        self.assertIn("highlights", products[0])
        self.assertEqual(products.persistence["status"], "failed")
        self.assertEqual(track.call_args.args[2], ["Flipkart"])

    def test_both_retailer_failures_record_failed_search(self):
        with patch.object(search_service, "search_amazon", side_effect=RuntimeError), \
             patch.object(search_service, "search_flipkart", side_effect=RuntimeError), \
             patch.object(search_service, "track_search") as track:
            with self.assertRaises(RuntimeError):
                search_service.search_products("phone")
            self.assertEqual(track.call_args.args[1], [])
            self.assertEqual(len(track.call_args.args[2]), 2)

    def test_flask_response_and_server_render_warning(self):
        import main
        from services import search_jobs as jobs_module
        from services.search_jobs import SearchJobs
        from time import monotonic, sleep
        from uuid import uuid4
        result = search_service.SearchResults([listing()], {"status": "failed", "warning": "Save failed"})
        manager = SearchJobs()
        try:
            with patch.object(main, "search_jobs", manager), patch.object(jobs_module, "search_products", return_value=result):
                client = main.app.test_client()
                submitted = client.post("/api/search", json={"query": "phone", "request_id": uuid4().hex})
                self.assertEqual(submitted.status_code, 202)
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    if manager.get(submitted.json["job_id"])["status"] == "completed":
                        break
                    sleep(0.005)
                response = client.get(submitted.json["results_url"])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["status"], "completed")
                self.assertTrue(response.json["success"])
                self.assertEqual(response.json["products"][0]["price"], 100)
                self.assertEqual(response.json["persistence"]["warning"], "Save failed")
                self.assertIn(b"Save failed", client.get("/?job=" + submitted.json["job_id"]).data)
                self.assertEqual(client.get("/").status_code, 200)
        finally:
            manager._executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
