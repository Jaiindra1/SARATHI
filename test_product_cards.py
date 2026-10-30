
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

    # Find the visible, editable search field.
    search_box = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, 'input[name="q"]:not([readonly])')
        )
    )

    # Enter and submit the query.
    search_box.send_keys(search_query)
    search_box.send_keys(Keys.ENTER)

    # Wait until the browser reaches a search-results URL.
    wait.until(lambda browser: "/search" in browser.current_url)

    # Allow the results page to finish its initial document loading.
    wait.until(
        lambda browser: browser.execute_script(
            "return document.readyState"
        ) == "complete"
    )

    print("\nResults URL:", driver.current_url)
    print("Page title:", driver.title)

    # Inspect links that might represent product listings.
    links = driver.find_elements(By.CSS_SELECTOR, "a[href]")

    print("\nTotal links on page:", len(links))
    print("\nFirst 15 links:")

    for index, link in enumerate(links[:15], start=1):
        print(f"\n--- Link {index} ---")
        print("Text:", link.text[:150])
        print("Href:", link.get_attribute("href"))
        print("HTML:", link.get_attribute("outerHTML")[:500])

print("\nProduct-page inspection completed.")
