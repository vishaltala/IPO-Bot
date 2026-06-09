# IPO GMP Bot

Automatically scrapes [investorgain.com Live IPO GMP](https://www.investorgain.com/report/ipo-gmp-live/331/)
every morning at **7:00 AM German time** and sends a Gmail alert if any IPO matches all three filters:

| Filter | Condition |
|--------|-----------|
| Tag | Must be **IPO** (Mainboard only, not SME) |
| Rating | Must be **4 or more 🔥** |
| Closing Date | Must be **today** |

If no IPO matches, no email is sent.

---

## Setup

### 1. Fork / clone this repository

```bash
git clone https://github.com/YOUR_USERNAME/ipo-gmp-bot.git
cd ipo-gmp-bot
```

### 2. Create a Gmail App Password

You need a **Gmail App Password** (not your regular Gmail password).

1. Go to your Google Account: https://myaccount.google.com/
2. Security → 2-Step Verification → make sure it is ON
3. Security → Search for "App passwords"
4. Create a new App Password: name it "IPO GMP Bot"
5. Copy the 16-character password (e.g. `abcd efgh ijkl mnop`)

### 3. Add GitHub Secrets

In your GitHub repository go to:
**Settings → Secrets and variables → Actions → New repository secret**

Add these three secrets:

| Secret Name | Value |
|-------------|-------|
| `GMAIL_SENDER` | Your Gmail address, e.g. `yourname@gmail.com` |
| `GMAIL_PASSWORD` | The 16-char App Password from step 2 (no spaces) |
| `GMAIL_RECEIVER` | Email address to receive alerts (can be same as sender) |

### 4. Push and enable Actions

```bash
git add .
git commit -m "Initial IPO GMP Bot setup"
git push origin main
```

Then go to **Actions** tab in GitHub and make sure workflows are enabled.

### 5. Test manually

Go to **Actions → IPO GMP Bot → Run workflow** to trigger it immediately and check the logs.

---

## How it works

```
GitHub Actions cron (7 AM Berlin time)
    → Playwright launches headless Chromium
    → Loads investorgain.com GMP page (JS rendered)
    → Waits for table to fully load
    → Parses all rows
    → Applies filters: IPO tag + 4+ fires + closing today
    → If matches found: sends formatted HTML email via Gmail SMTP
    → If no matches: exits silently (no email)
```

---

## Adjusting filters

Edit `gmp_bot.py`:

```python
MIN_FIRES = 4   # Change to 3 for 3+ fires, 5 for 5 fires only
```

To change the closing date filter (e.g. show IPOs closing in next 3 days),
edit the `filter_rows()` function in `gmp_bot.py`.

---

## Cron schedule

The workflow runs two cron jobs to handle German summer/winter time:

| Cron | UTC | German Time |
|------|-----|-------------|
| `0 5 * * *` | 05:00 UTC | 07:00 CEST (summer, Apr–Oct) |
| `0 6 * * *` | 06:00 UTC | 07:00 CET (winter, Oct–Mar) |

This means the bot runs twice on the days clocks change — harmless since
the second run will find the same data or none at all.

---

## Sample email

The email shows a clean HTML table with:
- Company name
- GMP and GMP %
- Fire rating
- Subscription
- Price, IPO Size, Lot
- Open / Close / Listing dates

---

## Disclaimer

GMP data is sourced from the grey market and is unofficial/indicative only.
Do your own research before investing. This bot is for informational purposes only.
