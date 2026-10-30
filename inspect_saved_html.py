
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Load the HTML saved by the previous Selenium inspection.
html_path = Path("page_inspections/Teddy_Bear.html")
html = html_path.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")

# Find a product link with a title and a Flipkart product URL.
title_link = soup.find(
    "a",
    attrs={"title": True},
    href=lambda href: href and "/p/" in href,
)

if title_link is None:
    print("No titled product link found.")
    raise SystemExit

# Find the product card containing the title link.
card = title_link.find_parent("div", attrs={"data-tkid": True})

if card is None:
    print("Product card not found.")
    raise SystemExit

# Extract the product title.
product_name = title_link.get("title", "").strip()

# Convert the relative product URL into a complete URL.
product_url = urljoin(
    "https://www.flipkart.com",
    title_link.get("href", ""),
)

# Find the actual product image, ignoring generic badges.
product_image = None

for image in card.find_all("img"):
    alt_text = (image.get("alt") or "").strip()
    image_src = image.get("src") or image.get("data-src")

    if alt_text and image_src and image_src.startswith("http"):
        product_image = image_src
        break

# Print every element containing a rupee price.
price_elements = []

for element in card.find_all(string=lambda text: text and "₹" in text):
    text = element.strip()

    if text:
        price_elements.append(text)

# Show the extracted values for verification.
print("PRODUCT NAME:", product_name)
print("PRODUCT URL:", product_url)
print("PRODUCT IMAGE:", product_image)
print("PRICE ELEMENTS:", price_elements)
