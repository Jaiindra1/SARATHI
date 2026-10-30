"""Combined Flask -> background executor -> search service -> SQLite checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from html import unescape
from pathlib import Path
import tempfile
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch
from uuid import uuid4

import main
from config import settings
from retailers.outcomes import RetailerSearchError
from services import search_jobs as jobs_module, search_service
from services.search_jobs import SearchJobs
from services.sqlite_client import connection
from test_sqlite_integration import listing


class BackgroundPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "products.sqlite3"
        setting = patch.object(settings, "SQLITE_DATABASE_PATH", self.path)
        setting.start()
        self.addCleanup(setting.stop)
        self.manager = SearchJobs()
        self.addCleanup(self.manager._executor.shutdown, wait=True)
        route = patch.object(main, "search_jobs", self.manager)
        route.start()
        self.addCleanup(route.stop)
        self.client = main.app.test_client()

    def submit(self, query="phone", request_id=None, client=None):
        return (client or self.client).post("/api/search", json={
            "query": query, "request_id": request_id or uuid4().hex,
        })

    def finish(self, submitted):
        self.assertEqual(submitted.status_code, 202)
        job_id = submitted.json["job_id"]
        deadline = monotonic() + 4
        while monotonic() < deadline:
            job = self.manager.get(job_id, include_products=True)
            with self.manager._lock:
                active = self.manager._active
            if job["status"] in {"completed", "failed"} and active is None:
                return self.client.get(submitted.json["results_url"]).json
            sleep(0.005)
        self.fail("Background job did not finish")

    def search_record(self, job_id):
        with connection(self.path) as db:
            return json.loads(db.execute("SELECT data FROM searches WHERE search_id = ?", (job_id,)).fetchone()[0])

    def count(self, table):
        with connection(self.path) as db:
            return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_submission_progress_busy_and_results_with_real_persistence(self):
        entered, release = Event(), Event()
        def held(**kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Controlled wait expired")
            return [listing(retailer="Flipkart")]
        with patch.object(search_service, "search_flipkart", side_effect=held), patch.object(search_service, "search_amazon", return_value=[listing()]):
            try:
                start = monotonic()
                submitted = self.submit()
                self.assertLess(monotonic() - start, 1)
                self.assertTrue(entered.wait(2))
                status = self.client.get(submitted.json["status_url"])
                self.assertEqual(status.json["status"], "running")
                self.assertEqual(status.json["retailers"]["Flipkart"]["status"], "running")
                self.assertEqual(status.headers["Cache-Control"], "no-store")
                self.assertNotIn("products", status.json)
                self.assertEqual(self.client.get(submitted.json["results_url"]).status_code, 202)
                self.assertEqual(self.submit().status_code, 409)
                self.assertEqual(self.client.post("/", data={"query": "second"}).status_code, 409)
            finally:
                release.set()
            result = self.finish(submitted)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["persistence"]["search_id"], submitted.json["job_id"])
        self.assertEqual(result["persistence"]["saved_count"], 2)
        self.assertEqual(self.count("products"), 2)
        self.assertEqual(self.count("price_history"), 2)
        self.assertEqual(self.search_record(submitted.json["job_id"])["status"], "completed")

    def test_concurrent_duplicate_requests_execute_and_persist_once(self):
        entered, release = Event(), Event()
        def held(**kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Controlled wait expired")
            return [listing()]
        request_id = uuid4().hex
        def post(_):
            with main.app.test_client() as client:
                return self.submit(request_id=request_id, client=client)
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", side_effect=held) as amazon:
            try:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    responses = list(pool.map(post, range(16)))
                self.assertTrue(entered.wait(2))
                self.assertTrue(all(r.status_code == 202 for r in responses))
                self.assertEqual(len({r.json["job_id"] for r in responses}), 1)
            finally:
                release.set()
            result = self.finish(responses[0])
            repeat = self.submit(request_id=request_id)
            self.assertEqual(repeat.json["job_id"], responses[0].json["job_id"])
            self.assertEqual(repeat.json["status"], "completed")
            amazon.assert_called_once()
        self.assertEqual(result["persistence"]["status"], "saved")
        self.assertEqual(self.count("searches"), 1)
        self.assertEqual(self.count("price_history"), 1)

    def test_same_request_with_different_query_conflicts(self):
        request_id = uuid4().hex
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", return_value=[]):
            submitted = self.submit(request_id=request_id)
            self.finish(submitted)
            self.assertEqual(self.submit(query="different", request_id=request_id).status_code, 409)
        self.assertEqual(self.count("searches"), 1)

    def test_lost_response_retry_recovers_original_job(self):
        request_id = uuid4().hex
        with patch.object(search_service, "search_flipkart", return_value=[listing(retailer="Flipkart")]) as flipkart, patch.object(search_service, "search_amazon", return_value=[]):
            discarded = self.submit(request_id=request_id)
            recovered = self.submit(request_id=request_id)
            self.assertEqual(recovered.json["job_id"], discarded.json["job_id"])
            self.finish(recovered)
            flipkart.assert_called_once()
        self.assertEqual(self.count("searches"), 1)

    def test_partial_retailer_failure_persists_successful_products(self):
        with patch.object(search_service, "search_flipkart", side_effect=RetailerSearchError("Flipkart", "blocked_page")), patch.object(search_service, "search_amazon", return_value=[listing()]):
            submitted = self.submit()
            result = self.finish(submitted)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["retailers"]["Flipkart"], {"status": "failed", "stage": "blocked_page"})
        self.assertEqual(len(result["products"]), 1)
        record = self.search_record(submitted.json["job_id"])
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["retailer_errors"], ["Flipkart"])
        self.assertEqual(self.count("products"), 1)

    def test_total_failure_keeps_outcomes_and_persists_failed_search(self):
        with patch.object(search_service, "search_flipkart", side_effect=RetailerSearchError("Flipkart", "navigation_timeout")), patch.object(search_service, "search_amazon", side_effect=RetailerSearchError("Amazon", "blocked_page")):
            submitted = self.submit()
            result = self.finish(submitted)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["success"])
        self.assertEqual(result["persistence"]["status"], "saved")
        self.assertEqual(result["products"], [])
        self.assertEqual(self.search_record(submitted.json["job_id"])["status"], "failed")
        self.assertEqual(self.count("products"), 0)

    def test_storage_failure_keeps_cards_and_exposes_warning(self):
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", return_value=[listing()]), patch("services.price_tracking_service.ProductRepository", side_effect=RuntimeError("controlled storage failure")):
            submitted = self.submit()
            result = self.finish(submitted)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["products"]), 1)
        self.assertEqual(result["persistence"]["status"], "failed")
        self.assertIn("SQLite", result["persistence"]["warning"])
        page = self.client.get("/?job=" + submitted.json["job_id"])
        self.assertIn(result["persistence"]["warning"], unescape(page.get_data(as_text=True)))

    def test_database_work_never_holds_job_state_lock(self):
        entered, release = Event(), Event()
        real_track = search_service.track_search
        def held(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Controlled wait expired")
            return real_track(*args, **kwargs)
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", return_value=[]), patch.object(search_service, "track_search", side_effect=held):
            try:
                submitted = self.submit()
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.manager._lock.acquire(timeout=0.2))
                self.manager._lock.release()
                self.assertEqual(self.client.get(submitted.json["status_url"]).json["status"], "running")
            finally:
                release.set()
            self.assertEqual(self.finish(submitted)["persistence"]["status"], "saved")

    def test_direct_service_call_keeps_optional_progress_and_list_contract(self):
        events = []
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", return_value=[listing()]):
            result = search_service.search_products("phone", progress=lambda *args, **kw: events.append((args, kw)))
        self.assertIsInstance(result, list)
        self.assertEqual(result.persistence["status"], "saved")
        self.assertEqual([e[0] for e in events], [
            ("Flipkart", "running"), ("Flipkart", "empty"),
            ("Amazon", "running"), ("Amazon", "completed"),
        ])

    def test_variant_identity_survives_job_results_and_database(self):
        variants = [listing(retailer="Flipkart"), listing(retailer="Flipkart", url="https://flipkart.com/phone/p/itm123?pid=MOB456")]
        with patch.object(search_service, "search_flipkart", return_value=variants), patch.object(search_service, "search_amazon", return_value=[]):
            result = self.finish(self.submit())
        self.assertEqual(len(result["products"]), 2)
        self.assertEqual(self.count("products"), 2)

    def test_form_submission_uses_same_job_and_renders_completed_results(self):
        request_id = uuid4().hex
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", return_value=[listing()]):
            form = self.client.post("/", data={"query": "phone", "request_id": request_id})
            self.assertEqual(form.status_code, 303)
            submitted = self.submit(request_id=request_id)
            result = self.finish(submitted)
        self.assertIn(submitted.json["job_id"], form.location)
        self.assertIn(b"Example phone", self.client.get(form.location).data)
        self.assertEqual(result["persistence"]["saved_count"], 1)

    def test_invalid_ids_queries_and_unavailable_jobs(self):
        with patch.object(search_service, "search_flipkart") as flipkart:
            for data in ([], {}, {"query": []}, {"query": "phone"}, {"query": "phone", "request_id": "bad"}, {"query": "x" * 201, "request_id": uuid4().hex}):
                self.assertEqual(self.client.post("/api/search", json=data).status_code, 400)
            flipkart.assert_not_called()
        for endpoint in ("status", "results"):
            response = self.client.get("/api/search/missing/" + endpoint)
            self.assertEqual(response.status_code, 404)
            self.assertIn("restarted", response.json["message"])

    def test_unexpected_job_exception_releases_slot(self):
        with patch.object(jobs_module, "search_products", side_effect=RuntimeError("controlled failure")):
            result = self.finish(self.submit())
        self.assertEqual(result["status"], "failed")
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", return_value=[]):
            self.assertEqual(self.finish(self.submit())["status"], "completed")

    def test_expiry_does_not_delete_persisted_records(self):
        request_id = uuid4().hex
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", return_value=[]):
            submitted = self.submit(request_id=request_id)
            self.finish(submitted)
            with self.manager._lock:
                self.manager._jobs[submitted.json["job_id"]]["finished_at"] = monotonic() - 1801
            self.assertEqual(self.client.get(submitted.json["status_url"]).status_code, 404)
            self.assertEqual(self.count("searches"), 1)
            next_submission = self.submit(request_id=request_id)
            self.assertNotEqual(next_submission.json["job_id"], submitted.json["job_id"])
            self.finish(next_submission)
        self.assertEqual(self.count("searches"), 2)

    def test_submission_executor_failure_has_clear_response_and_recovers(self):
        with patch.object(self.manager._executor, "submit", side_effect=RuntimeError("controlled failure")):
            self.assertEqual(self.submit().status_code, 503)
        self.assertIsNone(self.manager._active)
        with patch.object(search_service, "search_flipkart", return_value=[]), patch.object(search_service, "search_amazon", return_value=[]):
            self.assertEqual(self.finish(self.submit())["status"], "completed")


if __name__ == "__main__":
    unittest.main()
