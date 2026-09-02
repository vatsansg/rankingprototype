-- WTT Ranking Engine Prototype - SQLite schema
-- Two layers: (A) audit/orchestration tables (new, fix legacy auditability gaps)
--             (B) core ranking data tables (trimmed port of the legacy calculation path)
-- No rules_set / rules_group / rules / rules_alias tables -- see docs/legacy_rule_mapping.md
-- for the static reference mapping. Sequencing is hardcoded in engine/master.py.

PRAGMA foreign_keys = ON;

-- =====================================================================================
-- A. AUDIT & ORCHESTRATION SCHEMA
-- =====================================================================================

CREATE TABLE ranking_run (
    ranking_run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_code    TEXT NOT NULL DEFAULT 'WTT',
    category_code        TEXT NOT NULL CHECK (category_code IN ('SEN', 'YOU')),
    ranking_year         INTEGER NOT NULL,
    ranking_month        INTEGER NOT NULL,
    ranking_week         INTEGER NOT NULL,
    run_mode             TEXT NOT NULL DEFAULT 'normal' CHECK (run_mode IN ('normal', 'testing', 'replay')),
    trigger_type         TEXT NOT NULL DEFAULT 'on_demand' CHECK (trigger_type IN ('on_demand', 'scheduled')),
    scheduled_for         TEXT,               -- ISO-8601 datetime; set only when trigger_type='scheduled'
    status                 TEXT NOT NULL DEFAULT 'PENDING'
                            CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'ABORTED_DEPENDENCY')),
    started_at              TEXT,             -- ISO-8601, set on transition to RUNNING
    finished_at              TEXT,
    triggered_by               TEXT NOT NULL,  -- user email / 'system'
    input_snapshot_hash          TEXT,          -- sha256 of in-scope new_events_results rows, for reproducibility
    current_active                 INTEGER NOT NULL DEFAULT 0,
    superseded_by_run_id             INTEGER REFERENCES ranking_run(ranking_run_id),
    notes                               TEXT
);

CREATE INDEX idx_ranking_run_lookup ON ranking_run(category_code, ranking_year, ranking_month, ranking_week);
CREATE INDEX idx_ranking_run_status ON ranking_run(status);

-- One row per executed prototype "stored procedure" (Python function named identically
-- to its legacy SP). No FK to a rules table -- there is none by design.
CREATE TABLE ranking_run_step (
    ranking_run_step_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ranking_run_id           INTEGER NOT NULL REFERENCES ranking_run(ranking_run_id),
    step_seq                    INTEGER NOT NULL,
    step_group                    TEXT NOT NULL,   -- free-text display label, e.g. 'PreRequisitesValidation',
                                                     -- 'Orchestration', 'ResultsSelection', 'RankingResultPositions'
    step_name                       TEXT NOT NULL,  -- exact prototype function name, e.g.
                                                      -- 'sp_Calculate_WTT_SEN_Ranking_BestResults'
    status                             TEXT NOT NULL DEFAULT 'PENDING'
                                        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED')),
    started_at                            TEXT,
    finished_at                              TEXT,
    duration_ms                                 INTEGER,
    rows_inserted                                  INTEGER NOT NULL DEFAULT 0,
    rows_updated                                      INTEGER NOT NULL DEFAULT 0,
    rows_deleted                                         INTEGER NOT NULL DEFAULT 0,
    result_message                                          TEXT
);

CREATE INDEX idx_run_step_run ON ranking_run_step(ranking_run_id, step_seq);

CREATE TABLE ranking_run_error (
    ranking_run_error_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ranking_run_id             INTEGER NOT NULL REFERENCES ranking_run(ranking_run_id),
    ranking_run_step_id           INTEGER REFERENCES ranking_run_step(ranking_run_step_id),
    error_type                       TEXT NOT NULL,   -- python exception class name
    error_message                       TEXT NOT NULL,
    traceback                              TEXT,
    occurred_at                               TEXT NOT NULL
);

CREATE INDEX idx_run_error_run ON ranking_run_error(ranking_run_id);

CREATE TABLE ranking_run_metric (
    ranking_run_metric_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ranking_run_step_id        INTEGER NOT NULL REFERENCES ranking_run_step(ranking_run_step_id),
    metric_name                    TEXT NOT NULL,
    metric_value                      REAL,
    UNIQUE (ranking_run_step_id, metric_name)
);

-- Replaces Ranking_Validation_Summary, but retains history instead of wiping/re-populating each run.
CREATE TABLE ranking_validation_result (
    ranking_validation_result_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    ranking_run_id                   INTEGER NOT NULL REFERENCES ranking_run(ranking_run_id),
    validation_category                 TEXT NOT NULL CHECK (validation_category IN
                                          ('PreRankingValidation', 'PostRankingValidation')),
    check_name                             TEXT NOT NULL,
    passed                                    INTEGER NOT NULL CHECK (passed IN (0, 1)),
    remarks                                      TEXT,
    table_name                                      TEXT,
    competitor_id                                      INTEGER,
    event_id                                              INTEGER,
    total_points                                             REAL,
    main_ranking_points                                         REAL,
    created_at                                                     TEXT NOT NULL
);

CREATE INDEX idx_validation_result_run ON ranking_validation_result(ranking_run_id);

-- =====================================================================================
-- B. CORE RANKING DATA SCHEMA (trimmed port -- ~25 tables on the real calculation path)
-- =====================================================================================

CREATE TABLE categories (
    category_code         TEXT PRIMARY KEY CHECK (category_code IN ('SEN', 'YOU')),
    category_description     TEXT NOT NULL,
    organization_code           TEXT NOT NULL DEFAULT 'WTT'
);

CREATE TABLE age_categories (
    age_category_code       TEXT PRIMARY KEY,   -- SEN, U19, U17, U15, U13, U11
    age_category_description   TEXT,
    min_age_inclusive             INTEGER,
    max_age_inclusive                INTEGER,
    category_code                       TEXT NOT NULL REFERENCES categories(category_code),
    organization_code                      TEXT NOT NULL DEFAULT 'WTT'
);

CREATE TABLE ranking_categories (
    ranking_category_id     INTEGER PRIMARY KEY,
    ranking_category_code      TEXT NOT NULL,     -- MS, WS, MD, WD, XD, MDI, WDI, XDI, MT, WT, XT
    category_code                 TEXT NOT NULL REFERENCES categories(category_code),
    ranking_category_desc            TEXT,
    ranking_order                       INTEGER,
    UNIQUE (ranking_category_code, category_code)
);

CREATE TABLE result_position (
    result_position_id     INTEGER PRIMARY KEY,
    position                   TEXT NOT NULL,        -- W, F, SF, QF, R16, QR1..QR4, Qual, G2L, GL, ...
    phase                          TEXT,
    position_order                    INTEGER,
    phase_type                           TEXT,        -- KO, QUAL
    round_number                            INTEGER,
    position_value                             INTEGER NOT NULL,  -- draw-size denominator used in points lookup
    category_code                                 TEXT NOT NULL REFERENCES categories(category_code),
    organization_code                                TEXT NOT NULL DEFAULT 'WTT',
    UNIQUE (position, category_code, organization_code)
);

CREATE TABLE ranking_calc_main (   -- points-per-round lookup, sourced from legacy RankingCalcMain_New
    ranking_calc_main_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_code         TEXT NOT NULL DEFAULT 'WTT',
    category_code                TEXT NOT NULL REFERENCES categories(category_code),
    age_category_code               TEXT NOT NULL REFERENCES age_categories(age_category_code),
    ranking_category_code              TEXT NOT NULL,
    event_type                            TEXT NOT NULL,  -- GS, CF, OG, WTC, WCH, COC, Con, ...
    w INTEGER, f INTEGER, sf INTEGER, qf INTEGER,
    r16 INTEGER, r32 INTEGER, r64 INTEGER, r128 INTEGER, r256 INTEGER,
    qual INTEGER, qer INTEGER,
    qr4 INTEGER, qr3 INTEGER, qr2 INTEGER, qr1 INTEGER,
    g4l INTEGER, g3l INTEGER, g2l INTEGER, gl INTEGER,
    UNIQUE (organization_code, category_code, age_category_code, ranking_category_code, event_type)
);

CREATE TABLE modification_type (
    modification_type_id   INTEGER PRIMARY KEY,
    modification_type          TEXT NOT NULL
);

CREATE TABLE reason_type (
    reason_type_id   INTEGER PRIMARY KEY,
    reason_type          TEXT NOT NULL
);

CREATE TABLE available_ranking_runs (
    available_ranking_runs_id  INTEGER PRIMARY KEY,
    ranking_run_name               TEXT NOT NULL,    -- SeniorAndYouth, Senior, Youth
    ranking_run_description            TEXT,
    organization_code                     TEXT NOT NULL DEFAULT 'WTT'
);

CREATE TABLE available_ranking_runs_categories (
    available_ranking_runs_categories_id  INTEGER PRIMARY KEY,
    available_ranking_runs_id                 INTEGER NOT NULL REFERENCES available_ranking_runs(available_ranking_runs_id),
    category_code                                TEXT NOT NULL REFERENCES categories(category_code),
    run_order                                       INTEGER NOT NULL    -- SEN=1, YOU=2 for combined run
);

CREATE TABLE competitors (
    competitor_id       INTEGER PRIMARY KEY,     -- = legacy PlayerID
    player_name             TEXT NOT NULL,
    dob                        TEXT,             -- ISO date, nullable
    gender                        TEXT,
    country_code                     TEXT,
    nationality_code                    TEXT,
    age_category_code                      TEXT REFERENCES age_categories(age_category_code),
    is_retired                                INTEGER NOT NULL DEFAULT 0,
    wtt_eligibility                              INTEGER NOT NULL DEFAULT 1
        -- explicit field so the legacy "ranking status mapped to isActive, not the Eligibility tab" bug can't recur silently
);

CREATE TABLE events (
    event_id               INTEGER PRIMARY KEY,
    event_name                 TEXT NOT NULL,
    start_date                     TEXT,
    end_date                          TEXT,
    event_type_general_code              TEXT,    -- GS, WTC, WCH, CF, OG, ... drives ranking_calc_main.event_type lookup
    event_type_code                         TEXT,   -- CC, CCH, IEV, IOE, ... drives continental/ZPP event-type filters
    ranking_year                               INTEGER,
    ranking_month                                 INTEGER,
    ranking_week                                     INTEGER,
    is_forbidden                                        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE players_doubles (
    doubles_id          INTEGER PRIMARY KEY,
    player1_id              INTEGER NOT NULL REFERENCES competitors(competitor_id),
    player2_id                  INTEGER NOT NULL REFERENCES competitors(competitor_id),
    sub_event_code                  TEXT NOT NULL,   -- MD, WD, XD
    age_category_code                  TEXT REFERENCES age_categories(age_category_code)
        -- legacy bug: this stored column drifts to 'SEN' for youth pairs and silently drops them
        -- from main_ranking at Step3. Fix: sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking
        -- derives the effective age category from both players' competitors.age_category_code
        -- rather than trusting this column blindly.
);

-- Raw imported per-player-per-event staging (pre-processing input to a ranking run).
CREATE TABLE new_events_results (
    new_event_result_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id                  INTEGER NOT NULL REFERENCES events(event_id),
    competitor_id                 INTEGER NOT NULL REFERENCES competitors(competitor_id),
    sub_event_code                    TEXT NOT NULL,
    result_position                       TEXT NOT NULL,
    matches_played                            INTEGER,
    matches_won                                  INTEGER,
    matches_lost                                    INTEGER,
    qualifier                                          INTEGER NOT NULL DEFAULT 0,
    result_type                                            TEXT NOT NULL DEFAULT 'FINAL_RESULT',
    zero_point_penalty                                          INTEGER NOT NULL DEFAULT 0,
    last_phase_win                                                 INTEGER NOT NULL DEFAULT 0,
    ranking_category_code                                             TEXT NOT NULL,
    age_category_code                                                    TEXT NOT NULL,
    category_code                                                           TEXT NOT NULL REFERENCES categories(category_code),
    organization_code                                                          TEXT NOT NULL DEFAULT 'WTT',
    ranking_points                                                                REAL,
    cross_awarded_from_event_id                                                       INTEGER REFERENCES events(event_id)
        -- explicit lineage for the SEN<->YOU 5x cross-award at import time
);

CREATE INDEX idx_new_events_results_event ON new_events_results(event_id);
CREATE INDEX idx_new_events_results_category ON new_events_results(category_code);

-- Audit log for manual corrections made to an imported result BEFORE a calculation run
-- consumes it (result_position edits via the web UI's Manual Modifications screen).
-- Distinct from players_events_results_master_modified, which overrides the book-of-record
-- AFTER a run has seeded it -- this table logs edits to the raw import staging row itself.
-- new_event_result_id is deliberately NOT a foreign key: sp_Calculate_Ranking_FinalizeRun
-- deletes consumed new_events_results rows once a run succeeds, and this audit trail must
-- survive that deletion (same principle as ranking_run_error surviving business-data changes).
CREATE TABLE new_events_results_modification_log (
    modification_log_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    new_event_result_id      INTEGER NOT NULL,
    competitor_id                INTEGER NOT NULL,
    event_id                        INTEGER NOT NULL,
    old_result_position                TEXT NOT NULL,
    new_result_position                   TEXT NOT NULL,
    old_ranking_points                       REAL,
    new_ranking_points                          REAL,
    modified_by                                    TEXT NOT NULL,
    modified_at                                       TEXT NOT NULL
);

CREATE INDEX idx_new_events_results_mod_log_result ON new_events_results_modification_log(new_event_result_id);

-- Central per-player-per-event ranked result record -- the "book of record".
CREATE TABLE players_events_results_master (
    player_event_result_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id                INTEGER NOT NULL REFERENCES competitors(competitor_id),
    event_id                        INTEGER NOT NULL REFERENCES events(event_id),
    sub_event_code                     TEXT NOT NULL,
    ranking_category_code                 TEXT NOT NULL,
    result_position                          TEXT NOT NULL,
    ranking_points                              REAL NOT NULL DEFAULT 0,
    ranking_year                                   INTEGER NOT NULL,
    ranking_month                                     INTEGER NOT NULL,
    ranking_week                                         INTEGER NOT NULL,
    expiry_year                                             INTEGER,
    expiry_month                                               INTEGER,
    expiry_week                                                   INTEGER,
    player_best_ranking_result_number                                INTEGER NOT NULL DEFAULT 0,
    best_result_no_sen_you                                              INTEGER NOT NULL DEFAULT 0,
    active                                                                 INTEGER NOT NULL DEFAULT 1,
    zero_point_penalty                                                        INTEGER NOT NULL DEFAULT 0,
    excluded_due_to_zero_point_penalty                                           INTEGER NOT NULL DEFAULT 0,
    mandatory_inclusion_for_best_results                                            INTEGER NOT NULL DEFAULT 0,
    age_category_code                                                                  TEXT NOT NULL,
    category_code                                                                         TEXT NOT NULL REFERENCES categories(category_code),
    organization_code                                                                        TEXT NOT NULL DEFAULT 'WTT',
    ranking_run_id_created                                                                      INTEGER REFERENCES ranking_run(ranking_run_id)
);

CREATE INDEX idx_perm_competitor ON players_events_results_master(competitor_id, category_code, ranking_category_code);
CREATE INDEX idx_perm_event ON players_events_results_master(event_id);

-- Manual correction/override staging -- feeds sp_Rules_Set_Weekly_Events_ManualModifications.
CREATE TABLE players_events_results_master_modified (
    player_modification_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id                INTEGER NOT NULL REFERENCES competitors(competitor_id),
    event_id                        INTEGER NOT NULL REFERENCES events(event_id),
    sub_event_code                     TEXT NOT NULL,
    ranking_category_code                 TEXT NOT NULL,
    age_category_code                        TEXT,
    category_code                               TEXT NOT NULL REFERENCES categories(category_code),
    result_position                                TEXT,
    ranking_points                                    REAL,
    ranking_year INTEGER, ranking_month INTEGER, ranking_week INTEGER,
    expiry_year INTEGER, expiry_month INTEGER, expiry_week INTEGER,
    modified_result_position                            TEXT,
    modified_ranking_points                                REAL,
    modified_expiry_year                                      INTEGER,
    modified_expiry_month                                        INTEGER,
    modified_expiry_week                                            INTEGER,
    modified_active                                                    INTEGER,
    modification_type_id                                                  INTEGER NOT NULL REFERENCES modification_type(modification_type_id),
    reason_type_id                                                           INTEGER REFERENCES reason_type(reason_type_id),
    reason_description                                                          TEXT,
    modified_date                                                                  TEXT NOT NULL,
    modified_by                                                                       TEXT NOT NULL,
    applied                                                                              INTEGER NOT NULL DEFAULT 0,
    applied_in_ranking_run_id                                                               INTEGER REFERENCES ranking_run(ranking_run_id)
);

CREATE INDEX idx_perm_modified_applied ON players_events_results_master_modified(category_code, applied);

-- Published ranking output.
CREATE TABLE main_ranking (
    main_ranking_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id             INTEGER NOT NULL REFERENCES competitors(competitor_id),
    ranking_pos                  INTEGER,
    ranking_points                   REAL NOT NULL DEFAULT 0,
    ranking_category                     TEXT NOT NULL,   -- = ranking_category_code
    ranking_year                            INTEGER NOT NULL,
    ranking_month                              INTEGER NOT NULL,
    ranking_week                                  INTEGER NOT NULL,
    organization_code                                TEXT NOT NULL DEFAULT 'WTT',
    category_code                                       TEXT NOT NULL REFERENCES categories(category_code),
    age_category_code                                      TEXT NOT NULL,
    ranking_pos_age_category                                  INTEGER,
    ranking_run_id                                               INTEGER NOT NULL REFERENCES ranking_run(ranking_run_id)
);

CREATE INDEX idx_main_ranking_lookup ON main_ranking(category_code, ranking_year, ranking_month, ranking_week, ranking_category);
CREATE INDEX idx_main_ranking_run ON main_ranking(ranking_run_id);

CREATE TABLE schedule (
    schedule_id       INTEGER PRIMARY KEY,
    schedule_date         TEXT NOT NULL,
    status                    TEXT NOT NULL,   -- Completed, Kept on Hold, Scheduled
    organization_code            TEXT NOT NULL DEFAULT 'WTT',
    category_code                    TEXT NOT NULL REFERENCES categories(category_code),
    ranking_year INTEGER, ranking_month INTEGER, ranking_week INTEGER,
    published_date_utc                  TEXT
);

CREATE TABLE ranking_engine_info (   -- singleton current-state pointer per category
    ranking_info_id       INTEGER PRIMARY KEY,
    category_code             TEXT NOT NULL UNIQUE REFERENCES categories(category_code),
    organization_code            TEXT NOT NULL DEFAULT 'WTT',
    current_ranking_year            INTEGER NOT NULL,
    current_ranking_month              INTEGER NOT NULL,
    current_ranking_week                  INTEGER NOT NULL
);
