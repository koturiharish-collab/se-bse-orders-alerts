#!/usr/bin/env python3
"""
Order-win alerts: NSE + BSE corporate announcements -> Telegram.

Runs once per invocation (designed for GitHub Actions cron).
Dedupes via seen.json (committed back to the repo by the workflow).
"""
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

IST = timezone(timedelta(hours=5, minutes=30))
STATE_FILE = Path("seen.json")
MAX_SEEN = 5000
MAX_ALERTS_PER_RUN = 25  # safety cap against floods

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# --- What counts as an "order win" -------------------------------------------
INCLUDE = re.compile(
    r"\b("
    r"bagging\s*/?\s*receiving|"
    r"(receiving|receipt|award(ing)?|bagging)\s+of\s+(an?\s+)?(new\s+)?(order|contract)s?|"
    r"order(s)?\s+(win|won|received|inflow|book)|"
    r"(bagg(ed|s)|secur(ed|es)|win(s)?|won|receiv(ed|es)|awarded|grabs?|clinch(ed|es)?)"
    r"[^.]{0,60}\b(order|contract|project|tender|work)|"
    r"letter\s+of\s+(award|intent|acceptance)|\bLoA\b|\bLoI\b|"
    r"work\s+order|purchase\s+order|new\s+order|"
    r"(order|contract)\s+(worth|valued|of\s+rs|of\s+inr|for)|"
    r"empanel(l)?ment|bagging\s+of\s+order"
    r")",
    re.I,
)
# Drop obvious noise (tweak freely)
EXCLUDE = re.compile(
    r"(newspaper\s+publication|trading\s+window|loss\s+of\s+share\s+certificate|"
    r"duplicate\s+share|analyst\s*/?\s*investor\s+meet|credit\s+rating|"
    r"cancel(led|lation)\s+of\s+(the\s+)?order)",
    re.I,
)

HEADERS_COMMON = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# --- Sources -----------------------------------------------------------------
def fetch_bse(day: datetime):
    """BSE corporate announcements for a single day."""
    url = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    headers = {
        **HEADERS_COMMON,
        "Referer": "https://www.bseindia.com/",
        "Origin": "https://www.bseindia.com",
        "Accept": "application/json, text/plain, */*",
    }
    d = day.strftime("%Y%m%d")
    out = []
    for page in range(1, 11):
        params = {
            "pageno": page,
            "strCat": "-1",
            "subcategory": "-1",
            "strPrevDate": d,
            "strToDate": d,
            "strSearch": "P",
            "strscrip": "",
            "strType": "C",
        }
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        rows = r.json().get("Table") or []
        if not rows:
            break
        for x in rows:
            att = x.get("ATTACHMENTNAME") or ""
            out.append(
                {
                    "id": f"BSE:{x.get('NEWSID')}",
                    "exchange": "BSE",
                    "company": x.get("SLONGNAME") or "",
                    "symbol": str(x.get("SCRIP_CD") or ""),
                    "title": x.get("HEADLINE") or "",
                    "text": x.get("NEWSSUB") or "",
                    "category": x.get("SUBCATNAME") or x.get("CATEGORYNAME") or "",
                    "time": x.get("NEWS_DT") or "",
                    "link": (
                        f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}"
                        if att
                        else ""
                    ),
                }
            )
        if len(rows) < 50:
            break
        time.sleep(0.5)
    return out


def fetch_nse(day: datetime):
    """NSE corporate announcements (equities) for a single day."""
    s = requests.Session()
    s.headers.update(
        {
            **HEADERS_COMMON,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        }
    )
    # NSE requires cookies from the homepage first
    s.get("https://www.nseindia.com", timeout=30)
    d = day.strftime("%d-%m-%Y")
    r = s.get(
        "https://www.nseindia.com/api/corporate-announcements",
        params={"index": "equities", "from_date": d, "to_date": d},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    out = []
    for x in data if isinstance(data, list) else []:
        key = x.get("seq_id") or f"{x.get('symbol')}|{x.get('an_dt')}|{x.get('desc')}"
        out.append(
            {
                "id": f"NSE:{key}",
                "exchange": "NSE",
                "company": x.get("sm_name") or "",
                "symbol": x.get("symbol") or "",
                "title": x.get("desc") or "",
                "text": x.get("attchmntText") or "",
                "category": x.get("desc") or "",
                "time": x.get("an_dt") or "",
                "link": x.get("attchmntFile") or "",
            }
        )
    return out


# --- Telegram ----------------------------------------------------------------
def tg_send(text: str):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not r.ok:
        log("Telegram error:", r.status_code, r.text[:300])
    r.raise_for_status()


def fmt(a: dict) -> str:
    body = re.sub(r"\s+", " ", a["text"]).strip()
    if len(body) > 700:
        body = body[:700].rstrip() + "…"
    lines = [
        f"🟢 <b>Order Win Alert</b> · {a['exchange']}",
        f"<b>{html.escape(a['company'])}</b> ({html.escape(str(a['symbol']))})",
    ]
    if a["title"] and a["title"] != a["text"]:
        lines.append(f"<i>{html.escape(a['title'])}</i>")
    if body:
        lines.append(html.escape(body))
    if a["time"]:
        lines.append(f"🕒 {html.escape(str(a['time']))}")
    if a["link"]:
        lines.append(f"<a href=\"{html.escape(a['link'])}\">Open filing</a>")
    return "\n".join(lines)[:4000]


# --- State -------------------------------------------------------------------
def load_seen():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def save_seen(seen: list):
    STATE_FILE.write_text(json.dumps(seen[-MAX_SEEN:]))


# --- Main --------------------------------------------------------------------
def main():
    if not BOT_TOKEN or not CHAT_ID:
        log("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return 1

    today = datetime.now(IST)
    items, ok_sources = [], 0
    for name, fn in (("BSE", fetch_bse), ("NSE", fetch_nse)):
        try:
            got = fn(today)
            log(f"{name}: {len(got)} announcements")
            items += got
            ok_sources += 1
        except Exception as e:  # keep going if one exchange blocks us
            log(f"{name} fetch failed: {e!r}")

    if ok_sources == 0:
        log("Both sources failed; nothing to do this run.")
        return 0

    seen_list = load_seen()
    first_run = seen_list is None
    seen_list = seen_list or []
    seen = set(seen_list)

    new = [a for a in items if a["id"] not in seen]
    for a in new:
        seen_list.append(a["id"])

    if first_run:
        log(f"First run: {len(new)} items today; sending any order wins already published.")
        try:
            tg_send("✅ Order-win alert bot is live. Sending today's order announcements so far, then new ones as they appear.")
        except Exception as e:
            log("Startup message failed:", e)

    hits = []
    for a in new:
        blob = f"{a['title']} {a['text']}"
        if INCLUDE.search(blob) and not EXCLUDE.search(blob):
            hits.append(a)

    log(f"{len(new)} new, {len(hits)} order-win matches")
    for a in hits[:MAX_ALERTS_PER_RUN]:
        try:
            tg_send(fmt(a))
            time.sleep(1)
        except Exception as e:
            log("send failed:", e)
            # don't mark as seen so it retries next run
            if a["id"] in seen_list:
                seen_list.remove(a["id"])
    if len(hits) > MAX_ALERTS_PER_RUN:
        tg_send(f"…and {len(hits) - MAX_ALERTS_PER_RUN} more order announcements this run.")

    save_seen(seen_list)
    return 0


if __name__ == "__main__":
    sys.exit(main())
