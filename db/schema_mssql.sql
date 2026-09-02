-- WTT Ranking Engine Prototype - Azure SQL (T-SQL) schema.
-- Ported from db/schema.sql (SQLite). See docs/legacy_rule_mapping.md and README.md for the
-- full type-mapping rationale (DECIMAL not FLOAT for points, BIT for booleans, DATETIME2 for
-- timestamps computed server-side via SYSUTCDATETIME(), etc.)
-- No rules_set/rules_group/rules/rules_alias tables -- sequencing is hardcoded in the master
-- stored procedures (db/procedures/master/).

-- =====================================================================================
-- A. AUDIT & ORCHESTRATION SCHEMA
-- =====================================================================================

CREATE TABLE dbo.ranking_run (
    ranking_run_id        INT IDENTITY(1,1) PRIMARY KEY,
    organization_code     NVARCHAR(10)  NOT NULL CONSTRAINT DF_ranking_run_org DEFAULT ('WTT'),
    category_code         NVARCHAR(3)   NOT NULL CONSTRAINT CK_ranking_run_category CHECK (category_code IN ('SEN','YOU')),
    ranking_year           INT NOT NULL,
    ranking_month              INT NOT NULL,
    ranking_week                   INT NOT NULL,
    run_mode                          NVARCHAR(10) NOT NULL CONSTRAINT DF_ranking_run_mode DEFAULT ('normal')
                                          CONSTRAINT CK_ranking_run_mode CHECK (run_mode IN ('normal','testing','replay')),
    trigger_type                          NVARCHAR(10) NOT NULL CONSTRAINT DF_ranking_run_trigger DEFAULT ('on_demand')
                                              CONSTRAINT CK_ranking_run_trigger CHECK (trigger_type IN ('on_demand','scheduled')),
    scheduled_for                             DATETIME2(3) NULL,
    status                                        NVARCHAR(20) NOT NULL CONSTRAINT DF_ranking_run_status DEFAULT ('PENDING')
                                                    CONSTRAINT CK_ranking_run_status CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','ABORTED_DEPENDENCY')),
    started_at                                        DATETIME2(3) NULL,
    finished_at                                            DATETIME2(3) NULL,
    triggered_by                                              NVARCHAR(100) NOT NULL,
    input_snapshot_hash                                            NVARCHAR(64) NULL,
    current_active                                                     BIT NOT NULL CONSTRAINT DF_ranking_run_active DEFAULT (0),
    superseded_by_run_id                                                   INT NULL REFERENCES dbo.ranking_run(ranking_run_id),
    notes                                                                      NVARCHAR(MAX) NULL
);
CREATE INDEX idx_ranking_run_lookup ON dbo.ranking_run(category_code, ranking_year, ranking_month, ranking_week);
CREATE INDEX idx_ranking_run_status ON dbo.ranking_run(status);

CREATE TABLE dbo.ranking_run_step (
    ranking_run_step_id   INT IDENTITY(1,1) PRIMARY KEY,
    ranking_run_id            INT NOT NULL REFERENCES dbo.ranking_run(ranking_run_id),
    step_seq                     INT NOT NULL,
    step_group                       NVARCHAR(50) NOT NULL,
    step_name                            NVARCHAR(100) NOT NULL,
    status                                    NVARCHAR(20) NOT NULL CONSTRAINT DF_step_status DEFAULT ('PENDING')
                                                CONSTRAINT CK_step_status CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','SKIPPED')),
    started_at                                    DATETIME2(3) NULL,
    finished_at                                        DATETIME2(3) NULL,
    duration_ms                                            INT NULL,
    rows_inserted                                              INT NOT NULL CONSTRAINT DF_step_ri DEFAULT (0),
    rows_updated                                                   INT NOT NULL CONSTRAINT DF_step_ru DEFAULT (0),
    rows_deleted                                                       INT NOT NULL CONSTRAINT DF_step_rd DEFAULT (0),
    result_message                                                         NVARCHAR(400) NULL
);
CREATE INDEX idx_run_step_run ON dbo.ranking_run_step(ranking_run_id, step_seq);

CREATE TABLE dbo.ranking_run_error (
    ranking_run_error_id  INT IDENTITY(1,1) PRIMARY KEY,
    ranking_run_id            INT NOT NULL REFERENCES dbo.ranking_run(ranking_run_id),
    ranking_run_step_id           INT NULL REFERENCES dbo.ranking_run_step(ranking_run_step_id),
    error_type                        NVARCHAR(200) NOT NULL,
    error_message                         NVARCHAR(MAX) NOT NULL,
    traceback                                 NVARCHAR(MAX) NULL,
    occurred_at                                   DATETIME2(3) NOT NULL
);
CREATE INDEX idx_run_error_run ON dbo.ranking_run_error(ranking_run_id);

CREATE TABLE dbo.ranking_run_metric (
    ranking_run_metric_id   INT IDENTITY(1,1) PRIMARY KEY,
    ranking_run_step_id         INT NOT NULL REFERENCES dbo.ranking_run_step(ranking_run_step_id),
    metric_name                     NVARCHAR(100) NOT NULL,
    metric_value                        DECIMAL(18,4) NULL,
    CONSTRAINT UQ_run_metric UNIQUE (ranking_run_step_id, metric_name)
);

CREATE TABLE dbo.ranking_validation_result (
    ranking_validation_result_id  INT IDENTITY(1,1) PRIMARY KEY,
    ranking_run_id                    INT NOT NULL REFERENCES dbo.ranking_run(ranking_run_id),
    validation_category                   NVARCHAR(30) NOT NULL
                                             CONSTRAINT CK_validation_category CHECK (validation_category IN ('PreRankingValidation','PostRankingValidation')),
    check_name                                NVARCHAR(100) NOT NULL,
    passed                                        BIT NOT NULL,
    remarks                                           NVARCHAR(500) NULL,
    table_name                                            NVARCHAR(100) NULL,
    competitor_id                                             INT NULL,
    event_id                                                      INT NULL,
    total_points                                                      DECIMAL(10,2) NULL,
    main_ranking_points                                                   DECIMAL(10,2) NULL,
    created_at                                                                DATETIME2(3) NOT NULL
);
CREATE INDEX idx_validation_result_run ON dbo.ranking_validation_result(ranking_run_id);

-- =====================================================================================
-- B. CORE RANKING DATA SCHEMA
-- =====================================================================================

CREATE TABLE dbo.categories (
    category_code         NVARCHAR(3) PRIMARY KEY CONSTRAINT CK_categories_code CHECK (category_code IN ('SEN','YOU')),
    category_description     NVARCHAR(50) NOT NULL,
    organization_code            NVARCHAR(10) NOT NULL CONSTRAINT DF_categories_org DEFAULT ('WTT')
);

CREATE TABLE dbo.age_categories (
    age_category_code       NVARCHAR(10) PRIMARY KEY,
    age_category_description   NVARCHAR(50) NULL,
    min_age_inclusive             INT NULL,
    max_age_inclusive                INT NULL,
    category_code                       NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    organization_code                      NVARCHAR(10) NOT NULL CONSTRAINT DF_age_categories_org DEFAULT ('WTT')
);

CREATE TABLE dbo.ranking_categories (
    ranking_category_id     INT PRIMARY KEY,
    ranking_category_code       NVARCHAR(10) NOT NULL,
    category_code                  NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    ranking_category_desc              NVARCHAR(100) NULL,
    ranking_order                          INT NULL,
    CONSTRAINT UQ_ranking_categories UNIQUE (ranking_category_code, category_code)
);

CREATE TABLE dbo.result_position (
    result_position_id     INT PRIMARY KEY,
    position                   NVARCHAR(10) NOT NULL,
    phase                          NVARCHAR(10) NULL,
    position_order                    INT NULL,
    phase_type                            NVARCHAR(10) NULL,
    round_number                              INT NULL,
    position_value                                INT NOT NULL,
    category_code                                     NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    organization_code                                     NVARCHAR(10) NOT NULL CONSTRAINT DF_result_position_org DEFAULT ('WTT'),
    CONSTRAINT UQ_result_position UNIQUE (position, category_code, organization_code)
);

CREATE TABLE dbo.ranking_calc_main (
    ranking_calc_main_id   INT IDENTITY(1,1) PRIMARY KEY,
    organization_code          NVARCHAR(10) NOT NULL CONSTRAINT DF_rcm_org DEFAULT ('WTT'),
    category_code                  NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    age_category_code                  NVARCHAR(10) NOT NULL REFERENCES dbo.age_categories(age_category_code),
    ranking_category_code                  NVARCHAR(10) NOT NULL,
    event_type                                 NVARCHAR(10) NOT NULL,
    w INT NULL, f INT NULL, sf INT NULL, qf INT NULL,
    r16 INT NULL, r32 INT NULL, r64 INT NULL, r128 INT NULL, r256 INT NULL,
    qual INT NULL, qer INT NULL,
    qr4 INT NULL, qr3 INT NULL, qr2 INT NULL, qr1 INT NULL,
    g4l INT NULL, g3l INT NULL, g2l INT NULL, gl INT NULL,
    CONSTRAINT UQ_ranking_calc_main UNIQUE (organization_code, category_code, age_category_code, ranking_category_code, event_type)
);

CREATE TABLE dbo.modification_type (
    modification_type_id   INT PRIMARY KEY,
    modification_type          NVARCHAR(50) NOT NULL
);

CREATE TABLE dbo.reason_type (
    reason_type_id   INT PRIMARY KEY,
    reason_type          NVARCHAR(50) NOT NULL
);

CREATE TABLE dbo.available_ranking_runs (
    available_ranking_runs_id  INT PRIMARY KEY,
    ranking_run_name               NVARCHAR(50) NOT NULL,
    ranking_run_description            NVARCHAR(200) NULL,
    organization_code                      NVARCHAR(10) NOT NULL CONSTRAINT DF_arr_org DEFAULT ('WTT')
);

CREATE TABLE dbo.available_ranking_runs_categories (
    available_ranking_runs_categories_id  INT PRIMARY KEY,
    available_ranking_runs_id                 INT NOT NULL REFERENCES dbo.available_ranking_runs(available_ranking_runs_id),
    category_code                                 NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    run_order                                         INT NOT NULL
);

CREATE TABLE dbo.competitors (
    competitor_id       INT PRIMARY KEY,   -- legacy PlayerID; NOT identity -- supplied by the import feed
    player_name             NVARCHAR(200) NOT NULL,
    dob                         DATE NULL,
    gender                          NVARCHAR(10) NULL,
    country_code                        NVARCHAR(5) NULL,
    nationality_code                        NVARCHAR(5) NULL,
    age_category_code                           NVARCHAR(10) NULL REFERENCES dbo.age_categories(age_category_code),
    is_retired                                      BIT NOT NULL CONSTRAINT DF_competitors_retired DEFAULT (0),
    wtt_eligibility                                     BIT NOT NULL CONSTRAINT DF_competitors_eligibility DEFAULT (1)
);

CREATE TABLE dbo.events (
    event_id               INT PRIMARY KEY,  -- supplied by import feed, not identity
    event_name                 NVARCHAR(300) NOT NULL,
    start_date                     DATE NULL,
    end_date                           DATE NULL,
    event_type_general_code                NVARCHAR(10) NULL,
    event_type_code                            NVARCHAR(10) NULL,
    ranking_year                                   INT NULL,
    ranking_month                                      INT NULL,
    ranking_week                                           INT NULL,
    is_forbidden                                               BIT NOT NULL CONSTRAINT DF_events_forbidden DEFAULT (0)
);

CREATE TABLE dbo.players_doubles (
    doubles_id          INT IDENTITY(1,1) PRIMARY KEY,
    player1_id              INT NOT NULL REFERENCES dbo.competitors(competitor_id),
    player2_id                  INT NOT NULL REFERENCES dbo.competitors(competitor_id),
    sub_event_code                  NVARCHAR(10) NOT NULL,
    age_category_code                   NVARCHAR(10) NULL REFERENCES dbo.age_categories(age_category_code)
    -- KNOWN LEGACY BUG, preserved by design: this column drifts to 'SEN' for youth pairs.
    -- sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking derives the effective age
    -- category from both players' competitors.age_category_code instead of trusting this
    -- column -- see db/procedures/steps/sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking.sql
);

CREATE TABLE dbo.new_events_results (
    new_event_result_id   INT IDENTITY(1,1) PRIMARY KEY,
    event_id                  INT NOT NULL REFERENCES dbo.events(event_id),
    competitor_id                 INT NOT NULL REFERENCES dbo.competitors(competitor_id),
    sub_event_code                    NVARCHAR(10) NOT NULL,
    result_position                       NVARCHAR(10) NOT NULL,
    matches_played                            INT NULL,
    matches_won                                   INT NULL,
    matches_lost                                      INT NULL,
    qualifier                                             BIT NOT NULL CONSTRAINT DF_ner_qualifier DEFAULT (0),
    result_type                                               NVARCHAR(30) NOT NULL CONSTRAINT DF_ner_result_type DEFAULT ('FINAL_RESULT'),
    zero_point_penalty                                            BIT NOT NULL CONSTRAINT DF_ner_zpp DEFAULT (0),
    last_phase_win                                                    BIT NOT NULL CONSTRAINT DF_ner_lpw DEFAULT (0),
    ranking_category_code                                                 NVARCHAR(10) NOT NULL,
    age_category_code                                                         NVARCHAR(10) NOT NULL,
    category_code                                                                 NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    organization_code                                                                 NVARCHAR(10) NOT NULL CONSTRAINT DF_ner_org DEFAULT ('WTT'),
    ranking_points                                                                        DECIMAL(10,2) NULL,
    cross_awarded_from_event_id                                                               INT NULL REFERENCES dbo.events(event_id)
);
CREATE INDEX idx_new_events_results_event ON dbo.new_events_results(event_id);
CREATE INDEX idx_new_events_results_category ON dbo.new_events_results(category_code);

-- new_event_result_id is DELIBERATELY NOT a foreign key: sp_Calculate_Ranking_FinalizeRun
-- deletes consumed new_events_results rows on every successful run, and this audit trail
-- must survive that deletion (same principle as ranking_run_error surviving business writes).
CREATE TABLE dbo.new_events_results_modification_log (
    modification_log_id   INT IDENTITY(1,1) PRIMARY KEY,
    new_event_result_id      INT NOT NULL,   -- NOT a FK -- see comment above
    competitor_id                INT NOT NULL,
    event_id                        INT NOT NULL,
    old_result_position                 NVARCHAR(10) NOT NULL,
    new_result_position                     NVARCHAR(10) NOT NULL,
    old_ranking_points                          DECIMAL(10,2) NULL,
    new_ranking_points                              DECIMAL(10,2) NULL,
    modified_by                                         NVARCHAR(100) NOT NULL,
    modified_at                                             DATETIME2(3) NOT NULL
);
CREATE INDEX idx_ner_mod_log_result ON dbo.new_events_results_modification_log(new_event_result_id);

CREATE TABLE dbo.players_events_results_master (
    player_event_result_id   INT IDENTITY(1,1) PRIMARY KEY,
    competitor_id                 INT NOT NULL REFERENCES dbo.competitors(competitor_id),
    event_id                          INT NOT NULL REFERENCES dbo.events(event_id),
    sub_event_code                        NVARCHAR(10) NOT NULL,
    ranking_category_code                     NVARCHAR(10) NOT NULL,
    result_position                               NVARCHAR(10) NOT NULL,
    ranking_points                                    DECIMAL(10,2) NOT NULL CONSTRAINT DF_perm_points DEFAULT (0),
    ranking_year                                          INT NOT NULL,
    ranking_month                                             INT NOT NULL,
    ranking_week                                                  INT NOT NULL,
    expiry_year                                                       INT NULL,
    expiry_month                                                          INT NULL,
    expiry_week                                                               INT NULL,
    player_best_ranking_result_number                                            INT NOT NULL CONSTRAINT DF_perm_rank DEFAULT (0),
    best_result_no_sen_you                                                            BIT NOT NULL CONSTRAINT DF_perm_best DEFAULT (0),
    active                                                                                 BIT NOT NULL CONSTRAINT DF_perm_active DEFAULT (1),
    zero_point_penalty                                                                         BIT NOT NULL CONSTRAINT DF_perm_zpp DEFAULT (0),
    excluded_due_to_zero_point_penalty                                                             BIT NOT NULL CONSTRAINT DF_perm_zpp_excl DEFAULT (0),
    mandatory_inclusion_for_best_results                                                               BIT NOT NULL CONSTRAINT DF_perm_mand DEFAULT (0),
    age_category_code                                                                                      NVARCHAR(10) NOT NULL,
    category_code                                                                                              NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    organization_code                                                                                              NVARCHAR(10) NOT NULL CONSTRAINT DF_perm_org DEFAULT ('WTT'),
    ranking_run_id_created                                                                                             INT NULL REFERENCES dbo.ranking_run(ranking_run_id)
);
CREATE INDEX idx_perm_competitor ON dbo.players_events_results_master(competitor_id, category_code, ranking_category_code);
CREATE INDEX idx_perm_event ON dbo.players_events_results_master(event_id);
CREATE INDEX idx_perm_active_category ON dbo.players_events_results_master(category_code, active);

CREATE TABLE dbo.players_events_results_master_modified (
    player_modification_id   INT IDENTITY(1,1) PRIMARY KEY,
    competitor_id                 INT NOT NULL REFERENCES dbo.competitors(competitor_id),
    event_id                          INT NOT NULL REFERENCES dbo.events(event_id),
    sub_event_code                        NVARCHAR(10) NOT NULL,
    ranking_category_code                     NVARCHAR(10) NOT NULL,
    age_category_code                             NVARCHAR(10) NULL,
    category_code                                     NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    result_position                                       NVARCHAR(10) NULL,
    ranking_points                                            DECIMAL(10,2) NULL,
    ranking_year INT NULL, ranking_month INT NULL, ranking_week INT NULL,
    expiry_year INT NULL, expiry_month INT NULL, expiry_week INT NULL,
    modified_result_position                                      NVARCHAR(10) NULL,
    modified_ranking_points                                           DECIMAL(10,2) NULL,
    modified_expiry_year                                                  INT NULL,
    modified_expiry_month                                                     INT NULL,
    modified_expiry_week                                                          INT NULL,
    modified_active                                                                   BIT NULL,
    modification_type_id                                                                  INT NOT NULL REFERENCES dbo.modification_type(modification_type_id),
    reason_type_id                                                                              INT NULL REFERENCES dbo.reason_type(reason_type_id),
    reason_description                                                                              NVARCHAR(300) NULL,
    modified_date                                                                                       DATETIME2(3) NOT NULL,
    modified_by                                                                                             NVARCHAR(100) NOT NULL,
    applied                                                                                                     BIT NOT NULL CONSTRAINT DF_permod_applied DEFAULT (0),
    applied_in_ranking_run_id                                                                                       INT NULL REFERENCES dbo.ranking_run(ranking_run_id)
);
CREATE INDEX idx_perm_modified_applied ON dbo.players_events_results_master_modified(category_code, applied);

CREATE TABLE dbo.main_ranking (
    main_ranking_id       INT IDENTITY(1,1) PRIMARY KEY,
    competitor_id              INT NOT NULL REFERENCES dbo.competitors(competitor_id),
    ranking_pos                    INT NULL,
    ranking_points                     DECIMAL(10,2) NOT NULL CONSTRAINT DF_mr_points DEFAULT (0),
    ranking_category                       NVARCHAR(10) NOT NULL,
    ranking_year                               INT NOT NULL,
    ranking_month                                  INT NOT NULL,
    ranking_week                                       INT NOT NULL,
    organization_code                                      NVARCHAR(10) NOT NULL CONSTRAINT DF_mr_org DEFAULT ('WTT'),
    category_code                                              NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    age_category_code                                              NVARCHAR(10) NOT NULL,
    ranking_pos_age_category                                           INT NULL,
    ranking_run_id                                                         INT NOT NULL REFERENCES dbo.ranking_run(ranking_run_id)
);
CREATE INDEX idx_main_ranking_lookup ON dbo.main_ranking(category_code, ranking_year, ranking_month, ranking_week, ranking_category);
CREATE INDEX idx_main_ranking_run ON dbo.main_ranking(ranking_run_id);

CREATE TABLE dbo.schedule (
    schedule_id       INT IDENTITY(1,1) PRIMARY KEY,
    schedule_date         DATE NOT NULL,
    status                    NVARCHAR(20) NOT NULL,
    organization_code            NVARCHAR(10) NOT NULL CONSTRAINT DF_schedule_org DEFAULT ('WTT'),
    category_code                    NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    ranking_year INT NULL, ranking_month INT NULL, ranking_week INT NULL,
    published_date_utc                  DATETIME2(3) NULL
);

CREATE TABLE dbo.ranking_engine_info (
    ranking_info_id       INT IDENTITY(1,1) PRIMARY KEY,
    category_code             NVARCHAR(3) NOT NULL UNIQUE REFERENCES dbo.categories(category_code),
    organization_code             NVARCHAR(10) NOT NULL CONSTRAINT DF_rei_org DEFAULT ('WTT'),
    current_ranking_year              INT NOT NULL,
    current_ranking_month                 INT NOT NULL,
    current_ranking_week                      INT NOT NULL
);

-- Reference tables replacing the two Python constant lists (CONTINENTAL_EVENT_TYPE_CODES,
-- ZPP_EVENT_TYPE_CODES) so step procedures can query them instead of needing a comma-list
-- parameter or a TVP for every call.
CREATE TABLE dbo.continental_event_type_code (
    event_type_general_code   NVARCHAR(10) PRIMARY KEY
);
CREATE TABLE dbo.zpp_event_type_code (
    event_type_code           NVARCHAR(10) PRIMARY KEY
);

-- =====================================================================================
-- C. RBAC SCHEMA (new)
-- =====================================================================================

CREATE TABLE dbo.app_role (
    role_code            NVARCHAR(20) PRIMARY KEY
                              CONSTRAINT CK_app_role_code CHECK (role_code IN ('SUPERADMIN','RANKINGUSER','RANKINGVIEWER')),
    role_description         NVARCHAR(200) NOT NULL
);

CREATE TABLE dbo.app_user (
    app_user_id       INT IDENTITY(1,1) PRIMARY KEY,
    username              NVARCHAR(50) NOT NULL,
    password_hash             NVARCHAR(255) NOT NULL,   -- werkzeug PBKDF2 hash string, never plaintext
    role_code                     NVARCHAR(20) NOT NULL REFERENCES dbo.app_role(role_code),
    is_active                         BIT NOT NULL CONSTRAINT DF_app_user_active DEFAULT (1),
    created_at                            DATETIME2(3) NOT NULL CONSTRAINT DF_app_user_created DEFAULT (SYSUTCDATETIME()),
    updated_at                                DATETIME2(3) NOT NULL CONSTRAINT DF_app_user_updated DEFAULT (SYSUTCDATETIME()),
    last_login_at                                 DATETIME2(3) NULL,
    created_by                                        NVARCHAR(100) NULL,
    CONSTRAINT UQ_app_user_username UNIQUE (username)
);

CREATE TABLE dbo.app_user_audit_log (
    app_user_audit_log_id   INT IDENTITY(1,1) PRIMARY KEY,
    action_type                 NVARCHAR(30) NOT NULL
                                     CONSTRAINT CK_audit_action CHECK (action_type IN
                                     ('CREATE_USER','EDIT_USER','DEACTIVATE_USER','ACTIVATE_USER','DELETE_USER',
                                      'RESET_PASSWORD','ROLE_CHANGE','SELF_PASSWORD_CHANGE','LOGIN_SUCCESS','LOGIN_FAILURE')),
    target_app_user_id              INT NULL REFERENCES dbo.app_user(app_user_id),
    performed_by                        NVARCHAR(100) NOT NULL,
    details                                 NVARCHAR(500) NULL,
    occurred_at                                 DATETIME2(3) NOT NULL CONSTRAINT DF_audit_occurred DEFAULT (SYSUTCDATETIME())
);
CREATE INDEX idx_app_user_audit_target ON dbo.app_user_audit_log(target_app_user_id);
