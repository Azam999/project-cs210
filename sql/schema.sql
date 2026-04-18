-- ============================================================================
-- CS 210 Project: Do Tech Layoffs Help Stock Prices?
-- Schema Version: 1.0
-- ============================================================================
-- Design principles:
--   1. Third Normal Form (3NF) - no transitive dependencies
--   2. Surrogate keys (SERIAL) for all primary keys
--   3. Natural keys enforced via UNIQUE constraints
--   4. All dates stored as DATE type (not VARCHAR)
--   5. Monetary/percentage values stored as NUMERIC, never FLOAT
-- ============================================================================

-- Drop in reverse dependency order (children before parents)
-- This makes the script idempotent — safe to re-run during development
DROP TABLE IF EXISTS event_windows CASCADE;
DROP TABLE IF EXISTS daily_prices CASCADE;
DROP TABLE IF EXISTS layoff_events CASCADE;
DROP TABLE IF EXISTS market_index CASCADE;
DROP TABLE IF EXISTS companies CASCADE;


-- ----------------------------------------------------------------------------
-- TABLE: companies
-- Purpose: Master record for every company we track.
-- One row per company. This is the "hub" that layoffs and prices link back to.
-- ----------------------------------------------------------------------------
CREATE TABLE companies (
    company_id      SERIAL PRIMARY KEY,
    company_name    VARCHAR(255) NOT NULL,
    ticker_symbol   VARCHAR(10),              -- NULL allowed: private companies have no ticker
    industry        VARCHAR(100),
    headquarters    VARCHAR(255),
    country         VARCHAR(100),
    is_public       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- A company name should be unique in our system.
    -- We normalize to lowercase on insert to prevent "Meta" vs "meta" duplicates.
    CONSTRAINT uq_company_name UNIQUE (company_name),

    -- A ticker, if it exists, must be unique. Two companies can't share MSFT.
    -- NULLs are allowed multiple times (Postgres treats NULL != NULL in UNIQUE).
    CONSTRAINT uq_ticker UNIQUE (ticker_symbol)
);

CREATE INDEX idx_companies_ticker ON companies(ticker_symbol) WHERE ticker_symbol IS NOT NULL;


-- ----------------------------------------------------------------------------
-- TABLE: layoff_events
-- Purpose: One row per layoff announcement.
-- A company can have multiple layoff events over time (Meta did several).
-- ----------------------------------------------------------------------------
CREATE TABLE layoff_events (
    event_id            SERIAL PRIMARY KEY,
    company_id          INTEGER NOT NULL,
    announcement_date   DATE NOT NULL,
    employees_laid_off  INTEGER,              -- NULL allowed: layoffs.fyi sometimes reports % only
    percentage_laid_off NUMERIC(5,2),         -- e.g., 12.50 means 12.50%
    funds_raised_usd    NUMERIC(15,2),        -- Company's total funding at time of layoff
    stage               VARCHAR(50),          -- "Post-IPO", "Series C", etc.
    source_url          TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key: every event MUST belong to a known company.
    -- ON DELETE CASCADE: if we remove a company, its events go too.
    CONSTRAINT fk_event_company
        FOREIGN KEY (company_id)
        REFERENCES companies(company_id)
        ON DELETE CASCADE,

    -- Data validation at the DB layer (defense in depth).
    -- Percentages must be between 0 and 100.
    CONSTRAINT chk_percentage_range
        CHECK (percentage_laid_off IS NULL OR (percentage_laid_off >= 0 AND percentage_laid_off <= 100)),

    -- You can't lay off a negative number of people.
    CONSTRAINT chk_employees_positive
        CHECK (employees_laid_off IS NULL OR employees_laid_off >= 0),

    -- A company cannot have two separate "events" on the exact same day.
    -- If layoffs.fyi has duplicate entries, we want the DB to reject them.
    CONSTRAINT uq_company_date
        UNIQUE (company_id, announcement_date)
);

-- Index for the most common query pattern: "all events for company X"
CREATE INDEX idx_events_company ON layoff_events(company_id);
-- Index for time-range queries: "all events in Q1 2024"
CREATE INDEX idx_events_date ON layoff_events(announcement_date);


-- ----------------------------------------------------------------------------
-- TABLE: daily_prices
-- Purpose: One row per (company, trading_date) pair.
-- This table will be the largest — ~30K-40K rows expected.
-- ----------------------------------------------------------------------------
CREATE TABLE daily_prices (
    price_id        BIGSERIAL PRIMARY KEY,    -- BIGSERIAL: this table grows fast
    company_id      INTEGER NOT NULL,
    trade_date      DATE NOT NULL,
    open_price      NUMERIC(12,4),
    close_price     NUMERIC(12,4),            -- Unadjusted close
    adj_close       NUMERIC(12,4) NOT NULL,   -- Split/dividend-adjusted — this is what we actually use
    volume          BIGINT,

    CONSTRAINT fk_price_company
        FOREIGN KEY (company_id)
        REFERENCES companies(company_id)
        ON DELETE CASCADE,

    -- A stock has exactly one price per trading day. Period.
    CONSTRAINT uq_company_tradedate
        UNIQUE (company_id, trade_date),

    CONSTRAINT chk_prices_positive
        CHECK (adj_close > 0)
);

-- Composite index for the core query: "get prices for company X in date range Y to Z"
-- Order matters: company_id first because we always filter on it, then date for range scans.
CREATE INDEX idx_prices_company_date ON daily_prices(company_id, trade_date);


-- ----------------------------------------------------------------------------
-- TABLE: market_index
-- Purpose: S&P 500 daily prices, used as the market benchmark for abnormal returns.
-- Separate from daily_prices because the index isn't a "company" in our schema.
-- ----------------------------------------------------------------------------
CREATE TABLE market_index (
    trade_date      DATE PRIMARY KEY,         -- Date IS the natural key here
    index_symbol    VARCHAR(10) NOT NULL DEFAULT '^GSPC',
    adj_close       NUMERIC(12,4) NOT NULL,
    volume          BIGINT,

    CONSTRAINT chk_market_positive CHECK (adj_close > 0)
);


-- ----------------------------------------------------------------------------
-- TABLE: event_windows
-- Purpose: Computed results per event. This is derived data — the output of our analysis.
-- We separate it from layoff_events because it's recomputable, not source-of-truth.
-- ----------------------------------------------------------------------------
CREATE TABLE event_windows (
    window_id               SERIAL PRIMARY KEY,
    event_id                INTEGER NOT NULL,
    window_start_offset     INTEGER NOT NULL,   -- e.g., -30 (trading days before event)
    window_end_offset       INTEGER NOT NULL,   -- e.g., +30
    cumulative_abnormal_return  NUMERIC(10,6),  -- CAR
    avg_abnormal_return     NUMERIC(10,6),
    t_statistic             NUMERIC(10,6),
    computed_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_window_event
        FOREIGN KEY (event_id)
        REFERENCES layoff_events(event_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_window_order
        CHECK (window_start_offset < window_end_offset)
);

CREATE INDEX idx_windows_event ON event_windows(event_id);