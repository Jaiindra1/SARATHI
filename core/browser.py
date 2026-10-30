
from contextlib import contextmanager
from time import monotonic

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from core import search_diagnostics as diagnostics


def create_browser():
    """Create and return a Selenium-controlled Chrome browser."""

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--log-level=3")

    diagnostics.browser_environment()
    started = monotonic()
    diagnostics.event("browser_starting")
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as error:
        diagnostics.event("browser_start_failed", seconds=round(monotonic() - started, 2),
                          **diagnostics.error_details(error))
        # Manager may have downloaded a binary since the initial inventory.
        diagnostics.browser_environment(refresh=True)
        raise
    if diagnostics.enabled():
        try:
            capabilities = driver.capabilities
            diagnostics.event("browser_started", seconds=round(monotonic() - started, 2),
                              browser_version=diagnostics.version_number(capabilities.get("browserVersion")),
                              driver_version=diagnostics.version_number(capabilities.get("chrome", {}).get("chromedriverVersion")))
        except Exception:
            diagnostics.event("browser_started", versions="unavailable")
    return driver


@contextmanager
def browser_session():
    """Create a browser and always close it when the session ends."""

    driver = create_browser()

    try:
        yield driver
    finally:
        driver.quit()
