
"""
Inspect retailer search pages using Selenium.

This module saves page-inspection artifacts only.
It does NOT extract product records or write response.json.
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from core.browser import browser_session


# Product searches to inspect.
# Add or remove search terms as needed.
SEARCH_QUERIES = {
        "mobile": "mobiles",
        "sofa": "sofa",
        "teddy_bear": "teddy bear",
        "car": "toy car",
        "Fashion": "store",
        "Electronics": "electronics",
        "Home": "home products",
        "Furniture": "furniture",
        "Books": "books",
        "2 weelers": "two wheeler",
}

# Base URL of the retailer search page.
SEARCH_URL = "https://www.flipkart.com/search?q={query}"

# Keep inspection files separate from product data.
OUTPUT_DIR = (
    Path(__file__).resolve().parent
    / "page_inspections"
    / "selenium_dom_audit"
)

# CSS properties useful for identifying product-card structure.
STYLE_PROPERTIES = [
    "display",
    "position",
    "visibility",
    "color",
    "backgroundColor",
    "fontSize",
    "fontWeight",
    "lineHeight",
    "width",
    "height",
    "padding",
    "margin",
    "overflow",
    "flexDirection",
    "gridTemplateColumns",
]


def safe_filename(value):
    """Convert a search term into a filesystem-safe filename."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")


def inspect_page(driver, query_name, query):
    """Open a search page and save its rendered structure."""

    filename = safe_filename(query_name)
    search_url = SEARCH_URL.format(query=quote_plus(query))

    print(f"\nInspecting: {query}")
    print(f"URL: {search_url}")

    driver.get(search_url)

    # Wait for the page body to exist.
    WebDriverWait(driver, 25).until(
        lambda browser: browser.find_element(By.TAG_NAME, "body")
    )

    # Allow JavaScript-rendered content to settle.
    time.sleep(3)

    # Scroll gradually to trigger lazy-loaded page elements.
    # This does not extract or save product records.
    for _ in range(4):
        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);"
        )
        time.sleep(1.5)

    # Return to the top before taking the screenshot.
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

    # Create a separate folder for this search.
    search_dir = OUTPUT_DIR / filename
    search_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save the complete rendered HTML.
    html_path = search_dir / "page.html"
    html_path.write_text(
        driver.page_source,
        encoding="utf-8",
    )

    # 2. Save a screenshot of the current browser viewport.
    screenshot_path = search_dir / "page.png"
    screenshot_saved = driver.save_screenshot(
        str(screenshot_path)
    )

    # 3. Inspect every element currently present in the DOM.
    # This captures attributes and selected computed CSS properties.
    dom_inventory = driver.execute_script(
        """
        const styleProperties = arguments[0];

        return Array.from(document.querySelectorAll("*")).map((el, index) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();

            const computedStyles = {};
            for (const property of styleProperties) {
                computedStyles[property] = style[property];
            }

            return {
                index: index,
                tag: el.tagName.toLowerCase(),
                id: el.id || "",
                classes: Array.from(el.classList),
                attributes: Object.fromEntries(
                    Array.from(el.attributes).map(
                        attr => [attr.name, attr.value]
                    )
                ),
                text: (el.innerText || el.textContent || "")
                    .replace(/\\\\s+/g, " ")
                    .trim()
                    .slice(0, 500),
                visible: (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden"
                ),
                rectangle: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height)
                },
                computedStyles: computedStyles
            };
        });
        """,
        STYLE_PROPERTIES,
    )

    inventory_path = search_dir / "dom_inventory.json"
    inventory_path.write_text(
        json.dumps(dom_inventory, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 4. Record page metadata and linked stylesheets.
    metadata = driver.execute_script(
        """
        return {
            title: document.title,
            currentUrl: window.location.href,
            readyState: document.readyState,
            documentWidth: document.documentElement.scrollWidth,
            documentHeight: document.documentElement.scrollHeight,
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
            elementCount: document.querySelectorAll("*").length,
            stylesheets: Array.from(document.styleSheets).map(sheet => ({
                href: sheet.href,
                disabled: sheet.disabled,
                media: sheet.media ? sheet.media.mediaText : ""
            })),
            externalScripts: Array.from(document.scripts)
                .map(script => script.src)
                .filter(Boolean)
        };
        """
    )

    metadata["searchQuery"] = query
    metadata["requestedUrl"] = search_url

    metadata_path = search_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Page title: {metadata['title']}")
    print(f"DOM elements: {metadata['elementCount']}")
    print(f"HTML: {html_path}")
    print(f"DOM inventory: {inventory_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Screenshot saved: {screenshot_saved}")

    return metadata


def main():
    """Inspect each search using one browser session."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    summaries = []

    with browser_session() as driver:
        for query_name, query in SEARCH_QUERIES.items():
            try:
                summary = inspect_page(
                    driver,
                    query_name,
                    query,
                )
                summaries.append(summary)

            except Exception as error:
                # Preserve the remaining inspections if one search fails.
                print(f"Inspection failed for '{query}': {error}")

    # Save only an inspection summary, never product records.
    summary_path = OUTPUT_DIR / "inspection_summary.json"
    summary_path.write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nInspection finished.")
    print(f"Inspection files: {OUTPUT_DIR}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
