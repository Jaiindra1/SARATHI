"""Exercise shipped JavaScript against a real local Flask/SQLite test server."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from werkzeug.serving import make_server
import main
from config import settings
from retailers.outcomes import RetailerSearchError
from services import search_service
from services.search_jobs import SearchJobs
from services.sqlite_client import connection
from test_sqlite_integration import listing


class FrontendPollingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is needed only for JavaScript verification")
    def test_real_api_polling_rendering_and_lost_response_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "frontend.sqlite3"
            manager = SearchJobs()
            real_track = search_service.track_search

            def adapter(retailer):
                def run(query, **kwargs):
                    if query == "both-fail":
                        raise RetailerSearchError(retailer, "blocked_page")
                    return [listing(retailer=retailer)]
                return run

            class FailedRepository:
                def save_search(self, *args, **kwargs):
                    raise OSError("Controlled unavailable storage")

            def track(query, *args, **kwargs):
                if query == "storage-failure":
                    kwargs["repository"] = FailedRepository()
                return real_track(query, *args, **kwargs)

            with patch.object(settings, "SQLITE_DATABASE_PATH", database), patch.object(main, "search_jobs", manager), \
                 patch.object(search_service, "search_flipkart", side_effect=adapter("Flipkart")), \
                 patch.object(search_service, "search_amazon", side_effect=adapter("Amazon")), \
                 patch.object(search_service, "track_search", side_effect=track):
                server = make_server("127.0.0.1", 0, main.app, threaded=True)
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    env = dict(os.environ, SARATHI_TEST_BASE_URL=f"http://127.0.0.1:{server.server_port}")
                    result = subprocess.run(["node", "test_frontend_polling.cjs"], env=env,
                                            capture_output=True, text=True, encoding="utf-8", timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    print(result.stdout.strip())
                    # The lost response must not create a second stored search.
                    with connection(database) as db:
                        self.assertEqual(db.execute("SELECT COUNT(*) FROM searches").fetchone()[0], 2)
                        self.assertEqual(db.execute("SELECT COUNT(*) FROM products").fetchone()[0], 2)
                        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
                    server.server_close()
                    manager._executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
