
from urllib.parse import quote
from core.browser import browser_session
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

search_query = input("Enter a product query to test search input: ").strip()

if not search_query:
    raise ValueError("Search query cannot be empty.")

with browser_session() as driver:
    driver.get("https://www.flipkart.com/")
    driver.set_window_size(1366, 900)

    wait = WebDriverWait(driver, 15)

    # Locate a visible, editable search field.
    search_box = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, 'input[name="q"]:not([readonly])')
        )
    )

        # Re-find the editable search field immediately before typing.
    search_box = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, 'input[name="q"]:not([readonly])')
        )
    )

    # Enter the query without an explicit click.
    search_box.send_keys(search_query)

    # Check the actual input value.
    entered_value = search_box.get_attribute("value")
    print("Expected query:", repr(search_query))
    print("Actual field value:", repr(entered_value))

    # Read the value back from the actual input.
    entered_value = search_box.get_attribute("value")

    print("Expected query:", repr(search_query))
    print("Actual field value:", repr(entered_value))

    # Do not submit if the input value does not match.
    if entered_value != search_query:
        print("Query entry failed. Search will not be submitted.")
    else:
        print("Query entry successful.")

        # Submit using Enter, as a user would.
        search_box.send_keys(Keys.ENTER)

        # Wait for the search URL to contain the encoded query.
        expected_query = quote(search_query)
        wait.until(lambda browser: expected_query in browser.current_url)

        print("\n--- Search Results Verification ---")
        print("Results page URL:", driver.current_url)
        print("Results page title:", driver.title)
        print("Search submitted successfully.")

print("\nSearch query test completed.")
