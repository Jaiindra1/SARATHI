
from core.browser import browser_session
from selenium.webdriver.common.by import By

# Open Flipkart using our existing browser manager.
with browser_session() as driver:
    driver.get("https://www.flipkart.com/")

    # Find every input element currently available on the page.
    inputs = driver.find_elements(By.TAG_NAME, "input")

    print(f"Total input elements found: {len(inputs)}")

    # Inspect each input to discover its attributes.
    for index, element in enumerate(inputs, start=1):
        print(f"\n--- Input {index} ---")
        print("Type:", element.get_attribute("type"))
        print("Name:", element.get_attribute("name"))
        print("Placeholder:", element.get_attribute("placeholder"))
        print("ARIA label:", element.get_attribute("aria-label"))
        print("Title:", element.get_attribute("title"))

print("\nSearch-input inspection completed.")
