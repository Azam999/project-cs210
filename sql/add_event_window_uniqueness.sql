-- ============================================================================
-- Migration 003: Add uniqueness to event_windows
-- ============================================================================
-- Without this constraint, re-running analyze_events.py would duplicate rows
-- in event_windows. Adding UNIQUE (event_id, window_start_offset,
-- window_end_offset) lets us use INSERT ... ON CONFLICT DO NOTHING and keeps
-- the Phase 3 analysis script idempotent, matching the pattern used in
-- Phase 1 (companies/layoff_events) and Phase 2b (daily_prices/market_index).
-- ============================================================================

ALTER TABLE event_windows
    ADD CONSTRAINT uq_event_window
    UNIQUE (event_id, window_start_offset, window_end_offset);
