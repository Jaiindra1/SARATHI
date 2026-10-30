
from bs4 import BeautifulSoup
from core.browser import browser_session
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

search_query = input("Enter a product query: ").strip()

if not search_query:
    raise ValueError("Search query cannot be empty.")

with browser_session() as driver:
    # Open Flipkart using a desktop-sized viewport.
    driver.set_window_size(1366, 900)
    driver.get("https://www.flipkart.com/")

    wait = WebDriverWait(driver, 15)

    # Find the editable search field.
    search_box = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, 'input[name="q"]:not([readonly])')
        )
    )

    # Submit the search query.
    search_box.send_keys(search_query)
    search_box.send_keys(Keys.ENTER)

    # Wait for the results page to load.
    wait.until(lambda browser: "/search" in browser.current_url)
    wait.until(
        lambda browser: browser.execute_script(
            "return document.readyState"
        ) == "complete"
    )

    # Parse the current page HTML with BeautifulSoup.
    soup = BeautifulSoup(driver.page_source, "html.parser")

    # Find links whose URLs resemble Flipkart product-detail pages.
    product_links = soup.select('a[href*="/p/"]')

    print("\nProduct-like links found:", len(product_links))

    # Print only the first five for manual inspection.
    for index, link in enumerate(product_links[:5], start=1):
        print(f"\n--- Product-like link {index} ---")
        print("Link text:", link.get_text(" ", strip=True)[:250])
        print("Href:", link.get("href"))
        print("CSS classes:", link.get("class"))

print("\nProduct HTML inspection completed.")
