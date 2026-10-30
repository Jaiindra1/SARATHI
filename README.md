# SARTHI 1.2

Flask product search using the existing Amazon India and Flipkart Selenium and
BeautifulSoup scrapers. SQLite stores product observations, price history, and
search records. No AI, LLM, cloud database, credentials, or database server is used.
Existing cards, highlights, loading animation, and search endpoints are unchanged.

## Local setup

From `scraper-service` in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "from services.sqlite_client import initialize_database; initialize_database()"
python check_database.py
python main.py
```

Open http://127.0.0.1:5000. Chrome and a compatible driver must be available for
actual searches. SQLite is included in Python; no extra package is needed.
SMTP settings remain optional for feedback delivery.

## Local persistence

There was no existing SQLite file, schema, or connection utility in this checkout.
The repository interface is retained, backed by one SQLite database at
`data/products.sqlite3`. Set optional `SQLITE_DATABASE_PATH` to use another file;
relative paths resolve against the project root, absolute paths are supported.
The parent directory must be writable. Importing the application does not create
or open the database. Initialization or the first persistence operation creates
missing tables using `CREATE TABLE IF NOT EXISTS`; no table is dropped or cleared.
An incompatible existing schema is not silently reset. Back it up and inspect it
before changing its schema. Do not point this setting at an unrelated database.

HTTP routes -> SearchJobs single executor -> search_products with progress and
search_id=job_id -> existing retailer adapters/Product model -> track_search ->
SQLite repository. Each database operation owns and closes its own connection.
HTTP routes never scrape or save observations inline.

Tables:

- `products`: SHA-256 product ID, retailer-qualified identity key (unique),
  product_name, retailer, product_url, product_image, current_price, original_price,
  currency, first_seen, last_checked, price_status, and `product_data` JSON retaining
  all fields of the first normalized product observation, including specifications,
  highlights, rating, category, and availability.
- `price_history`: product_id, search_id, price, currency, recorded_at, change_type;
  primary key `(product_id, search_id)` keeps retry writes idempotent.
- `searches`: search_id primary key and merged JSON data containing the query,
  UTC timestamp, retailer outcomes, product count/IDs, and persistence status.

The repository's existing identity function is preserved: Amazon ASIN, Flipkart
PID, or retailer-qualified canonical URL. Known tracking parameters are removed;
variant parameters are retained. Names never serve as identities. Retailers remain
separate, and search-result deduplication is unchanged.

Price normalization is unchanged. Invalid/missing prices never replace a valid
stored price. First valid prices create initial history; changed prices add history;
unchanged prices update only last_checked. Older observations cannot replace newer
ones. Product metadata retains the existing first-observation behavior. All times
are stored as UTC ISO-8601 strings. Repository product reads return datetime values
for first_seen/last_checked, preserving the Python contract.

Each product read/update/history write uses one `BEGIN IMMEDIATE` transaction.
Separate connections allow thread use, with a 10-second SQLite lock wait. Failed
writes roll back; errors remain visible through the existing persistence warning
without discarding scraped cards. Search records commit separately, so interruption
may leave a search marked processing while prior product commits remain intact.

`python check_database.py` opens an existing database read-only, runs quick_check,
and prints row counts. It never creates a missing database. Back up a database
while the service is stopped or use SQLite's backup API for a consistent live copy.
Existing JSON exports and browser snapshots are left untouched, not imported or
deleted automatically. Remote records from a former cloud backend are not migrated
by this change: no export or access was supplied. Retain any needed remote data
and obtain an export for a separately verified migration before removing that data.

## Combined background-search and persistence contract

Both POST routes retain the remote job manager. The API immediately returns 202
with job/status/results URLs; ordinary form POST returns 303 to its job page.
A 128-bit client request ID makes repeat submissions return the existing job.
Reusing it with a different query returns 409. A new request while busy returns
409. Request lookup, admission, and job state remain lock-protected; only one
executor runs Selenium. Existing browser reload and lost-response recovery remain.

The service interface is:

    search_products(query, max_results=20, *, progress=None, search_id=None)

Existing CLI callers can omit both optional arguments and still receive a
list-compatible result. The background executor supplies its job ID as the stored
search ID, so retried submissions do not create duplicate search records.
The existing retailer progress callbacks are preserved.

After both sequential retailer attempts and product normalization/deduplication,
the same executor persists observations and the search summary. Database operations
run outside the job-state lock, so HTTP polling continues while saving. No second
executor, queue, database system, or dependency is introduced. SQLite's existing
10-second lock wait is per operation, not a whole-job deadline; the active slot
remains reserved until persistence finishes. A failed save retains scraped cards.

Completed job status/results include persistence with search_id, status,
saved_count, and an optional warning. JavaScript adds that warning to the
existing results area; ordinary job pages also show it. Partial retailer failures
retain successful listings and save a partial search summary. When both retailers
fail, the service records the failed search and attaches the persistence report
to the existing failure; the job still ends as failed with retailer outcomes.

Product observations and search summaries are durable only to the extent that
the SQLite file is durable. Jobs and request-ID mappings remain in memory, with
the existing 30-minute/50-completed-job retention. Restart/expiry loses those
mappings even if SQLite still has the corresponding historical search record.
No durable job resumption or cancellation is added.

The boundary fixture uses each adapter's SEARCH_URL with a fixed query. Only the
obsolete Flipkart base constant/defaults are renamed to SEARCH_BASE_URL;
SEARCH_URL, selectors, parsing, navigation, and timeout snapshots are retained.
Amazon, browser settings, and one-worker/two-gthread-thread startup are retained.

## Combined verification

Run only the named offline/localhost checks, not blanket test discovery:

    python -m unittest test_background_search test_retailer_outcomes test_sqlite_integration test_specification_extractor test_frontend_integration
    node --check static/js/search.js
    node --check test_frontend_polling.cjs
    python check_database.py

Node is used only by the frontend verification harness, with built-in Node modules;
it is not an application dependency or backend runtime. Without Node that one
harness test is explicitly skipped. All other tests use existing Python
dependencies and the standard library.

The 61 automated checks exercise the combined architecture: 202/303 submission,
running/terminal polling, shared busy protection, 16 simultaneous idempotent
submissions, lost-response recovery, optional progress callbacks, SQLite writes,
partial/total retailer failure, persistence warnings, retention, transaction
rollback, concurrent observations, and product identity/history. The JavaScript
harness runs the shipped search.js against a real local Flask server and temporary
SQLite database with a minimal DOM and substituted retailer adapters. It verifies
polling, product rendering, rupee symbols, errors, and persistence warnings.
It is not visual browser verification or a live retailer test.

No existing database is used as a test fixture. Tests create isolated temporary
databases. For manual local startup against an intended preserved database, confirm
SQLITE_DATABASE_PATH first, then run python main.py; opening the homepage does
not perform a retailer search. The database checker reads without creating a DB.
Linux/Python 3.12 Docker preflight and real retailer searches still require
separate verification; passing these checks does not establish Render success.

## Deployment persistence

Keep Render's Docker Command unset so the supplied startup script executes.
Gunicorn remains one gthread worker, two HTTP threads, and a 30-second timeout;
GUNICORN_CMD_ARGS is cleared and explicit flags/config prevent conflicting overrides.
Existing Selenium strategy/timeout environment settings are unchanged, including
the separate 15-second preflight override.

SQLite requires a writable file. The default is data/products.sqlite3 under the
project root. For persistence across redeployment/replacement, mount persistent
storage and set SQLITE_DATABASE_PATH to an absolute path on that mount. Ensure
appuser (UID 10001) can write the directory as well as its database/journal files.
Use one service instance because job state and idempotency mappings are process-local.

The image deliberately excludes local databases, exports, credentials, and tests.
Restore a consistent backup to the deployment's persistent volume separately;
deploying code does not copy the local database or migrate remote records.
If storage is ephemeral, historical records may be lost on replacement. Do not
claim durable production persistence until restart/redeployment checks establish it.

## Manual production search diagnostics

Set `SEARCH_DIAGNOSTICS=1` in the Render service's environment and deploy the
diagnostic changes. Use `sh scripts/start_render.sh` and the existing browser options.
No new dependency or diagnostic HTTP endpoint is required.

Open the deployed website, search for a common product such as `headphones`, and
inspect Render runtime logs for `[search-diagnostics]`. Each retailer attempt has
a `trace` identifier; match events using that identifier and `retailer`.

Read the sequence as follows:

- `browser_environment`: platform, Selenium version, browser/driver availability
  on PATH and in Selenium Manager's cache. False PATH flags alone do not prove
  failure: Manager may subsequently download the binaries.
- `binary_probe` / `linux_libraries`: executable version, process exit code, and
  missing Linux library names. A failed `ldd` probe does not establish that all
  dependencies are installed. Inventory runs initially and again after a failed
  launch so that newly downloaded binaries are included.
- `browser_starting` -> `browser_started`: confirms Chrome actually launched,
  with browser/driver versions. `browser_start_failed` instead provides a safe
  reason category and exception type. A generic `chrome_exited` result still
  requires investigation; it is not proof of a missing library.
- `navigation_started` -> `navigation_finished`: confirms `driver.get()` returned.
  This does not establish an HTTP 200 response from the retailer.
- `retailer_page`: reports the phase, retailer hostname category, existing card
  count, and a best-effort page category such as `captcha`, `access_denied`,
  `possible_consent`, `no_results`, or `unclassified`. Classification is diagnostic
  evidence only; unclassified does not prove the page is unblocked.
- `retailer_page` with `phase=parsed`: compare card count with the number of
  products returned by the existing parser. `retailer_failed` identifies the
  stage where the attempt stopped.

No search queries, full URLs, raw titles, page contents, credentials, or raw SDK
exception messages are emitted by these diagnostics. They do not save or replace
HTML snapshots and do not change search results. Probes are best effort and add
some startup overhead while enabled. Remove `SEARCH_DIAGNOSTICS` or set it to `0`
after collecting a failed search. Do not change selectors or install browser
components until the runtime evidence identifies what is missing or failing.


## Deterministic Render browser deployment

The production traceback showed a Gunicorn timeout while Selenium Manager was
running its discovery/download subprocess. It did not prove that either binary
was absent. Explicit executable paths remove this request-time dependency.

Use the included Dockerfile with Render's **Docker** runtime. The former native
Python build (`pip install -r requirements.txt`) alone cannot guarantee the
presence of Linux OS packages. Debian Bookworm supplies `chromium` and
`chromium-driver`; the driver depends on the exact matching Chromium package.
Apt installs their shared-library dependencies. The build checks the installed
package versions are identical and prints both executable versions.

Render configuration for the existing service (do not create a duplicate service):

- Runtime: Docker; Dockerfile path: `./Dockerfile`; build context: repository root.
- Native Build Command: no longer used. Render builds the Dockerfile automatically.
- Docker Command: leave unset so the image runs `sh scripts/start_render.sh`.
- Equivalent local image build: `docker build -t sarathi .`.
- The startup script launches a real browser on a local data URL, closes it, and
  then starts Gunicorn with the single-worker configuration documented below.
- Gunicorn's timeout is not increased. Readiness happens before Gunicorn starts.

These defaults are provided by the image; ensure existing Render environment
values do not override them with old paths:

```dotenv
CHROME_BINARY_PATH=/usr/bin/chromium
CHROMEDRIVER_PATH=/usr/bin/chromedriver
SEARCH_DIAGNOSTICS=1
CHROME_NO_SANDBOX=1
```

`CHROME_NO_SANDBOX=1` disables Chrome's internal sandbox for container
compatibility. The image runs the app and browser as the unprivileged `appuser`.
Set it to `0` if the deployment supports Chrome's sandbox. Linux also uses
`--disable-dev-shm-usage` to avoid relying on the container's small shared-memory
mount. Neither Linux option is applied on Windows.

When paths are supplied, both must exist and be executable. Bounded Linux version
checks verify matching major versions once per worker. Windows leaves compatibility
checking to ChromeDriver because Windows Chrome may not print a version to stdout. Selenium receives
`Options.binary_location` and an explicit Chrome `Service` path, which skips
Selenium Manager. Render without both paths fails immediately with a configuration
error; it does not attempt downloads. On localhost Windows, leave both variables
unset to retain the existing automatic discovery, or supply both Windows paths.
The Docker build's package check is stricter than the runtime major-version check.

Verify on Render:

1. Deploy the Docker configuration and check build logs for matching Chromium and
   ChromeDriver package/executable versions.
2. Look for `browser_configuration` with `mode=explicit` and
   `selenium_manager=false`, followed by `browser_started` and
   `browser_preflight_passed`. A failed readiness launch stops startup.
3. Open the real service website and search for `headphones`.
4. For each retailer trace, verify `browser_started`, `navigation_finished`, and
   the parsed product count. A CAPTCHA/access-denied result is a separate retailer
   blocking issue, not proof that browser startup failed.
5. Confirm the request no longer stalls inside Selenium Manager. A later timeout
   while waiting for retailer results requires separate evidence and review.

Do not claim the deployment is fixed based on package checks or the homepage
alone. Browser startup must be observed in the updated Render deployment and a
real website search. No automated test suite is required for this verification.

Sources: https://packages.debian.org/bookworm/chromium-driver and
https://render.com/docs/docker.

## Milestone 2A: bounded Selenium navigation

In the existing Render service, open **Environment**, add the following variables,
and save/redeploy the updated code. Keep the current Docker configuration,
browser paths, and use the startup script documented below:

```dotenv
SELENIUM_PAGE_LOAD_STRATEGY=eager
SELENIUM_PAGE_LOAD_TIMEOUT=8
SEARCH_DIAGNOSTICS=1
```

`SELENIUM_PAGE_LOAD_STRATEGY` accepts `normal`, `eager`, or `none`. The recommended
Render value is `eager`: navigation waits for DOM readiness instead of the full
page-load event. The existing product-element waits still determine when the
listing is ready to parse. This does not bypass retailer blocking.

`SELENIUM_PAGE_LOAD_TIMEOUT` accepts a positive finite number of seconds, including
fractional seconds. Each newly created browser receives this value through
`driver.set_page_load_timeout()`. Invalid settings fail before browser creation.
An empty value is invalid; remove the variable to retain the existing default.
If either variable is absent, its corresponding Selenium default is unchanged.
Windows localhost may leave both variables unset; the same configuration also
works with the existing explicit Linux browser and driver paths.

The startup script's existing readiness browser retains its separate explicit
15-second data-page timeout. Product searches use the configured 8-second value.
No second browser or new browser-sharing lifecycle is introduced.

Manual verification:

1. After deployment, confirm `browser_preflight_passed` and open the actual website.
2. Search for a common product such as `headphones` and follow its retailer trace
   in Render runtime logs under `[search-diagnostics]`.
3. Confirm `browser_navigation_settings` reports `page_load_strategy=eager` and
   `page_load_timeout_seconds=8.0`.
4. Navigation emits `navigation_started`, followed by `navigation_finished`,
   `navigation_timeout`, or `navigation_failed`. These events' `seconds` values
   measure navigation alone, excluding browser startup and cleanup. Failure
   events include a safe exception type/reason and `stage=navigation`, without
   logging the query, URL, raw page content, or exception message.
5. A Selenium navigation timeout follows the existing retailer failure mechanism
   with stage `navigation_timeout`. Existing partial-result behavior is retained.
6. `browser_cleanup_started` is followed by `browser_cleanup_finished`, or
   `browser_cleanup_failed` if `driver.quit()` raises. Cleanup duration is logged
   separately; the existing quit behavior and exception propagation are retained.

Limitations: the timeout is enforced by ChromeDriver, not an overall Python request
deadline. An unresponsive driver or cleanup operation may still block. Fatal
worker termination may prevent completion/failure logs from being emitted.
The 30-second Gunicorn timeout remains unchanged, as do Flipkart's 25- and
5-second product waits and Amazon's 25-second wait. In the earlier synchronous
flow, browser startups, navigation, waits, and cleanup could exceed that HTTP
worker limit. The background-search implementation below moves this work out of
the HTTP request. This navigation milestone does not add request budgets,
retries, process-killing logic, or automated test suites. Production success must
be established by a real website search and its Render logs after deployment.


## Background product searches (current architecture)

Both `POST /` and `POST /api/search` use one process-local job manager.
The API returns HTTP 202 with a random job ID immediately. The ordinary form
returns a 303 redirect to `/?job=<id>`; without JavaScript, reload that page to
check progress/results. JavaScript polls `/api/search/<id>/status` every two
seconds, then fetches `/api/search/<id>/results` and uses the existing product
cards. The URL retains the job ID so a reload can reconnect after connection loss.
Requests have 15-second deadlines; transient polling connection failures are
retried up to three attempts. Missing jobs explicitly report restart or expiry.
Terminal status and results stop polling. Partial retailer failures remain visible.

One `ThreadPoolExecutor(max_workers=1)` runs the existing search service, which
still calls Flipkart then Amazon. A lock atomically reserves the only active
slot, protects status/results, and rejects additional submissions with HTTP 409;
there is no accumulating search queue. Browser cleanup, parsing, normalization,
and deduplication are unchanged. Completed jobs include per-retailer outcomes.
Unexpected exceptions mark the job failed and release the slot. Disconnecting
an HTTP client does not cancel or corrupt the background job.

Completed/failed jobs expire after 30 minutes, with at most 50 retained. Cleanup
runs on submissions, reads, and job completion; an idle process may retain expired
records until its next operation. Active jobs are never evicted. This is a prototype:
restarts, redeploys, Render suspension, or worker termination lose all job state.
Job IDs act as access tokens; do not share result links containing private queries.
There is no durable job recovery or cancellation. SQLite retains observations and
search summaries, but does not restore process-local jobs. A stuck driver can keep
the single slot busy until it exits or the service restarts; thread cancellation
cannot safely terminate Selenium. Background execution does not bypass retailer
CAPTCHAs, IP blocking, or memory limits.

### Required web process configuration

Keep Render's Docker Command unset so the image invokes `sh scripts/start_render.sh`.
After the existing browser preflight, that script executes:

```sh
unset GUNICORN_CMD_ARGS
exec gunicorn --config /dev/null --workers 1 --worker-class gthread --threads 2 --timeout 30 --bind "0.0.0.0:${PORT:-10000}" main:app
```

Clearing `GUNICORN_CMD_ARGS`, disabling automatic config-file loading with
`--config /dev/null`, and supplying explicit flags prevents conflicting Gunicorn
environment arguments, `WEB_CONCURRENCY`, or a default config file from changing
this design. Two HTTP threads serve short requests; the one executor thread runs
Selenium. Do not enable reload, multiple workers, multiple service instances, or
an alternative startup command: separate processes cannot share these jobs.
The 30-second Gunicorn timeout is unchanged. Existing Selenium timeout environment
settings and the separate 15-second preflight timeout remain unchanged.

### Manual local verification

1. Start `python main.py` for local Windows verification (no browser preflight or
   Gunicorn). Open `http://127.0.0.1:5000/` and confirm the existing UI and feedback
   page load. This does not verify Linux startup.
2. Submit invalid input to `/api/search`; expect 400, including JSON arrays and
   non-string queries. Submit a valid query; expect 202 and a job ID promptly.
3. While running, poll status and request results; expect queued/running and
   HTTP 202 for unfinished results. Submit a second search through both API and
   ordinary form; expect 409. The homepage/status requests should remain responsive.
4. Observe Flipkart then Amazon progress. Completion must return existing product
   dictionaries. One retailer failure must preserve the other retailer's products;
   two failures must be failed, not a successful empty search. Check safe error stages.
5. Reload the job URL to reconnect. Request an unknown ID; expect 404 with an
   explicit restart/expiry message. Restart the process and reopen the old job URL;
   expect the same explanation. Closing a tab must not cancel an active search.
6. Check browser cleanup logs. Distinguish actual browser runs from controlled,
   in-process checks using substituted retailer responses; the latter verify job
   orchestration only. Do not infer live scraping success from them.
7. Where Docker is available, build/run the image and confirm browser preflight
   passes before Gunicorn starts with one gthread worker. With conflicting
   `GUNICORN_CMD_ARGS` and `WEB_CONCURRENCY`, verify those remain fixed.

### Manual Render verification after deployment

1. Deploy the updated existing Docker service; inspect build logs for matching
   Chromium/ChromeDriver. Confirm `browser_preflight_passed` precedes Gunicorn
   startup, one worker, and `Using worker: gthread`.
2. Open the real website. In browser Network tools submit `headphones`; confirm
   `/api/search` promptly returns 202 and a job ID, followed by short status polls
   rather than one long Selenium HTTP request.
3. Observe both retailer outcomes and logs; confirm real product cards appear,
   product links work, partial failures are visible, and polling stops at a terminal
   state. Record CAPTCHA/blocked/navigation failures honestly.
4. From another tab submit while busy; confirm 409 and a useful message. Check
   homepage and feedback remain usable. Disconnect/reconnect and reload the job URL.
5. Restart/redeploy, then poll an old job ID; confirm restart/expiry feedback and
   ability to submit a fresh job. Confirm unexpected failures do not leave a slot
   permanently occupied (a truly stuck driver is the limitation described above).

Local orchestration checks cannot establish production success. An actual product
search on the newly deployed Render service is required before claiming it works.


### Baseline verification before SQLite integration (historical)

Passed using Python 3.14 on Windows with Flask's in-process request client and
controlled retailer responses (no real browser searches): app import and syntax;
homepage, feedback page, static JS; invalid/malformed input rejection; immediate
202 submission (~1 ms while the controlled search remained running); status and
unfinished-results responses; API and form busy rejection; form 303 redirect;
sequential retailer execution; partial success with unchanged normalization and
URL deduplication; confirmed empty outcomes; both-retailer and unexpected failures;
executor-submission failure recovery; missing/expired job messages; 16 concurrent
submissions admitting exactly one; 50-record retention and active-job protection.

Passed JavaScript syntax and controlled Node execution with a minimal DOM:
submission/polling/results sequence; terminal completion and failure stopping
polls; partial retailer error display; missing-job message; three-attempt connection
failure limit; recovery after a transient disconnect. `git diff --check` passed.
No new test suite/files or dependencies were added.

No local checks failed. Not performed: visual browser verification, real local
Selenium searches, Linux/Python 3.12 image execution, browser preflight, or actual
Gunicorn runtime verification (Docker/shell unavailable in this Windows session).
No Render deployment or production search was performed. The Render checklist
above remains required after the user deploys these changes.
