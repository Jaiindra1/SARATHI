Create a virtual environment
Run:
python -m venv .venv

This creates an isolated Python environment inside your project.

Activate it:

.venv\Scripts\activate

## Manual production search diagnostics

Set `SEARCH_DIAGNOSTICS=1` in the Render service's environment and deploy the
diagnostic changes. Keep `gunicorn main:app` and the existing browser options.
No new dependency, frontend change, or diagnostic HTTP endpoint is required.

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
