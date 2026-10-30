
from core.browser import browser_session


# Start a managed browser session.
with browser_session() as driver:
    driver.get("https://flipkart.com")

    print("Page title:", driver.title)
    print("Current URL:", driver.current_url)

# Reaching this line means the context manager has exited.
print("Browser session closed.")
