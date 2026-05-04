-- adds match metadata to companies so we know how each ticker was matched
-- and how confident we are in it

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS match_method VARCHAR(20),
    ADD COLUMN IF NOT EXISTS match_confidence NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS match_attempted_at TIMESTAMP;

-- if method is set, confidence has to be set too (no half-filled metadata)
ALTER TABLE companies
    ADD CONSTRAINT chk_match_consistency
    CHECK (
        (match_method IS NULL AND match_confidence IS NULL)
        OR
        (match_method IS NOT NULL AND match_confidence IS NOT NULL)
    );

-- match_method values:
--   manual: from the hardcoded override map
--   yf_search: matched via Yahoo's search API
--   yf_direct: yfinance recognized the ticker directly
--   fuzzy: rapidfuzz match (currently disabled)
--   unresolved: no match found, probably private
ALTER TABLE companies
    ADD CONSTRAINT chk_match_method_valid
    CHECK (
        match_method IS NULL
        OR match_method IN ('manual', 'yf_search', 'yf_direct', 'fuzzy', 'unresolved')
    );

-- index for filtering by match quality
CREATE INDEX IF NOT EXISTS idx_companies_match_method ON companies(match_method);
