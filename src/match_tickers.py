"""
match_tickers.py
----------------
Phase 2a: Resolve company names in the `companies` table to stock ticker symbols.

Strategy (descending confidence):
  1. Manual override map    - hand-curated, confidence 100
  2a. yfinance Search       - name -> ticker via Yahoo search, US equity only
  2b. yfinance direct       - try heuristic ticker candidates, validate
  3. Fuzzy matching         - DISABLED by design (see comments below)
  4. Mark as unresolved     - likely private company

Every match is recorded with a method tag and confidence score so Phase 4
analysis can filter by match quality if results look suspicious.

Idempotent: only processes companies where match_method IS NULL.
Re-runs are safe and only work on new/unprocessed rows.
"""

import logging
import sys
import time
from datetime import datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# Load .env FIRST so get_engine() sees DB_PASS.
load_dotenv()

# Import AFTER load_dotenv so get_engine reads the populated env vars.
from ingest_layoffs import get_engine


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("ticker_matching.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,  # Override handlers set by ingest_layoffs import
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Manual override map
# ----------------------------------------------------------------------------
# Hand-curated mapping of normalized company name (lowercase) -> ticker symbol.
# Highest-impact companies by layoff count go here; these are NOT fuzzy-matched.
#
# Rules:
#   - Map to the ticker that trades on NYSE or NASDAQ (US primary listing).
#   - If a company went private or was acquired, set value to None explicitly.
#   - For dual-class stocks (Google, Meta pre-2022), pick the more liquid class.
#
# An explicit `None` is a POSITIVE signal: it tells the matcher "we know this
# company is private; don't try to fuzzy-match it into something wrong."
# ----------------------------------------------------------------------------
MANUAL_TICKER_MAP = {
    # --- Mega-cap tech ---
    "meta": "META",
    "facebook": "META",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "microsoft": "MSFT",
    "apple": "AAPL",
    "netflix": "NFLX",

    # --- Large-cap tech ---
    "salesforce": "CRM",
    "oracle": "ORCL",
    "ibm": "IBM",
    "cisco": "CSCO",
    "intel": "INTC",
    "adobe": "ADBE",
    "sap": "SAP",
    "nvidia": "NVDA",
    "amd": "AMD",

    # --- Hardware / semiconductor / enterprise infra ---
    "dell": "DELL",
    "dell technologies": "DELL",
    "hp": "HPQ",                         # HP Inc (consumer)
    "hewlett packard enterprise": "HPE", # HPE (enterprise spinoff)
    "hpe": "HPE",
    "micron": "MU",
    "micron technology": "MU",
    "seagate": "STX",
    "seagate technology": "STX",
    "western digital": "WDC",
    "lenovo": "LNVGY",
    "ericsson": "ERIC",
    "nokia": "NOK",
    "philips": "PHG",
    "xerox": "XRX",
    "toshiba": None,                     # Taken private 2023
    "qualcomm": "QCOM",
    "texas instruments": "TXN",
    "arm holdings": "ARM",
    "arm": "ARM",
    "asml": "ASML",
    "tsmc": "TSM",

    # --- Consumer tech / marketplaces ---
    "uber": "UBER",
    "lyft": "LYFT",
    "airbnb": "ABNB",
    "doordash": "DASH",
    "instacart": "CART",
    "ebay": "EBAY",
    "etsy": "ETSY",
    "shopify": "SHOP",
    "expedia": "EXPE",
    "booking": "BKNG",
    "booking.com": "BKNG",
    "wayfair": "W",
    "groupon": "GRPN",
    "stitch fix": "SFIX",
    "carvana": "CVNA",
    "cargurus": "CARG",
    "chewy": "CHWY",

    # --- Fintech ---
    "paypal": "PYPL",
    "block": "XYZ",
    "square": "XYZ",
    "robinhood": "HOOD",
    "coinbase": "COIN",
    "sofi": "SOFI",
    "affirm": "AFRM",
    "paytm": "PAYTM.NS",                 # India NSE listing
    "upstart": "UPST",
    "lemonade": "LMND",

    # --- Media / social ---
    "spotify": "SPOT",
    "snap": "SNAP",
    "snapchat": "SNAP",
    "pinterest": "PINS",
    "reddit": "RDDT",
    "roblox": "RBLX",
    "bilibili": "BILI",
    "unity": "U",
    "unity software": "U",

    # --- Enterprise / SaaS ---
    "zoom": "ZM",
    "docusign": "DOCU",
    "dropbox": "DBX",
    "twilio": "TWLO",
    "okta": "OKTA",
    "atlassian": "TEAM",
    "hubspot": "HUBS",
    "workday": "WDAY",
    "servicenow": "NOW",
    "splunk": None,                      # Acquired by Cisco 2024
    "coursera": "COUR",
    "autodesk": "ADSK",
    "opentext": "OTEX",
    "akamai": "AKAM",
    "amplitude": "AMPL",
    "applovin": "APP",
    "appfolio": "APPF",
    "indeed": None,                      # Owned by Recruit Holdings (Japan)
    "linkedin": None,                    # Owned by Microsoft
    "github": None,                      # Owned by Microsoft
    "cerner": None,                      # Acquired by Oracle 2022

    # --- Automotive / hardware ---
    "tesla": "TSLA",
    "rivian": "RIVN",
    "lucid motors": "LCID",
    "lucid": "LCID",
    "peloton": "PTON",
    "fisker": None,                      # Bankrupt 2024

    # --- Real estate / proptech ---
    "compass": "COMP",
    "opendoor": "OPEN",
    "redfin": "RDFN",
    "zillow": "Z",

    # --- Companies that went private, acquired, or are otherwise untracked ---
    "twitter": None,
    "x": None,
    "vmware": None,                      # Acquired by Broadcom 2023
    "activision": None,
    "activision blizzard": None,         # Acquired by Microsoft 2023
    "slack": None,                       # Acquired by Salesforce 2021
    "zendesk": None,                     # Taken private 2022
    "katerra": None,                     # Bankrupt 2021
    "better.com": None,                  # Went public as BETR, but highly illiquid
    "northvolt": None,                   # Bankrupt 2024
    "ukg": None,                         # Private (Hellman & Friedman)
    "amdocs": "DOX",                     # Actually public, NYSE listed

    # --- Known-private unicorns ---
    "stripe": None,
    "databricks": None,
    "spacex": None,
    "openai": None,
    "anthropic": None,
    "bytedance": None,
    "tiktok": None,
    "canva": None,
    "revolut": None,
    "klarna": None,
    "epic games": None,
    "chime": None,
    "discord": None,
    "flink": None,
    "getir": None,
    "byju's": None,
    "byjus": None,
    "swiggy": None,                      # IPO'd late 2024 but layoffs predate listing
    "ola": None,                         # India private
    "bolt": None,

    # --- Mid-cap additions (Phase 2a expansion) ---
    "intuit": "INTU",
    "electronic arts": "EA",
    "ea": "EA",
    "synopsys": "SNPS",
    "applied materials": "AMAT",
    "lam research": "LRCX",
    "solaredge": "SEDG",
    "solaredge technologies": "SEDG",
    "netapp": "NTAP",
    "f5": "FFIV",
    "f5 networks": "FFIV",
    "capital one": "COF",
    "godaddy": "GDDY",
    "yelp": "YELP",
    "tripadvisor": "TRIP",
    "sabre": "SABR",
    "viasat": "VSAT",
    "chegg": "CHGG",
    "toast": "TOST",
    "grab": "GRAB",
    "playtika": "PLTK",
    "vacasa": "VCSA",
    "palantir": "PLTR",
    "snowflake": "SNOW",
    "datadog": "DDOG",
    "mongodb": "MDB",
    "elastic": "ESTC",
    "crowdstrike": "CRWD",
    "sentinelone": "S",
    "zscaler": "ZS",
    "cloudflare": "NET",
    "fastly": "FSLY",
    "asana": "ASAN",
    "pagerduty": "PD",
    "box": "BOX",
    "ringcentral": "RNG",
    "vimeo": "VMEO",
    "nutanix": "NTNX",
    "teradata": "TDC",
    "palo alto networks": "PANW",
    "coupang": "CPNG",
    "roku": "ROKU",
    "bumble": "BMBL",
    "duolingo": "DUOL",
    "draftkings": "DKNG",
    "matterport": None,                  # Acquired by CoStar 2024, delisted
    "offerpad": "OPAD",
    "smartsheet": "SMAR",
    "liveperson": "LPSN",
    "marqeta": "MQ",
    "outbrain": "OB",
    "taboola": "TBLA",
    "udemy": "UDMY",
    "nerdy": "NRDY",
    "blend": "BLND",
    "blackberry": "BB",
    "plug power": "PLUG",
    "quantumscape": "QS",
    "buzzfeed": "BZFD",
    "clover health": "CLOV",
    "ginkgo bioworks": "DNA",
    "rent the runway": "RENT",
    "getty images": "GETY",
    "warby parker": "WRBY",
    "bill.com": "BILL",
    "deliveroo": None,                   # London listed (ROO.L), not US
    "ocado": None,                       # London listed (OCDO.L), not US
    "wisetech": None,                    # ASX listed (WTC.AX), not US
    "just eat": None,                    # Amsterdam (TKWY.AS), not US
    "zomato": None,                      # NSE India listing only
    "flipkart": None,                    # Owned by Walmart, private
    "yahoo": None,                       # Taken private (Apollo) 2021
    "qualtrics": None,                   # Taken private 2023
    "citrix": None,                      # Taken private 2022
    "kraken": None,                      # Private
    "shutterfly": None,                  # Private (Apollo)
    "juul": None,                        # Private
    "noom": None,                        # Private
    "magic leap": None,                  # Private
    "blue origin": None,                 # Private (Bezos)
    "binance": None,                     # Private
    "crypto.com": None,                  # Private
    "gopuff": None,                      # Private
    "oyo": None,                         # Private at layoff time
    "wework": None,                      # Bankruptcy/delisted 2023
    "invitae": None,                     # Bankruptcy 2024, delisted
    "grubhub": None,                     # Private (owned by Wonder)
    "sony interactive": None,            # Parent SONY trades, division not separate
    "olx group": None,                   # Owned by Prosus, not separately traded
    "indeed + glassdoor": None,          # Owned by Recruit Holdings
    "informatica": "INFA",
    "farfetch": None,                    # Delisted 2024, acquired by Coupang
    "vroom": None,                       # Delisted 2024, restructuring
    "cruise": None,                      # GM subsidiary, not separately traded
}


# ----------------------------------------------------------------------------
# Load unmatched companies from the DB
# ----------------------------------------------------------------------------
def load_unmatched_companies(engine) -> pd.DataFrame:
    """
    Load companies where match_method IS NULL.

    Filtering by NULL makes the script idempotent: already-matched companies
    are skipped on re-runs. To force re-matching, set match_method to NULL
    manually: `UPDATE companies SET match_method = NULL WHERE ...;`
    """
    query = text("""
        SELECT
            company_id,
            company_name,
            LOWER(TRIM(company_name)) AS normalized
        FROM companies
        WHERE match_method IS NULL
        ORDER BY company_name
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    logger.info(f"Loaded {len(df)} unmatched companies")
    return df


# ----------------------------------------------------------------------------
# Strategy 1: Manual override map
# ----------------------------------------------------------------------------
def try_manual_match(normalized_name: str):
    """
    O(1) dict lookup. Highest confidence since human-verified.

    Returns:
      - (ticker_str, 'manual', 100.0) if company is in the map with a ticker
      - (None, 'manual', 100.0) if company is in the map but is private
      - None if company is not in the map at all (try next strategy)
    """
    if normalized_name in MANUAL_TICKER_MAP:
        ticker = MANUAL_TICKER_MAP[normalized_name]
        return (ticker, "manual", 100.0)
    return None


# ----------------------------------------------------------------------------
# Strategy 2: yfinance direct lookup
# ----------------------------------------------------------------------------
def try_yfinance_direct(company_name: str):
    """
    Generate plausible ticker candidates from the company name, then ask Yahoo
    Finance if any of them are real tickers whose registered company name
    matches our input.

    Returns (ticker, 'yf_direct', 85.0) or None.
    """
    candidates = _generate_ticker_candidates(company_name)

    for candidate in candidates:
        if _validate_ticker(candidate, company_name):
            return (candidate, "yf_direct", 85.0)

    return None


# ----------------------------------------------------------------------------
# Strategy 2b: yfinance Search lookup (name -> ticker)
# ----------------------------------------------------------------------------
# US primary listing exchange codes returned by Yahoo's search API.
# NMS/NGM/NCM = NASDAQ tiers, NYQ = NYSE, ASE = NYSE American, PCX = NYSE Arca,
# BTS = BATS. We deliberately exclude foreign listings (LSE, TSX, SAO, etc.)
# to keep downstream price history in USD and on one trading calendar.
_US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS"}


def try_yfinance_search(company_name: str):
    """
    Ask Yahoo Finance to search by name, then pick the best US-listed equity
    whose registered name is fuzzy-similar to the input.

    Returns (ticker, 'yf_search', similarity_score) or None.

    We require:
      - quoteType == 'EQUITY' (not ETF, index, currency, etc.)
      - exchange in _US_EXCHANGES (USD, one trading calendar)
      - token_set_ratio >= 85 (tighter than yf_direct's 70 since Search returns
        a lot of loosely-related hits)
    """
    try:
        search = yf.Search(company_name, max_results=10)
        quotes = search.quotes or []
    except Exception as e:
        logger.debug(f"  yfinance Search failed for {company_name}: {e}")
        return None

    for q in quotes:
        if q.get("quoteType") != "EQUITY":
            continue
        if q.get("exchange") not in _US_EXCHANGES:
            continue

        symbol = q.get("symbol")
        yf_name = q.get("longname") or q.get("shortname") or ""
        if not symbol or not yf_name:
            continue

        similarity = fuzz.token_set_ratio(yf_name.lower(), company_name.lower())
        if similarity >= 85:
            return (symbol, "yf_search", float(similarity))

    return None


def _generate_ticker_candidates(company_name: str) -> list:
    """
    Heuristic ticker candidate generation.

    Real tickers on US exchanges are 1-5 uppercase letters. We generate:
      - First word of the name, truncated to various lengths
      - Acronym of capitalized words (e.g., "International Business Machines" -> "IBM")

    Deduplicated while preserving order (first candidate tried first).
    """
    name = company_name.strip()
    candidates = []

    # Heuristic 1: first word at several lengths
    first_word = name.split()[0] if name else ""
    clean = "".join(c for c in first_word if c.isalpha()).upper()
    if 1 <= len(clean) <= 5:
        candidates.append(clean)
    if len(clean) >= 4:
        candidates.append(clean[:4])
    if len(clean) >= 3:
        candidates.append(clean[:3])

    # Heuristic 2: acronym of capitalized words
    acronym = "".join(w[0] for w in name.split() if w and w[0].isupper())
    if 2 <= len(acronym) <= 5:
        candidates.append(acronym)

    # Dedupe while preserving order
    seen = set()
    result = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _validate_ticker(ticker: str, expected_name: str) -> bool:
    """
    Check whether `ticker` is a real, live ticker AND corresponds to
    `expected_name`.

    Validation via yfinance:
      1. Ticker().info must return a non-empty dict with a 'symbol' key
      2. The registered longName/shortName must have >=70 fuzzy similarity
         to expected_name (token_set_ratio, case-insensitive)

    Why 70 and not 90? Yahoo's registered names often include legal suffixes
    ("Apple Inc.", "Meta Platforms, Inc.") that don't appear in colloquial
    names. token_set_ratio handles this, but we still want some slack.
    """
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info

        # yfinance returns near-empty dict for invalid tickers
        if not info or "symbol" not in info:
            return False

        yf_name = info.get("longName") or info.get("shortName") or ""
        if not yf_name:
            return False

        # token_set_ratio ignores word order and duplicates:
        # "Apple Inc." vs "Apple" scores near 100
        similarity = fuzz.token_set_ratio(yf_name.lower(), expected_name.lower())
        return similarity >= 70

    except Exception as e:
        # yfinance can raise various network/parse errors. Treat any as "no match."
        logger.debug(f"  yfinance validation failed for {ticker}: {e}")
        return False


# ----------------------------------------------------------------------------
# Strategy 3: Fuzzy matching - INTENTIONALLY NOT IMPLEMENTED
# ----------------------------------------------------------------------------
def try_fuzzy_match(company_name: str):
    """
    DISABLED BY DESIGN.

    Unconstrained fuzzy matching against an SEC ticker corpus has high
    false-positive risk. "Apple" could silently match "Apple Hospitality REIT"
    (APLE) and pollute the entire event study with wrong price data.

    For an event study, precision matters more than recall: a known gap
    ("unresolved") is safer than a confident wrong answer. Companies not
    caught by the manual map or yfinance direct validation are marked
    unresolved and excluded from the stock analysis.

    If expanding later, a proper implementation would:
      1. Load ~10K known US tickers + long names from SEC EDGAR
      2. Use rapidfuzz.process.extractOne with a high score_cutoff (>=90)
      3. Additionally verify via yfinance that the match is live
    """
    return None


# ----------------------------------------------------------------------------
# Matching cascade
# ----------------------------------------------------------------------------
def match_company(row) -> tuple:
    """
    Run the full matching cascade for one company.
    First hit wins; order matters (manual before yfinance before fuzzy).
    """
    # Strategy 1: manual (uses normalized name)
    result = try_manual_match(row["normalized"])
    if result is not None:
        return result

    # Strategy 2a: yfinance Search (name -> ticker via Yahoo's search API)
    result = try_yfinance_search(row["company_name"])
    if result is not None:
        return result

    # Strategy 2b: yfinance direct (heuristic ticker candidates)
    result = try_yfinance_direct(row["company_name"])
    if result is not None:
        return result

    # Strategy 3: fuzzy (disabled)
    result = try_fuzzy_match(row["company_name"])
    if result is not None:
        return result

    # Fallback: mark as unresolved
    return (None, "unresolved", 0.0)


# ----------------------------------------------------------------------------
# Database update
# ----------------------------------------------------------------------------
def update_company_match(conn, company_id: int, ticker, method: str, confidence: float):
    """
    Write match result back to the companies table.

    If the ticker is already claimed by another company (UNIQUE constraint
    violation on uq_ticker), this indicates the fuzzy validator accepted
    an incorrect match. We demote that company to 'unresolved' rather than
    crashing. The first company to claim a ticker wins.
    """
    update_sql = text("""
        UPDATE companies
        SET ticker_symbol = :ticker,
            match_method = :method,
            match_confidence = :confidence,
            match_attempted_at = :attempted_at,
            is_public = :is_public
        WHERE company_id = :company_id
    """)
    try:
        conn.execute(update_sql, {
            "ticker": ticker,
            "method": method,
            "confidence": confidence,
            "attempted_at": datetime.utcnow(),
            "is_public": ticker is not None,
            "company_id": company_id,
        })
    except IntegrityError as e:
        # Ticker already claimed by another company. Demote to unresolved
        # and log for manual review.
        if "uq_ticker" in str(e.orig):
            logger.warning(
                f"  Ticker collision: company_id={company_id} tried to claim "
                f"'{ticker}' but it's already taken. Marking unresolved."
            )
            # Rollback the failed UPDATE and retry with None/unresolved
            conn.rollback()
            conn.execute(update_sql, {
                "ticker": None,
                "method": "unresolved",
                "confidence": 0.0,
                "attempted_at": datetime.utcnow(),
                "is_public": False,
                "company_id": company_id,
            })
        else:
            # Some other integrity error — re-raise
            raise

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    logger.info("=" * 60)
    logger.info(f"Ticker matching started at {datetime.now().isoformat()}")
    logger.info("=" * 60)

    engine = get_engine()
    unmatched = load_unmatched_companies(engine)

    if len(unmatched) == 0:
        logger.info("No unmatched companies. Nothing to do.")
        return

    stats = {"manual": 0, "yf_search": 0, "yf_direct": 0, "fuzzy": 0, "unresolved": 0}
    public_count = 0

    # One transaction per row. Simpler than savepoints and bulletproof:
    # each row either fully commits or fully rolls back, no shared state
    # between rows. Slower than batching, but for ~2,800 rows it's fine
    # and the clarity is worth it.
    for i, (_, row) in enumerate(unmatched.iterrows(), start=1):
        ticker, method, confidence = match_company(row)

        try:
            with engine.begin() as conn:
                update_company_match(
                    conn, row["company_id"], ticker, method, confidence
                )
            # Transaction committed. Update in-memory stats.
            # Note: update_company_match may have demoted to 'unresolved'
            # on ticker collision, so re-read what actually got stored.
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        "SELECT match_method, ticker_symbol "
                        "FROM companies WHERE company_id = :cid"
                    ),
                    {"cid": row["company_id"]},
                ).first()
            final_method = result.match_method
            final_ticker = result.ticker_symbol
            stats[final_method] = stats.get(final_method, 0) + 1
            if final_ticker is not None:
                public_count += 1

            logger.info(
                f"  [{i:4d}/{len(unmatched)}] {row['company_name']:40s} -> "
                f"{str(final_ticker):6s} [{final_method}, {confidence:.0f}%]"
            )
        except Exception as e:
            logger.error(f"  Failed to process {row['company_name']}: {e}")
            continue

        # Politeness delay ONLY when we hit the network
        # (manual matches don't touch yfinance).
        if method in ("yf_search", "yf_direct", "unresolved"):
            time.sleep(0.1)

    logger.info("=" * 60)
    logger.info("Matching complete.")
    logger.info(f"  Manual:     {stats.get('manual', 0)}")
    logger.info(f"  yf_search:  {stats.get('yf_search', 0)}")
    logger.info(f"  yf_direct:  {stats.get('yf_direct', 0)}")
    logger.info(f"  Fuzzy:      {stats.get('fuzzy', 0)}")
    logger.info(f"  Unresolved: {stats.get('unresolved', 0)}")
    logger.info(f"  Total public (ticker found): {public_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()