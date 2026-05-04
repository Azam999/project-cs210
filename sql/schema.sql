-- CS 210 project schema
-- 5 tables in 3NF: companies, layoff_events, daily_prices, market_index, event_windows
-- surrogate SERIAL primary keys, NUMERIC for prices, dates as DATE

-- drop in reverse FK order so re-running this is safe
DROP TABLE IF EXISTS event_windows CASCADE;
DROP TABLE IF EXISTS daily_prices CASCADE;
DROP TABLE IF EXISTS layoff_events CASCADE;
DROP TABLE IF EXISTS market_index CASCADE;
DROP TABLE IF EXISTS companies CASCADE;


-- companies: master record, one row per firm
CREATE TABLE companies (
    company_id      SERIAL PRIMARY KEY,
    company_name    VARCHAR(255) NOT NULL,
    ticker_symbol   VARCHAR(10),              -- NULL for private companies
    industry        VARCHAR(100),
    headquarters    VARCHAR(255),
    country         VARCHAR(100),
    is_public       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- company name has to be unique
    CONSTRAINT uq_company_name UNIQUE (company_name),

    -- ticker has to be unique too (NULLs allowed multiple times)
    CONSTRAINT uq_ticker UNIQUE (ticker_symbol)
);

CREATE INDEX idx_companies_ticker ON companies(ticker_symbol) WHERE ticker_symbol IS NOT NULL;


-- layoff_events: one row per layoff announcement
-- a company can have multiple layoff events over time
CREATE TABLE layoff_events (
    event_id            SERIAL PRIMARY KEY,
    company_id          INTEGER NOT NULL,
    announcement_date   DATE NOT NULL,
    employees_laid_off  INTEGER,              -- NULL if layoffs.fyi only has %
    percentage_laid_off NUMERIC(5,2),         -- e.g. 12.50 means 12.5%
    funds_raised_usd    NUMERIC(15,2),
    stage               VARCHAR(50),          -- "Post-IPO", "Series C", etc.
    source_url          TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- every event belongs to a company, delete events if the company is removed
    CONSTRAINT fk_event_company
        FOREIGN KEY (company_id)
        REFERENCES companies(company_id)
        ON DELETE CASCADE,

    -- DB level data validation
    CONSTRAINT chk_percentage_range
        CHECK (percentage_laid_off IS NULL OR (percentage_laid_off >= 0 AND percentage_laid_off <= 100)),

    CONSTRAINT chk_employees_positive
        CHECK (employees_laid_off IS NULL OR employees_laid_off >= 0),

    -- a company can't have two events on the same day
    CONSTRAINT uq_company_date
        UNIQUE (company_id, announcement_date)
);

-- index for "all events for company X"
CREATE INDEX idx_events_company ON layoff_events(company_id);
-- index for date range queries
CREATE INDEX idx_events_date ON layoff_events(announcement_date);


-- daily_prices: one row per (company, trading_date)
-- this is the biggest table, ~280K rows
CREATE TABLE daily_prices (
    price_id        BIGSERIAL PRIMARY KEY,
    company_id      INTEGER NOT NULL,
    trade_date      DATE NOT NULL,
    open_price      NUMERIC(12,4),
    close_price     NUMERIC(12,4),
    adj_close       NUMERIC(12,4) NOT NULL,   -- split/dividend adjusted, this is what we use
    volume          BIGINT,

    CONSTRAINT fk_price_company
        FOREIGN KEY (company_id)
        REFERENCES companies(company_id)
        ON DELETE CASCADE,

    -- one price per company per trading day
    CONSTRAINT uq_company_tradedate
        UNIQUE (company_id, trade_date),

    CONSTRAINT chk_prices_positive
        CHECK (adj_close > 0)
);

-- composite index for the main query: prices for company X in date range Y to Z
CREATE INDEX idx_prices_company_date ON daily_prices(company_id, trade_date);


-- market_index: S&P 500 daily prices, used as the benchmark
-- separate table because it's not really a "company"
CREATE TABLE market_index (
    trade_date      DATE PRIMARY KEY,
    index_symbol    VARCHAR(10) NOT NULL DEFAULT '^GSPC',
    adj_close       NUMERIC(12,4) NOT NULL,
    volume          BIGINT,

    CONSTRAINT chk_market_positive CHECK (adj_close > 0)
);


-- event_windows: computed CAR/SCAR per event per window
-- this is derived data, not source of truth
CREATE TABLE event_windows (
    window_id               SERIAL PRIMARY KEY,
    event_id                INTEGER NOT NULL,
    window_start_offset     INTEGER NOT NULL,   -- e.g. -30
    window_end_offset       INTEGER NOT NULL,   -- e.g. +30
    cumulative_abnormal_return  NUMERIC(10,6),
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
