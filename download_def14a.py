"""
Downloads the most recent DEF 14A proxy statement (PDF) for each S&P 600
company from SEC EDGAR, saving to SEC_Filings/{symbol}_DEF_14A_{date}.pdf.

For each company:
  1. Fetch the EDGAR submissions JSON to find the most recent DEF 14A.
  2. If the primary document is already a PDF, download it directly.
  3. Otherwise (the common case), download the HTML via requests (which
     satisfies SEC's User-Agent requirement), rewrite relative asset URLs
     to absolute, then render to PDF via a headless Chromium browser.
     One browser instance is reused across all companies for speed.

Skipped companies are listed in a summary at the end.

Dependencies:
    pip install requests beautifulsoup4 playwright
    playwright install chromium
"""

import csv
import time
import requests
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

CSV_FILE = "sp600_companies.csv"
OUTPUT_DIR = Path("SEC_Filings")
SEC_HEADERS = {"User-Agent": "Executive Compensation Research kipp.andrew.p@gmail.com"}
SLEEP = 0.12  # stay under SEC's 10 req/s rate limit


def padded_cik(cik: str) -> str:
    return str(int(cik)).zfill(10)


def get_submissions(cik: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{padded_cik(cik)}.json"
    resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(SLEEP)
    return resp.json()


def find_most_recent_def14a(submissions: dict):
    """Return (accession_number, filing_date, primary_document) for the newest DEF 14A."""
    recent = submissions["filings"]["recent"]
    for form, acc, date, primary in zip(
        recent["form"],
        recent["accessionNumber"],
        recent["filingDate"],
        recent["primaryDocument"],
    ):
        if form == "DEF 14A":
            return acc, date, primary
    return None, None, None


def edgar_doc_url(cik: str, accession: str, filename: str) -> str:
    cik_int = str(int(cik))
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{filename}"


def download_direct(url: str, dest: Path) -> None:
    resp = requests.get(url, headers=SEC_HEADERS, timeout=60, stream=True)
    resp.raise_for_status()
    time.sleep(SLEEP)
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=16384):
            f.write(chunk)


def fetch_and_absolutize(url: str) -> str:
    """Download HTML and rewrite all relative URLs to absolute."""
    resp = requests.get(url, headers=SEC_HEADERS, timeout=60)
    resp.raise_for_status()
    time.sleep(SLEEP)
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.find_all(True):
        for attr in ("src", "href", "action"):
            val = tag.get(attr)
            if val and not val.startswith(("http", "data:", "#", "javascript:", "mailto:")):
                tag[attr] = urljoin(url, val)
    return str(soup)


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    downloaded = 0
    rendered = 0
    skipped = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # Context-level user_agent ensures all browser asset requests also pass SEC checks
        context = browser.new_context(
            user_agent=SEC_HEADERS["User-Agent"],
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        for i, row in enumerate(rows, 1):
            symbol = row["Symbol"]
            cik = row["CIK"]

            print(f"[{i}/{total}] {symbol}", end=" ... ", flush=True)

            try:
                subs = get_submissions(cik)
                accession, filing_date, primary_doc = find_most_recent_def14a(subs)

                if not accession:
                    print("no DEF 14A found")
                    skipped.append((symbol, "no DEF 14A in recent filing history"))
                    continue

                dest = OUTPUT_DIR / f"{symbol}_DEF_14A_{filing_date}.pdf"
                if dest.exists():
                    print("already exists, skipping")
                    continue

                doc_url = edgar_doc_url(cik, accession, primary_doc)

                if primary_doc.lower().endswith(".pdf"):
                    # Native PDF: direct download, no browser needed
                    download_direct(doc_url, dest)
                    downloaded += 1
                    print(f"downloaded  [{filing_date}]")
                else:
                    # HTML filing: download + absolutize URLs + render to PDF
                    abs_html = fetch_and_absolutize(doc_url)
                    page.set_content(abs_html, wait_until="load")
                    page.pdf(
                        path=str(dest),
                        format="Letter",
                        print_background=True,
                        margin={
                            "top": "0.5in",
                            "bottom": "0.5in",
                            "left": "0.5in",
                            "right": "0.5in",
                        },
                    )
                    rendered += 1
                    print(f"rendered HTML->PDF  [{filing_date}]")

            except PwTimeout:
                print("timed out")
                skipped.append((symbol, "page render timed out"))
            except requests.HTTPError as e:
                print(f"HTTP {e.response.status_code}")
                skipped.append((symbol, f"HTTP {e.response.status_code}"))
            except Exception as e:
                print(f"ERROR: {e}")
                skipped.append((symbol, str(e)))

        context.close()
        browser.close()

    print(
        f"\n--- Complete: {downloaded} native PDFs, {rendered} rendered from HTML, "
        f"{len(skipped)} skipped out of {total} ---"
    )
    if skipped:
        print("\nSkipped:")
        for sym, reason in skipped:
            print(f"  {sym}: {reason}")


if __name__ == "__main__":
    main()
