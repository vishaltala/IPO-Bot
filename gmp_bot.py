"""
IPO GMP Bot
===========
Scrapes Live IPO GMP from investorgain.com using Playwright (headless Chromium).
Filters: tag == "IPO" (Mainboard), rating >= MIN_FIRES, closing date == today.
Sends a formatted Gmail alert if any matches are found.
Runs once daily at 7:00 AM German time via GitHub Actions.
"""

import os
import re
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytz
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Config (all sensitive values come from GitHub Secrets / env vars)
# ---------------------------------------------------------------------------
GMAIL_SENDER   = os.environ["GMAIL_SENDER"]
GMAIL_PASSWORD = os.environ["GMAIL_PASSWORD"]
GMAIL_RECEIVER = os.environ["GMAIL_RECEIVER"]
GMAIL_RECEIVER_HV = os.environ["GMAIL_RECEIVER_2"]
MIN_FIRES = = os.environ["FIRES"]

GMP_URL = "https://www.investorgain.com/report/ipo-gmp-live/331/"

# Minimum number of fire emojis required
# MIN_FIRES = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_today_str() -> str:
    """Return today's date in the short format used by the site, e.g. '9-Jun'."""
    berlin = pytz.timezone("Europe/Berlin")
    now = datetime.now(berlin)
    return now.strftime("%-d-%b")


def count_fires(text: str) -> int:
    return text.count("🔥")


def has_ipo_tag(name_cell_text: str) -> bool:
    """
    Mainboard IPOs have the badge text 'IPO' in the name cell.
    SME IPOs have 'BSE SME' or 'NSE SME' instead.
    The site concatenates badges without spaces, e.g. 'Hexagon Nutrition IPOCT'
    or 'CMR Green Technologies IPOCALLOTTED'.
    Strategy: check that 'IPO' appears in the text AND 'SME' does NOT appear.
    This correctly separates Mainboard (IPO) from SME (BSE SME / NSE SME).
    """
    has_ipo = 'IPO' in name_cell_text
    has_sme = 'SME' in name_cell_text
    return has_ipo and not has_sme


def scrape_gmp_table() -> list[dict]:
    """
    Launch headless Chromium, load the GMP page, wait for the table,
    and return all rows as a list of dicts.
    """
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()

        print(f"Loading {GMP_URL} ...")
        page.goto(GMP_URL, wait_until="networkidle", timeout=60000)

        try:
            page.wait_for_selector("table tbody tr td a", timeout=30000)
        except Exception:
            print("Table did not load within 30 s — no data today.")
            browser.close()
            return rows

        # First, detect column positions from the header row
        header_cells = page.query_selector_all("table thead tr th")
        headers = [th.inner_text().strip().upper() for th in header_cells]
        print(f"Headers detected: {headers}")

        # Build index map (strip sort arrows etc.)
        col_index = {}
        for i, h in enumerate(headers):
            clean = re.sub(r'[^A-Z\s]', '', h).strip()
            col_index[clean] = i

        print(f"Column index map: {col_index}")

        # Fallback known positions if header detection fails
        IDX_NAME    = col_index.get("NAME",    0)
        IDX_GMP     = col_index.get("GMP",     1)
        IDX_RATING  = col_index.get("RATING",  2)
        IDX_SUB     = col_index.get("SUB",     3)
        IDX_PRICE   = col_index.get("PRICE",   4)  # "PRICE " with rupee sign
        IDX_SIZE    = col_index.get("IPO SIZE", 5)
        IDX_LOT     = col_index.get("LOT",     6)
        IDX_OPEN    = col_index.get("OPEN",    7)
        IDX_CLOSE   = col_index.get("CLOSE",   8)
        IDX_LISTING = col_index.get("LISTING", 10)

        # Fallback: scan for partial matches
        for i, h in enumerate(headers):
            if "PRICE" in h:   IDX_PRICE   = i
            if "SIZE"  in h:   IDX_SIZE    = i
            if "OPEN"  in h:   IDX_OPEN    = i
            if "CLOSE" in h:   IDX_CLOSE   = i
            if "LISTING" in h: IDX_LISTING = i
            if "RATING" in h:  IDX_RATING  = i

        print(f"Using: NAME={IDX_NAME} GMP={IDX_GMP} RATING={IDX_RATING} "
              f"OPEN={IDX_OPEN} CLOSE={IDX_CLOSE} LISTING={IDX_LISTING}")

        # Grab all table rows
        table_rows = page.query_selector_all("table tbody tr")
        print(f"Found {len(table_rows)} raw rows in table.")

        for tr in table_rows:
            tds = tr.query_selector_all("td")
            if len(tds) < 9:
                continue

            def cell(idx):
                return tds[idx].inner_text().strip() if idx < len(tds) else ""

            name_cell    = cell(IDX_NAME)
            gmp_cell     = cell(IDX_GMP)
            rating_cell  = cell(IDX_RATING)
            sub_cell     = cell(IDX_SUB)
            price_cell   = cell(IDX_PRICE)
            size_cell    = cell(IDX_SIZE)
            lot_cell     = cell(IDX_LOT)
            open_cell    = cell(IDX_OPEN)
            close_cell   = cell(IDX_CLOSE)
            listing_cell = cell(IDX_LISTING)

            # Strip badge suffixes (IPOCT, IPOCALLOTTED, BSE SMEU, L@price etc.)
            raw_name = name_cell.split("\n")[0].strip()
            company_name = re.sub(r'\s*(BSE\s*SME|NSE\s*SME|IPO)[A-Z@0-9\.\-\(\)%\s]*$', '', raw_name).strip()
            company_name = re.sub(r'\s+[A-Z]+L?@[\d\.\-\(\)%\s]+$', '', company_name).strip()

            # Debug output — shows exact raw values in Actions log
            print(f"  [{company_name}] name_raw={name_cell!r} | "
                  f"rating={rating_cell!r} | close={close_cell!r}")

            rows.append({
                "name":       company_name,
                "name_raw":   name_cell,
                "gmp":        gmp_cell,
                "rating":     rating_cell,
                "sub":        sub_cell,
                "price":      price_cell,
                "ipo_size":   size_cell,
                "lot":        lot_cell,
                "open":       open_cell,
                "close":      close_cell.split("\n")[0].strip(),
                "listing":    listing_cell,
            })

        browser.close()

    return rows


def filter_rows(rows: list[dict], today: str) -> list[dict]:
    """Apply the three filters."""
    matched = []
    for row in rows:
        fires      = count_fires(row["rating"])
        is_ipo_tag = has_ipo_tag(row["name_raw"])
        # Date check: today string must appear anywhere in the close cell text
        close_text   = row["close"]
        is_today     = today in close_text

        print(f"  FILTER [{row['name']}]: ipo_tag={is_ipo_tag} "
              f"fires={fires}/{MIN_FIRES} today={is_today} (close={close_text!r})")

        if not is_ipo_tag:
            continue
        if fires < MIN_FIRES:
            continue
        if not is_today:
            continue

        row["fires"] = fires
        matched.append(row)

    return matched


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def build_html_email(matched: list[dict], today: str) -> str:
    rows_html = ""
    for r in matched:
        rows_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600;color:#1d4ed8;">
            {r['name']}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#16a34a;font-weight:600;">
            {r['gmp']}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">
            {"🔥" * r['fires']}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{r['sub']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{r['price']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{r['ipo_size']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{r['lot']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{r['open']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600;color:#dc2626;">
            {r['close']}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{r['listing']}</td>
        </tr>"""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f9fafb;margin:0;padding:20px;">
  <div style="max-width:900px;margin:0 auto;background:#fff;border-radius:12px;
              box-shadow:0 2px 8px rgba(0,0,0,0.08);overflow:hidden;">

    <div style="background:linear-gradient(135deg,#1d4ed8,#2563eb);padding:24px 32px;">
      <h1 style="color:#fff;margin:0;font-size:22px;">📈 IPO GMP Alert</h1>
      <p style="color:#bfdbfe;margin:6px 0 0;font-size:14px;">
        {len(matched)} IPO(s) closing today ({today}) with {MIN_FIRES}+ fire rating
      </p>
    </div>

    <div style="overflow-x:auto;padding:24px;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#f1f5f9;">
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">Company</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">GMP</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">Rating</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">Subscription</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">Price (₹)</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">IPO Size</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">Lot</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">Open</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">Close</th>
            <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0;">Listing</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>

    <div style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;">
      <p style="color:#94a3b8;font-size:12px;margin:0;">
        Data sourced from
        <a href="https://www.investorgain.com/report/ipo-gmp-live/331/"
           style="color:#2563eb;">investorgain.com</a>.
        GMP is unofficial grey market data. Do your own research before investing.
      </p>
      <p style="color:#94a3b8;font-size:12px;margin:4px 0 0;">
        Filters: Tag = IPO (Mainboard) | Rating ≥ {MIN_FIRES}🔥 | Closing Today ({today})
      </p>
    </div>
  </div>
</body>
</html>"""


def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_SENDER
    msg["To"] = f"{GMAIL_RECEIVER}, {GMAIL_RECEIVER_HV}"
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_SENDER, [GMAIL_RECEIVER, GMAIL_RECEIVER_HV], msg.as_string())

    print(f"Email sent to {GMAIL_RECEIVER}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    berlin = pytz.timezone("Europe/Berlin")
    today  = get_today_str()
    print(f"Running IPO GMP Bot | Today (Berlin): {today}")

    rows    = scrape_gmp_table()
    print(f"Total rows scraped: {len(rows)}")

    matched = filter_rows(rows, today)
    print(f"Rows matching all filters: {len(matched)}")

    if not matched:
        print("No IPOs matched today's filters. No email sent.")
        sys.exit(0)

    for r in matched:
        print(f"  MATCH: {r['name']} | GMP: {r['gmp']} | "
              f"Fires: {r['fires']} | Close: {r['close']}")

    subject   = f"📈 IPO GMP Alert — {len(matched)} IPO(s) closing today ({today})"
    html_body = build_html_email(matched, today)
    send_email(subject, html_body)


if __name__ == "__main__":
    main()
