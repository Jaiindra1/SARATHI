import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from core.browser import browser_session


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

OUTPUT_FILE = Path("response.json")
INSPECTION_DIR = Path("page_inspections")
PRODUCTS_PER_QUERY = 10

PRODUCT_QUERIES = {
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

# Flipkart currently uses two product-card layouts in the saved HTML:
# a compact/mobile-style card and a regular grid card.
PRODUCT_CARD_SELECTOR = (
    "div.jIjQ8S[data-tkid], "
    "div.RGLWAk[data-tkid]"
)

MOBILE_CARD_SELECTOR = "div.jIjQ8S[data-tkid]"
GRID_CARD_SELECTOR = "div.RGLWAk[data-tkid]"

INSPECTION_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# Small, defensive extraction helpers
# ---------------------------------------------------------

def get_text(element):
    """Return trimmed element text, or an empty string if unavailable."""

    try:
        return (element.text or "").strip()
    except Exception:
        return ""


def find_first_element(parent, selector):
    """Return the first matching descendant, or None if it is absent."""

    try:
        elements = parent.find_elements(By.CSS_SELECTOR, selector)
        return elements[0] if elements else None
    except Exception:
        return None


def parse_rupee_amount(text):
    """
    Parse a price from an already isolated price element.

    The rupee symbol is required so nearby numbers such as '50% off'
    cannot be mistaken for part of the price.
    Return an int for whole-rupee values and a float for decimal values.
    """

    match = re.search(
        r"₹\s*([\d,]+(?:\.\d{1,2})?)",
        text or "",
    )

    if not match:
        return None

    normalized = match.group(1).replace(",", "")

    try:
        amount = float(normalized)
    except ValueError:
        return None

    if not amount >= 0:
        return None

    return int(amount) if amount.is_integer() else amount


def extract_prices(card):
    """
    Extract selling and original prices from their dedicated DOM elements.

    Do not parse the combined card text: it may contain the discount
    percentage immediately after the original price.
    """

    selling_element = find_first_element(
        card,
        ".QiMO5r > .hZ3P6w",
    )
    original_element = find_first_element(
        card,
        ".QiMO5r > .kRYCnD",
    )

    current_price = parse_rupee_amount(get_text(selling_element))
    original_price = parse_rupee_amount(get_text(original_element))

    # Reject an implausible original price rather than guessing.
    if (
        current_price is not None
        and original_price is not None
        and original_price <= current_price
    ):
        original_price = None

    return current_price, original_price


def get_product_path(url):
    """Return a URL path without its query string or trailing slash."""

    return urlparse(url or "").path.rstrip("/")


def get_card_layout(card):
    """Identify the audited card layout from its class name."""

    try:
        classes = card.get_attribute("class") or ""
    except Exception:
        classes = ""

    if "jIjQ8S" in classes:
        return "mobile"

    if "RGLWAk" in classes:
        return "grid"

    return "unknown"


def extract_product_url(card, layout):
    """Get the product URL from the appropriate link within this card."""

    if layout == "mobile":
        selectors = (
            "a.k7wcnx[href*='/p/']",
            "a[href*='/p/']",
        )
    else:
        selectors = (
            "a.pIpigb[title][href*='/p/']",
            "a.GnxRXv[href*='/p/']",
            "a[href*='/p/']",
        )

    for selector in selectors:
        link = find_first_element(card, selector)
        if link is None:
            continue

        try:
            url = (link.get_attribute("href") or "").strip()
        except Exception:
            url = ""

        if get_product_path(url):
            return url

    return ""


def extract_product_name(card, layout):
    """Read the full product name from the layout-specific title element."""

    if layout == "mobile":
        title_element = find_first_element(card, ".RG5Slk")
        return get_text(title_element)

    title_link = find_first_element(
        card,
        "a.pIpigb[title][href*='/p/']",
    )

    if title_link is not None:
        try:
            title = (title_link.get_attribute("title") or "").strip()
        except Exception:
            title = ""

        if title:
            return title

        # The visible grid title can be truncated; text is only a fallback.
        return get_text(title_link)

    return ""


def extract_rating(card):
    """Extract an optional rating without interpreting review-count text."""

    rating_element = find_first_element(card, ".MKiFS6")
    rating_text = get_text(rating_element)

    match = re.search(r"(?<!\d)([0-5](?:\.\d)?)(?!\d)", rating_text)
    if not match:
        return None

    try:
        rating = float(match.group(1))
    except ValueError:
        return None

    return rating if 0 <= rating <= 5 else None


def extract_image_url(card, layout):
    """Prefer the primary product image; ignore unrelated icon images."""

    if layout == "mobile":
        image_selector = "a.k7wcnx img.UCc1lI"
    else:
        image_selector = "a.GnxRXv[href*='/p/'] img.UCc1lI"

    images = []

    try:
        images = card.find_elements(By.CSS_SELECTOR, image_selector)
    except Exception:
        pass

    # Defensive fallback for small future markup changes, still card-scoped.
    if not images:
        try:
            images = card.find_elements(By.CSS_SELECTOR, "img.UCc1lI")
        except Exception:
            images = []

    for image in images:
        candidate = ""

        for attribute in ("src", "data-src", "data-lazy-src"):
            try:
                candidate = (image.get_attribute(attribute) or "").strip()
            except Exception:
                candidate = ""

            if candidate:
                break

        if (
            candidate.startswith("https://")
            and "rukminim" in candidate.lower()
        ):
            return candidate

    return None


# ---------------------------------------------------------
# Extract one product from one product card
# ---------------------------------------------------------

def extract_product(card, category):
    """
    Extract one record using only elements inside the identified card.

    Both audited layouts are supported. Missing optional data stays None;
    the scraper does not infer values from unrelated card text.
    """

    layout = get_card_layout(card)

    name = extract_product_name(card, layout)
    product_url = extract_product_url(card, layout)

    if not name or not get_product_path(product_url):
        return None

    current_price, original_price = extract_prices(card)
    rating = extract_rating(card)
    image_url = extract_image_url(card, layout)

    return {
        "name": name,
        "price": current_price,
        "original_price": original_price,
        "rating": rating,
        "url": product_url,
        "image_url": image_url,
        "retailer": "Flipkart",
        "category": category,
    }


# ---------------------------------------------------------
# Search and collect products
# ---------------------------------------------------------

def search_products(driver, category, query):
    search_url = (
        "https://www.flipkart.com/search?q="
        + quote(query)
    )

    print(f"\nSearching: {category} ({query})")

    try:
        driver.get(search_url)

        WebDriverWait(driver, 25).until(
            lambda browser: browser.find_elements(
                By.CSS_SELECTOR,
                PRODUCT_CARD_SELECTOR,
            )
        )

        # Give the already-present product cards a short time to settle.
        time.sleep(2)

    except Exception as error:
        print(f"Search did not load for {category}: {error}")

        diagnostic_file = INSPECTION_DIR / f"{category}_failed.html"
        diagnostic_file.write_text(
            driver.page_source,
            encoding="utf-8",
        )

        return []

    cards = driver.find_elements(
        By.CSS_SELECTOR,
        PRODUCT_CARD_SELECTOR,
    )

    products = []
    seen_urls = set()

    for card in cards:
        if len(products) >= PRODUCTS_PER_QUERY:
            break

        try:
            product = extract_product(card, category)

            if not product:
                continue

            product_path = get_product_path(product["url"])

            if not product_path or product_path in seen_urls:
                continue

            # Keep the existing output contract: records need a usable
            # selling price and primary product image.
            if product["price"] is None or not product["image_url"]:
                continue

            seen_urls.add(product_path)
            products.append(product)

        except Exception as error:
            print(f"Skipped one product: {error}")

    print(f"Collected {len(products)} products for {category}")

    if not products:
        diagnostic_file = INSPECTION_DIR / f"{category}_no_products.html"
        diagnostic_file.write_text(
            driver.page_source,
            encoding="utf-8",
        )

    return products


# ---------------------------------------------------------
# Validate and save the catalogue
# ---------------------------------------------------------

def main():
    catalogue = {}

    with browser_session() as driver:
        for category, query in PRODUCT_QUERIES.items():
            catalogue[category] = search_products(
                driver,
                category,
                query,
            )

    OUTPUT_FILE.write_text(
        json.dumps(catalogue, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    total_products = sum(
        len(products)
        for products in catalogue.values()
    )

    print("\n========== SCRAPING SUMMARY ==========")
    print(f"Total products saved: {total_products}")
    print(f"Output file: {OUTPUT_FILE.resolve()}")

    for category, products in catalogue.items():
        print(f"{category}: {len(products)} products")

    print("\nCheck response.json before using these records.")
    print("=======================================")


if __name__ == "__main__":
    main()
