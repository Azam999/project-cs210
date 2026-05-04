"""
match_tickers.py
Phase 2a: turn company names into stock tickers.

We try the manual map first, then Yahoo's search API. We skip plain fuzzy
matching because it kept giving wrong answers (Apple matched APLE which is
a hotel company).
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

# load .env before importing get_engine so it picks up DB_PASS
load_dotenv()

from ingest_layoffs import get_engine


# logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("ticker_matching.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)
logger = logging.getLogger(__name__)


# manual map of company name (lowercase) to US ticker
# we hand pick the top ~50 firms here so we don't get a wrong fuzzy match
# None means the company is private, don't bother trying to match it
MANUAL_TICKER_MAP = {
    # mega cap tech
    "meta": "META",
    "facebook": "META",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "microsoft": "MSFT",
    "apple": "AAPL",
    "netflix": "NFLX",

    # large cap tech
    "salesforce": "CRM",
    "oracle": "ORCL",
    "ibm": "IBM",
    "cisco": "CSCO",
    "intel": "INTC",
    "adobe": "ADBE",
    "sap": "SAP",
    "nvidia": "NVDA",
    "amd": "AMD",

    # hardware and semiconductors
    "dell": "DELL",
    "dell technologies": "DELL",
    "hp": "HPQ",                         # HP Inc, the consumer one
    "hewlett packard enterprise": "HPE", # the enterprise spinoff
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
    "toshiba": None,                     # went private in 2023
    "qualcomm": "QCOM",
    "texas instruments": "TXN",
    "arm holdings": "ARM",
    "arm": "ARM",
    "asml": "ASML",
    "tsmc": "TSM",

    # consumer tech and marketplaces
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

    # fintech
    "paypal": "PYPL",
    "block": "XYZ",
    "square": "XYZ",
    "robinhood": "HOOD",
    "coinbase": "COIN",
    "sofi": "SOFI",
    "affirm": "AFRM",
    "paytm": "PAYTM.NS",                 # India NSE
    "upstart": "UPST",
    "lemonade": "LMND",

    # media and social
    "spotify": "SPOT",
    "snap": "SNAP",
    "snapchat": "SNAP",
    "pinterest": "PINS",
    "reddit": "RDDT",
    "roblox": "RBLX",
    "bilibili": "BILI",
    "unity": "U",
    "unity software": "U",

    # enterprise and SaaS
    "zoom": "ZM",
    "docusign": "DOCU",
    "dropbox": "DBX",
    "twilio": "TWLO",
    "okta": "OKTA",
    "atlassian": "TEAM",
    "hubspot": "HUBS",
    "workday": "WDAY",
    "servicenow": "NOW",
    "splunk": None,                      # bought by Cisco in 2024
    "coursera": "COUR",
    "autodesk": "ADSK",
    "opentext": "OTEX",
    "akamai": "AKAM",
    "amplitude": "AMPL",
    "applovin": "APP",
    "appfolio": "APPF",
    "indeed": None,                      # owned by Recruit Holdings (Japan)
    "linkedin": None,                    # owned by Microsoft
    "github": None,                      # owned by Microsoft
    "cerner": None,                      # bought by Oracle in 2022

    # automotive and hardware
    "tesla": "TSLA",
    "rivian": "RIVN",
    "lucid motors": "LCID",
    "lucid": "LCID",
    "peloton": "PTON",
    "fisker": None,                      # bankrupt 2024

    # real estate and proptech
    "compass": "COMP",
    "opendoor": "OPEN",
    "redfin": "RDFN",
    "zillow": "Z",

    # private, acquired, or otherwise untracked
    "twitter": None,
    "x": None,
    "vmware": None,                      # bought by Broadcom in 2023
    "activision": None,
    "activision blizzard": None,         # bought by Microsoft in 2023
    "slack": None,                       # bought by Salesforce in 2021
    "zendesk": None,                     # taken private 2022
    "katerra": None,                     # bankrupt 2021
    "better.com": None,                  # listed as BETR but barely trades
    "northvolt": None,                   # bankrupt 2024
    "ukg": None,                         # private (Hellman and Friedman)
    "amdocs": "DOX",                     # actually public on NYSE

    # known private unicorns
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
    "swiggy": None,                      # IPO'd late 2024 but layoffs were earlier
    "ola": None,                         # India private
    "bolt": None,

    # mid cap additions added later
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
    "matterport": None,                  # acquired by CoStar in 2024, delisted
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
    "deliveroo": None,                   # London, not US
    "ocado": None,                       # London, not US
    "wisetech": None,                    # ASX, not US
    "just eat": None,                    # Amsterdam, not US
    "zomato": None,                      # India only
    "flipkart": None,                    # owned by Walmart, private
    "yahoo": None,                       # taken private (Apollo) in 2021
    "qualtrics": None,                   # taken private 2023
    "citrix": None,                      # taken private 2022
    "kraken": None,
    "shutterfly": None,
    "juul": None,
    "noom": None,
    "magic leap": None,
    "blue origin": None,                 # private (Bezos)
    "binance": None,
    "crypto.com": None,
    "gopuff": None,
    "oyo": None,
    "wework": None,                      # bankrupt 2023
    "invitae": None,                     # bankrupt 2024
    "grubhub": None,                     # private (owned by Wonder)
    "sony interactive": None,            # parent SONY trades, not the division
    "olx group": None,                   # owned by Prosus
    "indeed + glassdoor": None,          # owned by Recruit Holdings
    "informatica": "INFA",
    "farfetch": None,                    # delisted 2024, bought by Coupang
    "vroom": None,                       # delisted 2024
    "cruise": None,                      # GM subsidiary, not separately traded
}


# only pull companies we haven't tried to match yet so re-runs are safe
def load_unmatched_companies(engine) -> pd.DataFrame:
    """Get companies where match_method is still NULL."""
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


# strategy 1: manual map (just a dict lookup)
def try_manual_match(normalized_name: str):
    """Returns (ticker, 'manual', 100) if in the map, else None."""
    if normalized_name in MANUAL_TICKER_MAP:
        ticker = MANUAL_TICKER_MAP[normalized_name]
        return (ticker, "manual", 100.0)
    return None


# strategy 2: yfinance direct lookup
# guess plausible tickers from the name and check yfinance
def try_yfinance_direct(company_name: str):
    candidates = _generate_ticker_candidates(company_name)
    for candidate in candidates:
        if _validate_ticker(candidate, company_name):
            return (candidate, "yf_direct", 85.0)
    return None


# US listings only so prices stay in USD on one trading calendar
# NMS/NGM/NCM are NASDAQ tiers, NYQ is NYSE, ASE is NYSE American
_US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS"}


# strategy 2b: search Yahoo by company name and filter to US equities
def try_yfinance_search(company_name: str):
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

        # tighter threshold than yf_direct since search returns lots of loose hits
        similarity = fuzz.token_set_ratio(yf_name.lower(), company_name.lower())
        if similarity >= 85:
            return (symbol, "yf_search", float(similarity))

    return None


def _generate_ticker_candidates(company_name: str) -> list:
    """Build plausible ticker guesses from the company name."""
    name = company_name.strip()
    candidates = []

    # try first word at a few different lengths
    first_word = name.split()[0] if name else ""
    clean = "".join(c for c in first_word if c.isalpha()).upper()
    if 1 <= len(clean) <= 5:
        candidates.append(clean)
    if len(clean) >= 4:
        candidates.append(clean[:4])
    if len(clean) >= 3:
        candidates.append(clean[:3])

    # try acronym of capitalized words (e.g. "International Business Machines" gives IBM)
    acronym = "".join(w[0] for w in name.split() if w and w[0].isupper())
    if 2 <= len(acronym) <= 5:
        candidates.append(acronym)

    # remove duplicates but keep order
    seen = set()
    result = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


# check if a ticker is real and matches the company we expected
def _validate_ticker(ticker: str, expected_name: str) -> bool:
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info

        # yfinance gives a near empty dict for fake tickers
        if not info or "symbol" not in info:
            return False

        yf_name = info.get("longName") or info.get("shortName") or ""
        if not yf_name:
            return False

        # threshold of 70 is lenient because Yahoo names include "Inc.", "Corp." etc
        similarity = fuzz.token_set_ratio(yf_name.lower(), expected_name.lower())
        return similarity >= 70

    except Exception as e:
        logger.debug(f"  yfinance validation failed for {ticker}: {e}")
        return False


# strategy 3: plain fuzzy matching is intentionally off
# we tried it and it kept matching things wrong (e.g. Apple to Apple Hospitality)
# better to leave a company unresolved than to get a confidently wrong ticker
def try_fuzzy_match(company_name: str):
    return None


# run all strategies in order, first hit wins
def match_company(row) -> tuple:
    # try manual map first
    result = try_manual_match(row["normalized"])
    if result is not None:
        return result

    # then Yahoo search
    result = try_yfinance_search(row["company_name"])
    if result is not None:
        return result

    # then guess tickers from the name
    result = try_yfinance_direct(row["company_name"])
    if result is not None:
        return result

    # fuzzy is off
    result = try_fuzzy_match(row["company_name"])
    if result is not None:
        return result

    # nothing worked, mark unresolved
    return (None, "unresolved", 0.0)


# write the match back to the companies table
def update_company_match(conn, company_id: int, ticker, method: str, confidence: float):
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
        # another company already claimed this ticker, demote this one to unresolved
        if "uq_ticker" in str(e.orig):
            logger.warning(
                f"  Ticker collision: company_id={company_id} tried to claim "
                f"'{ticker}' but it's already taken. Marking unresolved."
            )
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
            raise

# main
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

    # one transaction per row keeps things simple, slower but easier to reason about
    for i, (_, row) in enumerate(unmatched.iterrows(), start=1):
        ticker, method, confidence = match_company(row)

        try:
            with engine.begin() as conn:
                update_company_match(
                    conn, row["company_id"], ticker, method, confidence
                )
            # re-read in case update_company_match demoted us to unresolved
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

        # only sleep when we actually hit the network
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
