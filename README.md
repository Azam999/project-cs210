# Do Tech Layoffs Help Stock Prices?

**CS 210: Data Management for Data Science — Spring 2026**
**Authors:** Azam Ahmed, Xuan Liao

A data pipeline and event-study analysis examining whether tech layoff announcements produce measurable, statistically significant changes in company stock prices.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Setup](#setup)
4. [Running the Pipeline](#running-the-pipeline)
5. [Data Sources](#data-sources)
6. [Repository Structure](#repository-structure)
7. [Design Decisions](#design-decisions)
8. [Known Limitations](#known-limitations)

---

## Project Overview

We investigate a common claim: "Wall Street rewards companies for announcing layoffs." Using ~4,300 layoff events from layoffs.fyi and daily stock prices from Yahoo Finance, we compute Cumulative Abnormal Returns (CAR) around each announcement and test whether the effect is statistically distinguishable from zero.

**Primary question:** Do tech stocks outperform the S&P 500 in the trading days following a layoff announcement?

**Secondary questions:**
- Does layoff size (absolute or percentage) affect the outcome?
- Do first-time layoffs differ from repeat layoffs?
- How does the market regime (bull/bear) interact with the effect?

---

## Architecture

The project is a five-stage ETL pipeline backed by a normalized PostgreSQL database.

```
   ┌─────────────┐        ┌─────────────┐        ┌──────────────┐
   │ layoffs.fyi │───┐    │   yfinance  │    ┌───│  S&P 500     │
   │   (CSV)     │   │    │   (JSON)    │    │   │  benchmark   │
   └─────────────┘   │    └─────────────┘    │   └──────────────┘
                     ▼            ▼          ▼
              ┌──────────────────────────────────┐
              │   PostgreSQL (normalized 3NF)    │
              │  companies / layoff_events /     │
              │  daily_prices / market_index /   │
              │  event_windows                   │
              └──────────────┬───────────────────┘
                             ▼
              ┌──────────────────────────────────┐
              │   Event study + regression +     │
              │   Random Forest analysis         │
              └──────────────┬───────────────────┘
                             ▼
                      Visualizations
```

See [Design Decisions](#design-decisions) for why this architecture.

---

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- ~500 MB free disk space for the database

### 1. Clone and install

```bash
git clone <this-repo>
cd layoffs-analysis
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create the database

```bash
createdb layoffs_analysis
psql layoffs_analysis -f sql/schema.sql
```

### 3. Configure credentials

Copy `.env.example` to `.env` and fill in your Postgres credentials:

```
DB_USER=postgres
DB_PASS=yourpassword
DB_HOST=localhost
DB_PORT=5432
DB_NAME=layoffs_analysis
```

### 4. Download the source data

Download the layoffs dataset from Kaggle:
https://www.kaggle.com/datasets/swaptr/layoffs-2022

Place the file at `data/layoffs.csv`.

---

## Running the Pipeline

Run the scripts in order:

```bash
# Phase 1: Load layoff events
python ingest_layoffs.py

# Phase 2: Match companies to stock tickers
python match_tickers.py

# Phase 3: Fetch stock prices via yfinance
python fetch_prices.py

# Phase 4: Compute event windows and CARs
python analyze_events.py

# Phase 5: Generate visualizations
python visualize.py
```

Each script writes to its own log file (`*.log`) and is **idempotent** — you can re-run any stage without duplicating data.

---

## Data Sources

| Source | Format | Fields Used | License |
|--------|--------|-------------|---------|
| layoffs.fyi (via Kaggle mirror) | CSV | Company, date, # laid off, %, industry, stage | Public |
| Yahoo Finance (via `yfinance`) | JSON → DataFrame | Date, adjusted close, volume | Yahoo ToS |
| S&P 500 Index (`^GSPC`) | JSON → DataFrame | Date, adjusted close | Yahoo ToS |

**Why the Kaggle mirror?** Reproducibility. A frozen snapshot guarantees that anyone re-running the pipeline processes the identical input, which is required for scientific reproducibility. Scraping the live site would cause results to drift as layoffs.fyi updates.

---

## Repository Structure

```
layoffs-analysis/
├── sql/
│   └── schema.sql                 # PostgreSQL DDL: tables, indexes, constraints
├── data/
│   └── layoffs.csv                # Source data (not checked into git)
├── ingest_layoffs.py              # Phase 1: CSV → companies, layoff_events
├── match_tickers.py               # Phase 2: Company name → ticker symbol
├── fetch_prices.py                # Phase 3: yfinance → daily_prices
├── analyze_events.py              # Phase 4: Event study, CARs, regression
├── visualize.py                   # Phase 5: Charts and plots
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Design Decisions

This section exists specifically to document the reasoning behind architectural choices — feedback for graders and future collaborators.

### Why PostgreSQL over SQLite or MongoDB?

- **vs. SQLite:** We need real concurrent writes for the parallel price fetcher, and `CHECK` constraints / proper foreign keys are better supported.
- **vs. MongoDB:** The data is inherently relational — events link to companies link to prices. A document store would force us to either denormalize (update anomalies) or do application-side joins (slow and error-prone).

### Why third normal form?

Five normalized tables rather than one wide table. This prevents update anomalies (change Meta's industry in one place, not 30,000), enforces referential integrity, and separates source-of-truth data (`layoff_events`) from derived/recomputable data (`event_windows`).

### Why surrogate keys (SERIAL) instead of ticker as primary key?

Tickers change. Meta used to be FB; Block used to be SQ. If ticker were the PK, a rename would cascade through every table. Surrogate keys are stable; tickers are enforced via UNIQUE constraints, giving us the best of both worlds.

### Why NUMERIC instead of FLOAT for prices?

Floats have binary rounding errors (`0.1 + 0.2 != 0.3`) that compound over millions of calculations. `NUMERIC` gives exact decimal arithmetic — this is standard practice for any system that touches money.

### Why a manual ticker override map?

For the top ~50 highest-impact companies, fuzzy string matching can silently choose the wrong ticker (e.g., matching "Apple" to `APLE` — Apple Hospitality REIT). A hand-curated map for the companies that dominate the dataset is worth the 30 minutes of work.

### Why event study methodology?

Event studies are the standard method in financial economics for measuring the impact of a discrete announcement on asset prices (Fama et al., 1969). The "abnormal return" normalizes against market movement, so a 2% stock rise during a 2% market rally contributes zero — isolating company-specific reaction.

---

## Known Limitations

- **Sample bias:** layoffs.fyi primarily tracks tech and tech-adjacent companies. Results don't generalize to non-tech sectors.
- **Private companies excluded:** Roughly 40% of layoff events involve private companies with no ticker. These are filtered out of the stock analysis, potentially biasing toward larger/more established firms.
- **Single-factor market model:** We benchmark against the S&P 500 only. A more rigorous analysis would use a Fama-French multi-factor model.
- **Announcement date ≠ leak date:** Some layoffs leak to the press before official announcement, meaning the "event date" may already reflect some of the price impact.

---

## License

Academic project, Rutgers CS 210. Not for commercial use.