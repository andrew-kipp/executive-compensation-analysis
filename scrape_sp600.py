"""
Scrapes the S&P 600 components table from Wikipedia and saves it as a CSV.
The SEC filings column stores the full hyperlink URL; all other columns store plain text.
"""

import csv
import requests
from bs4 import BeautifulSoup

URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
OUTPUT = "sp600_companies.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (research script; contact: kipp.andrew.p@gmail.com)"
}


def scrape_sp600():
    response = requests.get(URL, headers=HEADERS, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # The main constituents table has the wikitable class
    table = soup.find("table", {"class": "wikitable"})
    if table is None:
        raise RuntimeError("Could not find the wikitable on the page.")

    rows = table.find_all("tr")
    header_row = rows[0]
    column_names = [th.get_text(strip=True) for th in header_row.find_all("th")]

    # Identify which column index holds SEC filings
    sec_col_index = next(
        (i for i, name in enumerate(column_names) if "SEC" in name),
        None,
    )
    if sec_col_index is None:
        raise RuntimeError("Could not locate the 'SEC filings' column.")

    records = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue

        record = []
        for i, cell in enumerate(cells):
            if i == sec_col_index:
                # Extract the href from the anchor tag
                anchor = cell.find("a", href=True)
                value = anchor["href"] if anchor else cell.get_text(strip=True)
            else:
                value = cell.get_text(strip=True)
            record.append(value)

        records.append(record)

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(column_names)
        writer.writerows(records)

    print(f"Saved {len(records)} rows to {OUTPUT}")


if __name__ == "__main__":
    scrape_sp600()
