"""Opt-in production diagnostics. Never log credentials, raw HTML, or unredacted retailer page text."""
import json
import logging
import os
import platform
import re
import shutil
import subprocess
from contextvars import ContextVar
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup

logger = logging.getLogger("sarathi.search_diagnostics")
_runtime_logged = False
_trace = ContextVar("search_diagnostic_trace", default=None)


def begin(retailer):
    if enabled():
        _trace.set(uuid4().hex[:12])
        event("retailer_started", retailer=retailer)


def enabled():
    return os.getenv("SEARCH_DIAGNOSTICS", "").lower() in {"1", "true", "yes"}


def event(name, **fields):
    if not enabled():
        return
    try:
        # INFO must reach stderr even when Gunicorn's root log level is WARNING.
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("[search-diagnostics] %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        logger.info(json.dumps({"event": name, "pid": os.getpid(), "trace": _trace.get(), **fields}, sort_keys=True))
    except Exception:
        pass  # Observability must never change a search outcome.


def error_details(error):
    """Classify SDK errors without emitting their message or stack trace."""
    text = " ".join(str(part).lower() for part in
                    (error, error.__cause__, error.__context__) if part is not None)
    reasons = [
        ("error while loading shared libraries", "missing_linux_library"),
        ("cannot open shared object file", "missing_linux_library"),
        ("only supports chrome version", "browser_driver_version_mismatch"),
        ("cannot find chrome binary", "browser_binary_missing"),
        ("no chrome binary", "browser_binary_missing"),
        ("unable to obtain driver", "driver_discovery_failed"),
        ("devtoolsactiveport", "chrome_startup_failed"),
        ("no usable sandbox", "sandbox_unavailable"),
        ("without --no-sandbox", "sandbox_rejected"),
        ("permission denied", "permission_denied"),
        ("dns error", "network_dns_failure"),
        ("failed to download", "download_failed"),
        ("certificate verify failed", "network_certificate_failure"),
        ("chrome instance exited", "chrome_exited"),
        ("tab crashed", "renderer_crashed"),
        ("invalid session id", "session_unavailable"),
        ("disconnected", "browser_disconnected"),
        ("chrome not reachable", "browser_unreachable"),
        ("unsupported operation", "unsupported_operation"),
        ("timed out", "timeout"),
        ("timeout", "timeout"),
    ]
    return {"error_type": type(error).__name__,
            "reason": next((reason for marker, reason in reasons if marker in text), "unclassified")}


def version_number(value):
    match = re.search(r"\b\d+(?:\.\d+){1,3}\b", str(value))
    return match.group() if match else "unknown"


def browser_environment(refresh=False):
    """Report PATH/cache availability and unresolved Linux libraries, best effort."""
    global _runtime_logged
    if not enabled() or (_runtime_logged and not refresh):
        return
    _runtime_logged = True
    try:
        from importlib.metadata import version
        browsers = [shutil.which(name) for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")]
        drivers = [shutil.which("chromedriver")]
        configured_browser = os.getenv("CHROME_BINARY_PATH")
        configured_driver = os.getenv("CHROMEDRIVER_PATH")
        # Manager cache availability is distinct from PATH availability.
        cache = Path(os.getenv("SE_CACHE_PATH") or Path.home() / ".cache" / "selenium")
        cached_chrome = list(cache.glob("chrome/**/chrome"))[:3] if cache.is_dir() else []
        cached_driver = list(cache.glob("chromedriver/**/chromedriver"))[:3] if cache.is_dir() else []
        event("browser_environment", platform=platform.system(), architecture=platform.machine(),
              selenium_version=version("selenium"), browser_on_path=any(browsers),
              driver_on_path=any(drivers), chrome_in_manager_cache=bool(cached_chrome),
              driver_in_manager_cache=bool(cached_driver),
              explicit_browser_configured=bool(configured_browser),
              explicit_driver_configured=bool(configured_driver),
              running_as_root=(os.geteuid() == 0) if hasattr(os, "geteuid") else False)
        if platform.system() == "Linux" and Path("/dev/shm").is_dir():
            space = shutil.disk_usage("/dev/shm")
            event("shared_memory", total_mb=space.total // (1024 * 1024), free_mb=space.free // (1024 * 1024))
        for kind, candidates in [("chrome", [configured_browser] + browsers + cached_chrome),
                                 ("chromedriver", [configured_driver] + drivers + cached_driver)]:
            binary = next((str(p) for p in candidates if p and Path(p).is_file()), None)
            if not binary:
                continue
            result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=3)
            missing = sorted(set(re.findall(r"\b(lib[\w.+-]+\.so(?:\.[\d]+)*)", result.stderr)))
            event("binary_probe", binary=kind, exit_code=result.returncode,
                  version=version_number(result.stdout), mentioned_libraries=missing[:15])
            if platform.system() == "Linux" and shutil.which("ldd"):
                result = subprocess.run(["ldd", binary], capture_output=True, text=True, timeout=3)
                missing = re.findall(r"\b([\w.+-]+\.so(?:\.\d+)*)\s+=>\s+not found", result.stdout)
                event("linux_libraries", binary=kind, exit_code=result.returncode,
                      missing_libraries=missing[:20])
    except Exception as error:
        event("environment_probe_incomplete", **error_details(error))


def page(retailer, driver, phase, card_selector, link_selector=None, products=None):
    """Counts and classifications only: no page title, body, query, or full URL."""
    if not enabled():
        return
    try:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).lower().split())
        markers = [
            ("captcha", "captcha"), ("robot check", "captcha"),
            ("enter the characters you see below", "captcha"),
            ("verify you are human", "captcha"), ("access denied", "access_denied"),
            ("automated access", "blocked"), ("before you continue", "possible_consent"),
            ("no results for", "no_results"), ("no results found", "no_results"),
        ]
        kind = next((kind for marker, kind in markers if marker in title or marker in text), "unclassified")
        host = (urlsplit(driver.current_url).hostname or "").removeprefix("www.")
        event("retailer_page", retailer=retailer, phase=phase,
              host=host if host in {"amazon.in", "flipkart.com"} else "other",
              page_kind=kind, cards=len(soup.select(card_selector)),
              product_links=len(soup.select(link_selector)) if link_selector else None,
              products=products)
    except Exception as error:
        event("page_probe_incomplete", retailer=retailer, phase=phase, **error_details(error))


def _safe_navigation_url(value):
    """Allow known origins/routes only; never emit query values or fragments."""
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        return {"scheme": parts.scheme if parts.scheme in {"about", "chrome", "chrome-error", "data"} else "other",
                "url": "[redacted non-http URL]"}
    host = parts.hostname or ""
    host = host if host in {"www.amazon.in", "amazon.in", "www.flipkart.com", "flipkart.com"} else "[redacted-host]"
    path = parts.path if parts.path in {"/", "/s", "/search", "/errors/validateCaptcha", "/ap/cvf"} else "/[redacted-path]"
    return {"url": f"{parts.scheme}://{host}{path}",
            "query_redacted": bool(parts.query), "fragment_redacted": bool(parts.fragment)}


def _safe_navigation_title(value):
    # Titles can contain queries, names, or tokens. Only exact generic titles
    # are safe to retain; all other titles are deliberately redacted in full.
    title = " ".join(value.split())
    safe = {"robot check", "access denied", "captcha", "privacy error",
            "this site can\u2019t be reached", "this site can't be reached",
            "amazon.in", "flipkart"}
    return {"title": title if title.lower() in safe else "[redacted]",
            "title_redacted": title.lower() not in safe, "title_length": len(title)}


def _navigation_probe(retailer, probe, operation):
    """One attempt per probe, with independent timing and safe failure details.

    WebDriver commands may stall: this adds no retries or timeout changes and
    makes no promise of an overall snapshot deadline.
    """
    started = monotonic()
    event("navigation_timeout_probe_started", retailer=retailer, probe=probe)
    try:
        fields = operation()
    except Exception as error:
        event("navigation_timeout_probe", retailer=retailer, probe=probe,
              success=False, seconds=round(monotonic() - started, 3), **error_details(error))
    else:
        event("navigation_timeout_probe", retailer=retailer, probe=probe,
              success=True, seconds=round(monotonic() - started, 3), **fields)


def navigation_timeout_snapshot(retailer, driver, requested_url, elapsed, card_selector):
    """Observe the failed navigation before cleanup; never replace its exception."""
    if not enabled():
        return
    try:
        _navigation_probe(retailer, "requested_url", lambda: {
            **_safe_navigation_url(requested_url), "navigation_seconds": round(elapsed, 3)})
        _navigation_probe(retailer, "current_url", lambda: {
            **_safe_navigation_url(driver.current_url), "driver_command_responsive": True})
        _navigation_probe(retailer, "ready_state", lambda: {
            "ready_state": driver.execute_script("return document.readyState"),
            "renderer_script_responsive": True})
        _navigation_probe(retailer, "title", lambda: _safe_navigation_title(driver.title))
        _navigation_probe(retailer, "product_cards", lambda: {
            "cards": len(driver.find_elements("css selector", card_selector))})
        _navigation_probe(retailer, "page_indicators", lambda: driver.execute_script("""
            const text = ((document.title || '') + ' ' +
                ((document.body && document.body.innerText) || '').slice(0, 200000)).toLowerCase();
            return {
                captcha: text.includes('captcha') || text.includes('verify you are human') ||
                    text.includes('enter the characters you see below'),
                access_denied: text.includes('access denied') || text.includes('automated access'),
                robot_check: text.includes('robot check'),
                chrome_error_page: location.protocol === 'chrome-error:'
            };
        """))

        def browser_errors():
            entries = driver.get_log("browser")
            # No raw messages, URLs, stack traces, cookies, or console arguments.
            # Availability depends on ChromeDriver logging; do not enable new logs.
            codes = sorted(set(re.findall(r"\b(?:net::)?ERR_[A-Z_]+\b",
                                          " ".join(str(entry.get("message", "")) for entry in entries))))
            allowed_codes = {"ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_TIMED_OUT", "ERR_CONNECTION_RESET",
                             "ERR_CONNECTION_CLOSED", "ERR_CONNECTION_REFUSED", "ERR_TIMED_OUT",
                             "ERR_CERT_AUTHORITY_INVALID", "ERR_CERT_DATE_INVALID", "ERR_SSL_PROTOCOL_ERROR",
                             "ERR_INTERNET_DISCONNECTED", "ERR_NETWORK_CHANGED", "ERR_ABORTED", "ERR_FAILED"}
            return {"entries": len(entries),
                    "severe_entries": sum(entry.get("level") == "SEVERE" for entry in entries),
                    "network_error_codes": sorted({code.removeprefix("net::") for code in codes}
                                                  & allowed_codes)[:15]}
        _navigation_probe(retailer, "browser_errors", browser_errors)
    except Exception:
        # Even unexpected instrumentation errors must leave the bare raise in
        # the retailer handler intact. Individual probe errors are handled above.
        pass


def browser_session_settings(driver, arguments):
    """Best-effort negotiated settings; a failed read cannot fail startup."""
    if not enabled():
        return
    try:
        event("browser_application_arguments", arguments=list(arguments))
        _navigation_probe("session", "negotiated_page_load_strategy", lambda: {
            "page_load_strategy": driver.capabilities.get("pageLoadStrategy", "unavailable")})
        _navigation_probe("session", "effective_page_load_timeout", lambda: {
            "page_load_timeout_seconds": driver.timeouts.page_load})
    except Exception:
        pass
