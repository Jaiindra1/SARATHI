"""Milestone 1: no live browsers, retailer traffic, or cloud credentials."""
import unittest
from time import monotonic, sleep
from uuid import uuid4
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import TimeoutException, WebDriverException

import main
from retailers import amazon, flipkart
from retailers.outcomes import AllRetailersFailed, RetailerSearchError
from services import search_service
from services.search_jobs import SearchJobs


def product(retailer):
    return {
        "name": "Example headphones", "price": 999, "rating": 4.5,
        "retailer": retailer,
        "url": ("https://amazon.in/dp/B012345678" if retailer == "Amazon"
                else "https://flipkart.com/headphones/p/itm123?pid=TEST123"),
    }


class SearchOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.persistence = patch.object(search_service, "track_search", return_value={"status": "saved"})
        self.track = self.persistence.start()
        self.addCleanup(self.persistence.stop)
        self.manager = SearchJobs()
        self.route = patch.object(main, "search_jobs", self.manager)
        self.route.start()
        self.addCleanup(self.route.stop)
        self.addCleanup(self.manager._executor.shutdown, wait=True)
        self.client = main.app.test_client()

    def search(self, amazon_result, flipkart_result):
        def outcome(value):
            return {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
        with patch.object(search_service, "search_amazon", **outcome(amazon_result)) as a, \
             patch.object(search_service, "search_flipkart", **outcome(flipkart_result)) as f:
            submission = self.client.post("/api/search", json={"query": "headphones", "request_id": uuid4().hex})
            self.assertEqual(submission.status_code, 202)
            deadline = monotonic() + 3
            while monotonic() < deadline:
                status = self.client.get(submission.json["status_url"]).json
                if status["status"] in {"completed", "failed"}:
                    break
                sleep(0.005)
            self.assertIn(status["status"], {"completed", "failed"})
            response = self.client.get(submission.json["results_url"])
            a.assert_called_once()
            f.assert_called_once()
        return response

    def assert_success(self, response, retailers):
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual([p["retailer"] for p in data["products"]], retailers)
        if retailers:
            expected = {"name", "price", "rating", "url", "image_url", "retailer",
                        "category", "specifications", "availability", "original_price", "highlights"}
            self.assertEqual(set(data["products"][0]), expected)

    def test_both_succeed_with_products(self):
        self.assert_success(self.search([product("Amazon")], [product("Flipkart")]), ["Flipkart", "Amazon"])
        self.assertEqual(self.track.call_args.args[2], [])

    def test_amazon_succeeds_flipkart_fails(self):
        response = self.search([product("Amazon")], RetailerSearchError("Flipkart", "browser_startup"))
        self.assert_success(response, ["Amazon"])
        self.assertEqual(self.track.call_args.args[2], ["Flipkart"])

    def test_flipkart_succeeds_amazon_fails(self):
        response = self.search(RetailerSearchError("Amazon", "navigation_timeout"), [product("Flipkart")])
        self.assert_success(response, ["Flipkart"])
        self.assertEqual(self.track.call_args.args[2], ["Amazon"])

    def test_both_fail_marks_background_job_failed(self):
        response = self.search(RetailerSearchError("Amazon", "blocked_page"),
                               RetailerSearchError("Flipkart", "results_timeout"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "failed")
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["products"], [])
        self.assertIn("retailers", data)
        self.assertIn("persistence", data)
        self.assertNotIn("No matching", data["message"])

    def test_both_successful_empty_preserves_no_results(self):
        response = self.search([], [])
        self.assert_success(response, [])
        self.assertEqual(response.json["message"], "No matching products found. Try another search.")
        self.assertEqual(self.track.call_args.args[2], [])

    def test_one_empty_success_and_one_failure_is_not_total_failure(self):
        for a, f in [([], RetailerSearchError("Flipkart", "browser_startup")),
                     (RetailerSearchError("Amazon", "browser_startup"), [])]:
            with self.subTest(amazon=a):
                self.assert_success(self.search(a, f), [])

    def test_one_empty_and_one_products(self):
        self.assert_success(self.search([], [product("Flipkart")]), ["Flipkart"])
        self.assert_success(self.search([product("Amazon")], []), ["Amazon"])

    def test_unexpected_retailer_errors_do_not_leak_exception_text(self):
        with self.assertLogs("services.search_service", level="ERROR") as logs:
            response = self.search(RuntimeError("SECRET query and credentials"), [])
        self.assert_success(response, [])
        self.assertNotIn("SECRET", " ".join(logs.output))
        self.assertIn("unexpected_failure", " ".join(logs.output))

    def test_invalid_query_does_not_call_retailers(self):
        with patch.object(search_service, "search_amazon") as a, patch.object(search_service, "search_flipkart") as f:
            response = self.client.post("/api/search", json={"query": " "})
        self.assertEqual(response.status_code, 400)
        a.assert_not_called()
        f.assert_not_called()


class RetailerBoundaryTests(unittest.TestCase):
    cases = [(amazon, amazon.search_amazon, "Amazon", "parse_amazon_product_cards"),
             (flipkart, flipkart.search_flipkart, "Flipkart", "parse_product_cards")]

    def test_browser_failures_raise_by_default_and_with_legacy_keyword(self):
        for module, search, retailer, _ in self.cases:
            for options in [{}, {"raise_on_error": True}, {"raise_on_error": False}]:
                with self.subTest(retailer=retailer, options=options), \
                     patch.object(module, "browser_session", side_effect=WebDriverException("SECRET startup detail")), \
                     self.assertLogs("retailers.outcomes", level="ERROR") as logs:
                    with self.assertRaises(RetailerSearchError) as raised:
                        search("headphones", **options)
                    self.assertEqual(raised.exception.stage, "browser_startup")
                    self.assertNotIn("SECRET", str(raised.exception))
                    self.assertNotIn("SECRET", " ".join(logs.output))

    def run_fake_page(self, module, search, html, parse_result=None, wait_error=None, navigation_error=None, parse_error=None):
        driver = MagicMock()
        driver.page_source = html
        driver.current_url = module.SEARCH_URL.format(query="headphones")
        driver.find_elements.return_value = []
        if navigation_error:
            driver.get.side_effect = navigation_error
        parser = "parse_amazon_product_cards" if module is amazon else "parse_product_cards"
        with patch.object(module, "browser_session") as session, \
             patch.object(module, "WebDriverWait") as wait, \
             patch.object(module, parser, return_value=parse_result or []) as parse:
            session.return_value.__enter__.return_value = driver
            if wait_error:
                wait.return_value.until.side_effect = wait_error
            if parse_error:
                parse.side_effect = parse_error
            return search("headphones")

    def test_explicit_empty_pages_return_empty_on_results_timeout(self):
        for module, search, retailer, _ in self.cases:
            html = "<h1>No results for headphones</h1>" if retailer == "Amazon" else "<h1>Sorry, no results found!</h1>"
            with self.subTest(retailer=retailer):
                self.assertEqual(self.run_fake_page(module, search, html, wait_error=TimeoutException()), [])

    def test_successful_product_lists_unchanged(self):
        for module, search, retailer, _ in self.cases:
            expected = [product(retailer)]
            with self.subTest(retailer=retailer):
                self.assertEqual(self.run_fake_page(module, search, "<p>Products</p>", parse_result=expected), expected)

    def test_unknown_timeout_is_failure_not_empty(self):
        for module, search, retailer, _ in self.cases:
            with self.subTest(retailer=retailer), self.assertRaises(RetailerSearchError) as raised:
                self.run_fake_page(module, search, "<p>Unexpected page</p>", wait_error=TimeoutException())
            self.assertEqual(raised.exception.stage, "results_timeout")

    def test_blocked_page_takes_precedence_over_empty_marker(self):
        for module, search, retailer, _ in self.cases:
            with self.subTest(retailer=retailer), self.assertRaises(RetailerSearchError) as raised:
                self.run_fake_page(module, search, "<p>CAPTCHA No results for headphones</p>", wait_error=TimeoutException())
            self.assertEqual(raised.exception.stage, "blocked_page")

    def test_navigation_timeout_is_distinct(self):
        for module, search, retailer, _ in self.cases:
            with self.subTest(retailer=retailer), self.assertRaises(RetailerSearchError) as raised:
                self.run_fake_page(module, search, "", navigation_error=TimeoutException("SECRET"))
            self.assertEqual(raised.exception.stage, "navigation_timeout")

    def test_unparseable_nonempty_page_is_failure(self):
        for module, search, retailer, _ in self.cases:
            with self.subTest(retailer=retailer), self.assertRaises(RetailerSearchError) as raised:
                self.run_fake_page(module, search, "<p>Products are here but parser rejected them</p>")
            self.assertEqual(raised.exception.stage, "parsing_failure")

    def test_parser_exception_is_failure(self):
        for module, search, retailer, _ in self.cases:
            with self.subTest(retailer=retailer), self.assertRaises(RetailerSearchError) as raised:
                self.run_fake_page(module, search, "<p>Products</p>", parse_error=ValueError("SECRET"))
            self.assertEqual(raised.exception.stage, "parsing")

    def test_no_results_words_in_scripts_are_not_empty_evidence(self):
        for module, search, retailer, _ in self.cases:
            with self.subTest(retailer=retailer), self.assertRaises(RetailerSearchError):
                self.run_fake_page(module, search, "<script>No results for; no results found</script>", wait_error=TimeoutException())


if __name__ == "__main__":
    unittest.main()
