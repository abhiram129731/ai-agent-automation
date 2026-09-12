"""
pipeline.py
Orchestrates autonomous discovery -> enrichment/filtering -> CEO contact verification,
continuing discovery rounds until target lead count (default 15) is fulfilled.
"""

from discovery import discover_candidates
from enrich import enrich_candidate, qualifies
from people import find_ceo_contact

MIN_LEADS = 15
MAX_QUERY_ROUNDS = 5
QUERIES_PER_ROUND = 12


def run_pipeline(
    min_leads: int = MIN_LEADS,
    api_key: str | None = None,
    log=print
) -> list[dict]:
    """
    Runs the multi-stage autonomous lead generation pipeline:
    1. Multi-source autonomous discovery (Gemini + Live Web/Press)
    2. Enrichment & 3-point hard filtering ($1M-$5M, tech platform, non-US)
    3. Contact extraction & email verification (CEO/co-founder, MX-verified)
    """
    qualifying_leads = []
    seen_domains = set()

    log(f"[START] Starting TVB Lead Agent Pipeline (Target: {min_leads} qualifying leads)...")

    for round_num in range(1, MAX_QUERY_ROUNDS + 1):
        if len(qualifying_leads) >= min_leads:
            break

        log(f"\n=======================================================")
        log(f"[ROUND {round_num}/{MAX_QUERY_ROUNDS}] "
            f"({len(qualifying_leads)}/{min_leads} qualified leads so far)")
        log(f"=======================================================")

        candidates = discover_candidates(
            n_queries=QUERIES_PER_ROUND,
            api_key=api_key,
            log=log
        )

        new_candidates = [c for c in candidates if c["domain"] not in seen_domains]
        for c in new_candidates:
            seen_domains.add(c["domain"])

        if not new_candidates:
            log("[pipeline] No new unique domains found in this round. Continuing to next round...")
            continue

        log(f"[pipeline] Analyzing & filtering {len(new_candidates)} new candidate companies...")

        for candidate in new_candidates:
            enriched = enrich_candidate(candidate, log=log)
            if enriched is None:
                continue

            # Hard filter against TVB criteria ($1M-$5M funding, tech platform, non-US)
            if not qualifies(enriched):
                log(f"[filter] REJECTED: {enriched['domain']} does not meet all 3 target parameters.")
                continue

            # Find and verify CEO / Co-founder contact
            contact = find_ceo_contact(
                domain=enriched["domain"],
                homepage_html=enriched.get("page_html"),
                candidate_meta=candidate,
                log=log
            )

            # Per brief: Name & email of CEO or Co-founder must be available
            # If unverified, leave out rather than putting generic data
            if not contact.get("email") or not contact.get("name"):
                log(f"[filter] REJECTED: {enriched['domain']} passed profile check, but no verified CEO contact found.")
                continue

            lead = {
                "company_name": enriched["company_name"],
                "description": enriched["description"],
                "sector": enriched["sector"],
                "website": enriched["homepage_url"],
                "funding_amount_millions": enriched["funding_amount_millions"],
                "country": enriched.get("region") or "International (Non-US)",
                "ceo_or_founder_name": contact.get("name") or "",
                "verified_email": contact["email"],
                "email_verification_method": contact["verification"],
                "source_url": enriched["source_url"],
            }
            qualifying_leads.append(lead)
            log(f"[QUALIFIED #{len(qualifying_leads)}]: {lead['company_name']} | "
                f"${lead['funding_amount_millions']}M | "
                f"CEO: {lead['ceo_or_founder_name']} <{lead['verified_email']}> "
                f"[{lead['email_verification_method']}]")

            if len(qualifying_leads) >= min_leads:
                break

    log(f"\n[DONE] Pipeline Complete: Successfully identified {len(qualifying_leads)} verified qualifying leads!")
    return qualifying_leads
