
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from core.browser import browser_session
from retailers.amazon import (
    build_amazon_search_url,
    PRODUCT_CARD_SELECTOR,
)

query = "Apple iPhone 15 Pro Max"
url = build_amazon_search_url(query)

with browser_session() as driver:
    print("Opening:", url)
    driver.get(url)

    cards = driver.find_elements(By.CSS_SELECTOR, PRODUCT_CARD_SELECTOR)
    print("Amazon product cards found:", len(cards))

    # Capture HTML while the WebDriver session is active.
    html = driver.page_source
    page_title = driver.title
    current_url = driver.current_url

# Everything below uses saved HTML; Selenium is no longer needed.
print("Page title:", page_title)
print("Current URL:", current_url)

soup = BeautifulSoup(html, "html.parser")
cards = soup.select(PRODUCT_CARD_SELECTOR)

if not cards:
    print("No matching cards in captured HTML.")
else:
    card = cards[0]

    print("\n--- Product title candidates ---")

    for selector in (
        "h2",
        "h2 span",
        "[data-cy='title-recipe']",
        "a.a-link-normal",
        "img.s-image",
    ):
        for element in card.select(selector)[:5]:
            print({
                "selector": selector,
                "tag": element.name,
                "text": element.get_text(" ", strip=True)[:180],
                "title": element.get("title"),
                "alt": element.get("alt"),
                "href": element.get("href"),
                "class": element.get("class"),
            })

    print("\n--- Product links ---")

    for anchor in card.select("a[href]"):
        href = anchor.get("href", "")

        if "/dp/" in href or "/gp/" in href:
            print({
                "href": href[:300],
                "text": anchor.get_text(" ", strip=True)[:150],
            })

    print("\n--- Price candidates ---")

    for element in card.select(
        ".a-price .a-offscreen, "
        ".a-price-whole, "
        ".a-price-fraction"
    )[:10]:
        print(element.get_text(" ", strip=True))
