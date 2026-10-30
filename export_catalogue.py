
import json
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from services.search_service import search_products


# --------------------------------------------------
# 1. Configure the product searches for this first run.
# Each query represents a product type, not one product.
# --------------------------------------------------

CATALOGUE_QUERIES = [
    ("Furniture", "Sofa"),
    ("Furniture", "Office Chair"),
    ("Furniture", "Dining Table"),
    ("Furniture", "Bed"),
]

# Maximum number of products requested for each search.
PRODUCTS_PER_SEARCH = 5

# Create an output directory without changing existing files.
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Save the collected product records and PDF report here.
JSON_FILE = OUTPUT_DIR / "scraped_products.json"
PDF_FILE = OUTPUT_DIR / "scraped_products_report.pdf"


def collect_products():
    """Scrape products for each query and collect unique listings."""

    all_products = []
    seen_urls = set()
    search_errors = []

    # Process one product type at a time.
    for category, query in CATALOGUE_QUERIES:
        print(f"\nSearching: {query}")

        try:
            # Reuse the existing scraper and normalizer.
            products = search_products(
                query=query,
                max_results=PRODUCTS_PER_SEARCH,
            )

            # Process every product returned by this search.
            for product in products:
                # Ignore products without a usable product URL.
                product_url = product.get("url")

                if not product_url:
                    continue

                # Avoid adding the same listing more than once.
                if product_url in seen_urls:
                    continue

                seen_urls.add(product_url)

                # Record which catalogue category produced this result.
                product["catalogue_category"] = category
                product["search_query"] = query

                # Keep the real extracted product details.
                all_products.append(product)

                print(
                    f"  Collected: {product.get('name', 'Unknown')} "
                    f"| Price: {product.get('price') or 'Not available'}"
                )

            print(f"  Results returned: {len(products)}")

        except Exception as error:
            # Record this failure and continue with the next query.
            message = f"{query}: {type(error).__name__}: {error}"
            search_errors.append(message)
            print(f"  Search failed: {message}")

    return all_products, search_errors


def save_products_json(products):
    """Save structured product records for future website integration."""

    # Write UTF-8 JSON so product names and symbols are preserved.
    with JSON_FILE.open("w", encoding="utf-8") as file:
        json.dump(products, file, ensure_ascii=False, indent=2)

    print(f"\nJSON saved to: {JSON_FILE.resolve()}")


def make_paragraph(value, style):
    """Convert a value into a PDF paragraph with safe text escaping."""

    # Display missing values clearly rather than inventing information.
    text = str(value) if value not in (None, "") else "Not available"

    # Escape extracted retailer text so it cannot break PDF markup.
    return Paragraph(escape(text), style)


def make_link(url, label, style):
    """Create a clickable link in the PDF when a URL is available."""

    if not url:
        return make_paragraph("Not available", style)

    # Escape the label; preserve the URL as the link destination.
    safe_label = escape(label)
    return Paragraph(
        f'<link href="{escape(url)}">{safe_label}</link>',
        style,
    )


def save_products_pdf(products, search_errors):
    """Generate a PDF report containing the extracted product records."""

    # Use landscape A4 so product details fit into readable columns.
    document = SimpleDocTemplate(
        str(PDF_FILE),
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )

    # Prepare PDF text styles.
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    normal_style = styles["BodyText"]

    cell_style = ParagraphStyle(
        "ProductCell",
        parent=normal_style,
        fontSize=7,
        leading=9,
        alignment=TA_LEFT,
        spaceAfter=2,
    )

    heading_style = ParagraphStyle(
        "ProductHeading",
        parent=cell_style,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    story = []

    # Add the report title and extraction details.
    story.append(Paragraph("Scraped Product Catalogue", title_style))
    story.append(
        Paragraph(
            f"Generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            normal_style,
        )
    )
    story.append(Paragraph(f"Unique product listings: {len(products)}", normal_style))
    story.append(Spacer(1, 8 * mm))

    # Create the table headings.
    rows = [[
        Paragraph("Category", heading_style),
        Paragraph("Search", heading_style),
        Paragraph("Product name", heading_style),
        Paragraph("Price", heading_style),
        Paragraph("Retailer", heading_style),
        Paragraph("Product page", heading_style),
        Paragraph("Product image", heading_style),
    ]]

    # Add one row for every unique product listing.
    for product in products:
        rows.append([
            make_paragraph(product.get("catalogue_category"), cell_style),
            make_paragraph(product.get("search_query"), cell_style),
            make_paragraph(product.get("name"), cell_style),
            make_paragraph(product.get("price"), cell_style),
            make_paragraph(product.get("retailer"), cell_style),
            make_link(product.get("url"), "Open listing", cell_style),
            make_link(product.get("image_url"), "Open image", cell_style),
        ])

    # Add a clear message if no products were extracted.
    if not products:
        story.append(
            Paragraph(
                "No product listings were collected. Check the scraper output "
                "and recorded search errors.",
                normal_style,
            )
        )
    else:
        # Repeat the header row if the table spans multiple pages.
        table = Table(
            rows,
            colWidths=[
                23 * mm,
                25 * mm,
                55 * mm,
                22 * mm,
                23 * mm,
                28 * mm,
                28 * mm,
            ],
            repeatRows=1,
            hAlign="LEFT",
        )

        # Format the table for readability.
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243447")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                colors.white,
                colors.HexColor("#F2F5F8"),
            ]),
        ]))

        story.append(table)

    # Include search errors so failed searches are visible in the report.
    if search_errors:
        story.append(PageBreak())
        story.append(Paragraph("Search Errors", styles["Heading1"]))

        for error in search_errors:
            story.append(Paragraph(escape(error), cell_style))
            story.append(Spacer(1, 2 * mm))

    # Write the finished PDF file.
    document.build(story)

    print(f"PDF saved to: {PDF_FILE.resolve()}")


def main():
    """Run extraction, save JSON, and generate the PDF report."""

    print("Starting catalogue extraction...")

    # Step 1: Extract real product listings from the retailer.
    products, errors = collect_products()

    # Step 2: Save structured records even if some searches failed.
    save_products_json(products)

    # Step 3: Generate a report from the collected records.
    save_products_pdf(products, errors)

    # Print a final summary.
    print("\n========== EXTRACTION SUMMARY ==========")
    print(f"Unique products collected: {len(products)}")
    print(f"Search errors: {len(errors)}")
    print(f"JSON file: {JSON_FILE.resolve()}")
    print(f"PDF file: {PDF_FILE.resolve()}")
    print("========================================")


# Run the workflow only when this file is executed directly.
if __name__ == "__main__":
    main()
