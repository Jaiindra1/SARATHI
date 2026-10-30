
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def create_browser():
    """Create and return a Selenium-controlled Chrome browser."""

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--log-level=3")

    return webdriver.Chrome(options=options)


@contextmanager
def browser_session():
    """Create a browser and always close it when the session ends."""

    driver = create_browser()

    try:
        yield driver
    finally:
        driver.quit()
