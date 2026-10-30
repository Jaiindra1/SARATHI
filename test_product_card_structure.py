
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
    driver.set_window_size(1366, 900)
    driver.get("https://www.flipkart.com/")

    wait = WebDriverWait(driver, 15)

    # Locate the editable search field and submit the query.
    search_box = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, 'input[name="q"]:not([readonly])')
        )
    )
    search_box.send_keys(search_query)
    search_box.send_keys(Keys.ENTER)

    # Wait until the search results page is reached.
    wait.until(lambda browser: "/search" in browser.current_url)

    # Parse the returned HTML.
    soup = BeautifulSoup(driver.page_source, "html.parser")

    # Select the first link that resembles a product detail link.
    product_link = soup.select_one('a[href*="/p/"]')

    if product_link is None:
        print("No product-like link found.")
    else:
        print("Product link text:")
        print(product_link.get_text(" ", strip=True)[:300])

        # Walk up the HTML tree to inspect the link's parent containers.
        parent = product_link

        for level in range(1, 6):
            parent = parent.parent

            if parent is None:
                break

            print(f"\n--- Parent level {level} ---")
            print("Tag:", parent.name)
            print("Classes:", parent.get("class"))
            print("Text:", parent.get_text(" ", strip=True)[:350])
            print("HTML:", str(parent)[:700])

print("\nProduct card structure inspection completed.")
