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
  then starts `gunicorn --bind "0.0.0.0:${PORT:-10000}" main:app`.
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
