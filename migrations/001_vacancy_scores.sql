CREATE TABLE IF NOT EXISTS vacancy_scores (
    id               SERIAL PRIMARY KEY,
    vacancy_id       INTEGER NOT NULL REFERENCES vacancies(id),
    scored_at        TIMESTAMP DEFAULT NOW(),
    prompt_version   TEXT NOT NULL,
    tier             VARCHAR(1) NOT NULL,
    action           TEXT NOT NULL,
    score            INTEGER NOT NULL,
    score_breakdown  JSONB,
    visa_sponsorship TEXT,
    relocation_support TEXT,
    remote_policy    TEXT,
    salary_min       INTEGER,
    salary_max       INTEGER,
    salary_currency  TEXT,
    experience_level TEXT,
    verbatim_evidence JSONB,
    pre_filter_blocked BOOLEAN DEFAULT FALSE,
    reason           TEXT
);

CREATE INDEX IF NOT EXISTS vacancy_scores_vacancy_id_idx ON vacancy_scores(vacancy_id);
CREATE INDEX IF NOT EXISTS vacancy_scores_tier_idx ON vacancy_scores(tier);
CREATE INDEX IF NOT EXISTS vacancy_scores_scored_at_idx ON vacancy_scores(scored_at);
