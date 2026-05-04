"""
ingest_layoffs.py
Phase 1: clean the layoffs.fyi CSV and load it into Postgres.

We do this in two passes. First we put unique companies into the companies
table, then we loop over the layoff rows and link each one to the right
company_id. Doing it in one pass would mean a bunch of inline lookups
because of the foreign key.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# load env vars from .env so we don't hardcode DB credentials
from dotenv import load_dotenv
load_dotenv()


# DB config from .env
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "layoffs_analysis")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "layoffs.csv"

# log everything we insert, skip, or fail on
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("ingestion.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# connect to Postgres via SQLAlchemy (used by other phases too)
def get_engine():
    """SQLAlchemy engine. We use this instead of raw psycopg2 for pooling."""
    conn_string = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(conn_string, pool_pre_ping=True)


# load the CSV and clean it up
def load_and_clean_csv(csv_path: Path) -> pd.DataFrame:
    """Read the CSV, clean column names, parse dates, dedupe by (company, date)."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found at {csv_path}")

    logger.info(f"Loading CSV from {csv_path}")
    df = pd.read_csv(csv_path)
    logger.info(f"  Raw rows: {len(df)}")

    # snake_case the columns
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace("#", "num")
        .str.replace("%", "pct")
    )

    logger.info(f"  Columns: {list(df.columns)}")

    # strip whitespace and turn empty strings / "N/A" into real NaN
    string_cols = df.select_dtypes(include="object").columns
    for col in string_cols:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": None, "": None, "N/A": None})

    # parse dates, drop rows we can't parse
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    bad_dates = df["date"].isna().sum()
    if bad_dates:
        logger.warning(f"  Dropping {bad_dates} rows with unparseable dates")
    df = df.dropna(subset=["date", "company"])

    # turn numeric columns into actual numbers, "N/A" becomes NaN
    if "total_laid_off" in df.columns:
        df["total_laid_off"] = pd.to_numeric(df["total_laid_off"], errors="coerce")
    if "percentage_laid_off" in df.columns:
        df["percentage_laid_off"] = (
            df["percentage_laid_off"].astype(str).str.replace("%", "", regex=False)
        )
        df["percentage_laid_off"] = pd.to_numeric(df["percentage_laid_off"], errors="coerce")
    if "funds_raised" in df.columns:
        df["funds_raised"] = pd.to_numeric(df["funds_raised"], errors="coerce")

    # dedupe by (company, date), keep the row with the most data filled in
    df["__non_null_count"] = df.notna().sum(axis=1)
    df = df.sort_values("__non_null_count", ascending=False)
    before = len(df)
    df = df.drop_duplicates(subset=["company", "date"], keep="first")
    after = len(df)
    if before != after:
        logger.info(f"  Deduplicated: {before} -> {after} rows")
    df = df.drop(columns=["__non_null_count"])

    # lowercase version for matching later
    df["company_normalized"] = df["company"].str.lower().str.strip()

    logger.info(f"  Final clean rows: {len(df)}")
    return df.reset_index(drop=True)


# pass 1: insert unique companies
def insert_companies(df: pd.DataFrame, engine) -> dict:
    """Insert each unique company and return {normalized_name: company_id}."""
    # one row per company, take the first non null value for each field
    unique_companies = (
        df.groupby("company_normalized")
        .agg({
            "company": "first",
            "industry": "first",
            "location": "first",
            "country": "first",
        })
        .reset_index()
    )
    logger.info(f"Inserting {len(unique_companies)} unique companies")

    # ON CONFLICT DO NOTHING means re-runs are safe
    insert_sql = text("""
        INSERT INTO companies (company_name, industry, headquarters, country, is_public)
        VALUES (:company_name, :industry, :headquarters, :country, FALSE)
        ON CONFLICT (company_name) DO NOTHING
    """)

    with engine.begin() as conn:
        for _, row in unique_companies.iterrows():
            conn.execute(insert_sql, {
                "company_name": row["company"],
                "industry": row["industry"],
                "headquarters": row["location"],
                "country": row["country"],
            })

    # build the name to id map for pass 2
    with engine.connect() as conn:
        result = conn.execute(text("SELECT company_id, LOWER(TRIM(company_name)) AS norm FROM companies"))
        mapping = {row.norm: row.company_id for row in result}

    logger.info(f"  Company to ID map built: {len(mapping)} entries")
    return mapping


# pass 2: insert layoff events
def insert_events(df: pd.DataFrame, company_map: dict, engine):
    """Insert one row per layoff, link to the right company_id."""
    insert_sql = text("""
        INSERT INTO layoff_events (
            company_id, announcement_date, employees_laid_off,
            percentage_laid_off, funds_raised_usd, stage, source_url
        ) VALUES (
            :company_id, :announcement_date, :employees_laid_off,
            :percentage_laid_off, :funds_raised_usd, :stage, :source_url
        )
        ON CONFLICT (company_id, announcement_date) DO UPDATE
        SET percentage_laid_off = COALESCE(
                layoff_events.percentage_laid_off,
                EXCLUDED.percentage_laid_off
            ),
            funds_raised_usd = COALESCE(
                layoff_events.funds_raised_usd,
                EXCLUDED.funds_raised_usd
            ),
            stage = COALESCE(layoff_events.stage, EXCLUDED.stage),
            source_url = COALESCE(layoff_events.source_url, EXCLUDED.source_url),
            employees_laid_off = COALESCE(
                layoff_events.employees_laid_off,
                EXCLUDED.employees_laid_off
            )
    """)

    inserted = 0
    skipped = 0
    failed = 0

    with engine.begin() as conn:
        for _, row in df.iterrows():
            company_id = company_map.get(row["company_normalized"])
            if company_id is None:
                # shouldn't happen but just in case
                logger.warning(f"No company_id for '{row['company']}', skipping")
                skipped += 1
                continue

            try:
                result = conn.execute(insert_sql, {
                    "company_id": company_id,
                    "announcement_date": row["date"].date(),
                    "employees_laid_off": _safe_int(row.get("total_laid_off")),
                    "percentage_laid_off": _safe_float(row.get("percentage_laid_off")),
                    "funds_raised_usd": _safe_float(row.get("funds_raised")),
                    "stage": row.get("stage"),
                    "source_url": row.get("source"),
                })
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1  # already in the table
            except IntegrityError as e:
                # something slipped past our cleaning, log and move on
                logger.error(f"IntegrityError for {row['company']} on {row['date']}: {e.orig}")
                failed += 1

    logger.info(f"Events: {inserted} inserted, {skipped} skipped (duplicates), {failed} failed")


def _safe_int(value):
    """Cast to int or return None."""
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_float(value):
    """Cast to float or return None."""
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# main
def main():
    logger.info("=" * 60)
    logger.info(f"Layoff ingestion started at {datetime.now().isoformat()}")
    logger.info("=" * 60)

    engine = get_engine()

    # quick connectivity check
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
