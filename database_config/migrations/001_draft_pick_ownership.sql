-- Future pick ownership from Vincent's snapshot, separate from draft-slot values.
CREATE TABLE IF NOT EXISTS draft_pick_ownership (
    draft_year INTEGER NOT NULL,
    round INTEGER NOT NULL CHECK (round IN (1, 2)),
    original_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    owner_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    ownership_type TEXT NOT NULL CHECK (ownership_type IN
        ('owned', 'traded', 'conditional', 'swap_right', 'pooled')),
    is_resolved BOOLEAN NOT NULL,
    pool_id TEXT,
    notes TEXT,
    source_url TEXT,
    retrieved_at TIMESTAMPTZ,
    PRIMARY KEY (draft_year, round, original_team_id)
);
