"""
scrape_events.py
────────────────
Raccoglie eventi futuri (o aperti) da 8 sorgenti relative all'ecosistema
di innovazione e finanziamento europeo. Produce events.json.

Sorgenti:
  1. EEN  – Enterprise Europe Network events
  2. EIC  – European Innovation Council events
  3. Access2EIC – NCP events network
  4. EBAN – European Business Angels Network events
  5. BpiFrance – eventi matchmaking/investimento (JS-rendered, Playwright)
  6. ESN  – European Startup Network news/events
  7. EuroQuity – Access2EIC community events (JS-rendered, Playwright)
  8. EC Seal of Excellence – EIC Seal of Excellence opportunities

Output: events.json
  {
    "generated": "2026-03-24T...",
    "count": N,
    "events": [
      {
        "title": "...",
        "source": "EEN",
        "date": "2026-04-15",          # ISO, empty if not found
        "date_end": "2026-04-16",       # ISO, empty if single-day
        "location": "Online only",      # or city/country
        "url": "https://...",
        "description": "..."            # short excerpt, may be empty
      }, ...
    ]
  }

Run:
    pip install requests beautifulsoup4 playwright
    playwright install chromium --with-deps
    python scrape_events.py
"""

import json
import re
import time
from datetime import datetime, timezone, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TODAY = date.today().isoformat()   # YYYY-MM-DD — filter past events

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ── Date helpers ──────────────────────────────────────────────────────────────

MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    "january":1,"february":2,"march":3,"april":4,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

def _iso(d: int, m: int, y: int) -> str:
    try:
        return date(y, m, d).isoformat()
    except Exception:
        return ""

def parse_date(text: str) -> str:
    """Try to extract an ISO date from a free-form string."""
    if not text:
        return ""
    t = text.strip()

    # ISO or near-ISO: 2026-04-15 / 2026/04/15
    m = re.search(r'(202\d)[/-](\d{1,2})[/-](\d{1,2})', t)
    if m:
        return _iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))

    # DD Month YYYY  or  Month DD, YYYY
    m = re.search(
        r'(\d{1,2})\s+([A-Za-z]+)\s+(202\d)', t)
    if m:
        mo = MONTH_MAP.get(m.group(2).lower()[:3])
        if mo:
            return _iso(int(m.group(1)), mo, int(m.group(3)))

    m = re.search(
        r'([A-Za-z]+)\s+(\d{1,2}),?\s+(202\d)', t)
    if m:
        mo = MONTH_MAP.get(m.group(1).lower()[:3])
        if mo:
            return _iso(int(m.group(2)), mo, int(m.group(3)))

    # Month YYYY (no day)
    m = re.search(r'([A-Za-z]+)\s+(202\d)', t)
    if m:
        mo = MONTH_MAP.get(m.group(1).lower()[:3])
        if mo:
            return _iso(1, mo, int(m.group(2)))

    return ""

def is_future_or_ongoing(date_str: str) -> bool:
    """Return True if date_str is >= TODAY, or if date_str is empty (unknown)."""
    if not date_str:
        return True   # keep if date unknown
    return date_str >= TODAY


def get_html(url: str, timeout: int = 20) -> BeautifulSoup | None:
    try:
        r = SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [HTTP ERR] {url}: {e}")
        return None


def get_html_playwright(url: str) -> str | None:
    """Fetch JS-rendered page via Playwright and return HTML string."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=HEADERS["User-Agent"],
                locale="en-US",
            )
            page.goto(url, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  [PLAYWRIGHT ERR] {url}: {e}")
        return None


# ── SOURCE 1: Enterprise Europe Network ──────────────────────────────────────
# Brokerage events, matchmaking, EDF Partner Pool, MSCA events

def scrape_een() -> list:
    print("EEN…", flush=True)
    events = []
    base = "https://een.ec.europa.eu"
    url  = f"{base}/events?f[0]=event_date%3Agt%7C{TODAY}T00%3A00%3A00%2B00%3A00%7C{TODAY}T00%3A00%3A00%2B00%3A00&f[1]=t%3A627"

    # Paginate through results
    page = 0
    while True:
        page_url = url + (f"&page={page}" if page else "")
        soup = get_html(page_url)
        if not soup:
            break

        articles = soup.find_all("article")
        if not articles:
            # Try generic event cards
            articles = soup.find_all(class_=re.compile(r"event|node"))

        found = 0
        for art in articles:
            title_tag = art.find(["h3", "h2", "h4"]) or art.find("a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not title:
                continue

            link_tag = art.find("a", href=True)
            href = link_tag["href"] if link_tag else ""
            event_url = href if href.startswith("http") else base + href

            # Date: look for time tag or text with date patterns
            time_tag = art.find("time")
            date_text = time_tag.get("datetime","") or (time_tag.get_text(strip=True) if time_tag else "")
            if not date_text:
                date_text = art.get_text(" ", strip=True)

            iso = parse_date(date_text)

            # Location
            loc_tag = art.find(class_=re.compile(r"location|place|city"))
            location = loc_tag.get_text(strip=True) if loc_tag else ""
            if not location and "online" in art.get_text("",strip=True).lower():
                location = "Online"

            if title and is_future_or_ongoing(iso):
                events.append({
                    "title": title, "source": "EEN",
                    "date": iso, "date_end": "",
                    "location": location,
                    "url": event_url, "description": ""
                })
                found += 1

        if found == 0:
            break
        page += 1
        if page > 5:
            break
        time.sleep(0.3)

    print(f"  → {len(events)} events")
    return events


# ── SOURCE 2: EIC Events ──────────────────────────────────────────────────────

def scrape_eic() -> list:
    print("EIC…", flush=True)
    events = []
    base = "https://eic.ec.europa.eu"
    url  = f"{base}/events_en"
    soup = get_html(url)
    if not soup:
        return events

    for item in soup.find_all(class_=re.compile(r"card|event|listing")):
        title_tag = item.find(["h3","h2","h4","h5"])
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        link_tag = item.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        event_url = href if href.startswith("http") else base + href

        time_tag = item.find("time")
        date_text = time_tag.get("datetime","") if time_tag else ""
        if not date_text:
            date_text = item.get_text(" ", strip=True)
        iso = parse_date(date_text)

        loc_tag = item.find(class_=re.compile(r"location|place|country"))
        location = loc_tag.get_text(strip=True) if loc_tag else ""

        desc_tag = item.find(class_=re.compile(r"summary|description|teaser|body"))
        desc = desc_tag.get_text(strip=True)[:200] if desc_tag else ""

        if title and is_future_or_ongoing(iso):
            events.append({
                "title": title, "source": "EIC",
                "date": iso, "date_end": "",
                "location": location, "url": event_url, "description": desc
            })

    print(f"  → {len(events)} events")
    return events


# ── SOURCE 3: Access2EIC ──────────────────────────────────────────────────────

def scrape_access2eic() -> list:
    print("Access2EIC…", flush=True)
    events = []
    url  = "https://access2eic.eu/eventi/"
    soup = get_html(url)
    if not soup:
        return events

    # WordPress event posts
    for item in soup.find_all(["article", "div"], class_=re.compile(r"event|post|entry")):
        title_tag = item.find(["h2","h3","h4"])
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        link_tag = item.find("a", href=True)
        event_url = link_tag["href"] if link_tag else ""

        date_text = item.get_text(" ", strip=True)
        iso = parse_date(date_text)

        desc_tag = item.find("p")
        desc = desc_tag.get_text(strip=True)[:200] if desc_tag else ""

        if title and is_future_or_ongoing(iso):
            events.append({
                "title": title, "source": "Access2EIC",
                "date": iso, "date_end": "",
                "location": "Online", "url": event_url, "description": desc
            })

    print(f"  → {len(events)} events")
    return events


# ── SOURCE 4: EBAN ────────────────────────────────────────────────────────────

def scrape_eban() -> list:
    print("EBAN…", flush=True)
    events = []
    url  = "https://www.eban.org/events-page/"
    soup = get_html(url)
    if not soup:
        return events

    for item in soup.find_all(["article","div"], class_=re.compile(r"event|post|card|tribe")):
        title_tag = item.find(["h2","h3","h4","h5"])
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        link_tag = item.find("a", href=True)
        event_url = link_tag["href"] if link_tag else ""

        date_text = item.get_text(" ", strip=True)
        iso = parse_date(date_text)

        loc_tag = item.find(class_=re.compile(r"location|venue|city"))
        location = loc_tag.get_text(strip=True) if loc_tag else ""

        if title and is_future_or_ongoing(iso):
            events.append({
                "title": title, "source": "EBAN",
                "date": iso, "date_end": "",
                "location": location, "url": event_url, "description": ""
            })

    print(f"  → {len(events)} events")
    return events


# ── SOURCE 5: BpiFrance (Playwright) ─────────────────────────────────────────

def scrape_bpifrance() -> list:
    print("BpiFrance…", flush=True)
    events = []
    url = "https://evenements.bpifrance.fr/events"

    html = get_html_playwright(url)
    if not html:
        return events

    soup = BeautifulSoup(html, "html.parser")

    for item in soup.find_all(["article","div","li"], class_=re.compile(r"event|card|item")):
        title_tag = item.find(["h2","h3","h4","h5"])
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        link_tag = item.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        event_url = href if href.startswith("http") else "https://evenements.bpifrance.fr" + href

        date_text = item.get_text(" ", strip=True)
        iso = parse_date(date_text)

        if title and is_future_or_ongoing(iso):
            events.append({
                "title": title, "source": "BpiFrance",
                "date": iso, "date_end": "",
                "location": "", "url": event_url, "description": ""
            })

    print(f"  → {len(events)} events")
    return events


# ── SOURCE 6: European Startup Network ───────────────────────────────────────

def scrape_esn() -> list:
    print("European Startup Network…", flush=True)
    events = []
    url  = "https://europeanstartupnetwork.eu/news/"
    soup = get_html(url)
    if not soup:
        return events

    for item in soup.find_all(["article","div"], class_=re.compile(r"post|news|card|entry")):
        title_tag = item.find(["h2","h3","h4"])
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        link_tag = item.find("a", href=True)
        event_url = link_tag["href"] if link_tag else ""

        date_text = item.get_text(" ", strip=True)
        iso = parse_date(date_text)

        desc_tag = item.find("p")
        desc = desc_tag.get_text(strip=True)[:200] if desc_tag else ""

        # ESN /news is general news, include all recent items
        if title:
            events.append({
                "title": title, "source": "European Startup Network",
                "date": iso, "date_end": "",
                "location": "", "url": event_url, "description": desc
            })

    print(f"  → {len(events)} events")
    return events


# ── SOURCE 7: EuroQuity / Access2EIC community (Playwright) ──────────────────

def scrape_euroquity() -> list:
    print("EuroQuity…", flush=True)
    events = []
    url = "https://www.euroquity.com/en/community/access2eic"

    html = get_html_playwright(url)
    if not html:
        return events

    soup = BeautifulSoup(html, "html.parser")

    for item in soup.find_all(["article","div","li"], class_=re.compile(r"event|card|item|post")):
        title_tag = item.find(["h2","h3","h4","h5"])
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        link_tag = item.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        event_url = href if href.startswith("http") else "https://www.euroquity.com" + href

        date_text = item.get_text(" ", strip=True)
        iso = parse_date(date_text)

        if title and is_future_or_ongoing(iso):
            events.append({
                "title": title, "source": "EuroQuity",
                "date": iso, "date_end": "",
                "location": "", "url": event_url, "description": ""
            })

    print(f"  → {len(events)} events")
    return events


# ── SOURCE 8: EC Seal of Excellence ──────────────────────────────────────────

def scrape_seal_of_excellence() -> list:
    print("EC Seal of Excellence…", flush=True)
    events = []
    url = "https://research-and-innovation.ec.europa.eu/funding/funding-opportunities/seal-excellence/eic-seal-excellence-opportunities_en"
    soup = get_html(url)
    if not soup:
        return events

    # This page lists funding opportunities, not events per se.
    # We treat each listed opportunity as an item.
    for item in soup.find_all(["article","div","li","tr"], class_=re.compile(r"item|card|row|opportunity")):
        title_tag = item.find(["h2","h3","h4","h5","td","strong"])
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        link_tag = item.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        item_url = href if href.startswith("http") else "https://research-and-innovation.ec.europa.eu" + href

        date_text = item.get_text(" ", strip=True)
        iso = parse_date(date_text)

        if title and is_future_or_ongoing(iso):
            events.append({
                "title": title, "source": "EC Seal of Excellence",
                "date": iso, "date_end": "",
                "location": "", "url": item_url or url, "description": ""
            })

    print(f"  → {len(events)} opportunities")
    return events


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    all_events = []

    # Static HTML sources (fast)
    all_events += scrape_een()
    all_events += scrape_eic()
    all_events += scrape_access2eic()
    all_events += scrape_eban()
    all_events += scrape_esn()
    all_events += scrape_seal_of_excellence()

    # JS-rendered sources (slower, Playwright)
    all_events += scrape_bpifrance()
    all_events += scrape_euroquity()

    # Deduplicate by URL
    seen_urls = set()
    deduped = []
    for e in all_events:
        url = e.get("url","")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(e)

    # Sort: events with dates first (ascending), then undated
    dated   = [e for e in deduped if e.get("date")]
    undated = [e for e in deduped if not e.get("date")]
    dated.sort(key=lambda e: e["date"])
    all_sorted = dated + undated

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "count": len(all_sorted),
        "events": all_sorted,
    }

    out = Path("events.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Saved {out} with {len(all_sorted)} events/opportunities")

    # Summary by source
    by_src = {}
    for e in all_sorted:
        s = e["source"]
        by_src[s] = by_src.get(s, 0) + 1
    for s, n in sorted(by_src.items()):
        print(f"  {n:4d}  {s}")


if __name__ == "__main__":
    main()
