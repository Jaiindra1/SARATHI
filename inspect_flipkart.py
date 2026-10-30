
from pathlib import Path
import re

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.browser import browser_session


# Store inspected pages in a separate folder.
OUTPUT_DIR = Path("page_inspections")
OUTPUT_DIR.mkdir(exist_ok=True)

# Inspect a few representative products from different categories.
SEARCHES = [
    "Sofa",
    "Smart TV",
    "Refrigerator",
    "Washing Machine",
    "Mobiles",
    "Teddy Bear",
]


def safe_filename(value: str) -> str:
    """Convert a search query into a safe filename."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")


def inspect_search(query: str) -> None:
    """Save a retailer search page and print its product-link structure."""

    print(f"\n{'=' * 70}")
    print(f"Inspecting: {query}")
    print("=" * 70)

    with browser_session() as driver:
        # Use a consistent desktop viewport.
        driver.set_window_size(1366, 900)
        driver.get("https://www.flipkart.com/")

        wait = WebDriverWait(driver, 25)

        # Find the editable search input.
        search_box = wait.until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, 'input[name="q"]:not([readonly])')
            )
        )

        # Submit the selected product query.
        search_box.send_keys(query)
        search_box.send_keys(Keys.ENTER)

        # Wait until the browser reaches a search URL.
        wait.until(lambda browser: "/search" in browser.current_url)

        # Allow product links to appear before inspecting the page.
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'a[href*="/p/"]')
            )
        )

        # Save the complete current page HTML for later analysis.
        filename = safe_filename(query) + ".html"
        output_path = OUTPUT_DIR / filename
        output_path.write_text(
            driver.page_source,
            encoding="utf-8",
        )

        print("Page title:", driver.title)
        print("Page URL:", driver.current_url)
        print("Saved HTML:", output_path.resolve())

        # Print a sample of candidate product links.
        links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/p/"]')
        print("Candidate product links:", len(links))

        for index, link in enumerate(links[:3], start=1):
            text = " ".join((link.text or "").split())
            href = link.get_attribute("href") or ""

            print(f"\nLink {index}")
            print("Text:", repr(text[:250]))
            print("URL:", href[:250])
            print("HTML:", (link.get_attribute("outerHTML") or "")[:500])
            print(
                "PARENT HTML:",
                (link.find_element(By.XPATH, "..").get_attribute("outerHTML") or "")[:2000]
            )


if __name__ == "__main__":
    for search_query in SEARCHES:
        try:
            inspect_search(search_query)
        except Exception as error:
            # Continue inspecting other categories if one search fails.
            print(f"Inspection failed for {search_query}: {error}")
