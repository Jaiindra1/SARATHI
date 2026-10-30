"""Process-local search jobs: run with exactly one web worker."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import logging
import re
from threading import Lock
from time import monotonic
from uuid import uuid4

from retailers.outcomes import AllRetailersFailed
from services.search_service import search_products

logger = logging.getLogger(__name__)


class SearchBusy(RuntimeError):
    pass


class RequestConflict(RuntimeError):
    pass


class SearchJobs:
    RETENTION_SECONDS = 30 * 60
    MAX_COMPLETED = 50

    def __init__(self):
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="product-search")
        self._jobs = {}
        self._active = None

    def _prune(self):
        # Called only under the lock. Active jobs are never removed.
        completed = sorted(
            ((key, job) for key, job in self._jobs.items() if "finished_at" in job),
            key=lambda pair: pair[1]["finished_at"],
        )
        excess = max(0, len(completed) - self.MAX_COMPLETED)
        for index, (key, job) in enumerate(completed):
            if index < excess or monotonic() - job["finished_at"] >= self.RETENTION_SECONDS:
                del self._jobs[key]

    def submit(self, query, request_id):
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
            raise ValueError("Please enter a product name of up to 200 characters.")
        query = query.strip()
        if not isinstance(request_id, str) or re.fullmatch(r"[0-9a-f]{32}", request_id) is None:
            raise ValueError("A valid client request ID (32 lowercase hexadecimal characters) is required.")
        with self._lock:
            self._prune()
            # Scan the bounded store so request IDs expire with their jobs.
            for existing in self._jobs.values():
                if existing["request_id"] == request_id:
                    if existing["query"] != query:
                        raise RequestConflict("This request ID was already used for a different search.")
                    return {"job_id": existing["job_id"], "status": existing["status"]}
            if self._active is not None:
                raise SearchBusy("Another search is running. Please try again when it finishes.")
            job_id = uuid4().hex
            self._jobs[job_id] = {
                "job_id": job_id, "request_id": request_id, "query": query, "status": "queued",
                "message": "Search queued.", "products": [],
                "retailers": {name: {"status": "queued"} for name in ("Flipkart", "Amazon")},
            }
            self._active = job_id
            try:
                self._executor.submit(self._run, job_id, query)
            except Exception:
                del self._jobs[job_id]
                self._active = None
                raise
            return {"job_id": job_id, "status": "queued"}

    def get(self, job_id, include_products=False):
        with self._lock:
            self._prune()
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return deepcopy({key: value for key, value in job.items()
                             if key not in {"finished_at", "request_id"} and (include_products or key != "products")})

    def _progress(self, job_id, retailer, status, **details):
        with self._lock:
            self._jobs[job_id]["retailers"][retailer] = {"status": status, **details}

    def _run(self, job_id, query):
        try:
            with self._lock:
                self._jobs[job_id].update(status="running", message="Searching Flipkart and Amazon...")
            products = search_products(
                query, max_results=20,
                progress=lambda retailer, status, **details: self._progress(job_id, retailer, status, **details),
            )
            with self._lock:
                self._jobs[job_id].update(
                    status="completed", products=products,
                    message="Products found successfully." if products else "No matching products found. Try another search.",
                )
        except Exception as error:
            logger.error("Background search failed job_id=%s error_type=%s", job_id, type(error).__name__)
            with self._lock:
                self._jobs[job_id].update(
                    status="failed",
                    message=("Retailer searches are unavailable. Please try again later."
                             if isinstance(error, AllRetailersFailed)
                             else "Product search failed unexpectedly. Please try again later."),
                )
                for outcome in self._jobs[job_id]["retailers"].values():
                    if outcome["status"] in {"queued", "running"}:
                        outcome.update(status="failed", stage="job_failure")
        finally:
            with self._lock:
                self._jobs[job_id]["finished_at"] = monotonic()
                self._active = None
                self._prune()


search_jobs = SearchJobs()
