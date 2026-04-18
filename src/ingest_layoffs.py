"""
ingest_layoffs.py
-----------------
Cleans the layoffs.fyi CSV and loads it into the PostgreSQL `companies` and
`layoff_events` tables.

Design: Two-pass ingestion.
  Pass 1: Extract unique companies → insert into companies table.
  Pass 2: For each layoff row → look up company_id, insert into layoff_events.

This separation matters because companies must exist before events can reference them
(foreign key constraint). Doing it in one pass would require messy inline lookups.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
# DB credentials come from environment variables, NOT hardcoded.
# This is security hygiene: we never want credentials in a GitHub commit.
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "layoffs_analysis")

CSV_PATH = Path("data/layoffs.csv")

# Logging configuration — we want a record of every insert, skip, and failure.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("ingestion.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Step 1: Connect to the database
# ----------------------------------------------------------------------------
def get_engine():
    """
    Create a SQLAlchemy engine. We use SQLAlchemy (not raw psycopg2) because:
      - It gives us connection pooling for free.
      - pandas.to_sql() integrates natively.
      - We can swap Postgres → SQLite for local testing with one line change.
    """
    conn_string = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(conn_string, pool_pre_ping=True)


# ----------------------------------------------------------------------------
# Step 2: Load and clean the CSV
# ----------------------------------------------------------------------------
def load_and_clean_csv(csv_path: Path) -> pd.DataFrame:
    """
    Load the layoffs.fyi CSV and apply cleaning rules.

    Cleaning steps (in order):
      1. Normalize column names to snake_case.
      2. Strip whitespace from all string columns.
      3. Parse `date` column as proper datetime (rejecting unparseable rows).
      4. Coerce numeric columns, turning '' and 'N/A' into NaN (not 0 — that's a lie).
      5. Deduplicate on (company, date) — keeping the row with MORE data.
      6. Drop rows missing a company name entirely.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found at {csv_path}")

    logger.info(f"Loading CSV from {csv_path}")
    df = pd.read_csv(csv_path)
    logger.info(f"  Raw rows: {len(df)}")

    # ---- Step 2a: Normalize column names ----
    # layoffs.fyi uses "Company", "Location HQ", etc. We want snake_case.
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace("#", "num")
        .str.replace("%", "pct")
    )

    # Expected columns after normalization:
    # company, location_hq, industry, num_laid_off, date, pct,
    # stage, funds_raised, country
    logger.info(f"  Columns: {list(df.columns)}")

    # ---- Step 2b: Strip whitespace on string columns ----
    # A trailing space in "Meta " vs "Meta" will cause duplicate company rows.
    string_cols = df.select_dtypes(include="object").columns
    for col in string_cols:
        df[col] = df[col].astype(str).str.strip()
        # Replace the literal string 'nan' (from pandas coercion) with actual NaN.
        df[col] = df[col].replace({"nan": None, "": None, "N/A": None})

    # ---- Step 2c: Parse dates ----
    # errors="coerce" turns bad dates into NaT instead of crashing the whole script.
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    bad_dates = df["date"].isna().sum()
    if bad_dates:
        logger.warning(f"  Dropping {bad_dates} rows with unparseable dates")
    df = df.dropna(subset=["date", "company"])

    # ---- Step 2d: Coerce numerics ----
    # pd.to_numeric with errors="coerce" gracefully handles "N/A", "", etc.
    if "num_laid_off" in df.columns:
        df["num_laid_off"] = pd.to_numeric(df["num_laid_off"], errors="coerce")
    if "pct" in df.columns:
        # Remove '%' sign if present, then convert.
        df["pct"] = (
            df["pct"].astype(str).str.replace("%", "", regex=False)
        )
        df["pct"] = pd.to_numeric(df["pct"], errors="coerce")
    if "funds_raised" in df.columns:
        df["funds_raised"] = pd.to_numeric(df["funds_raised"], errors="coerce")

    # ---- Step 2e: Deduplicate ----
    # When we have two rows for (Company, Date), keep the one with more non-null data.
    # Heuristic: sort by count of non-null values DESC, then drop_duplicates keeps first.
    df["__non_null_count"] = df.notna().sum(axis=1)
    df = df.sort_values("__non_null_count", ascending=False)
    before = len(df)
    df = df.drop_duplicates(subset=["company", "date"], keep="first")
    after = len(df)
    if before != after:
        logger.info(f"  Deduplicated: {before} → {after} rows")
    df = df.drop(columns=["__non_null_count"])

    # ---- Step 2f: Normalize company name for matching ----
    # We keep the display name but store a lowercase version for dedup.
    df["company_normalized"] = df["company"].str.lower().str.strip()

    logger.info(f"  Final clean rows: {len(df)}")
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------
# Step 3: Insert companies (Pass 1)
# ----------------------------------------------------------------------------
def insert_companies(df: pd.DataFrame, engine) -> dict:
    """
    Insert unique companies and return a mapping: {company_normalized → company_id}.

    Uses INSERT ... ON CONFLICT DO NOTHING so re-running the script is safe
    (idempotent). Postgres handles the dedup at the constraint level.
    """
    # Build one row per unique company, taking the first non-null value for each field.
    unique_companies = (
        df.groupby("company_normalized")
        .agg({
            "company": "first",
            "industry": "first",
            "location_hq": "first",
            "country": "first",
        })
        .reset_index()
    )
    logger.info(f"Inserting {len(unique_companies)} unique companies")

    insert_sql = text("""
        INSERT INTO companies (company_name, industry, headquarters, country, is_public)
        VALUES (:company_name, :industry, :headquarters, :country, FALSE)
        ON CONFLICT (company_name) DO NOTHING
    """)

    with engine.begin() as conn:  # `.begin()` = auto-commit on success, rollback on exception
        for _, row in unique_companies.iterrows():
            conn.execute(insert_sql, {
                "company_name": row["company"],
                "industry": row["industry"],
                "headquarters": row["location_hq"],
                "country": row["country"],
            })

    # Now fetch the id mapping. We need this for the foreign key in Pass 2.
    with engine.connect() as conn:
        result = conn.execute(text("SELECT company_id, LOWER(TRIM(company_name)) AS norm FROM companies"))
        mapping = {row.norm: row.company_id for row in result}

    logger.info(f"  Company → ID map built: {len(mapping)} entries")
    return mapping


# ----------------------------------------------------------------------------
# Step 4: Insert layoff events (Pass 2)
# ----------------------------------------------------------------------------
def insert_events(df: pd.DataFrame, company_map: dict, engine):
    """
    Insert one row per layoff event, linking to the correct company_id.
    """
    insert_sql = text("""
        INSERT INTO layoff_events (
            company_id, announcement_date, employees_laid_off,
            percentage_laid_off, funds_raised_usd, stage, source_url
        ) VALUES (
            :company_id, :announcement_date, :employees_laid_off,
            :percentage_laid_off, :funds_raised_usd, :stage, :source_url
        )
        ON CONFLICT (company_id, announcement_date) DO NOTHING
    """)

    inserted = 0
    skipped = 0
    failed = 0

    with engine.begin() as conn:
        for _, row in df.iterrows():
            company_id = company_map.get(row["company_normalized"])
            if company_id is None:
                # Shouldn't happen since we inserted all companies in Pass 1,
                # but defensive programming matters when dealing with real data.
                logger.warning(f"No company_id for '{row['company']}' — skipping")
                skipped += 1
                continue

            try:
                result = conn.execute(insert_sql, {
                    "company_id": company_id,
                    "announcement_date": row["date"].date(),
                    "employees_laid_off": _safe_int(row.get("num_laid_off")),
                    "percentage_laid_off": _safe_float(row.get("pct")),
                    "funds_raised_usd": _safe_float(row.get("funds_raised")),
                    "stage": row.get("stage"),
                    "source_url": row.get("source"),
                })
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1  # ON CONFLICT fired — duplicate
            except IntegrityError as e:
                # CHECK constraint violation (e.g., pct > 100 that slipped past cleaning)
                logger.error(f"IntegrityError for {row['company']} on {row['date']}: {e.orig}")
                failed += 1

    logger.info(f"Events: {inserted} inserted, {skipped} skipped (duplicates), {failed} failed")


def _safe_int(value):
    """Convert to int or return None. Handles NaN, strings, etc."""
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_float(value):
    """Convert to float or return None."""
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------
def main():
    logger.info("=" * 60)
    logger.info(f"Layoff ingestion started at {datetime.now().isoformat()}")
    logger.info("=" * 60)

    engine = get_engine()

    # Sanity check the connection before doing any work.
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("DB connection OK")
    except SQLAlchemyError as e:
        logger.error(f"DB connection failed: {e}")
        sys.exit(1)

    df = load_and_clean_csv(CSV_PATH)
    company_map = insert_companies(df, engine)
    insert_events(df, company_map, engine)

    logger.info("Ingestion complete")


if __name__ == "__main__":
    main()