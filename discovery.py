"""
discovery.py
Autonomously discovers candidate companies matching TVB's criteria:
- Discovers from dynamic live sources (not a static list).
- Supports Gemini API (with models like gemini-3.1-flash-lite, gemini-3.6-flash, etc.).
- Robust markdown parser that cleanly extracts companies even when formatted with bolding/markdown.
- Resilient multi-source discovery (Gemini + Live Web feeds) ensuring high coverage across global hubs.
"""

import os
import re
import time
import socket
import random
import urllib.parse
import requests
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

# Deliberately non-US regions/hubs to bias discovery toward the "minimal/no US presence" requirement
REGIONS = [
    "United Kingdom", "Germany", "France", "Netherlands", "Sweden", "Poland",
    "Spain", "Estonia", "Finland", "India", "Singapore", "Indonesia",
    "Vietnam", "Malaysia", "UAE", "Saudi Arabia", "Egypt", "Nigeria",
    "Kenya", "South Africa", "Brazil", "Colombia", "Mexico", "Australia", "Canada"
]

SECTOR_ANGLES = [
    "B2B SaaS and enterprise software platforms",
    "fintech, payments, and financial infrastructure platforms",
    "AI, machine learning, and automation platforms",
    "healthtech and digital medical platforms",
    "logistics, freight, and supply chain tech platforms",
    "developer tools, API platforms, and cloud software",
    "edtech and learning management platforms",
    "e-commerce infrastructure and B2B marketplace platforms"
]

LINE_RE = re.compile(
    r"(?:COMPANY|Company):\s*(?P<name>[^|\n]+?)\s*\|\s*(?:DOMAIN|Domain):\s*(?P<domain>[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?:\s*\|\s*(?:FOUNDER|Founder|CEO):\s*(?P<founder>[^|\n]+?))?\s*\|\s*(?:NOTE|Note|DETAILS|Details):\s*(?P<note>.+)",
    re.IGNORECASE
)


def _clean_domain(raw_domain: str) -> str:
    domain = raw_domain.strip().lower()
    domain = domain.replace("**", "").replace("*", "")
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.split("/")[0].split(":")[0].strip()
    return domain


def _domain_is_active(domain: str) -> bool:
    """Fast DNS check (5-10ms) to ensure domain is real and resolving."""
    try:
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False


def _get_gemini_client(api_key: str | None = None):
    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key or not genai:
        return None, None
    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    try:
        client = genai.Client(api_key=key)
        return client, model
    except Exception:
        return None, None


def _parse_candidate_line(line: str) -> dict | None:
    # Clean markdown asterisks and backticks
    cleaned = line.replace("**", "").replace("*", "").replace("`", "").strip()
    if cleaned.startswith("- ") or cleaned.startswith("* "):
        cleaned = cleaned[2:].strip()
    m = LINE_RE.search(cleaned)
    if not m:
        return None

    domain = _clean_domain(m.group("domain"))
    if not domain or "." not in domain or len(domain) < 4:
        return None

    name = m.group("name").strip()
    note = m.group("note").strip()
    founder = m.group("founder").strip() if m.group("founder") else None

    return {
        "domain": domain,
        "title": name,
        "founder": founder,
        "snippet": note,
        "source_url": f"https://{domain}"
    }


def _discover_via_gemini(client, model_name: str, n_prompts: int, log=print) -> list[dict]:
    candidates = []
    seen = set()

    regions = REGIONS.copy()
    random.shuffle(regions)
    sectors = SECTOR_ANGLES.copy()
    random.shuffle(sectors)

    # Fast check: only use search grounding if explicitly enabled and available
    use_grounding = os.environ.get("ENABLE_SEARCH_GROUNDING", "false").lower() in ("true", "1")

    for i in range(n_prompts):
        region = regions[i % len(regions)]
        sector = sectors[i % len(sectors)]

        prompt = f"""Identify 4 to 6 real, currently operating tech startup companies matching ALL these parameters:
1. Stage: Total funding raised or annual revenue is between $1 million and $5 million USD.
2. Product: Operates a tech-related platform, software, or SaaS in {sector}.
3. Location: Headquartered and founded strictly in {region} (outside the United States).
4. Leadership: Include the actual real name of the CEO or Co-founder.

For each company, output exactly one line in this format (no extra commentary, no numbers):
COMPANY: <company name> | DOMAIN: <official website domain, e.g. company.com> | FOUNDER: <CEO or Co-founder full name> | NOTE: <raised $X million, headquarters location, one sentence summary>
"""
        log(f"[discovery:gemini] Query {i+1}/{n_prompts} across {region} ({sector.split()[0]})...")

        resp = None
        if use_grounding:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())]
                    ) if types else None
                )
            except Exception as e:
                use_grounding = False
                log(f"[discovery:gemini] Grounding tool not available ({e.__class__.__name__}). Using high-speed direct generation.")

        if not resp:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
            except Exception as e:
                log(f"[discovery:gemini] Request failed: {e}")
                break

        text = getattr(resp, "text", "") or ""
        for line in text.splitlines():
            cand = _parse_candidate_line(line)
            if cand and cand["domain"] not in seen:
                if _domain_is_active(cand["domain"]):
                    seen.add(cand["domain"])
                    candidates.append(cand)
                    log(f"[discovery:found] {cand['title']} ({cand['domain']})")

        time.sleep(0.5)

    return candidates


def _discover_via_web(regions: list[str], max_items: int = 30, log=print) -> list[dict]:
    """Fast live RSS tech funding announcement scraper."""
    candidates = []
    seen = set()

    for region in regions:
        if len(candidates) >= max_items:
            break

        query = f'"{region}" ("seed round" OR "Series A") ("$1" OR "$2" OR "$3" OR "$4" OR "$5") million (platform OR SaaS OR software) -US'
        rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en&gl=US&ceid=US:en"
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=6)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.find_all("item")

            for item in items[:4]:
                title_elem = item.find("title")
                if not title_elem:
                    continue
                title = title_elem.text.strip()

                comp_match = re.search(
                    r"(?:Startup|Fintech|AI startup|Platform)?\s*([A-Z][a-zA-Z0-9\s]{1,20}?)\s+(?:raises|secures|bags|closes|nabs|lands)\s+",
                    title,
                    re.IGNORECASE
                )
                company_name = comp_match.group(1).strip() if comp_match else ""
                if not company_name or len(company_name) < 3 or any(w.lower() == company_name.lower() for w in ["io", "za", "ai", "app", "the", "new", "seed", "tech"]) or any(w.lower() in company_name.lower() for w in ["startup", "raises", "funding", "seed", "series", "round", "investors"]):
                    continue

                # Fast DNS check for common TLDs
                slug = re.sub(r"[^a-zA-Z0-9]", "", company_name).lower()
                for ext in [".com", ".io", ".ai", ".co"]:
                    test_dom = f"{slug}{ext}"
                    if _domain_is_active(test_dom) and test_dom not in seen:
                        seen.add(test_dom)
                        candidates.append({
                            "domain": test_dom,
                            "title": company_name,
                            "snippet": f"{title}. Region: {region}.",
                            "source_url": f"https://{test_dom}"
                        })
                        log(f"[discovery:web] Found candidate: {company_name} ({test_dom})")
                        break
        except Exception:
            continue

    return candidates


def discover_candidates(
    n_queries: int = 10,
    api_key: str | None = None,
    log=print
) -> list[dict]:
    """
    Surfaces unique candidates across multiple discovery vectors.
    """
    candidates = []
    seen = set()

    client, model_name = _get_gemini_client(api_key)

    if client:
        log(f"[discovery] Running Gemini discovery with {model_name}...")
        gemini_candidates = _discover_via_gemini(client, model_name, n_prompts=min(n_queries, 6), log=log)
        for c in gemini_candidates:
            if c["domain"] not in seen:
                seen.add(c["domain"])
                candidates.append(c)

    # Complement with autonomous web news discovery if pool is low
    if len(candidates) < 20:
        log("[discovery] Complementing with autonomous live web funding feeds...")
        shuffled = random.sample(REGIONS, min(len(REGIONS), 10))
        web_cands = _discover_via_web(shuffled, max_items=20, log=log)
        for c in web_cands:
            if c["domain"] not in seen:
                seen.add(c["domain"])
                candidates.append(c)

    log(f"[discovery] Total unique candidates discovered: {len(candidates)}")
    return candidates
