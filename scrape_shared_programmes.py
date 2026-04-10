"""
scrape_shared_programmes.py
────────────────────────────
Scrapes the EC Regional Policy "Managing Authorities" pages for all 27 EU Member States
and extracts the 2021-2027 operational programmes (ERDF, ESF+, CF, JTF, Interreg).

Output: shared_programmes.json
  {
    "generated": "...",
    "programmes": [
      {
        "country_code": "AT",
        "country": "Austria",
        "programme_name": "ESF+ Programme Employment Austria & JTF 2021-2027",
        "managing_authority": "Bundesministerium für Arbeit...",
        "contact_name": "Mag. Bibiana Klingseisen",
        "email": "bibiana.klingseisen@...",
        "url": "https://ec.europa.eu/regional_policy/in-your-country/programmes/2021-2027/at/...",
        "cci": "2021AT05FFPR001",
        "fund": "ESF+",
        "thematic_clusters": ["Culture, Creativity & Inclusion", "Cross-cutting / Other"]
      }, ...
    ]
  }

Run:
    pip install requests beautifulsoup4
    python scrape_shared_programmes.py
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Country list ──────────────────────────────────────────────────────────────

COUNTRIES = [
    ("AT", "Austria",      "austria"),
    ("BE", "Belgium",      "belgium"),
    ("BG", "Bulgaria",     "bulgaria"),
    ("HR", "Croatia",      "croatia"),
    ("CY", "Cyprus",       "cyprus"),
    ("CZ", "Czech Republic","czechia"),
    ("DK", "Denmark",      "denmark"),
    ("EE", "Estonia",      "estonia"),
    ("FI", "Finland",      "finland"),
    ("FR", "France",       "france"),
    ("DE", "Germany",      "germany"),
    ("GR", "Greece",       "greece"),
    ("HU", "Hungary",      "hungary"),
    ("IE", "Ireland",      "ireland"),
    ("IT", "Italy",        "italy"),
    ("LV", "Latvia",       "latvia"),
    ("LT", "Lithuania",    "lithuania"),
    ("LU", "Luxembourg",   "luxembourg"),
    ("MT", "Malta",        "malta"),
    ("NL", "Netherlands",  "netherlands"),
    ("PL", "Poland",       "poland"),
    ("PT", "Portugal",     "portugal"),
    ("RO", "Romania",      "romania"),
    ("SK", "Slovakia",     "slovakia"),
    ("SI", "Slovenia",     "slovenia"),
    ("ES", "Spain",        "spain"),
    ("SE", "Sweden",       "sweden"),
]

BASE_URL = "https://ec.europa.eu/regional_policy/in-your-country/managing-authorities/{}_en"
PROG_BASE = "https://ec.europa.eu/regional_policy/in-your-country/programmes/2021-2027"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Fund detection from CCI code ──────────────────────────────────────────────
# CCI format: 2021CCXXYYYYY
#   CC = country code
#   XX = fund code (05=ESF+, 16=ERDF, TC=Interreg)
#   Also detect from name keywords

def detect_fund(cci: str, name: str) -> str:
    cci_up  = (cci or "").upper()
    name_lo = (name or "").lower()

    if "TC" in cci_up[:8]:          return "Interreg"
    if "JT" in cci_up[6:10]:        return "JTF"

    fund_code = cci_up[6:8] if len(cci_up) >= 8 else ""
    if fund_code == "05":            return "ESF+"
    if fund_code == "16":            return "ERDF"
    if fund_code == "08":            return "CF"

    # Fallback: name-based
    if "interreg" in name_lo:        return "Interreg"
    if "esf" in name_lo:             return "ESF+"
    if "erdf" in name_lo or "regional development" in name_lo: return "ERDF"
    if "cohesion fund" in name_lo:   return "CF"
    if "just transition" in name_lo or "jtf" in name_lo: return "JTF"
    if "emfaf" in name_lo or "maritime" in name_lo:      return "EMFAF"
    if "eafrd" in name_lo or "rural development" in name_lo:  return "EAFRD"

    return "ERDF/ESF+"


# ── Thematic classification from fund + programme name ───────────────────────

THEMATIC_KEYWORDS = {
    "Health & Life Sciences": [
        "health", "medical", "sanit", "hospital", "care", "salute",
    ],
    "Culture, Creativity & Inclusion": [
        "employment", "social", "inclusion", "education", "training",
        "youth", "poverty", "deprivat", "material", "culture", "creative",
        "erasmus", "esf", "labour", "workforce", "gender", "equal",
        "integr", "migrant", "asylum",
    ],
    "Digital, Industry & Space": [
        "digital", "innovation", "competitiv", "sme", "enterprise",
        "research", "technology", "industri", "smart",
    ],
    "Climate, Energy & Mobility": [
        "climate", "energy", "green", "low.carbon", "transition",
        "transport", "mobility", "infrastructure", "environment",
        "sustainable", "carbon", "jtf", "just transition", "erdf",
        "growth", "investment",
    ],
    "Food, Bioeconomy & Environment": [
        "rural", "agriculture", "food", "bioeconom", "maritime",
        "fisheries", "coastal", "eafrd", "emfaf",
    ],
    "Security & Resilience": [
        "security", "resilience", "civil protection", "border",
        "isf", "migration",
    ],
    "Regional Development & Territorial Cooperation": [
        "interreg", "territorial", "cooperation", "cross.border",
        "transnational",
    ],
}

def classify_thematic(name: str, fund: str) -> list:
    """Return list of thematic cluster labels for a programme."""
    name_lo = (name or "").lower()
    fund_lo = (fund or "").lower()
    combined = name_lo + " " + fund_lo

    found = []
    for label, keywords in THEMATIC_KEYWORDS.items():
        for kw in keywords:
            if re.search(kw, combined):
                found.append(label)
                break

    # Fund-based defaults when nothing matched
    if not found:
        if fund == "ESF+":   found = ["Culture, Creativity & Inclusion"]
        elif fund == "JTF":  found = ["Climate, Energy & Mobility"]
        elif fund == "EAFRD":found = ["Food, Bioeconomy & Environment"]
        elif fund == "EMFAF":found = ["Food, Bioeconomy & Environment"]
        elif fund == "Interreg": found = ["Regional Development & Territorial Cooperation"]
        elif fund == "CF":   found = ["Climate, Energy & Mobility"]
        else:                found = ["Cross-cutting / Other"]

    # Deduplicate preserving order
    return list(dict.fromkeys(found))


# ── HTML parsing ──────────────────────────────────────────────────────────────

def parse_page(html: str, country_code: str, country_name: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    programmes = []

    # Find the 2021-2027 section — it's after an h4 containing "2021"
    in_section = False
    current_ma = {}
  # creates an empty dictionary to store data of a managing authority

    for tag in soup.find_all(["h4", "h3", "dt", "dd"]):
        text = tag.get_text(strip=True)
      """ retrieves all HTML elements in the page that are sub-headings (h3, h4) or definition pairs (dt/dd) 
      and extracts clean text"""

        # Detect section markers
        if tag.name == "h4":
            if "2021" in text and "2027" in text:
                in_section = True
                continue
            elif "2014" in text or "2007" in text:
                in_section = False
                # Save any pending MA
                if current_ma.get("programme_name"):
                    programmes.append(current_ma)
                    current_ma = {}
                continue

        if not in_section:
            continue
          #ensures only headings containing 2021-2027 are considered

        # Each MA block is an h3 (subsection with managing authority name) 
        if tag.name == "h3":
            if current_ma.get("programme_name"):
                programmes.append(current_ma)
            current_ma = {
                "country_code": country_code,
                "country": country_name,
                "managing_authority": text,
                "contact_name": "",
                "email": "",
                "programme_name": "",
                "url": "",
                "cci": "",
                "fund": "",
                "thematic_clusters": [],
            }
          #if MA was already present, ssaves it in the list "programmes"
      """creates an empty list with all the fields, starts filling country code (AT, BE, ...), 
      name, and managing authority. the remaining fields will be filled later""" 

        elif tag.name == "dt":
            label = text.lower()
            dd = tag.find_next_sibling("dd")
            if not dd:
                continue
            value = dd.get_text(strip=True)

            if "contact" in label:
                current_ma["contact_name"] = value
            elif "email" in label:
                # get email from mailto link
                a = dd.find("a")
                if a and "mailto" in (a.get("href","") or ""):
                    current_ma["email"] = a["href"].replace("mailto:","").strip()
            elif "operational programme" in label or "programme" in label:
                current_ma["programme_name"] = value
                # get URL
                a = dd.find("a")
                if a and a.get("href"):
                    href = a["href"]
                    current_ma["url"] = (
                        "https://ec.europa.eu" + href
                        if href.startswith("/") else href
                    )
            elif "cci" in label:
                current_ma["cci"] = value

    # Save last block
    if current_ma.get("programme_name"):
        programmes.append(current_ma)

    # Post-process: detect fund and thematic
    for p in programmes:
        p["fund"] = detect_fund(p["cci"], p["programme_name"])
        p["thematic_clusters"] = classify_thematic(p["programme_name"], p["fund"])

    # Filter: only 2021-2027 (CCI starts with 2021) or no CCI but in section
    filtered = []
    for p in programmes:
        cci = p.get("cci","")
        if cci.startswith("2021") or not cci:
            filtered.append(p)

    return filtered


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    all_programmes = []

    for code, name, slug in COUNTRIES:
        url = BASE_URL.format(slug)
        print(f"Fetching {name} ({code})… ", end="", flush=True)
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            progs = parse_page(resp.text, code, name)
            print(f"{len(progs)} programmes")
            all_programmes.extend(progs)
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(0.5)

    # Remove Interreg duplicates (same programme listed under multiple countries)
    seen_cci = set()
    deduped = []
    for p in all_programmes:
        cci = p.get("cci","")
        if p["fund"] == "Interreg" and cci and cci in seen_cci:
            continue
        if cci:
            seen_cci.add(cci)
        deduped.append(p)

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "count": len(deduped),
        "programmes": deduped,
    }

    out = Path("shared_programmes.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Saved {out} with {len(deduped)} programmes")

    # Stats
    funds = {}
    for p in deduped:
        k = p["fund"]
        funds[k] = funds.get(k,0)+1
    print("By fund:", funds)


if __name__ == "__main__":
    main()
