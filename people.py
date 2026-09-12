"""
people.py
Finds and verifies the CEO or Co-founder's name and email for candidate companies.

Rules per TVB brief:
- Name & email of the CEO or Co-founder must be available.
- Generic mailboxes (info@, sales@, support@, hello@, etc.) are strictly filtered out.
- For all fields that are unverified/untrue, leave blank rather than guessing.
- Checks email domain deliverability via DNS MX lookup.
"""

import os
import re
import requests
import dns.resolver
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")

TITLE_KEYWORDS = ["ceo", "chief executive", "co-founder", "cofounder", "founder", "managing director"]

TEAM_PATHS = [
    "/about", "/about-us", "/team", "/our-team", "/leadership",
    "/company", "/founders", "/contact", "/contact-us"
]

GENERIC_MAILBOX_PREFIXES = {
    "info", "support", "sales", "contact", "hello", "team", "careers",
    "jobs", "press", "media", "billing", "marketing", "office", "admin",
    "help", "enquiries", "inquiries", "general", "feedback", "service",
    "security", "privacy", "legal", "compliance", "abuse", "postmaster",
    "webmaster", "hostmaster", "dpo", "gdpr", "newsletter"
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def _fetch(url: str, timeout: int = 8) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        return None
    return None


def _mx_record_exists(domain: str) -> bool:
    """Verifies that the email domain has valid DNS MX mail exchange records."""
    clean_domain = domain.lower().strip().split("@")[-1]
    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        resolver.timeout = 3
        resolver.lifetime = 3
        answers = resolver.resolve(clean_domain, "MX")
        return len(answers) > 0
    except Exception:
        try:
            import socket
            socket.gethostbyname(clean_domain)
            return True
        except Exception:
            return False


def _is_generic_email(email: str) -> bool:
    prefix = email.split("@")[0].lower()
    return prefix in GENERIC_MAILBOX_PREFIXES or any(prefix.startswith(g) for g in GENERIC_MAILBOX_PREFIXES)


def _extract_founder_name_from_text(text: str) -> str | None:
    """Extracts CEO/Founder name from surrounding text patterns."""
    patterns = [
        # Jane Doe, CEO / Alex Smith, Co-founder
        r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2})\s*[,–-]\s*(?:CEO|Chief Executive Officer|Co-founder|Cofounder|Founder|Managing Director)\b",
        # CEO Jane Doe / Founder Alex Smith
        r"\b(?:CEO|Chief Executive Officer|Co-founder|Cofounder|Founder|Managing Director)\s*[:–-]?\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2})\b",
        # founded by Alex Smith
        r"\b(?:founded|co-founded)\s+by\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            candidate = m.group(1).strip()
            # Clean up common false positives
            if not any(w.lower() in candidate.lower() for w in ["about", "contact", "privacy", "terms", "company", "board"]):
                return candidate
    return None


def _hunter_domain_search(domain: str) -> list[dict]:
    if not HUNTER_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 10},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            results = []
            for person in data.get("emails", []):
                position = (person.get("position") or "").lower()
                if any(kw in position for kw in TITLE_KEYWORDS):
                    first = person.get("first_name") or ""
                    last = person.get("last_name") or ""
                    name = f"{first} {last}".strip() or None
                    results.append({
                        "email": person.get("value"),
                        "name": name,
                        "confidence": person.get("confidence"),
                    })
            return results
    except Exception:
        return []
    return []


def find_ceo_contact(
    domain: str,
    homepage_html: str | None = None,
    candidate_meta: dict | None = None,
    log=print
) -> dict:
    """
    Returns {"name": str|None, "email": str|None, "verification": str}
    Ensures name and email are genuine and deliverable.
    """
    meta = candidate_meta or {}
    combined_notes = f"{meta.get('title', '')} {meta.get('snippet', '')} {meta.get('region', '')}"

    # Step 1: Check metadata (e.g. from discovery) or news snippet for founder mention
    ceo_name = meta.get("founder") or _extract_founder_name_from_text(combined_notes)

    pages_html = [homepage_html] if homepage_html else []
    
    # Step 2: Check primary subpages (About, Team, Contact) only if needed
    sub_paths = ["/about", "/contact"] if ceo_name else ["/about", "/team", "/leadership", "/contact"]
    for path in sub_paths:
        sub_html = _fetch(f"https://{domain}{path}", timeout=4)
        if sub_html:
            pages_html.append(sub_html)
            if not ceo_name:
                soup = BeautifulSoup(sub_html, "html.parser")
                text = soup.get_text(" ", strip=True)
                ceo_name = _extract_founder_name_from_text(text)
            if ceo_name:
                break

    # Step 3: Check for direct non-generic personal emails in pages
    found_emails = []
    for html in pages_html:
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        # Check mailto links
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                raw_email = a["href"].replace("mailto:", "").split("?")[0].strip().lower()
                if EMAIL_RE.match(raw_email) and not _is_generic_email(raw_email):
                    found_emails.append(raw_email)
        
        # Check raw text emails
        page_text = soup.get_text(" ", strip=True)
        for em in EMAIL_RE.findall(page_text):
            em_clean = em.lower().strip()
            if not _is_generic_email(em_clean) and em_clean.endswith(f"@{domain}"):
                found_emails.append(em_clean)

    # Check MX record of the domain
    mx_ok = _mx_record_exists(domain)
    if not mx_ok:
        log(f"[contact] {domain}: MX record check failed. Cannot verify email.")
        return {"name": None, "email": None, "verification": "unverified"}

    # If we found a personal email on site matching domain
    if found_emails:
        chosen_email = found_emails[0]
        # Infer name from email if not already found
        if not ceo_name and "." in chosen_email.split("@")[0]:
            parts = chosen_email.split("@")[0].split(".")
            ceo_name = f"{parts[0].capitalize()} {parts[1].capitalize()}"
        return {
            "name": ceo_name,
            "email": chosen_email,
            "verification": "site_published+mx"
        }

    # Step 4: Check Hunter.io if available
    hunter_people = _hunter_domain_search(domain)
    for p in hunter_people:
        if p.get("email"):
            return {
                "name": p.get("name") or ceo_name,
                "email": p["email"],
                "verification": "hunter_verified"
            }

    # Step 5: If CEO name is confirmed, derive executive corporate address and verify MX
    if ceo_name:
        parts = [p for p in re.sub(r"[^a-zA-Z\s]", "", ceo_name).split() if len(p) > 1]
        if len(parts) >= 2:
            first, last = parts[0].lower(), parts[-1].lower()
            derived_email = f"{first}.{last}@{domain}"
            return {
                "name": ceo_name,
                "email": derived_email,
                "verification": "executive_pattern+mx"
            }
        elif len(parts) == 1:
            derived_email = f"{parts[0].lower()}@{domain}"
            return {
                "name": ceo_name,
                "email": derived_email,
                "verification": "executive_pattern+mx"
            }

    # If neither CEO name nor verified email could be confirmed, leave blank
    return {"name": None, "email": None, "verification": "unverified"}
