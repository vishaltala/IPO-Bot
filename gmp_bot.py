"""
IPO GMP Bot
===========
Scrapes Live IPO GMP from investorgain.com using Playwright (headless Chromium).
Filters: tag == "IPO" (Mainboard), rating >= 4 fires, closing date == today.
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
GMAIL_SENDER   = os.environ["GMAIL_SENDER"]    # your Gmail address
GMAIL_PASSWORD = os.environ["GMAIL_PASSWORD"]  # Gmail App Password (16 chars)
GMAIL_RECEIVER = os.environ["GMAIL_RECEIVER"]  # where to send the alert

GMP_URL = "https://www.investorgain.com/report/ipo-gmp-live/331/"

# Minimum number of fire emojis required (4 fires = "🔥🔥🔥🔥")
MIN_FIRES = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_today_str() -> str:
    """Return today's date in the short format used by the site, e.g. '9-Jun'."""
    berlin = pytz.timezone("Europe/Berlin")
    now = datetime.now(berlin)
    # Site uses day without leading zero, e.g. '9-Jun', '12-Jun'
    return now.strftime("%-d-%b")


def count_fires(text: str) -> int:
    """Count 🔥 emojis in a string."""
    return text.count("🔥")


def has_ipo_tag(name_cell_text: str) -> bool:
    """
    The NAME column contains badge text like 'BSE SME', 'NSE SME', 'IPO'.
    We want rows where the badge is exactly 'IPO' (Mainboard IPO).
    """
    # The badge text is concatenated with the company name in the cell
    return re.search(r'\bIPO\b', name_cell_text) is not None


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

        # Wait for at least one data row to appear
        try:
            page.wait_for_selector("table tbody tr td a", timeout=30000)
        except Exception:
            print("Table did not load within 30 s — no data today.")
            browser.close()
            return rows

        # Grab all table rows
        table_rows = page.query_selector_all("table tbody tr")
        print(f"Found {len(table_rows)} raw rows in table.")

        for tr in table_rows:
            tds = tr.query_selector_all("td")
            if len(tds) < 10:
                continue

            name_cell  = tds[0].inner_text().strip()
            gmp_cell   = tds[1].inner_text().strip()
            rating_cell = tds[2].inner_text().strip()
            sub_cell   = tds[3].inner_text().strip()
            price_cell = tds[4].inner_text().strip()
            size_cell  = tds[5].inner_text().strip()
            lot_cell   = tds[6].inner_text().strip()
            open_cell  = tds[7].inner_text().strip()
            close_cell = tds[8].inner_text().strip()
            listing_cell = tds[10].inner_text().strip() if len(tds) > 10 else ""

            # Extract company name (first line of the cell)
            company_name = name_cell.split("\n")[0].strip()

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
                "close":      close_cell,
                "listing":    listing_cell,
            })

        browser.close()

    return rows


def filter_rows(rows: list[dict], today: str) -> list[dict]:
    """Apply the three filters."""
    matched = []
    for row in rows:
        # Filter 1: tag must be 'IPO' (Mainboard)
        if not has_ipo_tag(row["name_raw"]):
            continue

        # Filter 2: rating >= 4 fires
        fires = count_fires(row["rating"])
        if fires < MIN_FIRES:
            continue

        # Filter 3: closing date == today
        # close_cell may contain just the date or "GMP: xx\n<date>"
        close_text = row["close"]
        if today not in close_text:
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

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1d4ed8,#2563eb);padding:24px 32px;">
      <h1 style="color:#fff;margin:0;font-size:22px;">📈 IPO GMP Alert</h1>
      <p style="color:#bfdbfe;margin:6px 0 0;font-size:14px;">
        {len(matched)} IPO(s) closing today ({today}) with 4+ fire rating
      </p>
    </div>

    <!-- Table -->
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

    <!-- Footer -->
    <div style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;">
      <p style="color:#94a3b8;font-size:12px;margin:0;">
        Data sourced from
        <a href="https://www.investorgain.com/report/ipo-gmp-live/331/"
           style="color:#2563eb;">investorgain.com</a>.
        GMP is unofficial grey market data. Do your own research before investing.
      </p>
      <p style="color:#94a3b8;font-size:12px;margin:4px 0 0;">
        Filters applied: Tag = IPO (Mainboard) | Rating ≥ 4🔥 | Closing Today ({today})
      </p>
    </div>
  </div>
</body>
</html>"""


def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = GMAIL_RECEIVER
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_SENDER, GMAIL_RECEIVER, msg.as_string())

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

    # Print matches to Actions log
    for r in matched:
        print(f"  MATCH: {r['name']} | GMP: {r['gmp']} | Fires: {r['fires']} | Close: {r['close']}")

    subject   = f"📈 IPO GMP Alert — {len(matched)} IPO(s) closing today ({today})"
    html_body = build_html_email(matched, today)
    send_email(subject, html_body)


if __name__ == "__main__":
    main()
