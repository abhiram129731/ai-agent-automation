"""
enrich.py
Fetches a candidate company's website and checks TVB's hard investment filters:
  1. Funding or revenue figure roughly between $1M and $5M USD
  2. Operates a tech-related platform (SaaS, marketplace, API, software)
  3. Minimal to no US presence (HQ and core operations outside the US)
  4. Generates clean sector and description
"""

import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

PLATFORM_KEYWORDS = [
    "platform", "saas", "software as a service", "marketplace", "api",
    "app", "application", "mobile app", "web app", "cloud-based",
    "software", "tech stack", "ai-powered", "b2b software", "portal",
    "data platform", "workflow automation", "developer tools", "infrastructure",
    "fintech platform", "enterprise software", "analytics platform"
]

US_HQ_SIGNALS = [
    "headquartered in san francisco", "headquartered in new york", "headquartered in austin",
    "headquartered in seattle", "headquartered in boston", "headquartered in los angeles",
    "headquartered in silicon valley", "headquartered in chicago", "hq in san francisco",
    "hq in new york", "hq in austin", "hq: new york", "hq: san francisco", "hq: usa",
    "headquarters: united states", "headquartered in the united states"
]

NON_US_HUBS = [
    # UK & Europe
    "united kingdom", "uk", "london", "manchester", "cambridge", "oxford", "edinburgh",
    "germany", "berlin", "munich", "hamburg", "frankfurt", "france", "paris", "lyon",
    "netherlands", "amsterdam", "rotterdam", "poland", "warsaw", "krakow", "wroclaw",
    "sweden", "stockholm", "finland", "helsinki", "norway", "oslo", "denmark", "copenhagen",
    "estonia", "tallinn", "spain", "madrid", "barcelona", "italy", "milan", "rome",
    "switzerland", "zurich", "geneva", "austria", "vienna", "belgium", "brussels",
    "ireland", "dublin", "portugal", "lisbon", "czech republic", "prague", "romania", "bucharest",
    # Asia & Pacific
    "india", "bangalore", "bengaluru", "mumbai", "delhi", "gurgaon", "noida", "hyderabad", "pune", "chennai",
    "singapore", "indonesia", "jakarta", "vietnam", "ho chi minh", "hanoi", "malaysia", "kuala lumpur",
    "philippines", "manila", "thailand", "bangkok", "japan", "tokyo", "south korea", "seoul",
    "australia", "sydney", "melbourne", "brisbane", "new zealand", "auckland",
    # Middle East & North Africa
    "uae", "united arab emirates", "dubai", "abu dhabi", "saudi arabia", "riyadh", "jeddah",
    "egypt", "cairo", "morocco", "casablanca", "qatar", "doha", "bahrain", "manama", "israel", "tel aviv",
    # Sub-Saharan Africa
    "nigeria", "lagos", "kenya", "nairobi", "south africa", "cape town", "johannesburg", "ghana", "accra", "rwanda", "kigali",
    # Latin America
    "brazil", "são paulo", "sao paulo", "rio de janeiro", "mexico", "mexico city", "colombia", "bogotá", "bogota",
    "medellín", "chile", "santiago", "argentina", "buenos aires", "peru", "lima", "uruguay", "montevideo",
    # Canada
    "canada", "toronto", "vancouver", "montreal", "waterloo", "ottawa", "calgary"
]


def _fetch(url: str, timeout: int = 8) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and "text" in resp.headers.get("Content-Type", ""):
            return resp.text
    except Exception:
        return None
    return None


def extract_funding_amount(text: str) -> float | None:
    """
    Extracts a funding/revenue figure in millions USD, supporting
    multiple currencies (€, £, USD, $, etc.).
    """
    patterns = [
        # $2.5 million / $3M / USD 2.5 million
        (r"(?:\$|USD\s*)(\d+(?:\.\d+)?)\s*(?:million|m|mn)\b", 1.0),
        # €2 million / EUR 2M (convert ~1.08 to USD)
        (r"(?:€|EUR\s*)(\d+(?:\.\d+)?)\s*(?:million|m|mn)\b", 1.08),
        # £2 million / GBP 2M (convert ~1.28 to USD)
        (r"(?:£|GBP\s*)(\d+(?:\.\d+)?)\s*(?:million|m|mn)\b", 1.28),
        # 2.5 million USD / dollars
        (r"(\d+(?:\.\d+)?)\s*(?:million|m|mn)\s*(?:dollars|usd)\b", 1.0),
        # 2 million euros
        (r"(\d+(?:\.\d+)?)\s*(?:million|m|mn)\s*(?:euros|eur)\b", 1.08),
        # 2 million pounds
        (r"(\d+(?:\.\d+)?)\s*(?:million|m|mn)\s*(?:pounds|gbp)\b", 1.28),
        # 'raised $2.5M' or 'seed round of $3M'
        (r"(?:raised|secures|funding of|seed of)\s*\$?(\d+(?:\.\d+)?)\s*(?:million|m|mn)\b", 1.0),
        # Whole numbers like $2,500,000
        (r"\$\s*([1-9]\d{0,1}(?:,\d{3}){2})\b", 1e-6)
    ]

    for pat, multiplier in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                raw_num = m.group(1).replace(",", "")
                val = float(raw_num) * multiplier
                return round(val, 2)
            except Exception:
                continue
    return None


def has_platform_signal(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in PLATFORM_KEYWORDS)


def us_presence_signal(text: str) -> str:
    """
    Returns 'us', 'non_us', or 'unknown'.
    Prioritizes headquarters and operating base over incidental mentions.
    """
    t = text.lower()
    if any(sig in t for sig in US_HQ_SIGNALS):
        return "us"

    non_us_hits = [sig for sig in NON_US_HUBS if sig in t]
    if non_us_hits:
        return "non_us"

    return "unknown"


def guess_sector(text: str) -> str:
    t = text.lower()
    sector_map = {
        "FinTech Platform": ["fintech", "payments", "banking", "lending", "insurtech", "wealthtech"],
        "AI & Enterprise SaaS": ["artificial intelligence", "generative ai", "ai-powered", "machine learning", "enterprise software", "b2b saas"],
        "HealthTech Platform": ["healthtech", "health tech", "telemedicine", "medtech", "digital health"],
        "Logistics & Supply Chain Tech": ["logistics", "supply chain", "freight", "delivery platform", "fleet"],
        "Developer Tools & Cloud Infrastructure": ["developer tools", "api platform", "devtools", "cloud infrastructure", "database"],
        "EdTech Platform": ["edtech", "education technology", "e-learning", "online learning"],
        "E-Commerce & Marketplace Infrastructure": ["e-commerce", "ecommerce", "online marketplace", "retail tech", "b2b marketplace"],
        "CyberSecurity Platform": ["cybersecurity", "security platform", "identity management", "cloud security"],
        "CleanTech & Energy": ["climate tech", "cleantech", "renewable energy", "carbon accounting", "sustainability platform"],
        "HR & Workforce Tech": ["hr tech", "recruiting platform", "hiring platform", "workforce management"]
    }
    for sector, kws in sector_map.items():
        if any(kw in t for kw in kws):
            return sector
    return "Technology / SaaS Platform"


def enrich_candidate(candidate: dict, log=print) -> dict | None:
    """
    Fetches candidate's site, validates funding ($1M-$5M), platform signal,
    and non-US geography.
    """
    domain = candidate["domain"]
    homepage_url = f"https://{domain}"
    html = _fetch(homepage_url)
    if html is None:
        homepage_url = f"http://{domain}"
        html = _fetch(homepage_url)

    page_text = ""
    description = ""
    if html:
        soup = BeautifulSoup(html, "html.parser")
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc["content"].strip()
        page_text = soup.get_text(separator=" ", strip=True)[:6000]

    # Combine news snippet context + site context
    combined_text = " ".join([
        candidate.get("title", ""),
        candidate.get("snippet", ""),
        candidate.get("region", ""),
        page_text
    ])

    funding_amount = extract_funding_amount(combined_text)
    platform_ok = has_platform_signal(combined_text)
    us_signal = us_presence_signal(combined_text)
    sector = guess_sector(combined_text)

    if not description:
        description = candidate.get("snippet", "")
        if len(description) > 180:
            description = description[:177] + "..."

    company_name = candidate.get("title", "").split(" - ")[0].split(" | ")[0].strip()
    if not company_name:
        company_name = domain.split(".")[0].capitalize()

    result = {
        "company_name": company_name,
        "domain": domain,
        "homepage_url": homepage_url,
        "description": description,
        "sector": sector,
        "funding_amount_millions": funding_amount,
        "platform_signal": platform_ok,
        "us_presence_signal": us_signal,
        "source_url": candidate.get("source_url", f"https://{domain}"),
        "region": candidate.get("region", ""),
        "page_html": html,
        "page_text": page_text
    }
    log(f"[enrich] {domain}: funding=${funding_amount}M | platform={platform_ok} | location={us_signal}")
    return result


def qualifies(enriched: dict) -> bool:
    """Applies hard filter: $1M-$5M funding, platform signal, non-US presence."""
    amt = enriched.get("funding_amount_millions")
    # Criteria: Revenue or funding between 1.0 and 5.0 million USD
    if amt is None or not (1.0 <= amt <= 5.0):
        return False
    if not enriched.get("platform_signal"):
        return False
    if enriched.get("us_presence_signal") != "non_us":
        return False
    return True
