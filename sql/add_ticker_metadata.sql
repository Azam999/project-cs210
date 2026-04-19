-- ============================================================================
-- Migration 002: Add ticker match metadata to companies table
-- ============================================================================
-- Adds columns to track HOW a ticker was matched and how confident we are.
-- This lets Phase 4 analysis filter by match quality if results look suspicious.
-- ============================================================================

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS match_method VARCHAR(20),
    ADD COLUMN IF NOT EXISTS match_confidence NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS match_attempted_at TIMESTAMP;

-- Add a CHECK constraint: if method is set, confidence must also be set.
-- This prevents half-populated match metadata.
ALTER TABLE companies
    ADD CONSTRAINT chk_match_consistency
    CHECK (
        (match_method IS NULL AND match_confidence IS NULL)
        OR
        (match_method IS NOT NULL AND match_confidence IS NOT NULL)
    );

-- Valid values for match_method (enforced via CHECK):
--   'manual'     = from hardcoded override map (confidence 100)
--   'yf_direct'  = yfinance recognized the name as a ticker directly
--   'fuzzy'      = rapidfuzz match against known ticker list
--   'unresolved' = no match found (likely private)
ALTER TABLE companies
    ADD CONSTRAINT chk_match_method_valid
    CHECK (
        match_method IS NULL
        OR match_method IN ('manual', 'yf_direct', 'fuzzy', 'unresolved')
    );

-- Index for filtering by match quality
CREATE INDEX IF NOT EXISTS idx_companies_match_method ON companies(match_method);