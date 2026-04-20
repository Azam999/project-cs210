"""
fetch_prices.py
---------------
Phase 2b: Pull daily stock prices from Yahoo Finance for every matched ticker,
plus the S&P 500 (^GSPC) benchmark. Writes into `daily_prices` and
`market_index`.

Design notes:
  - One yfinance call per ticker covering the full date range the project
    needs. That's strictly more data than we analyze, but it's simpler than
    event-windowed fetches and lets Phase 3 compute SCAR estimation-window
    statistics going back up to 250 trading days before each event.
  - Idempotent: every INSERT uses ON CONFLICT DO NOTHING on the existing
    unique constraints (uq_company_tradedate, market_index PK). Re-runs
    only fill gaps.
  - One transaction per ticker. A failure on one ticker doesn't block the
    rest, and a retry just re-attempts the missing rows.
"""

import logging
import sys
import time
from datetime import datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

from ingest_layoffs import get_engine


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("price_fetch.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,  # Override handlers set by ingest_layoffs import
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
# Start ~6 months before the earliest event (2020-03-11) so there's room for
# a 250-trading-day SCAR estimation window for the earliest events. End date
# is today-ish; yfinance will just return whatever is available.
FETCH_START = "2019-09-01"
FETCH_END = "2026-05-31"

# Yahoo tolerates a few queries per second; we stay well under.
SLEEP_BETWEEN_TICKERS = 0.3
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_S = 2.0
# When Yahoo rate-limits ("Too Many Requests"), back off much longer before
# retrying. The standard cooldown window is 1-15 minutes.
RATE_LIMIT_BACKOFF_S = 90.0

MARKET_INDEX_SYMBOL = "^GSPC"


# ----------------------------------------------------------------------------
# Load tickers to fetch
# ----------------------------------------------------------------------------
def load_tickers(engine) -> pd.DataFrame:
    """Every public company we resolved in Phase 2a."""
    query = text("""
        SELECT company_id, company_name, ticker_symbol
        FROM companies
        WHERE ticker_symbol IS NOT NULL
        ORDER BY ticker_symbol
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    logger.info(f"Loaded {len(df)} tickers to fetch")
    return df


# ----------------------------------------------------------------------------
# yfinance fetch + retry
# ----------------------------------------------------------------------------
def fetch_ticker_history(ticker: str) -> pd.DataFrame:
    """
    Pull OHLCV history for `ticker`. Returns empty DataFrame on repeated
    failure — caller decides what to do.
    """
    last_err = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            hist = yf.Ticker(ticker).history(
                start=FETCH_START,
                end=FETCH_END,
                auto_adjust=False,
                actions=False,
            )
            if hist is None or hist.empty:
                return pd.DataFrame()
            return hist
        except Exception as e:
            last_err = e
            logger.debug(f"  {ticker}: attempt {attempt} failed: {e}")
            # "Too Many Requests" needs a long backoff, not a short one.
            backoff = (RATE_LIMIT_BACKOFF_S if "Too Many Requests" in str(e)
                       else RETRY_BACKOFF_S)
            if attempt < RETRY_ATTEMPTS:
                logger.info(f"  {ticker}: backing off {backoff}s before retry")
                time.sleep(backoff)
    logger.warning(f"  {ticker}: all {RETRY_ATTEMPTS} attempts failed ({last_err})")
    return pd.DataFrame()


# ----------------------------------------------------------------------------
# DB write helpers
# ----------------------------------------------------------------------------
_INSERT_PRICE_SQL = text("""
    INSERT INTO daily_prices
        (company_id, trade_date, open_price, close_price, adj_close, volume)
    VALUES
        (:company_id, :trade_date, :open_price, :close_price, :adj_close, :volume)
    ON CONFLICT (company_id, trade_date) DO NOTHING
""")


def upsert_prices(conn, company_id: int, df: pd.DataFrame) -> tuple:
    """
    Insert a ticker's history. Returns (inserted_attempts, skipped_invalid).

    "Inserted_attempts" counts rows we *tried* to insert; ON CONFLICT silently
    skips duplicates, so we don't distinguish between new and existing on the
    happy path.
    """
    attempted = 0
    skipped = 0
    for idx, row in df.iterrows():
        # yfinance index is a DatetimeIndex in local tz; extract date.
        trade_date = idx.date() if hasattr(idx, "date") else pd.Timestamp(idx).date()
        adj_close = row.get("Adj Close")
        # adj_close is NOT NULL in the schema; rows without it are useless to us.
        if pd.isna(adj_close) or adj_close <= 0:
            skipped += 1
            continue

        conn.execute(_INSERT_PRICE_SQL, {
            "company_id": company_id,
            "trade_date": trade_date,
            "open_price": _num_or_none(row.get("Open")),
            "close_price": _num_or_none(row.get("Close")),
            "adj_close": float(adj_close),
            "volume": _int_or_none(row.get("Volume")),
        })
        attempted += 1
    return attempted, skipped


_INSERT_INDEX_SQL = text("""
    INSERT INTO market_index
        (trade_date, index_symbol, adj_close, volume)
    VALUES
        (:trade_date, :index_symbol, :adj_close, :volume)
    ON CONFLICT (trade_date) DO NOTHING
""")


def upsert_market_index(conn, df: pd.DataFrame) -> int:
    attempted = 0
    for idx, row in df.iterrows():
        trade_date = idx.date() if hasattr(idx, "date") else pd.Timestamp(idx).date()
        adj_close = row.get("Adj Close")
        if pd.isna(adj_close) or adj_close <= 0:
            continue
        conn.execute(_INSERT_INDEX_SQL, {
            "trade_date": trade_date,
            "index_symbol": MARKET_INDEX_SYMBOL,
            "adj_close": float(adj_close),
            "volume": _int_or_none(row.get("Volume")),
        })
        attempted += 1
    return attempted


def _num_or_none(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def _int_or_none(v):
    if v is None or pd.isna(v):
        return None
    return int(v)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    logger.info("=" * 60)
    logger.info(f"Price fetch started at {datetime.now().isoformat()}")
    logger.info(f"Window: {FETCH_START} to {FETCH_END}")
    logger.info("=" * 60)

    engine = get_engine()

    # --- Market index first (Phase 3 needs the trading calendar) ---
    logger.info(f"Fetching market index {MARKET_INDEX_SYMBOL}...")
    idx_df = fetch_ticker_history(MARKET_INDEX_SYMBOL)
    if idx_df.empty:
        logger.error(f"  Market index fetch returned empty; aborting")
        sys.exit(1)
    with engine.begin() as conn:
        index_rows = upsert_market_index(conn, idx_df)
    logger.info(f"  Market index: {index_rows} rows attempted ({len(idx_df)} days in range)")

    # --- Per-ticker loop ---
    tickers = load_tickers(engine)
    n = len(tickers)
    stats = {"ok": 0, "empty": 0, "failed": 0}
    total_inserted = 0

    for i, (_, row) in enumerate(tickers.iterrows(), start=1):
        ticker = row["ticker_symbol"]
        company_id = int(row["company_id"])
        company_name = row["company_name"]

        hist = fetch_ticker_history(ticker)
        if hist.empty:
            logger.info(f"  [{i:3d}/{n}] {ticker:8s} ({company_name}) -> NO DATA")
            stats["empty"] += 1
            time.sleep(SLEEP_BETWEEN_TICKERS)
            continue

        try:
            with engine.begin() as conn:
                attempted, skipped = upsert_prices(conn, company_id, hist)
            total_inserted += attempted
            stats["ok"] += 1
            coverage_flag = "" if len(hist) >= 200 else "  [LOW-COVERAGE]"
            logger.info(
                f"  [{i:3d}/{n}] {ticker:8s} ({company_name}): "
                f"{len(hist)} days -> {attempted} attempted, {skipped} invalid"
                f"{coverage_flag}"
            )
        except Exception as e:
            logger.error(f"  [{i:3d}/{n}] {ticker}: DB write failed: {e}")
            stats["failed"] += 1

        time.sleep(SLEEP_BETWEEN_TICKERS)

    logger.info("=" * 60)
    logger.info("Price fetch complete.")
    logger.info(f"  Tickers with data:   {stats['ok']}")
    logger.info(f"  Tickers empty:       {stats['empty']}")
    logger.info(f"  Tickers failed:      {stats['failed']}")
    logger.info(f"  Rows attempted:      {total_inserted}")

    with engine.connect() as conn:
        dp_count = conn.execute(text("SELECT COUNT(*) FROM daily_prices")).scalar()
        mi_count = conn.execute(text("SELECT COUNT(*) FROM market_index")).scalar()
    logger.info(f"  daily_prices total:  {dp_count}")
    logger.info(f"  market_index total:  {mi_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
