-- adds a UNIQUE constraint on event_windows so we can use ON CONFLICT DO NOTHING
-- without it, re-running analyze_events.py would duplicate rows

ALTER TABLE event_windows
    ADD CONSTRAINT uq_event_window
    UNIQUE (event_id, window_start_offset, window_end_offset);
