# Database Object Inventory — WTT Ranking Engine (Azure SQL Prototype)

This document catalogs every database object built for the Azure SQL migration of the WTT
Ranking Engine prototype: every table (`db/schema_mssql.sql`), view (`db/views_mssql.sql`), the
table-valued type and inline function (`db/procedures/types/`), and every stored procedure
(`db/procedures/{steps,master,import,validation,admin}/*.sql`). For each object: its purpose,
its full current SQL, and its correspondence to the **original legacy SQL Server system**
(`C:\vatsan\ranking\RANKINGS2026\SPS\*.sql` for stored procedures, `...\views\*.sql` for views,
and `...\data\*.csv` for table structure, since the legacy system's table DDL was never
exported — only data extracts and the stored procedures that reference its columns).

Three legacy-correspondence categories are used throughout:
- **Direct/near-direct port** — a specific legacy object was read and compared line-by-line;
  concrete differences are listed.
- **NEW — no legacy equivalent** — this object was designed fresh for this architecture (RBAC,
  audit/orchestration views, the master procedures' return-contract helpers, demo reset).
- **Reimplemented with no single legacy source** — the object replaces legacy functionality
  whose implementation was not available to port (e.g. the points-derivation TVF
  `ufnGetEventResultsForRanking_stat`, whose body is not in the exported source) or that was
  added as new functionality during this project (the manual-modifications stage).

Every "changes" bullet list below is grounded in an actual read of the corresponding legacy
`.sql` file — not inferred generically — except where a table has no legacy DDL to read, in
which case the correspondence is reasoned from the matching legacy CSV's columns and from the
general type-mapping conventions documented inline in `db/schema_mssql.sql`.

---

## Part 1 — Tables (`db/schema_mssql.sql`)

The legacy system has no exported `CREATE TABLE` scripts — only CSV data extracts and the ~183
stored procedures that reference legacy table columns. Every table below therefore states its
legacy correspondence as reasoned from the matching CSV columns and/or SP references, plus the
type-mapping rules applied uniformly across the whole schema:

- `INTEGER PRIMARY KEY AUTOINCREMENT`-style legacy identity columns → `INT IDENTITY(1,1)`
- Points columns (legacy `FLOAT`/`REAL`) → **`DECIMAL(10,2)`**, not `FLOAT` — so the
  points-reconciliation validation check (`sp_ValidatePointsPositionMismatch`) can use an
  **exact** `<>` comparison instead of a float-tolerance workaround
- Boolean `INT` flag columns (`IsRetired`, `Active`, `ZeroPointPenalty`, `BestResultNoSENYOU`,
  `CurrentActive`, etc.) → **`BIT`**
- Free-text legacy timestamp columns → `DATETIME2(3)`, computed server-side via
  `SYSUTCDATETIME()` inside the writing procedure, never passed in from the application

### ranking_run (TABLE)

**Purpose**: The audit/orchestration root — one row per Senior or Youth calculation attempt,
tracking its status (`PENDING`/`RUNNING`/`SUCCEEDED`/`FAILED`/`ABORTED_DEPENDENCY`), timing,
trigger source, and which run is currently the published/active one for its period.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `RankingRunsLog` (`dbo_LogTable_RankingRunsLog.csv` / referenced constantly throughout `dbo_sp_Calculate_Ranking.sql`).
- Legacy `Status` is free text (`'PreRequisite Validation'`, `'In Progress'`, `'Draft'`,
  `'Published'`, `'Deleted'`, ad-hoc strings like `'FAILED WITH ERROR-8'`) with no CHECK
  constraint; our `status` is a closed 5-value enum enforced by `CK_ranking_run_status`.
- Legacy has a **separate `'Deleted'`/`'Published'`/`'Draft'` workflow** (a run is marked
  `'Draft'` on completion, then presumably promoted to `'Published'` by a separate,
  unavailable `Sp_Process_ScheduledtoPublish` process); our model has no separate Publish step —
  `status='SUCCEEDED'` is immediately the terminal, visible state (see `vw_RankingResult`).
- Legacy has **no `FAILED`/`ABORTED_DEPENDENCY` distinction** — every failure is just a
  `Status` string mutation (`'FAILED WITH ERROR-3'`, `-4`, `-5`, `-7`, `-8`) with no structured
  failure-reason column; our explicit `ABORTED_DEPENDENCY` status lets the Youth dependency
  guard be distinguished from a genuine calculation failure by any caller/UI.
- `input_snapshot_hash` (a SHA-256 hash of the in-scope `new_events_results` rows, for
  reproducibility) and `superseded_by_run_id` (explicit re-run lineage) are **new** — legacy has
  no equivalent; re-runs work by deleting/re-inserting rows in place.
- Legacy scopes uniqueness by `(CategoryCode, RankingYear, RankingMonth, RankingWeek)` only
  implicitly, via ad-hoc `UPDATE ... SET Status='Deleted' WHERE ... Status NOT IN ('Published')`
  logic at the top of `sp_Calculate_Ranking`; our schema doesn't need this because every run
  keeps its own row permanently (`current_active` tracks the latest one instead of mutating history).

### ranking_run_step (TABLE)

**Purpose**: One row per individual calculation procedure executed within a run — its sequence
number, group label, exact procedure name, status, timing, and row counts. This is the entire
step-by-step audit trail the Run Detail page renders.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: NEW — no legacy equivalent. Legacy tracks run-level progress only via
`RankingRunsLog.RunProgress` (a single free-text column repeatedly overwritten, e.g.
`'Step 2 - DataPreparation'`, then `'Step 3 - InsertRecordsintoMainRanking'`), with no per-step
row, no row-count capture at all, and no per-step timing. Every step's individual outcome —
including which steps actually succeeded before a later one failed — is a genuinely new
capability of this prototype.

### ranking_run_error (TABLE)

**Purpose**: Structured error record for a failed step, linked to both the run and (optionally)
the specific step, carrying the error type, message, and a traceback/diagnostic string.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `DB_Errors` (`dbo_DB_Errors.csv`,
inserted into throughout `dbo_sp_Calculate_Ranking.sql`'s error-handling blocks).
- Legacy columns are `ErrorNumber`/`ErrorState`/`ErrorSeverity`/`ErrorLine`/`ErrorProcedure` (5
  raw SQL Server error-function outputs) plus `UserName`; ours collapses this to
  `error_type`/`error_message`/`traceback`, with `error_type` populated from
  `ERROR_PROCEDURE()` and `traceback` synthesized from `ERROR_LINE()`/`ERROR_STATE()`/
  `ERROR_NUMBER()` (see `sp__RecordStepFailure`) — a deliberately simplified, more readable shape.
- Legacy's `sp_Calculate_Ranking` has **at least one confirmed dead-output-variable bug**: the
  Step 5 (`sp_Rules_RunRulesList`) call passes the *same* output variable
  (`@SpLocalResultMessage`) three times instead of separate result-message/procedure-name/
  error-number variables, so a rule failure during Step 5 never actually updates
  `@SpLocalErrorNo` and the surrounding `IF @SpLocalErrorNo<>0` check silently never fires —
  this DB_Errors row is only ever populated for failures at other steps that don't have this
  bug. Every step failure in this prototype reliably reaches `ranking_run_error` via the shared
  `sp__RecordStepFailure` helper, with no equivalent dead-parameter risk.
- `ranking_run_step_id` linking an error to its specific step is new (legacy only links errors
  to the run via `RankingRunsLogId`).

### ranking_run_metric (TABLE)

**Purpose**: Reserved free-form named-metric slot per step (e.g. future counters not covered by
the fixed rows_inserted/updated/deleted columns), unique per `(step, metric_name)`.

**Current SQL**:
```sql
CREATE TABLE dbo.ranking_run_metric (
    ranking_run_metric_id   INT IDENTITY(1,1) PRIMARY KEY,
    ranking_run_step_id         INT NOT NULL REFERENCES dbo.ranking_run_step(ranking_run_step_id),
    metric_name                     NVARCHAR(100) NOT NULL,
    metric_value                        DECIMAL(18,4) NULL,
    CONSTRAINT UQ_run_metric UNIQUE (ranking_run_step_id, metric_name)
);
```

**Legacy correspondence**: NEW — no legacy equivalent. Not currently written to by any
procedure in this prototype; reserved for future step-level metrics beyond row counts.

### ranking_validation_result (TABLE)

**Purpose**: One row per validation finding (pass or fail) from a `PreRankingValidation` or
`PostRankingValidation` pass, tagged to the run that produced it, retained as permanent history.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `Ranking_Validation_Summary`
(`dbo_Ranking_Validation_Summary.csv`, written by `dbo_SP_Ranking_DataValidation.sql`).
- **Legacy wipes and re-populates this table on every call**
  (`DELETE FROM [Ranking_Validation_Summary] WHERE rankingyear=@RankingYear AND rankingWeek=@RankingWeek AND ...`
  at the top of the SP) — history is lost on the next validation run for the same period. Ours
  is **append-only**: every call adds new rows tagged to a specific `ranking_run_id`, so past
  validation results are never destroyed.
- Legacy keys findings by `(RankingYear, RankingWeek, CategoryCode)`; ours keys by
  `ranking_run_id` directly, which is a stronger, unambiguous key (two different runs can share
  a year/week if one supersedes another).
- Column set matches closely (`CompetitorId`/`EventId`/`TotalPoints`/`MainRankingPoints`), but
  legacy also carries `RankingCategoryCode`/`AgeCategoryCode`/`RankingMonth` columns that this
  simplified 3-check subset doesn't need to populate.

### categories (TABLE)

**Purpose**: The two top-level ranking categories, SEN and YOU, with organization context.

**Current SQL**:
```sql
CREATE TABLE dbo.categories (
    category_code         NVARCHAR(3) PRIMARY KEY CONSTRAINT CK_categories_code CHECK (category_code IN ('SEN','YOU')),
    category_description     NVARCHAR(50) NOT NULL,
    organization_code            NVARCHAR(10) NOT NULL CONSTRAINT DF_categories_org DEFAULT ('WTT')
);
```

**Legacy correspondence**: Direct/near-direct port of legacy `Categories` (`dbo_Categories.csv`).
Same two rows (SEN/Senior, YOU/Youth); legacy has no CHECK constraint restricting values, ours
adds `CK_categories_code` since only these two categories are implemented.

### age_categories (TABLE)

**Purpose**: The age-band reference table (U19/U17/U15/U13/U11/SEN) with inclusive min/max age
bounds, used to derive/display a competitor's age category.

**Current SQL**:
```sql
CREATE TABLE dbo.age_categories (
    age_category_code       NVARCHAR(10) PRIMARY KEY,
    age_category_description   NVARCHAR(50) NULL,
    min_age_inclusive             INT NULL,
    max_age_inclusive                INT NULL,
    category_code                       NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    organization_code                      NVARCHAR(10) NOT NULL CONSTRAINT DF_age_categories_org DEFAULT ('WTT')
);
```

**Legacy correspondence**: Direct/near-direct port of legacy `Age_Categories`
(`dbo_Age_Categories.csv`). The age-bracket boundaries here match the CASE-based derivation seen
live in `dbo_SP_Calculate_Ranking_UpdatePlayersInfoFromTTU.sql` (`Age>17 AND <=19 → 'U19'`,
etc.). Two rows in the legacy CSV carry `OrganizationCode='3'` instead of `'WTT'` for U21 — a
documented legacy data-quality anomaly, intentionally excluded from this reference set.

### ranking_categories (TABLE)

**Purpose**: The 11 event-type ranking categories per top-level category (MS/WS/MD/WD/XD/MDI/
WDI/XDI/MT/WT/XT for SEN, the Boys/Girls/Youth equivalents for YOU) with display order.

**Current SQL**:
```sql
CREATE TABLE dbo.ranking_categories (
    ranking_category_id     INT PRIMARY KEY,
    ranking_category_code       NVARCHAR(10) NOT NULL,
    category_code                  NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    ranking_category_desc              NVARCHAR(100) NULL,
    ranking_order                          INT NULL,
    CONSTRAINT UQ_ranking_categories UNIQUE (ranking_category_code, category_code)
);
```

**Legacy correspondence**: Direct/near-direct port of legacy `RankingCategories`
(`dbo_RankingCategories.csv`) — same 22 rows (11 per category), same IDs/codes/descriptions.

### result_position (TABLE)

**Purpose**: Maps a tournament result code (W/F/SF/QF/R16/.../QR1-4/G2L-G4L etc.) to its round
metadata (phase, ordering, KO vs QUAL phase type, round number) per category.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `OVRResultPositions`
(`dbo_OVRResultPositions.csv`, joined in `dbo_SP_Ranking_DataValidation.sql`'s pre-ranking
"no mapping position" check: `LEFT JOIN [OVRResultPositions] r ON n.categorycode = r.category AND n.resultposition = r.result`).
Column names are reshaped to snake_case equivalents; the 26 rows (13 SEN + 13 YOU) match the
CSV's position/category combinations.

### ranking_calc_main (TABLE)

**Purpose**: The points lookup table — for a given organization/category/age-category/ranking-
category/event-type combination, the points awarded for each of the 19 possible round results
(W, F, SF, ..., QR1-4, G2L-G4L). This is the entire points schedule for the whole system.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `RankingCalcMain_New`
(`dbo_RankingCalcMain_New.csv`, 366 rows, seeded verbatim via `db/seed_ranking_calc_main.py`
from a bundled copy of this exact CSV). Points columns are `INT` here (matching the legacy
CSV's integer point values) rather than `DECIMAL` — the `DECIMAL(10,2)` conversion happens where
points are *computed and stored per result* (`new_events_results.ranking_points`,
`players_events_results_master.ranking_points`), not in this static lookup table. A documented
gap inherited from the source CSV: no Youth-U17 `MD` (mixed doubles) points row exists.

### modification_type (TABLE)

**Purpose**: The 4-value lookup for manual-modification kinds (Points, Position, Insert,
Deactivate) referenced by `players_events_results_master_modified.modification_type_id`.

**Current SQL**:
```sql
CREATE TABLE dbo.modification_type (
    modification_type_id   INT PRIMARY KEY,
    modification_type          NVARCHAR(50) NOT NULL
);
```

**Legacy correspondence**: Direct port of legacy `ModificationType` (`dbo_ModificationType.csv`)
— same 4 rows/IDs, referenced by `dbo_sp_Rules_Set_Weekly_Events_ManualModifications.sql`'s
`ModificationTypeID IN (1,2)` / `=3` / `=4` branches (Points/Position combined update, Insert,
Deactivate respectively).

### reason_type (TABLE)

**Purpose**: The 4-value lookup for why a manual modification was made (Late Cancellation,
Others, Injury, Anti-Doping Sanction).

**Current SQL**:
```sql
CREATE TABLE dbo.reason_type (
    reason_type_id   INT PRIMARY KEY,
    reason_type          NVARCHAR(50) NOT NULL
);
```

**Legacy correspondence**: Direct port of legacy `ReasonType` (referenced by
`PlayersEventsResultsMaster_Modified.ReasonTypeId` in the legacy schema's data extracts) — same
4 rows.

### available_ranking_runs (TABLE)

**Purpose**: The 3 selectable "run" options shown in the Start Calculation UI (Senior, Youth,
Senior+Youth combined).

**Current SQL**:
```sql
CREATE TABLE dbo.available_ranking_runs (
    available_ranking_runs_id  INT PRIMARY KEY,
    ranking_run_name               NVARCHAR(50) NOT NULL,
    ranking_run_description            NVARCHAR(200) NULL,
    organization_code                      NVARCHAR(10) NOT NULL CONSTRAINT DF_arr_org DEFAULT ('WTT')
);
```

**Legacy correspondence**: Direct port of legacy `AvailableRankingRuns`
(`dbo_AvailableRankingRuns.csv`) — same 3 rows/IDs.

### available_ranking_runs_categories (TABLE)

**Purpose**: Junction table mapping each `available_ranking_runs` option to the category
code(s) it triggers, in order (the combined option runs SEN then YOU).

**Current SQL**:
```sql
CREATE TABLE dbo.available_ranking_runs_categories (
    available_ranking_runs_categories_id  INT PRIMARY KEY,
    available_ranking_runs_id                 INT NOT NULL REFERENCES dbo.available_ranking_runs(available_ranking_runs_id),
    category_code                                 NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    run_order                                         INT NOT NULL
);
```

**Legacy correspondence**: Direct port of legacy `AvailableRankingRunsCategories`
(`dbo_AvailableRankingRunsCategories.csv`) — same 4 rows.

### competitors (TABLE)

**Purpose**: The player/pair master record — name, DOB, gender, country, age category,
retirement and WTT-eligibility flags. Both individual players and doubles pairs are rows here
(a doubles pair's `competitor_id` is its `doubles_id`).

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct, heavily trimmed port of legacy `Competitors`
(`dbo_Competitors.csv`). Legacy's `Competitors` (as read live in
`dbo_SP_Calculate_Ranking_UpdatePlayersInfoFromTTU.sql`) carries dozens of additional columns
this prototype doesn't need: `PlayerID`/`FirstName`/`Surname` split fields, `Age` (a stored,
periodically-recomputed derived column — ours has no stored `Age`, it isn't needed by any
current procedure), `UpdateDatetime`/`UpdatedBy`/`InsertUpdateDeleteFlag` (TTU-sync bookkeeping,
irrelevant since there's no live TTU feed), `OrganizationCode`, and Olympic/Team/World-title
eligibility flags (`olympicEligibility`, `TeamEligibility`, `worldTitleEligibility`) that no
ported calculation procedure reads. `wtt_eligibility` is a new, deliberately simple boolean
gate used by `sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking`, standing in for that
richer, unavailable eligibility model.

### events (TABLE)

**Purpose**: The tournament/event master record — name, dates, event-type codes, the
ranking period it belongs to, and a forbidden-event flag.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct, trimmed port of legacy `Events`
(`dbo_Events.csv`) — `EventTypeGeneralCode`/`IsForbidden` are read directly in
`dbo_sp_Calculate_WTT_SEN_Ranking_BestResults.sql`'s continental-cap and forbidden-event
filters. The full legacy `Events` table has many more TTU/tournament-linkage columns (see
`EventTournament*_TTU` in the untouched-table inventory) that no ported procedure needs.

### players_doubles (TABLE)

**Purpose**: A doubles pair's two constituent players and their sub-event/age-category tag.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `Players_Doubles`
(`dbo_Players_Doubles.csv`). The drift bug this column preserves is real and observed live:
`dbo_SP_Calculate_Ranking_UpdatePlayersInfoFromTTU.sql` has a normalization step
(`UPDATE Players_Doubles SET Player1Id = Player2Id, Player2Id = Player1Id WHERE Player1Id > Player2Id`)
that reorders the pair by ID but never re-derives `AgeCategoryCode` from the (possibly swapped)
players — this column can genuinely go stale relative to the two players' own age categories.

### new_events_results (TABLE)

**Purpose**: The raw import staging table — one row per player/event result as freshly
imported, before any calculation run has touched it. This is also where the Manual
Modifications screen edits results (position + recomputed points) before a run begins.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `NewEventsResults`
(`dbo_NewEventsResults.csv`), populated in the legacy system by
`sp_Import_Web_EventsResults`/`SP_Import_Step1..6`. Legacy populates this per-event
(`DELETE FROM NewEventsResults WHERE EventId=@EventId` then re-insert for that one event, called
once per event) with `ranking_points` derived entirely by the unexported TVF
`ufnGetEventResultsForRanking_stat`; this prototype imports a whole CSV file (many events, many
competitors) in one bulk TVP call (`sp_ImportNewEventsResults`) and derives `ranking_points`
itself via `fn_ComputeRankingPoints` (see below) — a reasonable, tested reconstruction of the
same points/round-code logic, not a guaranteed byte-for-byte match to the unseen original.
Legacy also has an `IsImported` flag and excludes `SubEventCode IN ('WT','MT')` (team events) at
import time; this table has no `is_imported` column and no team-event exclusion.

### new_events_results_modification_log (TABLE)

**Purpose**: Full audit trail of every manual edit made to a `new_events_results` row via the
Manual Modifications screen — old/new position, old/new points, who, when.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: NEW — no legacy equivalent. This is the audit table for the
pre-calculation Manual Modifications feature added to this prototype at the user's explicit
request (edit a freshly-imported result's position before calculation starts). The legacy
system has a *different*, mid-calculation manual-modification mechanism instead — see
`players_events_results_master_modified` below.

### players_events_results_master (TABLE)

**Purpose**: The book-of-record for every player-per-event result that has entered a
calculation run: points, active/expiry state, best-result flags, ZPP flags. This is the table
every calculation step (best-results selection, ZPP, ranking positions) reads and writes.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct, trimmed port of legacy `PlayersEventsResultsMaster`
(`dbo_PlayersEventsResultsMaster.csv`) — the busiest table in both systems, read/written by
nearly every legacy calculation SP read for this document. Legacy carries several columns not
ported here because no calculation procedure needs them: `ResultType` (`'FINAL_RESULT'`/
`'MANAULY_MODIFIED'` [sic]), `LastPhaseWin`/`LastPhaseWinWithoutBye`, `IsImported`,
`ResultCategory`, `Qualifier`. `mandatory_inclusion_for_best_results` corresponds to legacy's
implicit "ZPP row" concept but is an explicit named flag here, set by
`sp_Calculate_WTT_Ranking_ZeroPointPenalty` and consumed directly by `sp__ApplyBestResults`'s
`#mandatory_count` computation — legacy has no equivalent named flag; the same effect is
achieved by `ResultPosition='ZPP'` string checks scattered across several SPs.
`idx_perm_active_category` has no legacy analogue (a new index added purely for the hot
`WHERE category_code=... AND active=1` path every step procedure uses; legacy has no visible
indexing strategy in the exported source).

### players_events_results_master_modified (TABLE)

**Purpose**: Staged manual corrections (position/points/expiry/active/insert) applied onto
`players_events_results_master` **during** a calculation run by
`sp_Rules_Set_Weekly_Events_ManualModifications`, keyed by modification type and reason.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `PlayersEventsResultsMaster_Modified`
(`dbo_PlayersEventsResultsMaster_Modified.csv`, read by
`dbo_sp_Rules_Set_Weekly_Events_ManualModifications.sql`). `applied`/`applied_in_ranking_run_id`
are new — legacy tracks "already applied" implicitly by joining to
`RankingRunsLog.Status = 'In Progress'` (i.e. a modification is "pending" simply by virtue of
the run currently being mid-execution, with no persistent applied-flag on the modification row
itself), which means a modification could theoretically be re-applied on a subsequent run for
the same period; the explicit `applied` flag here makes each modification a true one-time
event. **This table currently has no populating UI/route in this prototype** — it is deployed
and its consuming procedure (`sp_Rules_Set_Weekly_Events_ManualModifications`) is wired into
both master procedures, but nothing writes to it yet (the pre-calculation Manual Modifications
screen writes to `new_events_results` instead — a different table/mechanism, see above).

### main_ranking (TABLE)

**Purpose**: The published ranking output for a run — one row per competitor per ranking
category per period, with position, points, and (for Youth) age-category position.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: Direct/near-direct port of legacy `MainRanking`
(`dbo_MainRanking.csv`). The critical difference: **every row here carries a `ranking_run_id`
foreign key** tying it permanently to the exact run that produced it; legacy's `MainRanking` has
no run-linkage column at all — a row's provenance is only inferable by re-joining on
`(RankingYear, RankingMonth, RankingWeek, CategoryCode)` back to whichever `RankingRunsLog` row
happens to match, which is ambiguous across re-runs of the same period. This `ranking_run_id`
column is what makes `vw_RankingResult`'s `status='SUCCEEDED'`-only filter possible at all.

### schedule (TABLE)

**Purpose**: Publish-schedule tracking per category/period.

**Current SQL**:
```sql
CREATE TABLE dbo.schedule (
    schedule_id       INT IDENTITY(1,1) PRIMARY KEY,
    schedule_date         DATE NOT NULL,
    status                    NVARCHAR(20) NOT NULL,
    organization_code            NVARCHAR(10) NOT NULL CONSTRAINT DF_schedule_org DEFAULT ('WTT'),
    category_code                    NVARCHAR(3) NOT NULL REFERENCES dbo.categories(category_code),
    ranking_year INT NULL, ranking_month INT NULL, ranking_week INT NULL,
    published_date_utc                  DATETIME2(3) NULL
);
```

**Legacy correspondence**: Direct/near-direct port of legacy `Schedule` (referenced by
`dbo_sp_API_GetNextScheduleDates.sql` and the `Sp_Process_ScheduledtoPublish` process named in
`docs/legacy_rule_mapping.md`). Present in the schema but **not currently written to or read by
any procedure in this prototype** — the equivalent "record intent, don't auto-fire" scheduling
behavior is implemented instead via `ranking_run.trigger_type='scheduled'` +
`ranking_run.scheduled_for` (see `sp_RankingRun_Schedule`), not this table.

### ranking_engine_info (TABLE)

**Purpose**: One row per category holding the "current" ranking year/month/week pointer,
updated whenever a run succeeds — the anchor the Start Calculation screen defaults to.

**Current SQL**:
```sql
CREATE TABLE dbo.ranking_engine_info (
    ranking_info_id       INT IDENTITY(1,1) PRIMARY KEY,
    category_code             NVARCHAR(3) NOT NULL UNIQUE REFERENCES dbo.categories(category_code),
    organization_code             NVARCHAR(10) NOT NULL CONSTRAINT DF_rei_org DEFAULT ('WTT'),
    current_ranking_year              INT NOT NULL,
    current_ranking_month                 INT NOT NULL,
    current_ranking_week                      INT NOT NULL
);
```

**Legacy correspondence**: Direct port of legacy `RankingEngineInfo`
(`dbo_RankingEngineInfo.csv`), updated identically in both systems at the very end of a
successful run (legacy: `UPDATE [dbo].[RankingEngineInfo] SET [Current_Ranking_Year]=...` inside
`sp_Calculate_Ranking`'s final block; ours: the equivalent update inside
`sp_RankingRun_Finalize`).

### continental_event_type_code (TABLE)

**Purpose**: The list of event-type-general codes considered "continental" for the max-1-
continental-result cap in best-results selection.

**Current SQL**:
```sql
-- Reference tables replacing the two Python constant lists (CONTINENTAL_EVENT_TYPE_CODES,
-- ZPP_EVENT_TYPE_CODES) so step procedures can query them instead of needing a comma-list
-- parameter or a TVP for every call.
CREATE TABLE dbo.continental_event_type_code (
    event_type_general_code   NVARCHAR(10) PRIMARY KEY
);
```

**Legacy correspondence**: Reimplemented with no single legacy source, but same underlying
concept as legacy: `dbo_sp_Calculate_WTT_SEN_Ranking_BestResults.sql` takes this list as a
**comma-separated `@ContinentalEventTypeCodes VARCHAR(MAX)` parameter** (split at query time via
`STRING_SPLIT`), not a table — the caller (originally the dynamic rules engine, via `RulesAlias`
parameter substitution) supplied the literal string. Making it a real reference table here means
the 15 codes are queryable/auditable data instead of a string baked into a rule-alias
configuration row this prototype doesn't otherwise implement.

### zpp_event_type_code (TABLE)

**Purpose**: The list of event-type codes eligible to trigger Zero-Point-Penalty tracking.

**Current SQL**:
```sql
CREATE TABLE dbo.zpp_event_type_code (
    event_type_code           NVARCHAR(10) PRIMARY KEY
);
```

**Legacy correspondence**: Reimplemented with no single legacy source, same relationship to
legacy as `continental_event_type_code` above — legacy's `sp_Calculate_WTT_Ranking_ZeroPointPenalty`
takes `@EventType VARCHAR(MAX)` as a comma-separated string parameter; this table makes the 16
codes real reference data instead.

### app_role (TABLE)

**Purpose**: The fixed 3-role RBAC lookup (SUPERADMIN, RANKINGUSER, RANKINGVIEWER).

**Current SQL**:
```sql
CREATE TABLE dbo.app_role (
    role_code            NVARCHAR(20) PRIMARY KEY
                              CONSTRAINT CK_app_role_code CHECK (role_code IN ('SUPERADMIN','RANKINGUSER','RANKINGVIEWER')),
    role_description         NVARCHAR(200) NOT NULL
);
```

**Legacy correspondence**: NEW — no legacy equivalent. The legacy system's user/permission model
(if any existed beyond raw SQL Server logins) was outside the scope of the reverse-engineering
pass and not present in the exported source; this whole RBAC subsystem was designed fresh for
this migration per the user's explicit request.

### app_user (TABLE)

**Purpose**: Application user accounts — username, PBKDF2 password hash, role, active flag,
timestamps, last login.

**Current SQL**:
```sql
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
```

**Legacy correspondence**: NEW — no legacy equivalent.

### app_user_audit_log (TABLE)

**Purpose**: Full audit trail of every user-management action (create/edit/deactivate/reactivate/
reset-password/role-change/self-password-change) and every login attempt (success or failure).

**Current SQL**:
```sql
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
```

**Legacy correspondence**: NEW — no legacy equivalent. `target_app_user_id` is nullable and not
a hard-cascading reference in practice (a user is only ever deactivated, never hard-deleted, so
this stays resolvable), following the same "audit survives the thing it references" principle
used for `new_events_results_modification_log` and `ranking_run_error`.

---

## Part 2 — Views (`db/views_mssql.sql`)

Every view here drops the SQLite-prototype convention of an `ORDER BY` inside the view
definition (not meaningful in a T-SQL view) — callers add their own `ORDER BY`/`TOP`.

### vw_RankingRunSummary (VIEW)

**Purpose**: One row per run with computed duration and step-succeeded/step-failed counts —
powers the Dashboard's run list.

**Current SQL**:
```sql
CREATE OR ALTER VIEW dbo.vw_RankingRunSummary AS
SELECT
    r.ranking_run_id, r.category_code, r.ranking_year, r.ranking_month, r.ranking_week,
    r.trigger_type, r.scheduled_for, r.status, r.started_at, r.finished_at,
    CASE WHEN r.started_at IS NOT NULL AND r.finished_at IS NOT NULL
         THEN DATEDIFF(SECOND, r.started_at, r.finished_at)
         ELSE NULL END AS duration_seconds,
    r.triggered_by, r.current_active,
    (SELECT COUNT(*) FROM dbo.ranking_run_step s WHERE s.ranking_run_id = r.ranking_run_id) AS total_steps,
    (SELECT COUNT(*) FROM dbo.ranking_run_step s WHERE s.ranking_run_id = r.ranking_run_id AND s.status = 'SUCCEEDED') AS steps_succeeded,
    (SELECT COUNT(*) FROM dbo.ranking_run_step s WHERE s.ranking_run_id = r.ranking_run_id AND s.status = 'FAILED') AS steps_failed
FROM dbo.ranking_run r;
GO
```

**Legacy correspondence**: NEW — no legacy equivalent. Legacy's closest analogue,
`RankingRunsLog`, is a raw table with a single free-text `RunProgress` column and no computed
duration or step-outcome aggregation of any kind — there is no legacy view that summarizes a
run this way.

### vw_RankingRunProgress (VIEW)

**Purpose**: Flat pass-through of `ranking_run_step` for live polling of an in-progress run.

**Current SQL**:
```sql
CREATE OR ALTER VIEW dbo.vw_RankingRunProgress AS
SELECT s.ranking_run_id, s.step_seq, s.step_group, s.step_name, s.status, s.started_at, s.finished_at,
       s.duration_ms, s.rows_inserted, s.rows_updated, s.rows_deleted, s.result_message
FROM dbo.ranking_run_step s;
GO
```

**Legacy correspondence**: NEW — no legacy equivalent (depends entirely on `ranking_run_step`,
itself a new table).

### vw_RankingRunStepAudit (VIEW)

**Purpose**: `ranking_run_step` joined back to its parent `ranking_run` — the exact query
powering the Run Detail page's step-by-step trace table.

**Current SQL**:
```sql
CREATE OR ALTER VIEW dbo.vw_RankingRunStepAudit AS
SELECT r.ranking_run_id, r.category_code, r.ranking_year, r.ranking_month, r.ranking_week,
       r.status AS run_status, s.step_seq, s.step_group, s.step_name, s.status AS step_status,
       s.started_at, s.finished_at, s.duration_ms, s.rows_inserted, s.rows_updated, s.rows_deleted, s.result_message
FROM dbo.ranking_run_step s
JOIN dbo.ranking_run r ON r.ranking_run_id = s.ranking_run_id;
GO
```

**Legacy correspondence**: NEW — no legacy equivalent.

### vw_RankingRunErrors (VIEW)

**Purpose**: Every recorded error, joined to its run and (if known) its specific step name —
what the Run Detail page renders under "Errors".

**Current SQL**:
```sql
CREATE OR ALTER VIEW dbo.vw_RankingRunErrors AS
SELECT e.ranking_run_error_id, e.ranking_run_id, r.category_code, r.ranking_year, r.ranking_month, r.ranking_week,
       s.step_seq, s.step_name, e.error_type, e.error_message, e.traceback, e.occurred_at
FROM dbo.ranking_run_error e
JOIN dbo.ranking_run r ON r.ranking_run_id = e.ranking_run_id
LEFT JOIN dbo.ranking_run_step s ON s.ranking_run_step_id = e.ranking_run_step_id;
GO
```

**Legacy correspondence**: NEW — no legacy equivalent (legacy's `DB_Errors` table has no
purpose-built reporting view over it in the exported source).

### vw_RankingResult (VIEW)

**Purpose**: The published ranking output — every `main_ranking` row belonging to a
`SUCCEEDED` run, joined to the competitor's name/country. This is what the Rankings page and
the public-facing ranking output are built from.

**Current SQL**:
```sql
-- CRITICAL, preserved exactly: only rows from a run whose status='SUCCEEDED' are ever visible
-- here. This is how a FAILED run's partial writes are never surfaced as published ranking
-- output, enforced at the query layer, not via whole-run rollback.
CREATE OR ALTER VIEW dbo.vw_RankingResult AS
SELECT mr.ranking_year, mr.ranking_month, mr.ranking_week, mr.category_code, mr.ranking_category,
       mr.ranking_pos, mr.ranking_pos_age_category, mr.ranking_points, mr.age_category_code,
       c.competitor_id, c.player_name, c.country_code, mr.ranking_run_id
FROM dbo.main_ranking mr
JOIN dbo.competitors c ON c.competitor_id = mr.competitor_id
JOIN dbo.ranking_run rr ON rr.ranking_run_id = mr.ranking_run_id AND rr.status = 'SUCCEEDED';
GO
```

**Legacy correspondence**: Direct/near-direct conceptual port of legacy `vw_MainRanking`
(`dbo_vw_MainRanking.sql`) — the closest legacy analogue for "published ranking output",
compared against a second candidate, `vw_WTT_PlayerRankingPosition`, which was judged a poorer
match (see below).
- Legacy's `vw_MainRanking` is **far more elaborate**: it distinguishes `Status='Published'` vs
  `Status='Draft'` rows via a `RankedLog` CTE (Draft rows are only surfaced for the single
  latest year/week, Published rows for every week), and computes a full **week-over-week
  comparison** for every competitor — their previous appearance's position/points and the
  position/points *delta* (`PosDifferenceCurrentMinusPrevious`,
  `PointsDifferenceCurrentMinusPrevious`), via a `RankedPrevious` CTE that finds each
  competitor's last prior appearance regardless of how long ago.
- `vw_RankingResult` implements **none of that** — it is deliberately minimal: `status='SUCCEEDED'`
  is the only run-status filter (no Draft/Published two-tier workflow exists in this prototype's
  run-status model at all), and there is no previous-week comparison logic of any kind.
- The alternative candidate `vw_WTT_PlayerRankingPosition` (`dbo_vw_WTT_PlayerRankingPosition.sql`)
  is a *different, richer* shape again — it depends on several UDFs never exported to this
  project (`ufnrule_CalculatedColumn_WTT_PlayersRanking_TotalMatchesCountedforRanking`,
  `..._TotalEventsCountedforRanking`, `..._BestResultinEventTypeOrCategory`,
  `ufnrule_CalculatedColumn_PlayersRanking_CurrentRankingPosition`) and filters on
  `RankingLog.Status='In Progress'` (a *draft-in-progress* ranking view, not a published-output
  view) — its purpose is closer to the internal working view
  `sp_Calculate_WTT_Ranking_RankingPositions` reads from (see that procedure's notes) than to
  what `vw_RankingResult` is for.

### vw_NewEventsResultsModificationLog (VIEW)

**Purpose**: Human-readable feed of manual-modification history — player name, country, event
name, old/new position and points, who and when — shown on the Manual Modifications screen.

**Current SQL**:
```sql
CREATE OR ALTER VIEW dbo.vw_NewEventsResultsModificationLog AS
SELECT l.modification_log_id, l.new_event_result_id, c.player_name, c.country_code, e.event_name,
       l.old_result_position, l.new_result_position, l.old_ranking_points, l.new_ranking_points,
       l.modified_by, l.modified_at
FROM dbo.new_events_results_modification_log l
JOIN dbo.competitors c ON c.competitor_id = l.competitor_id
JOIN dbo.events e ON e.event_id = l.event_id;
GO
```

**Legacy correspondence**: NEW — no legacy equivalent (both the underlying table and this
reporting view were built fresh for the Manual Modifications feature added to this prototype).

### vw_RankingCalculationTrace (VIEW)

**Purpose**: A full forensic trace of every `players_events_results_master` row for a
competitor/event — position, points, all the best-results/ZPP/expiry flags together — used for
debugging why a specific result did or didn't count.

**Current SQL**:
```sql
CREATE OR ALTER VIEW dbo.vw_RankingCalculationTrace AS
SELECT p.competitor_id, c.player_name, p.event_id, ev.event_name, p.ranking_category_code, p.result_position,
       p.ranking_points, p.best_result_no_sen_you, p.player_best_ranking_result_number, p.zero_point_penalty,
       p.excluded_due_to_zero_point_penalty, p.active, p.expiry_year, p.expiry_month, p.expiry_week, p.ranking_run_id_created
FROM dbo.players_events_results_master p
JOIN dbo.competitors c ON c.competitor_id = p.competitor_id
JOIN dbo.events ev ON ev.event_id = p.event_id;
GO
```

**Legacy correspondence**: NEW — no legacy equivalent as a named view, though its purpose
mirrors the many ad-hoc, commented-out troubleshooting `SELECT` statements scattered throughout
the legacy stored procedures (e.g. `--select '[sp_Calculate_Ranking_Step3_...]',* from PlayersEventsResultsMaster where eventid =2603`
in `dbo_sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking.sql`) — this view formalizes
that same "inspect one player/event's full calculation state" need as a permanent, always-
available object instead of a developer's inline debug query.

---

## Part 3 — Table Type

### NewEventsResultTVP (TABLE TYPE)

**Purpose**: A table-valued parameter type shaping one bulk import call's worth of parsed CSV
rows, so `sp_ImportNewEventsResults` can accept an entire result file in a single round trip and
a single server-side transaction, regardless of file size.

**Current SQL**:
```sql
-- Table type for bulk-importing a parsed result CSV in one round trip (see
-- db/procedures/import/sp_ImportNewEventsResults.sql and importer/load_new_events_results.py).
-- NOTE: table types cannot be ALTERed and cannot be dropped while any procedure references
-- them as a parameter type. On a from-scratch deploy (the normal case -- see db/deploy_db.py)
-- this CREATE runs once against an empty database. If you need to change this type's shape
-- later, drop dbo.sp_ImportNewEventsResults first, then this type, then redeploy both.
CREATE TYPE dbo.NewEventsResultTVP AS TABLE (
    event_id INT NOT NULL, event_name NVARCHAR(300) NOT NULL,
    event_type_general_code NVARCHAR(10) NOT NULL, event_type_code NVARCHAR(10) NULL,
    ranking_year INT NOT NULL, ranking_month INT NOT NULL, ranking_week INT NOT NULL,
    competitor_id INT NOT NULL, player_name NVARCHAR(200) NOT NULL, dob DATE NULL, gender NVARCHAR(10) NULL,
    country_code NVARCHAR(5) NULL, age_category_code NVARCHAR(10) NOT NULL, is_retired BIT NOT NULL DEFAULT 0,
    sub_event_code NVARCHAR(10) NOT NULL, ranking_category_code NVARCHAR(10) NOT NULL, category_code NVARCHAR(3) NOT NULL,
    result_position NVARCHAR(10) NOT NULL, matches_played INT NULL, matches_won INT NULL, matches_lost INT NULL,
    qualifier BIT NOT NULL DEFAULT 0, zero_point_penalty BIT NOT NULL DEFAULT 0
);
GO
```

**Legacy correspondence**: NEW — no legacy equivalent. The legacy import pipeline
(`SP_Import_Step1..6`, `sp_Import_Web_EventsResults`) is driven **per event** (one `@EventId` at
a time, called once per event from an external OVR-export process), with no bulk multi-event/
multi-competitor TVP mechanism anywhere in the exported source. This type exists purely to
support this prototype's whole-CSV-at-once import model.

## Part 4 — Inline Table-Valued Function

### fn_ComputeRankingPoints (FUNCTION)

**Purpose**: Given a category/age-category/ranking-category/event-type/result-position/ZPP-flag
combination, returns the points a result earns by unpivoting `ranking_calc_main`'s 19 round-
point columns and matching the one that corresponds to the result position. Used by both the
bulk importer and the Manual Modifications recompute-on-save path.

**Current SQL**:
```sql
-- Port of importer/load_new_events_results.py::compute_points(). Inline table-valued function
-- (inlined into the query plan, not a per-row scalar UDF): unpivots ranking_calc_main's 19
-- round columns via CROSS APPLY VALUES. Returns zero rows when zero_point_penalty=1, or no
-- matching ranking_calc_main row, or an unrecognized result_position -- callers always
-- ISNULL(...,0) the result, exactly as compute_points() does.
CREATE OR ALTER FUNCTION dbo.fn_ComputeRankingPoints
(
    @category_code NVARCHAR(3), @age_category_code NVARCHAR(10), @ranking_category_code NVARCHAR(10),
    @event_type_general_code NVARCHAR(10), @result_position NVARCHAR(10), @zero_point_penalty BIT
)
RETURNS TABLE
AS
RETURN
(
    SELECT TOP 1 CAST(pts.points AS DECIMAL(10,2)) AS ranking_points
    FROM dbo.ranking_calc_main rcm
    CROSS APPLY (VALUES
        ('W', rcm.w), ('F', rcm.f), ('SF', rcm.sf), ('QF', rcm.qf),
        ('R16', rcm.r16), ('R32', rcm.r32), ('R64', rcm.r64), ('R128', rcm.r128), ('R256', rcm.r256),
        ('QUAL', rcm.qual), ('QER', rcm.qer),
        ('QR4', rcm.qr4), ('QR3', rcm.qr3), ('QR2', rcm.qr2), ('QR1', rcm.qr1),
        ('G4L', rcm.g4l), ('G3L', rcm.g3l), ('G2L', rcm.g2l), ('GL', rcm.gl)
    ) AS pts(code, points)
    WHERE rcm.category_code = @category_code AND rcm.age_category_code = @age_category_code
      AND rcm.ranking_category_code = @ranking_category_code AND rcm.event_type = @event_type_general_code
      AND pts.code = UPPER(@result_position) AND @zero_point_penalty = 0
);
GO
```

**Legacy correspondence**: Reimplemented with no single legacy source. Legacy's points/position
derivation for a fresh import lives entirely inside `ufnGetEventResultsForRanking_stat` (called
as `[dbo].ufnGetEventResultsForRanking_stat(@EventId, @OrganizationCode, @CategoryCode)` from
`sp_Import_Web_EventsResults`) — a table-valued function whose **body is not present anywhere in
the exported legacy source**, only this one calling signature. This function is therefore not a
port at all but an independent, from-scratch reconstruction: given the two reference tables that
*are* fully documented (`result_position` mapping a position to a round, `ranking_calc_main`
mapping a round to points by category/age-category/ranking-category/event-type), it looks up
points directly. This is a reasonable, tested reconstruction — every fixture in `sample_data/`
exercises it — but it is explicitly **not** a guaranteed byte-for-byte match to whatever
additional logic the unseen legacy TVF might contain (e.g. it might have handled retired
players, forbidden events, or other edge cases invisibly folded into its unexported body).

---

## Part 5 — Stored Procedures: `db/procedures/steps/`

These are the individual calculation steps `EXEC`'d in a fixed sequence by the master
procedures (Part 6).

### SP_Calculate_Ranking_UpdatePlayersInfoFromTTU (STORED PROCEDURE)

**Purpose**: Step 1 of both master procedures. In the legacy system this syncs player
demographic/eligibility data from a live TTU (ITTF) data feed before every calculation; this
prototype has no such feed, so it is a documented stub that only reports the current
`competitors` row count.

**Current SQL**:
```sql
-- Port of SP_Calculate_Ranking_UpdatePlayersInfoFromTTU (documented stub -- no live TTU feed
-- in this prototype; simply reports the current competitors table size).
CREATE OR ALTER PROCEDURE dbo.SP_Calculate_Ranking_UpdatePlayersInfoFromTTU
    @organization_code NVARCHAR(10) = 'WTT', @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @cnt INT = (SELECT COUNT(*) FROM dbo.competitors);
    SET @result_message = CONCAT('stub: no live TTU feed in prototype; ', @cnt, ' competitor(s) already on file');
END
GO
```

**Legacy correspondence**: Direct read of legacy `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU`
confirms this is **not** a no-op in the legacy system, contrary to what might be assumed from its
"stub" role here — it is a substantial procedure that:
- Pulls from live TTU cache tables (`Cached_Individuals`, `Cached_Profiles`,
  `Cached_Organization`, `Cached_Individuals_Translation`, `Cached_Countries`,
  `Cached_Individual_Eligibility`) filtered to rows updated since the last global sync
  timestamp, and bulk-`UPDATE`s `Competitors` with fresh name/DOB/gender/country/nationality/
  eligibility/retirement data.
- On the year's first ranking week (`@rankingweek = 1`) only, additionally recomputes every
  competitor's `Age` and derives `AgeCategoryCode` via a hardcoded age-bracket `CASE` expression
  identical in shape to this project's `age_categories` table's bounds, **including the doubles-
  pair age-category derivation this project's Step 3 also has to handle** — legacy re-derives it
  here too (`WHEN c1.AgeCategoryCode='SEN' OR c2.AgeCategoryCode='SEN' THEN 'SEN' ... ELSE the
  older bracket wins`), then separately normalizes `Players_Doubles.Player1Id`/`Player2Id`
  ordering (`WHERE Player1Id > Player2Id`) without re-deriving `AgeCategoryCode` afterward —
  this is the exact mechanism that produces the drifted `'SEN'` value on `players_doubles`
  described elsewhere in this document.
- This prototype has **no live TTU feed to sync from at all** — every one of these behaviors
  is out of scope by design, documented as a known limitation, not silently dropped.

### sp_Calculate_Ranking_Step2_DataPreparationforNewRun (STORED PROCEDURE)

**Purpose**: Step 2 — clears expired/superseded `players_events_results_master` rows for the
category and period, resets best-result bookkeeping flags, deletes any pre-existing
`main_ranking` rows for the exact period, and inserts every not-yet-seen row from
`new_events_results` into `players_events_results_master` as the fresh working set for this run.

**Current SQL**:
```sql
-- Port of engine/procedures/step2.py::sp_Calculate_Ranking_Step2_DataPreparationforNewRun.
-- Defensive check (not present in the legacy SP -- a documented improvement, ported as-is
-- from the SQLite prototype): reject unrecognized ranking_category_code before it enters
-- the book of record.
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_Ranking_Step2_DataPreparationforNewRun
    @category_code NVARCHAR(3), @year INT, @month INT, @week INT, @run_id INT,
    @rows_inserted INT OUTPUT, @rows_updated INT OUTPUT, @rows_deleted INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM dbo.new_events_results n
        WHERE n.category_code = @category_code
          AND NOT EXISTS (SELECT 1 FROM dbo.ranking_categories rc
                           WHERE rc.category_code = n.category_code AND rc.ranking_category_code = n.ranking_category_code)
    )
    BEGIN
        DECLARE @bad NVARCHAR(400) = (
            SELECT STRING_AGG(x.ranking_category_code, ', ') FROM (
                SELECT DISTINCT n.ranking_category_code FROM dbo.new_events_results n
                WHERE n.category_code = @category_code
                  AND NOT EXISTS (SELECT 1 FROM dbo.ranking_categories rc
                                  WHERE rc.category_code = n.category_code AND rc.ranking_category_code = n.ranking_category_code)
            ) x
        );
        DECLARE @errmsg NVARCHAR(400) = CONCAT(
            'new_events_results contains unrecognized ranking_category_code(s) for category ', @category_code,
            ': ', @bad, '. Fix the import data before re-running the calculation.');
        THROW 51100, @errmsg, 1;
    END

    BEGIN TRAN;
    BEGIN TRY
        DELETE FROM dbo.main_ranking
        WHERE category_code = @category_code AND ranking_year = @year AND ranking_month = @month AND ranking_week = @week;
        SET @rows_deleted = @@ROWCOUNT;

        UPDATE dbo.players_events_results_master
        SET player_best_ranking_result_number = 0, best_result_no_sen_you = 0, excluded_due_to_zero_point_penalty = 0
        WHERE category_code = @category_code AND active = 1;
        SET @rows_updated = @@ROWCOUNT;

        INSERT INTO dbo.players_events_results_master
            (competitor_id, event_id, sub_event_code, ranking_category_code, result_position, ranking_points,
             ranking_year, ranking_month, ranking_week, expiry_year, expiry_month, expiry_week, active,
             zero_point_penalty, age_category_code, category_code, organization_code, ranking_run_id_created)
        SELECT
            n.competitor_id, n.event_id, n.sub_event_code, n.ranking_category_code, n.result_position,
            ISNULL(n.ranking_points, 0), @year, @month, @week, @year + 1, @month, @week,
            1, n.zero_point_penalty, n.age_category_code, n.category_code, n.organization_code, @run_id
        FROM dbo.new_events_results n
        WHERE n.category_code = @category_code
          AND NOT EXISTS (
              SELECT 1 FROM dbo.players_events_results_master p
              WHERE p.competitor_id = n.competitor_id AND p.event_id = n.event_id
                AND p.ranking_category_code = n.ranking_category_code AND p.category_code = n.category_code
          );
        SET @rows_inserted = @@ROWCOUNT;

        COMMIT TRAN;
        SET @result_message = CONCAT('deleted=', @rows_deleted, ' reset=', @rows_updated, ' inserted=', @rows_inserted);
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN;
        THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct/near-direct port of legacy
`sp_Calculate_Ranking_Step2_DataPreparationforNewRun`.
- **New defensive check added**: the `ranking_categories` existence check and `THROW 51100` at
  the top has no legacy equivalent at all — legacy inserts whatever `ranking_category_code`
  arrives in `NewEventsResults` without validation, which is precisely what the
  `calculation_failure` sample fixture (an unrecognized `'ZZ'` code) demonstrates failing safely
  here but would have silently entered the legacy book of record.
  and it insert Import feed with no defensive check.
- Legacy additionally deletes any ZPP row already expiring this exact week
  (`WHERE expiryyear=@RankingYear AND expiryweek=@RankingWeek AND ResultPosition='ZPP'`) and any
  row whose `EventId` is about to be re-imported this run, **before** resetting best-result
  flags — this prototype's single `UPDATE ... SET player_best_ranking_result_number=0, ...`
  covers the reset but does not replicate the pre-emptive ZPP/re-import row deletion (expiry is
  instead handled uniformly later, by `sp_Rules_UpdateEventsResultExpiry`).
  it also does not the hard-coded `WHEN (newEve.eventid = 3409)` one-off expiry-week override
  present in legacy — that was a documented one-time data fix, not live business logic, and is
  intentionally not ported.
- Legacy's expiry-year assignment is always `@RankingYear + 1` for every result regardless of
  event type (the Olympic-specific `+4`-year variant is commented out/dead in the legacy source)
  — this port matches that exact `@year + 1` behavior.
- Legacy re-derives `Players_Doubles.AgeCategoryCode` from the paired competitors' own age
  categories at the very end of this same procedure
  (`UPDATE Players_Doubles SET AgeCategoryCode = c.AgeCategoryCode ... WHERE ISNULL(...)<>ISNULL(...)`)
  — a second place (besides `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU`) where the drift bug
  is partially self-healed in legacy; this prototype instead derives the effective age category
  at read-time inside Step 3, leaving `players_doubles.age_category_code` itself untouched.

### sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking (STORED PROCEDURE)

**Purpose**: Step 3 — seeds `main_ranking` with one placeholder row (0 points, no position yet)
per competitor/ranking-category pairing that has any active result on file for the period,
deriving the correct age category for doubles pairs along the way.

**Current SQL**:
```sql
-- Port of engine/procedures/step3.py::sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking.
-- Fully set-based doubles age-category-derivation fix (no cursor): a CTE with OUTER APPLY +
-- a VALUES-based priority table picks the most-restrictive (youngest) age category from both
-- players of a doubles pair, instead of trusting players_doubles.age_category_code (which
-- drifts to 'SEN' for youth pairs -- the documented legacy bug).
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking
    @category_code NVARCHAR(3), @year INT, @month INT, @week INT, @run_id INT,
    @rows_inserted INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        ;WITH candidates AS (
            SELECT DISTINCT p.competitor_id, p.ranking_category_code, c.age_category_code AS stored_age_category
            FROM dbo.players_events_results_master p
            JOIN dbo.competitors c ON c.competitor_id = p.competitor_id
            WHERE p.category_code = @category_code AND p.active = 1
              AND c.is_retired = 0 AND c.wtt_eligibility = 1
        ),
        doubles_pair AS (
            SELECT cand.competitor_id, cand.ranking_category_code, cand.stored_age_category, pd.player1_id, pd.player2_id
            FROM candidates cand
            OUTER APPLY (
                SELECT TOP 1 player1_id, player2_id FROM dbo.players_doubles pd
                WHERE pd.player1_id = cand.competitor_id OR pd.player2_id = cand.competitor_id
                ORDER BY pd.doubles_id
            ) pd
            WHERE cand.ranking_category_code IN ('MD','WD','XD','MDI','WDI','XDI')
        ),
        pair_ages AS (
            SELECT dp.competitor_id, dp.ranking_category_code, dp.stored_age_category,
                   c1.age_category_code AS age1, c2.age_category_code AS age2
            FROM doubles_pair dp
            LEFT JOIN dbo.competitors c1 ON c1.competitor_id = dp.player1_id
            LEFT JOIN dbo.competitors c2 ON c2.competitor_id = dp.player2_id
        ),
        priority(rank_no, code) AS ( SELECT * FROM (VALUES (1,'U11'),(2,'U13'),(3,'U15'),(4,'U17'),(5,'U19'),(6,'SEN')) v(rank_no,code) ),
        effective AS (
            SELECT pa.competitor_id, pa.ranking_category_code,
                   COALESCE(
                       (SELECT TOP 1 pr.code FROM priority pr WHERE pr.code IN (pa.age1, pa.age2) ORDER BY pr.rank_no),
                       pa.stored_age_category
                   ) AS effective_age_category
            FROM pair_ages pa
        )
        INSERT INTO dbo.main_ranking
            (competitor_id, ranking_pos, ranking_points, ranking_category, ranking_year, ranking_month, ranking_week,
             category_code, age_category_code, ranking_run_id)
        SELECT
            cand.competitor_id, NULL, 0, cand.ranking_category_code, @year, @month, @week, @category_code,
            COALESCE(eff.effective_age_category, cand.stored_age_category, @category_code), @run_id
        FROM candidates cand
        LEFT JOIN effective eff ON eff.competitor_id = cand.competitor_id AND eff.ranking_category_code = cand.ranking_category_code;

        SET @rows_inserted = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('seeded ', @rows_inserted, ' main_ranking placeholder rows');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct/near-direct port of legacy
`sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking`, with one significant, deliberate
behavioral fix beyond just the age-category *label*.
- Legacy's own age-category handling here is a **display-time simplification**, not the drift
  fix: it just selects `Doubles.AgeCategoryCode` (the raw, potentially-drifted
  `players_doubles` column) straight into `MainRanking.AgeCategoryCode` for doubles rows — no
  derivation logic at all in this procedure. (The partial self-heal happens earlier, either in
  `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU` at week 1, or at the end of
  `sp_Calculate_Ranking_Step2_DataPreparationforNewRun` — see those entries.)
- **More importantly, legacy's doubles *inclusion* filter itself depends on the drifted column**:
  `(@CategoryCode = 'YOU' AND Doubles.AgeCategoryCode IS NOT NULL AND Doubles.AgeCategoryCode <> 'SEN')`
  — if the pair's stored `AgeCategoryCode` had drifted to `'SEN'`, the pair is **excluded from
  Youth main_ranking seeding entirely**, not just mislabeled. This is a real correctness bug
  beyond a cosmetic label issue: a genuinely youth doubles pair could be silently dropped from
  the Youth ranking. This prototype's `candidates` CTE has no such gate — it includes every
  competitor with any active Step-2-seeded result for the category, and only ever uses the
  effective-age-category derivation to choose the *label*, never to decide inclusion — so the
  same drift can no longer cause a valid pair to disappear from the ranking.
  This is exercised directly by the `youth_happy_path` sample fixture and its
  `test_youth_happy_path_end_to_end` assertion.
- Legacy uses two `INSERT` blocks (Singles, then Doubles) into a `#StageMainRanking` temp table
  followed by a `TABLOCK`-hinted bulk insert for performance; this port does the equivalent work
  as one CTE-driven `INSERT ... SELECT` without a staging temp table or table lock hint (the
  row volumes in this prototype don't warrant it).

### sp_Rules_Set_Weekly_Events_ManualModifications (STORED PROCEDURE)

**Purpose**: Applies any pending staged corrections from `players_events_results_master_modified`
onto `players_events_results_master` mid-calculation, then marks them applied.

**Current SQL**:
```sql
-- Port of engine/procedures/manual_modifications.py. Applies operator-staged corrections
-- from players_events_results_master_modified onto players_events_results_master via a
-- set-based correlated UPDATE...FROM (the Python original looped per-row only because SQLite
-- makes multi-table UPDATE joins awkward, not because the logic is inherently row-by-row).
CREATE OR ALTER PROCEDURE dbo.sp_Rules_Set_Weekly_Events_ManualModifications
    @category_code NVARCHAR(3), @run_id INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @pending_count INT;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE p
        SET result_position = COALESCE(m.modified_result_position, p.result_position),
            ranking_points   = COALESCE(m.modified_ranking_points, p.ranking_points),
            expiry_year      = COALESCE(m.modified_expiry_year, p.expiry_year),
            expiry_month     = COALESCE(m.modified_expiry_month, p.expiry_month),
            expiry_week      = COALESCE(m.modified_expiry_week, p.expiry_week),
            active           = COALESCE(m.modified_active, p.active)
        FROM dbo.players_events_results_master p
        JOIN dbo.players_events_results_master_modified m
          ON m.competitor_id = p.competitor_id AND m.event_id = p.event_id
         AND m.ranking_category_code = p.ranking_category_code AND m.category_code = p.category_code
        WHERE m.category_code = @category_code AND m.applied = 0;
        SET @rows_updated = @@ROWCOUNT;

        UPDATE dbo.players_events_results_master_modified
        SET applied = 1, applied_in_ranking_run_id = @run_id
        WHERE category_code = @category_code AND applied = 0;
        SET @pending_count = @@ROWCOUNT;

        COMMIT TRAN;
        SET @result_message = CONCAT('applied ', @pending_count, ' manual modification(s), ', @rows_updated, ' row(s) updated');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct/near-direct port of legacy
`sp_Rules_Set_Weekly_Events_ManualModifications`, with one confirmed functional gap.
- Legacy runs **four separate statements** keyed on `ModificationTypeID`: an `UPDATE` for types
  1+2 (points/position, combined via `COALESCE`), a second `UPDATE` for type 4 (deactivate,
  `Active = Modified_Active`), a `DELETE` + `INSERT` pair for type 3 (**insert a brand-new
  result row** via manual modification). **This port's single `UPDATE` covers types 1/2/4
  (points, position, expiry, active) but does not implement the type-3 insert/delete branch at
  all** — inserting a wholly new result via manual modification is a legacy capability with no
  current equivalent here. This is a genuine scope gap, not a hidden bug: `modification_type`
  row `3` ('Insert') exists in the reference data but nothing in this procedure branches on it.
- Legacy gates every statement on `RankingRunsLog.STATUS = 'In Progress'` (a join to the
  currently-executing run row) and excludes rows already carrying `ResultPosition='ZPP'`; this
  port instead gates on the modification row's own `applied = 0` flag (idempotent — a
  modification can never be re-applied) and has no explicit ZPP exclusion, since ZPP rows are
  seeded later in the sequence (Step 7, best-results) and don't exist yet at this point in this
  prototype's step ordering.
- This procedure and its underlying table (`players_events_results_master_modified`) are
  deployed and wired into both master procedures identically to legacy, but — as noted under
  that table's entry — **nothing in this prototype's UI currently writes to it**, so in practice
  it is a dormant no-op every run (0 rows updated) until a populating route is added.

### sp_Rules_UpdateEventsResultExpiry (STORED PROCEDURE)

**Purpose**: Deactivates any `players_events_results_master` row whose expiry period has passed
relative to the ranking period actually being calculated.

**Current SQL**:
```sql
-- Port of engine/procedures/expiry.py -- both expiry procedures.
CREATE OR ALTER PROCEDURE dbo.sp_Rules_UpdateEventsResultExpiry
    @category_code NVARCHAR(3), @year INT, @week INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.players_events_results_master
        SET active = 0
        WHERE category_code = @category_code AND active = 1
          AND expiry_year IS NOT NULL AND expiry_week IS NOT NULL
          AND (expiry_year < @year OR (expiry_year = @year AND expiry_week <= @week));
        SET @rows_updated = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('expired ', @rows_updated, ' result(s)');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct/near-direct port of legacy `sp_Rules_UpdateEventsResultExpiry`,
with one deliberate, significant correction to how the comparison anchor is determined.
- **Legacy takes no year/week parameter at all.** It self-derives the "current" anchor with
  `SELECT TOP 1 @ExpiryYear=rankingYear, @ExpiryWeek=rankingWeek FROM playerseventsresultsmaster
  WHERE Active=1 ORDER BY rankingyear DESC, rankingweek DESC` — critically, **with no
  `CategoryCode` filter**, so the anchor is the single most-recent active row across *both* SEN
  and YOU combined. If the two categories' calculation periods ever diverge (e.g. Youth is a
  week behind Senior), this can compute the wrong anchor for whichever category is being
  expired. This port takes `@year`/`@week` as explicit parameters passed down from the actual
  run being calculated (`sp_Calculate_Ranking_SEN`/`_YOU`'s own `@ranking_year`/`@ranking_week`),
  eliminating this cross-category ambiguity entirely.
- Added an explicit `expiry_year IS NOT NULL AND expiry_week IS NOT NULL` guard before the
  comparison (defensive; legacy relies on implicit NULL-comparison semantics to the same effect).

### sp_Rules_UpdateOlympicResultExpiry (STORED PROCEDURE)

**Purpose**: Ensures only the single most recent Olympic Games event's results remain active,
deactivating any older Olympic Games result.

**Current SQL**:
```sql
-- sp_Rules_UpdateOlympicResultExpiry has no category/organization parameter in the legacy SP
-- either -- it applies globally across categories, preserved here.
CREATE OR ALTER PROCEDURE dbo.sp_Rules_UpdateOlympicResultExpiry
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @latest_og INT;
    SELECT TOP 1 @latest_og = event_id FROM dbo.events
    WHERE event_type_general_code = 'OG' ORDER BY ranking_year DESC, event_id DESC;

    IF @latest_og IS NULL
    BEGIN
        SET @rows_updated = 0;
        SET @result_message = 'no Olympic Games event on file';
        RETURN;
    END

    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.players_events_results_master
        SET active = 0
        WHERE active = 1
          AND event_id IN (SELECT event_id FROM dbo.events WHERE event_type_general_code = 'OG' AND event_id <> @latest_og);
        SET @rows_updated = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('kept event ', @latest_og, ' active, expired ', @rows_updated, ' older Olympic result(s)');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct read of legacy `sp_Rules_UpdateOlympicResultExpiry` shows a
materially different, more complex rule, simplified deliberately here.
- Legacy expires an Olympic (`EventTypeGeneralCode LIKE '%OG%'`) result **1 year after its own
  event year** relative to the same globally-derived (non-category-filtered) "current"
  year/week anchor pattern seen in `sp_Rules_UpdateEventsResultExpiry`
  (`(e.rankingyear+1) = @RankingYear AND e.rankingweek = @RankingWeek) OR ((e.rankingyear+1) < @RankingYear`)
  — an aging rule, not a "keep only the latest" rule.
- Legacy also has a second block intended to deactivate Olympic events "if another Olympic event
  is added" via a `#ExistingEvents`/`OtherEvents` temp-table comparison — but since
  `#ExistingEvents` is populated as *every* `EventTypeGeneralCode LIKE '%OG%'` event and
  `OtherEvents` filters to events `NOT IN (SELECT eventid FROM #ExistingEvents)`, this second
  block can never match anything; it is dead code in the legacy source.
- This port replaces both of those with a single, simpler, and more clearly-intentional rule:
  find the single most-recent Olympic event on file and deactivate every *other* Olympic result,
  with no aging window and no dead code path.

### sp__ApplyBestResults (STORED PROCEDURE, private helper)

**Purpose**: The shared engine behind both `sp_Calculate_WTT_SEN_Ranking_BestResults` and
`sp_Calculate_WTT_YOU_Ranking_BestResults` — selects each competitor's best-of-X counted results
per ranking category, enforcing a max-1-continental-event cap and always including mandatory/ZPP
rows, then assigns `player_best_ranking_result_number` by points rank among the selected set.

**Current SQL** (as last redeployed, including the `@mand_count` reset fix described below):
```sql
-- Port of engine/procedures/best_results.py. Membership selection (which rows count) needs a
-- bounded procedural pass because the continental-cap "skip without consuming a slot" rule
-- cannot be expressed as a pure ROW_NUMBER()/RANK() predicate -- the Nth point-ranked row is
-- not necessarily the Nth *selected* row once skips happen. A single, non-nested, forward-only
-- cursor, ordered once by (competitor_id, ranking_category_code, ranking_points DESC), tracks
-- per-group state across the group boundary. Rank *assignment* is then pure set-based
-- ROW_NUMBER(), since all mandatory/ZPP rows carry exactly 0 points by construction, so
-- ranking selected rows by points DESC has no cap logic left to apply.
CREATE OR ALTER PROCEDURE dbo.sp__ApplyBestResults
    @category_code NVARCHAR(3), @best_x_results INT, @best_x_results_for_continental_events INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.players_events_results_master
        SET player_best_ranking_result_number = 0, best_result_no_sen_you = 0
        WHERE category_code = @category_code AND active = 1;

        SELECT p.competitor_id, p.ranking_category_code, COUNT(*) AS mandatory_count
        INTO #mandatory_count
        FROM dbo.players_events_results_master p
        WHERE p.category_code = @category_code AND p.active = 1
          AND (p.zero_point_penalty = 1 OR p.mandatory_inclusion_for_best_results = 1)
        GROUP BY p.competitor_id, p.ranking_category_code;

        UPDATE p SET best_result_no_sen_you = 1
        FROM dbo.players_events_results_master p
        WHERE p.category_code = @category_code AND p.active = 1
          AND (p.zero_point_penalty = 1 OR p.mandatory_inclusion_for_best_results = 1);

        DECLARE @competitor_id INT, @ranking_category_code NVARCHAR(10), @player_event_result_id INT, @is_continental BIT;
        DECLARE @cur_competitor INT = NULL, @cur_category NVARCHAR(10) = NULL;
        DECLARE @remaining_slots INT, @chosen_count INT, @continental_count INT, @mand_count INT;

        DECLARE best_cur CURSOR LOCAL FORWARD_ONLY READ_ONLY FOR
            SELECT p.competitor_id, p.ranking_category_code, p.player_event_result_id,
                   CAST(CASE WHEN e.event_type_general_code IN (SELECT event_type_general_code FROM dbo.continental_event_type_code)
                             THEN 1 ELSE 0 END AS BIT)
            FROM dbo.players_events_results_master p
            JOIN dbo.events e ON e.event_id = p.event_id
            WHERE p.category_code = @category_code AND p.active = 1
              AND p.zero_point_penalty = 0 AND p.mandatory_inclusion_for_best_results = 0
            ORDER BY p.competitor_id, p.ranking_category_code, p.ranking_points DESC, p.player_event_result_id ASC;

        OPEN best_cur;
        FETCH NEXT FROM best_cur INTO @competitor_id, @ranking_category_code, @player_event_result_id, @is_continental;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            IF @cur_competitor IS NULL OR @competitor_id <> @cur_competitor OR @ranking_category_code <> @cur_category
            BEGIN
                SET @cur_competitor = @competitor_id; SET @cur_category = @ranking_category_code;
                -- SELECT @var = col FROM ... WHERE <no match> leaves @var at its PREVIOUS
                -- value instead of NULL -- reset explicitly or a competitor/category group with
                -- no mandatory/ZPP rows silently inherits the prior group's mandatory_count,
                -- under-counting @remaining_slots by that amount for every group after the
                -- first one that had a mandatory row.
                SET @mand_count = NULL;
                SELECT @mand_count = mandatory_count FROM #mandatory_count
                WHERE competitor_id = @cur_competitor AND ranking_category_code = @cur_category;
                SET @remaining_slots = IIF(@best_x_results - ISNULL(@mand_count,0) > 0, @best_x_results - ISNULL(@mand_count,0), 0);
                SET @chosen_count = 0; SET @continental_count = 0;
            END

            IF @chosen_count < @remaining_slots
            BEGIN
                IF NOT (@is_continental = 1 AND @continental_count >= @best_x_results_for_continental_events)
                BEGIN
                    UPDATE dbo.players_events_results_master SET best_result_no_sen_you = 1
                    WHERE player_event_result_id = @player_event_result_id;
                    SET @chosen_count += 1;
                    IF @is_continental = 1 SET @continental_count += 1;
                END
                -- else: continental cap reached -- skip, does not consume a slot, row stays unselected
            END

            FETCH NEXT FROM best_cur INTO @competitor_id, @ranking_category_code, @player_event_result_id, @is_continental;
        END
        CLOSE best_cur; DEALLOCATE best_cur;

        ;WITH ranked AS (
            SELECT player_event_result_id,
                   ROW_NUMBER() OVER (PARTITION BY competitor_id, ranking_category_code
                                       ORDER BY ranking_points DESC, player_event_result_id ASC) AS rn
            FROM dbo.players_events_results_master
            WHERE category_code = @category_code AND active = 1 AND best_result_no_sen_you = 1
        )
        UPDATE p SET player_best_ranking_result_number = r.rn
        FROM dbo.players_events_results_master p JOIN ranked r ON r.player_event_result_id = p.player_event_result_id;

        SET @rows_updated = @@ROWCOUNT;
        DROP TABLE #mandatory_count;
        COMMIT TRAN;
        SET @result_message = CONCAT('selected best-of-', @best_x_results, ' results per player/category group for ', @category_code);
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN;
        IF OBJECT_ID('tempdb..#mandatory_count') IS NOT NULL DROP TABLE #mandatory_count;
        THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Reimplemented with no single legacy source (a deliberate, documented
simplification, not a port) — the legacy Senior and Youth best-results procedures
(`dbo_sp_Calculate_WTT_SEN_Ranking_BestResults.sql`, `dbo_sp_Calculate_WTT_YOU_Ranking_BestResults.sql`)
were read directly and are materially more complex than this reconstruction:
- Legacy joins to tables this prototype's trimmed schema doesn't have at all —
  `EventTypeGeneral` and `EventTypes` — to classify events, and has an entire additional
  sub-rule this prototype does not implement: a **"Youth events counted toward Senior ranking"**
  branch (`eg.CategoryCode='YOU' OR (eg.CategoryCode=@CategoryCode AND eg.EventTypeGeneralCode LIKE '%SEN%')`),
  where up to 3 or 4 youth-category results (the cap itself varies based on whether the
  competitor's continental result outranks their youth results) count toward a Senior
  competitor's best-of-8, unioned with the Senior-only best-of-8 selection and the max-1-
  continental selection via three separate ranked subqueries combined with `UNION`.
  **This prototype's `sp__ApplyBestResults` has no cross-category (Youth-into-Senior) counting
  rule at all** — it selects best-of-X purely within one category's own results.
- Legacy also filters out `IsForbidden=1` events from the general (non-continental) pool but
  explicitly *requires* `IsForbidden=1` for continental-event candidacy — an event-forbidden
  interaction this reconstruction does not replicate (`events.is_forbidden` exists in the
  trimmed schema but is not read by this procedure).
- Both versions share the same fundamental **best-of-X-with-a-continental-cap** concept and the
  **mandatory-always-included** principle (legacy's ZPP rows are always retained via the
  "youth events" union branch's implicit inclusion; this version makes it an explicit,
  always-first `mandatory_inclusion_for_best_results`/`zero_point_penalty` selection pass).
- **Real bug found and fixed during Azure SQL testing of this migration** (not present in the
  legacy source — introduced and then fixed within this port): the `@mand_count` reset
  highlighted above. Before the fix, `SELECT @mand_count = mandatory_count FROM #mandatory_count
  WHERE ...` left `@mand_count` holding the *previous* competitor/category group's value
  whenever the current group had no matching row (a T-SQL semantics gotcha, not a legacy bug),
  silently under-selecting one result for every competitor processed after the first one with a
  mandatory/ZPP row in the cursor's sort order. Caught by `test_senior_happy_path_end_to_end`
  (every player should have exactly 8 counted results; only the first player did), fixed by
  explicitly resetting `@mand_count = NULL` before each group's lookup, redeployed, and
  re-verified.

### sp_Calculate_WTT_SEN_Ranking_BestResults / sp_Calculate_WTT_YOU_Ranking_BestResults (STORED PROCEDURES)

**Purpose**: Thin, category-specific wrappers around `sp__ApplyBestResults`, supplying the
best-of-8-for-1-continental (Senior) / best-of-10-for-1-continental (Youth) parameters.

**Current SQL**:
```sql
-- SEN_BEST_X_RESULTS=8, BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS=1 (engine/constants.py)
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_WTT_SEN_Ranking_BestResults
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    EXEC dbo.sp__ApplyBestResults @category_code='SEN', @best_x_results=8, @best_x_results_for_continental_events=1,
        @rows_updated=@rows_updated OUTPUT, @result_message=@result_message OUTPUT;
END
GO

-- YOU_BEST_X_RESULTS=10, BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS=1 (engine/constants.py)
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_WTT_YOU_Ranking_BestResults
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    EXEC dbo.sp__ApplyBestResults @category_code='YOU', @best_x_results=10, @best_x_results_for_continental_events=1,
        @rows_updated=@rows_updated OUTPUT, @result_message=@result_message OUTPUT;
END
GO
```

**Legacy correspondence**: Same relationship to legacy as `sp__ApplyBestResults` above — legacy
has two large, independent, non-shared procedures with the same names; this prototype factors
their shared (simplified) logic into one private helper called by two thin wrappers, matching
the legacy `@BestXResults=8`/`10`, `@BestXResultsForContinantalEvents=1` parameter values exactly.

### sp_Calculate_WTT_Ranking_ZeroPointPenalty (STORED PROCEDURE)

**Purpose**: For each active penalty/ZPP-eligible result, walks forward from its own
ranking-period anchor counting subsequent non-ZPP results in the same category/ranking-category;
once that count reaches the category's event threshold (8 for SEN, 5 for YOU passed in via
`@event_count`), the ZPP row expires (`active=0`); otherwise it's marked
`mandatory_inclusion_for_best_results=1` so best-results always counts it at 0 points.

**Current SQL**:
```sql
-- Port of engine/procedures/zpp.py. A genuine per-row cursor is the right translation here --
-- each ZPP row needs its own correlated subquery against a different point in time (its own
-- ranking_year/ranking_week), which is not a group-boundary problem like best-results, just a
-- bounded per-row scan. Called with @event_count=8 for SEN, 5 for YOU -- one procedure,
-- category-parametrized, matching the Python original (no separate SEN/YOU variant).
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_WTT_Ranking_ZeroPointPenalty
    @category_code NVARCHAR(3), @event_count INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @expired INT = 0, @kept_active INT = 0, @total INT = 0;
    BEGIN TRAN;
    BEGIN TRY
        DECLARE @player_event_result_id INT, @competitor_id INT, @ranking_category_code NVARCHAR(10),
                @ranking_year INT, @ranking_week INT, @subsequent_count INT;

        -- TOP 10000 mirrors the Python sanity bound (MAX_ZPP_PER_PLAYER * 1000): a bound on
        -- total ZPP rows scanned per run, not a per-player cap.
        DECLARE zpp_cur CURSOR LOCAL FORWARD_ONLY READ_ONLY FOR
            SELECT TOP (10000) player_event_result_id, competitor_id, ranking_category_code, ranking_year, ranking_week
            FROM dbo.players_events_results_master
            WHERE category_code = @category_code AND active = 1 AND zero_point_penalty = 1
            ORDER BY player_event_result_id;

        OPEN zpp_cur;
        FETCH NEXT FROM zpp_cur INTO @player_event_result_id, @competitor_id, @ranking_category_code, @ranking_year, @ranking_week;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            SET @total += 1;
            SELECT @subsequent_count = COUNT(*)
            FROM dbo.players_events_results_master p
            JOIN dbo.events e ON e.event_id = p.event_id
            WHERE p.competitor_id = @competitor_id AND p.category_code = @category_code
              AND p.ranking_category_code = @ranking_category_code AND p.active = 1 AND p.zero_point_penalty = 0
              AND (p.ranking_year > @ranking_year OR (p.ranking_year = @ranking_year AND p.ranking_week > @ranking_week))
              AND e.event_type_code IN (SELECT event_type_code FROM dbo.zpp_event_type_code);

            IF @subsequent_count >= @event_count
            BEGIN
                UPDATE dbo.players_events_results_master SET active = 0, mandatory_inclusion_for_best_results = 0
                WHERE player_event_result_id = @player_event_result_id;
                SET @expired += 1;
            END
            ELSE
            BEGIN
                UPDATE dbo.players_events_results_master SET mandatory_inclusion_for_best_results = 1
                WHERE player_event_result_id = @player_event_result_id;
                SET @kept_active += 1;
            END

            FETCH NEXT FROM zpp_cur INTO @player_event_result_id, @competitor_id, @ranking_category_code, @ranking_year, @ranking_week;
        END
        CLOSE zpp_cur; DEALLOCATE zpp_cur;

        SET @rows_updated = @expired + @kept_active;
        COMMIT TRAN;
        SET @result_message = CONCAT(@total, ' ZPP row(s) evaluated: ', @expired, ' waived/expired, ', @kept_active, ' still active');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Reimplemented — direct read of legacy
`sp_Calculate_WTT_Ranking_ZeroPointPenalty` confirms the documented claim that this is a
substantial simplification, not a syntax-level port.
- Legacy is dramatically more elaborate: it reads penalties from a dedicated function
  (`ufnGetEventIndividualPenalties`), maintains a separate persistent tracking table
  (`ZPP_Expired_Event_Tracking`) across runs, uses **6+ temp tables**
  (`#ACTIVEZPPLIST1/2`, `#ACTIVEZPPLIST`, `#RankedResults`, `#EXPIREDZPPLIST`, `#ZPPRank`,
  `#rankwithzpp`, `#zpptooverride`, `#overidingevents`), a table-variable
  (`@InsertedEvents`), and an explicit `WHILE @ZPPCount <= @MaxZPPs` loop (`@MaxZPPs=10`) to
  insert successive, non-overlapping sets of qualifying events.
- Legacy separately handles **doubles pair penalties** (`CASE WHEN RankingCategoryCode IN
  ('MD','WD','XD') THEN PairId ELSE IttfId END AS CompetitorId`) when reading penalty records —
  this port applies the same ZPP logic uniformly to whatever `competitor_id` is already on the
  row (singles or doubles-pair id), with no penalty-source-specific branching, because it has no
  separate penalty-source table to read from at all (ZPP eligibility here comes purely from
  `players_events_results_master.zero_point_penalty`, itself set at import time).
- Legacy's "insert new ZPP as 0 points" step additionally derives `SubEventCode` from
  `RankingCategoryCode` via `REPLACE(RankingCategoryCode,'i','')` (stripping the trailing `I` in
  e.g. `MDI`→`MD`) — this prototype's ZPP rows are seeded at import time with their
  `sub_event_code` already correct, so no such derivation is needed here.
- Both implementations share the same fundamental threshold concept (a ZPP row expires once
  enough *subsequent* real results exist to fill the best-of-X requirement without it), which
  this reconstruction implements as one clean per-row correlated-count cursor instead of
  legacy's multi-table cross-run bookkeeping.

### sp_Calculate_WTT_Ranking_RankingPositions (STORED PROCEDURE)

**Purpose**: Sums each competitor's counted points into `main_ranking.ranking_points`, then
assigns `ranking_pos` per ranking category via a fully deterministic tiebreak ordering.

**Current SQL**:
```sql
-- Port of engine/procedures/positions.py. Pure set-based ROW_NUMBER(): all mandatory/ZPP rows
-- carry exactly 0 points by construction (see sp__ApplyBestResults), so summing points and
-- ranking by points DESC needs no cap/skip logic here.
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_WTT_Ranking_RankingPositions
    @category_code NVARCHAR(3), @run_id INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        ;WITH points AS (
            SELECT competitor_id, ranking_category_code, SUM(ranking_points) AS total_points,
                   COUNT(*) AS counted_results
            FROM dbo.players_events_results_master
            WHERE category_code = @category_code AND active = 1 AND best_result_no_sen_you = 1
            GROUP BY competitor_id, ranking_category_code
        )
        UPDATE mr SET ranking_points = ISNULL(pts.total_points, 0)
        FROM dbo.main_ranking mr
        LEFT JOIN points pts ON pts.competitor_id = mr.competitor_id AND pts.ranking_category_code = mr.ranking_category
        WHERE mr.ranking_run_id = @run_id;

        ;WITH ranked AS (
            SELECT mr.main_ranking_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY mr.ranking_category
                       ORDER BY mr.ranking_points DESC, ISNULL(pts.counted_results, 0) ASC,
                                c.dob DESC, mr.competitor_id ASC
                   ) AS rn
            FROM dbo.main_ranking mr
            LEFT JOIN points pts ON pts.competitor_id = mr.competitor_id AND pts.ranking_category_code = mr.ranking_category
            JOIN dbo.competitors c ON c.competitor_id = mr.competitor_id
            WHERE mr.ranking_run_id = @run_id
        )
        UPDATE mr SET ranking_pos = r.rn
        FROM dbo.main_ranking mr JOIN ranked r ON r.main_ranking_id = mr.main_ranking_id;

        SET @rows_updated = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('assigned positions for ', @rows_updated, ' main_ranking row(s)');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct/near-direct port of legacy `sp_Calculate_WTT_Ranking_RankingPositions`.
- Legacy's points-summation step is materially the same rule (`SUM(RankingPoints)` over rows
  with `PlayerBestRankingResultNumber>0` for SEN / `BestResultNoSENYOU<>0` for YOU, `Active=1`,
  `ExcludedDuetoZeroPointPenalty=0`, joined to a `RankingRunsLog.Status='In Progress'` row) —
  this port's `WHERE ... active = 1 AND best_result_no_sen_you = 1` is the equivalent gate,
  simplified since this schema doesn't carry a separate "in progress" run-status gate to join
  against (the run is implicitly the one being executed right now).
- **Tiebreak column order is preserved exactly**: `RankingPoints DESC, TotalEventsCountedforRanking
  [ASC], HighestNumberOfPoints DESC, BestResultinGrandSmash, RankinginPreviousWeek, dob DESC,
  <random-ish tiebreak>`. This prototype's simplified schema doesn't carry
  `HighestNumberOfPoints`/`BestResultinGrandSmash`/`RankinginPreviousWeek` (all three come from
  legacy UDFs — `ufnrule_CalculatedColumn_WTT_PlayersRanking_HighestNumberOfPoints`,
  `..._BestResultinEventTypeOrCategory`, `ufnrule_CalculatedColumn_PlayersRanking_CurrentRankingPosition`
  — never exported to this project), so this port keeps `points DESC, counted-results ASC, dob
  DESC` and replaces the missing middle columns and the final random-ish tiebreak with a single,
  fully deterministic `competitor_id ASC` as the last tiebreak.
- On the **final tiebreak column specifically**: the legacy source read for this document is a
  version that had *already* been patched away from true `NEWID()` (kept, commented out, as
  dead code below the live query, annotated `"faster than NEWID"`) to
  `CHECKSUM(CompetitorId) AS RandomOrder` — a deterministic-but-still-hash-based pseudo-order,
  not a transparent, auditable ordering rule (and `CHECKSUM` can theoretically collide across
  different competitor IDs). This port's plain `competitor_id ASC` is both fully deterministic
  *and* directly auditable ("lowest ID wins ties"), an improvement over both legacy variants.
- Legacy materializes an intermediate `vw_WTT_PlayerRankingPosition`-sourced temp table
  (`#RankData`) with an explicit non-clustered index (`IX_RankData_Sort`) purely for query-plan
  performance on a much larger legacy dataset; this prototype's data volumes don't warrant that,
  so the equivalent `ROW_NUMBER()` runs directly over the CTE.

### Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory (STORED PROCEDURE)

**Purpose**: Youth-only step 10 — assigns `ranking_pos_age_category` within each
(ranking category, age category) partition, using the same tiebreak philosophy as the main
positions procedure.

**Current SQL** (second procedure defined in `sp_Calculate_WTT_Ranking_RankingPositions.sql`):
```sql
-- Youth-only: partitions by (ranking_category, age_category_code) instead of ranking_category
-- alone. Shares the exact same deterministic tiebreak as sp_Calculate_WTT_Ranking_RankingPositions
-- above -- this is the specific fix for the legacy NEWID() non-determinism bug (see notes).
CREATE OR ALTER PROCEDURE dbo.Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory
    @category_code NVARCHAR(3), @run_id INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        ;WITH points AS (
            SELECT competitor_id, ranking_category_code, SUM(ranking_points) AS total_points,
                   COUNT(*) AS counted_results
            FROM dbo.players_events_results_master
            WHERE category_code = @category_code AND active = 1 AND best_result_no_sen_you = 1
            GROUP BY competitor_id, ranking_category_code
        ),
        ranked AS (
            SELECT mr.main_ranking_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY mr.ranking_category, mr.age_category_code
                       ORDER BY mr.ranking_points DESC, ISNULL(pts.counted_results, 0) ASC,
                                c.dob DESC, mr.competitor_id ASC
                   ) AS rn
            FROM dbo.main_ranking mr
            LEFT JOIN points pts ON pts.competitor_id = mr.competitor_id AND pts.ranking_category_code = mr.ranking_category
            JOIN dbo.competitors c ON c.competitor_id = mr.competitor_id
            WHERE mr.ranking_run_id = @run_id
        )
        UPDATE mr SET ranking_pos_age_category = r.rn
        FROM dbo.main_ranking mr JOIN ranked r ON r.main_ranking_id = mr.main_ranking_id;

        SET @rows_updated = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('assigned age-category positions for ', @rows_updated, ' main_ranking row(s)');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct/near-direct port of legacy
`Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory` — **this is the procedure that
confirmed the true, still-live `NEWID()` bug**, distinct from its sibling above.
- Legacy's tiebreak here ends in `ABS(CAST(CAST(NEWID() AS VARBINARY) AS INT))` — genuine,
  literal, per-execution-random ordering, **not** the `CHECKSUM`-based version already patched
  into the main `sp_Calculate_WTT_Ranking_RankingPositions`. The two sibling procedures had
  drifted out of sync in the legacy codebase: one was optimized/patched, the other was not.
  This port unifies both onto the exact same deterministic `competitor_id ASC` final tiebreak,
  closing that inconsistency along with the non-determinism itself.
- Otherwise structurally identical to legacy: same partition-by-(ranking category, age category)
  shape, same `RankingLog.Status='In Progress'` gate translated to this port's `run_id` scoping,
  same missing-UDF-column substitutions as its sibling procedure above.

### Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun (STORED PROCEDURE)

**Purpose**: Youth-only step 1 — verifies a Senior run for the exact same ranking period has
already succeeded before allowing a Youth calculation to proceed at all.

**Current SQL**:
```sql
-- Port of engine/procedures/dependency.py. THROW 51001 is a specific sentinel error number --
-- the YOU master procedure's CATCH block tests ERROR_NUMBER()=51001 to set the run's status to
-- ABORTED_DEPENDENCY instead of the generic FAILED (see sp_Calculate_Ranking_YOU.sql).
CREATE OR ALTER PROCEDURE dbo.Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun
    @ranking_year INT, @ranking_month INT, @ranking_week INT
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (
        SELECT 1 FROM dbo.ranking_run
        WHERE category_code = 'SEN' AND ranking_year = @ranking_year
          AND ranking_month = @ranking_month AND ranking_week = @ranking_week AND status = 'SUCCEEDED'
    )
    BEGIN
        DECLARE @msg NVARCHAR(400) = CONCAT(
            'Senior Category Ranking Run should be completed for ', @ranking_year, '-',
            RIGHT('0' + CAST(@ranking_month AS VARCHAR(2)), 2), ' week ', @ranking_week,
            ' before the Youth run can proceed.');
        THROW 51001, @msg, 1;
    END
END
GO
```

**Legacy correspondence**: Direct/near-direct port of legacy
`Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun`.
- Legacy's dependency check is keyed off the **most recently created `'PreRequisite
  Validation'`-status run row for the checking category** (`RankingRunsLogId = MAX(...) WHERE
  Status='PreRequisite Validation'`), then joins to a same-year/month/week SEN run with
  `Status IN ('Draft','Published')` — an indirect lookup that depends on the specific just-
  created row from *this* run's own Step 0 still existing with that exact status. This port
  checks directly for a `SUCCEEDED` SEN `ranking_run` row for the requested `(year, month,
  week)` tuple — a more direct, unambiguous check with no dependency on lookup-row bookkeeping.
- Legacy's failure path uses `RAISERROR('...', @ErrorSeverity, @ErrorState, @ErrorNumber, ...)`
  with the message-string overload — this overload does **not** actually let the caller set a
  custom `ERROR_NUMBER()`; SQL Server always reports `50000` for a string-message `RAISERROR`,
  regardless of the `@ErrorNumber=50000` local variable being set alongside it. This means the
  legacy caller has **no reliable way to distinguish this specific dependency failure from any
  other 50000-level error** by number. This port's `THROW 51001, @msg, 1` is a real, specific,
  catchable sentinel — the entire `ABORTED_DEPENDENCY` vs `FAILED` status distinction (a genuine
  new capability, not present in legacy's status model at all) depends on this working
  correctly, and it does: verified directly against the `youth_dependency_failure` fixture.
- Legacy's `'Draft','Published'` status check reflects its two-tier publish workflow (see
  `ranking_run` table notes); this port's `'SUCCEEDED'` check is the equivalent single-tier
  terminal-success state.

### sp_Calculate_Ranking_FinalizeRun (STORED PROCEDURE)

**Purpose**: Business-logic cleanup at the end of a successful run — removes any `main_ranking`
row that ended up with exactly 0 points, and clears the `new_events_results` staging rows now
consumed by this run.

**Current SQL**:
```sql
-- Port of the end-of-run cleanup block embedded directly inside legacy sp_Calculate_Ranking
-- (not a separately-named legacy procedure) -- extracted here as its own named, auditable step.
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_Ranking_FinalizeRun
    @category_code NVARCHAR(3), @run_id INT,
    @rows_deleted INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        DELETE FROM dbo.main_ranking WHERE ranking_run_id = @run_id AND ranking_points = 0;
        DECLARE @zero_purged INT = @@ROWCOUNT;

        DELETE FROM dbo.new_events_results WHERE category_code = @category_code;
        SET @rows_deleted = @@ROWCOUNT;

        COMMIT TRAN;
        SET @result_message = CONCAT('purged ', @zero_purged, ' zero-point main_ranking row(s), cleared ', @rows_deleted, ' consumed new_events_results row(s)');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct/near-direct port of the end-of-run cleanup block found inline
inside `dbo_sp_Calculate_Ranking.sql` (not a separately-callable legacy procedure — this
extraction into its own named, independently auditable step is itself a structural change).
- `Delete from Mainranking where CategoryCode=@CategoryCode and Rankingyear=... and
  RankingPoints=0` — matches this port's zero-point purge exactly, scoped here by
  `ranking_run_id` (a stronger key than legacy's year/month/week/category combination, per the
  `main_ranking` table notes above).
- `Delete from NewEventsResults where CategoryCode=@CategoryCode` — matches exactly; legacy has
  a commented-out `if @ForTesting=0` guard around this delete that was never actually enabled
  (the whole `IF` block is commented out, so the delete always runs unconditionally in the live
  legacy code) — this port always runs it unconditionally too, with no testing-mode bypass.
  it also does not include a same conditional `@ForTesting` flag , this port's `run_mode` column
  on `ranking_run` exists for a similar future purpose but isn't wired to this step's behavior.
- Legacy performs this cleanup as the tail end of one enormous `BEGIN TRAN ... COMMIT TRAN` that
  spans the entire run; this port's per-step-own-transaction model (see the master procedures'
  design notes) makes finalize its own independently committed step.

---

## Part 6 — Stored Procedures: `db/procedures/master/`

### sp__RecordStepFailure (STORED PROCEDURE, private helper)

**Purpose**: Shared helper called from every step's `CATCH` block inside both master
procedures — records the step as `FAILED` with timing and truncated error text, and inserts the
matching `ranking_run_error` row, deliberately with no open transaction so it commits
immediately even though the failing step's own transaction already rolled back.

**Current SQL**:
```sql
-- Shared helper called from every step's CATCH block inside the master procedures (avoids
-- duplicating this block 10-11 times per master procedure). Runs with NO open transaction at
-- the point it's called (the failing step's own BEGIN TRAN already rolled back and re-threw
-- before this point), so its UPDATE/INSERT commit immediately (autocommit) -- this is what
-- preserves "audit survives rollback" and "a concurrent dashboard reader sees FAILED as soon
-- as it's recorded", matching engine/step_runner.py's behavior in the SQLite prototype.
CREATE OR ALTER PROCEDURE dbo.sp__RecordStepFailure
    @run_id INT, @step_id INT, @step_start DATETIME2(3)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @err_msg NVARCHAR(MAX) = ERROR_MESSAGE(), @err_proc NVARCHAR(200) = ISNULL(ERROR_PROCEDURE(),'T-SQL');
    UPDATE dbo.ranking_run_step
    SET status='FAILED', finished_at=SYSUTCDATETIME(),
        duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), result_message=LEFT(@err_msg,400)
    WHERE ranking_run_step_id=@step_id;

    INSERT INTO dbo.ranking_run_error (ranking_run_id, ranking_run_step_id, error_type, error_message, traceback, occurred_at)
    VALUES (@run_id, @step_id, @err_proc, @err_msg,
            CONCAT('Line ', ERROR_LINE(), '; State ', ERROR_STATE(), '; Number ', ERROR_NUMBER()), SYSUTCDATETIME());
END
GO
```

**Legacy correspondence**: NEW — no legacy equivalent as a shared, reusable helper. Legacy
duplicates its equivalent error-handling block **inline, separately, at every single failure
point** inside `sp_Calculate_Ranking` (7+ near-identical copies of the same `UPDATE
RankingRunsLog ... INSERT INTO dbo.DB_Errors ...` block, one per step — see that procedure's
notes for the confirmed dead-output-variable bug this duplication allowed to hide at Step 5).
Factoring this into one shared procedure is what makes it possible for this prototype's version
to guarantee every step failure is recorded identically and correctly, with no risk of one
particular inline copy having a subtle bug the others don't.

### sp_RankingRun_Create (STORED PROCEDURE)

**Purpose**: Creates a new `RUNNING` `ranking_run` row for an on-demand calculation, computing
the SHA-256 input-snapshot hash over the in-scope `new_events_results` rows.

**Current SQL**:
```sql
-- T-SQL analogue of engine/run_registry.py: create/schedule/start/finalize a ranking_run row.
-- HASHBYTES('SHA2_256', ...) replaces Python's hashlib.sha256 for the input-snapshot hash.

CREATE OR ALTER PROCEDURE dbo.sp_RankingRun_Create
    @category_code NVARCHAR(3), @ranking_year INT, @ranking_month INT, @ranking_week INT,
    @triggered_by NVARCHAR(100), @run_mode NVARCHAR(10) = 'normal', @run_id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    -- STRING_AGG truncates its input/output to the 8000-byte nvarchar limit unless the input
    -- expression is already an nvarchar(max)/LOB type -- with enough imported rows the plain
    -- CONCAT(...) here silently overflowed that limit and errored (9829). Casting each row's
    -- concatenated string to NVARCHAR(MAX) forces STRING_AGG's result to be MAX-typed too.
    DECLARE @hash NVARCHAR(64) = CONVERT(NVARCHAR(64), HASHBYTES('SHA2_256', ISNULL((
        SELECT STRING_AGG(CAST(CONCAT(new_event_result_id,'|',event_id,'|',competitor_id,'|',sub_event_code,'|',result_position,'|',ranking_points) AS NVARCHAR(MAX)), '|')
            WITHIN GROUP (ORDER BY new_event_result_id)
        FROM dbo.new_events_results WHERE category_code = @category_code
    ), '')), 2);

    INSERT INTO dbo.ranking_run
        (category_code, ranking_year, ranking_month, ranking_week, run_mode, trigger_type, status, started_at, triggered_by, input_snapshot_hash)
    VALUES (@category_code, @ranking_year, @ranking_month, @ranking_week, @run_mode, 'on_demand', 'RUNNING', SYSUTCDATETIME(), @triggered_by, @hash);
    SET @run_id = SCOPE_IDENTITY();
END
GO
```

**Legacy correspondence**: NEW — no legacy equivalent as a standalone, callable procedure.
Legacy performs the equivalent row creation **inline, at the top of `sp_Calculate_Ranking`
itself** (the `INSERT INTO [dbo].[RankingRunsLog] (...) VALUES (...)` block after the
already-published-this-week guard), with no `input_snapshot_hash` concept at all — legacy has no
reproducibility hash of any kind; a re-run's identical input is indistinguishable from a
different one. Extracting run creation into its own procedure, and adding the hash, are both new.
**Deployment note (found and fixed during this migration)**: the hash's `STRING_AGG(...)`
expression originally overflowed SQL Server's 8000-byte `NVARCHAR` limit once enough rows were
imported (error 9829); fixed by casting the per-row concatenation to `NVARCHAR(MAX)` before
aggregating.

### sp_RankingRun_Schedule (STORED PROCEDURE)

**Purpose**: Records a future-dated run request as a `PENDING` row without executing it — the
"Schedule" option in the Start Calculation UI.

**Current SQL**:
```sql
CREATE OR ALTER PROCEDURE dbo.sp_RankingRun_Schedule
    @category_code NVARCHAR(3), @ranking_year INT, @ranking_month INT, @ranking_week INT,
    @scheduled_for DATETIME2(3), @triggered_by NVARCHAR(100), @run_mode NVARCHAR(10) = 'normal', @run_id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO dbo.ranking_run
        (category_code, ranking_year, ranking_month, ranking_week, run_mode, trigger_type, scheduled_for, status, triggered_by)
    VALUES (@category_code, @ranking_year, @ranking_month, @ranking_week, @run_mode, 'scheduled', @scheduled_for, 'PENDING', @triggered_by);
    SET @run_id = SCOPE_IDENTITY();

    -- pyodbc cannot reliably read back T-SQL OUTPUT parameters through {CALL} syntax (a known
    -- driver limitation), so -- matching the return-contract pattern used by the master
    -- procedures -- also surface @run_id via a trailing SELECT for Python callers.
    SELECT @run_id AS run_id;
END
GO
```

**Legacy correspondence**: NEW — no legacy equivalent as a standalone procedure. This maps
conceptually to the legacy `Schedule` table / `Sp_Process_ScheduledtoPublish` process named in
`docs/legacy_rule_mapping.md`, but that process's implementation was never exported — this
prototype's "record intent as a PENDING row, a human clicks Run Now" model is a new, simpler
design built specifically because the legacy auto-fire mechanism was unavailable to port.

### sp_RankingRun_StartScheduled (STORED PROCEDURE)

**Purpose**: Transitions a previously-scheduled `PENDING` run to `RUNNING` when a user clicks
"Run Now", recomputing the input-snapshot hash at actual execution time.

**Current SQL**:
```sql
CREATE OR ALTER PROCEDURE dbo.sp_RankingRun_StartScheduled
    @run_id INT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @status NVARCHAR(20), @category_code NVARCHAR(3);
    SELECT @status = status, @category_code = category_code FROM dbo.ranking_run WHERE ranking_run_id = @run_id;
    IF @status IS NULL THROW 51002, 'ranking_run not found', 1;
    IF @status <> 'PENDING' THROW 51003, 'ranking_run is not PENDING', 1;

    -- STRING_AGG truncates its input/output to the 8000-byte nvarchar limit unless the input
    -- expression is already an nvarchar(max)/LOB type -- with enough imported rows the plain
    -- CONCAT(...) here silently overflowed that limit and errored (9829). Casting each row's
    -- concatenated string to NVARCHAR(MAX) forces STRING_AGG's result to be MAX-typed too.
    DECLARE @hash NVARCHAR(64) = CONVERT(NVARCHAR(64), HASHBYTES('SHA2_256', ISNULL((
        SELECT STRING_AGG(CAST(CONCAT(new_event_result_id,'|',event_id,'|',competitor_id,'|',sub_event_code,'|',result_position,'|',ranking_points) AS NVARCHAR(MAX)), '|')
            WITHIN GROUP (ORDER BY new_event_result_id)
        FROM dbo.new_events_results WHERE category_code = @category_code
    ), '')), 2);

    UPDATE dbo.ranking_run SET status = 'RUNNING', started_at = SYSUTCDATETIME(), input_snapshot_hash = @hash WHERE ranking_run_id = @run_id;
END
GO
```

**Legacy correspondence**: NEW — no legacy equivalent. `THROW 51002`/`51003` are new sentinel
guards (run not found / not in `PENDING` state) with no legacy analogue — legacy has no
scheduled-but-not-yet-run state at all.

### sp_RankingRun_Finalize (STORED PROCEDURE)

**Purpose**: The run-lifecycle finalize step — sets the run's terminal status and timestamp,
and on `SUCCEEDED` only, hands off `current_active`/`superseded_by_run_id` to the new run and
updates `ranking_engine_info`'s current-period pointer.

**Current SQL**:
```sql
CREATE OR ALTER PROCEDURE dbo.sp_RankingRun_Finalize
    @run_id INT, @status NVARCHAR(20), @notes NVARCHAR(MAX) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.ranking_run SET status = @status, finished_at = SYSUTCDATETIME(), notes = @notes WHERE ranking_run_id = @run_id;

        IF @status = 'SUCCEEDED'
        BEGIN
            DECLARE @cat NVARCHAR(3), @y INT, @mo INT, @wk INT;
            SELECT @cat = category_code, @y = ranking_year, @mo = ranking_month, @wk = ranking_week
            FROM dbo.ranking_run WHERE ranking_run_id = @run_id;

            UPDATE dbo.ranking_run SET current_active = 0, superseded_by_run_id = @run_id
            WHERE category_code = @cat AND ranking_year = @y AND ranking_month = @mo AND ranking_week = @wk
              AND current_active = 1 AND ranking_run_id <> @run_id;

            UPDATE dbo.ranking_run SET current_active = 1 WHERE ranking_run_id = @run_id;

            UPDATE dbo.ranking_engine_info
            SET current_ranking_year = @y, current_ranking_month = @mo, current_ranking_week = @wk
            WHERE category_code = @cat;
        END
        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: Direct/near-direct conceptual port of the tail-end status-mutation
block inside legacy `sp_Calculate_Ranking` (`Update RankingRunsLog Set CurrentActive=0 ... /
Update RankingRunsLog Set CurrentActive=1, Status='Draft' ... / Update RankingEngineInfo Set
Current_Ranking_Year=...`), extracted into its own reusable procedure and generalized to accept
any terminal status (`SUCCEEDED`/`FAILED`/`ABORTED_DEPENDENCY`), not just the success path.
- Legacy's `CurrentActive=0` sweep has **no category/period scoping** in the read source
  (`Update RankingRunsLog Set CurrentActive=0 where CategoryCode=@CategoryCode` — no
  `RankingYear`/`Month`/`Week` filter), meaning it deactivates *every prior run ever made for
  that category*, not just the one for the same period; this port's equivalent sweep is scoped
  precisely to `(category_code, ranking_year, ranking_month, ranking_week)`, only deactivating
  the specific run being superseded for the exact same period, and additionally records
  `superseded_by_run_id` for explicit lineage (no legacy equivalent).
  Legacy also sets the final status to `'Draft'` (its intermediate, pre-publish state), not a
  terminal success — see the `ranking_run` table's Draft/Published notes.

### sp_Calculate_Ranking_SEN (STORED PROCEDURE)

**Purpose**: The Senior master procedure — creates or resumes a run, `EXEC`s all 10 Senior
calculation steps in a fixed sequence with per-step audit logging, and returns the final
outcome via a trailing `SELECT` (`ranking_run_id`, `status`, `failed_step_seq`,
`failed_step_name`, `error_message`).

**Current SQL**:
```sql
-- Master T-SQL procedure for the Senior ranking calculation. Direct, category-split successor
-- of the legacy parameterized sp_Calculate_Ranking. Internally EXECs each step's own stored
-- procedure in the fixed, verified order (see docs/legacy_rule_mapping.md), writing its own
-- step-audit rows via T-SQL, with TRY/CATCH per step replicating the exact per-step-atomic-
-- commit + audit-survives-rollback + live-visibility-to-a-concurrent-reader guarantee the
-- SQLite prototype's engine/step_runner.py established.
--
-- Return contract: rather than fight pyodbc OUTPUT-parameter quirks, this procedure never lets
-- an expected failure propagate as a raw exception -- it catches it, finalizes the run itself
-- (FAILED), and returns one final SELECT row (ranking_run_id, status, failed_step_seq,
-- failed_step_name, error_message). Python's thin wrapper just EXECs and reads that one row.
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_Ranking_SEN
    @ranking_year INT, @ranking_month INT, @ranking_week INT,
    @triggered_by NVARCHAR(100), @run_mode NVARCHAR(10) = 'normal', @run_id INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @category_code NVARCHAR(3) = 'SEN';
    DECLARE @step_id INT, @step_start DATETIME2(3);
    DECLARE @ri INT, @ru INT, @rd INT, @msg NVARCHAR(400);
    DECLARE @final_status NVARCHAR(20), @failed_step_seq INT = NULL,
            @failed_step_name NVARCHAR(100) = NULL, @failed_error_message NVARCHAR(MAX) = NULL;

    IF @run_id IS NULL
        EXEC dbo.sp_RankingRun_Create @category_code=@category_code, @ranking_year=@ranking_year,
            @ranking_month=@ranking_month, @ranking_week=@ranking_week, @triggered_by=@triggered_by,
            @run_mode=@run_mode, @run_id=@run_id OUTPUT;
    ELSE
        EXEC dbo.sp_RankingRun_StartScheduled @run_id=@run_id;

    -- ===== Step 1: PreRequisitesValidation =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 1, 'PreRequisitesValidation', 'SP_Calculate_Ranking_UpdatePlayersInfoFromTTU', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.SP_Calculate_Ranking_UpdatePlayersInfoFromTTU @organization_code='WTT', @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=1; SET @failed_step_name='SP_Calculate_Ranking_UpdatePlayersInfoFromTTU';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 2: Orchestration - Data preparation =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 2, 'Orchestration', 'sp_Calculate_Ranking_Step2_DataPreparationforNewRun', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_Step2_DataPreparationforNewRun
            @category_code=@category_code, @year=@ranking_year, @month=@ranking_month, @week=@ranking_week, @run_id=@run_id,
            @rows_inserted=@ri OUTPUT, @rows_updated=@ru OUTPUT, @rows_deleted=@rd OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()),
            rows_inserted=@ri, rows_updated=@ru, rows_deleted=@rd, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=2; SET @failed_step_name='sp_Calculate_Ranking_Step2_DataPreparationforNewRun';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 3: Orchestration - Seed main_ranking =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 3, 'Orchestration', 'sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking
            @category_code=@category_code, @year=@ranking_year, @month=@ranking_month, @week=@ranking_week, @run_id=@run_id,
            @rows_inserted=@ri OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_inserted=@ri, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=3; SET @failed_step_name='sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 4: ResultsSelection - Manual modifications =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 4, 'ResultsSelection', 'sp_Rules_Set_Weekly_Events_ManualModifications', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_Set_Weekly_Events_ManualModifications
            @category_code=@category_code, @run_id=@run_id, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=4; SET @failed_step_name='sp_Rules_Set_Weekly_Events_ManualModifications';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 5: ResultsSelection - Results expiry =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 5, 'ResultsSelection', 'sp_Rules_UpdateEventsResultExpiry', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_UpdateEventsResultExpiry
            @category_code=@category_code, @year=@ranking_year, @week=@ranking_week, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=5; SET @failed_step_name='sp_Rules_UpdateEventsResultExpiry';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 6: ResultsSelection - Olympic expiry =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 6, 'ResultsSelection', 'sp_Rules_UpdateOlympicResultExpiry', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_UpdateOlympicResultExpiry @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=6; SET @failed_step_name='sp_Rules_UpdateOlympicResultExpiry';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 7: ResultsSelection - Best-of-8 selection =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 7, 'ResultsSelection', 'sp_Calculate_WTT_SEN_Ranking_BestResults', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_SEN_Ranking_BestResults @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=7; SET @failed_step_name='sp_Calculate_WTT_SEN_Ranking_BestResults';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 8: ResultsSelection - Zero-Point-Penalty =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 8, 'ResultsSelection', 'sp_Calculate_WTT_Ranking_ZeroPointPenalty', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_Ranking_ZeroPointPenalty
            @category_code=@category_code, @event_count=8, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=8; SET @failed_step_name='sp_Calculate_WTT_Ranking_ZeroPointPenalty';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 9: RankingResultPositions - positions (Mandatory) =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 9, 'RankingResultPositions', 'sp_Calculate_WTT_Ranking_RankingPositions', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_Ranking_RankingPositions
            @category_code=@category_code, @run_id=@run_id, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=9; SET @failed_step_name='sp_Calculate_WTT_Ranking_RankingPositions';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 10: Orchestration - Finalize =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 10, 'Orchestration', 'sp_Calculate_Ranking_FinalizeRun', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_FinalizeRun
            @category_code=@category_code, @run_id=@run_id, @rows_deleted=@rd OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_deleted=@rd, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=10; SET @failed_step_name='sp_Calculate_Ranking_FinalizeRun';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    EXEC dbo.sp_RankingRun_Finalize @run_id=@run_id, @status='SUCCEEDED', @notes=NULL;
    SET @final_status = 'SUCCEEDED';
    GOTO return_result;

    finalize_failed:
        EXEC dbo.sp_RankingRun_Finalize @run_id=@run_id, @status='FAILED', @notes=@failed_error_message;
        SET @final_status = 'FAILED';

    return_result:
        SELECT @run_id AS ranking_run_id, @final_status AS status, @failed_step_seq AS failed_step_seq,
               @failed_step_name AS failed_step_name, @failed_error_message AS error_message;
END
GO
```

**Legacy correspondence**: Direct, but structurally reorganized, successor of legacy
`sp_Calculate_Ranking` — read in full for this document, this is where the largest, most
consequential set of differences lives.
- **Legacy is one procedure parametrized by `@CategoryCode` for both SEN and YOU**; this
  prototype splits it into two literal, category-specific procedures (`sp_Calculate_Ranking_SEN`
  and `sp_Calculate_Ranking_YOU`), matching `docs/legacy_rule_mapping.md`'s documented reasoning:
  total transparency over a shared, parametrized/rules-table-driven code path.
- **A confirmed, specific dead-output-variable bug in legacy Step 5**: the call to
  `[dbo].[sp_Rules_RunRulesList]` passes `@SpLocalResultMessage OUTPUT` **three times** for what
  should be three separate output parameters (result message, procedure name, error number):
  ```sql
  EXECUTE @RC = [dbo].[sp_Rules_RunRulesList]
         @RankingYear ,@RankingMonth ,@RankingWeek ,@OrganizationCode ,@CategoryCode ,@RulesSetId
        , @CurrentRunLogId
        ,@SpLocalResultMessage OUTPUT
        ,@SpLocalResultMessage OUTPUT
        ,@SpLocalResultMessage OUTPUT
  ```
  Because `@SpLocalErrorNo` is never actually bound to this call's true error-number output, the
  surrounding `IF @SpLocalErrorNo<>0 ... Return @SpLocalErrorNo` check can never fire for a rule
  failure during this step — a real, silent failure-swallowing bug in the live legacy source.
  This prototype's `EXEC ... @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT` calls always
  bind distinct output variables, and every step failure reaches `sp__RecordStepFailure`
  reliably (verified directly by `test_bad_ranking_category_code_fails_the_run_cleanly` and the
  `calculation_failure` fixture).
- **This prototype's dynamic-rules-engine replacement**: legacy's Step 5 (`Run rules`) calls
  `sp_Rules_RunRulesList`, which (per `docs/legacy_rule_mapping.md`'s verified active-rule
  sequence, derived from `dbo_Rules.csv`) dynamically resolves and executes each active rule for
  the category via alias substitution — the actual UDF bodies driving that resolution
  (`ufnrule_General_EvaluateAlias`, etc.) were never exported. This prototype has no dynamic
  dispatch layer at all: every step below is a **hardcoded, literal `EXEC`** in a fixed
  sequence, verified against that same CSV-derived rule order.
- **Legacy's Step 1** (`PreRequisitesValidation`) in the read source doesn't actually call
  `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU` at all in the visible flow of
  `sp_Calculate_Ranking` — that call happens as its own separately-scheduled process, per the
  legacy rule table. This prototype folds it in as an explicit Step 1 of the master procedure
  for auditability, even though (per that procedure's own notes) it's a documented stub here.
- **`@ForTesting`**: legacy's `sp_Calculate_Ranking` accepts a `@ForTesting INT=0` parameter
  gating two now-dead troubleshooting inserts into `ForTroubleshooting_RankingRunsDataChangesLog`
  (JSON snapshots of intermediate state) — neither the parameter's troubleshooting branches nor
  that logging table are ported; `run_mode` on `ranking_run` exists for a related future purpose
  but isn't wired to per-step troubleshooting output here.
- **Every step here is its own `BEGIN TRY/CATCH` with its own step-audit `INSERT`/`UPDATE`**,
  replicating the per-step-atomic-commit design (each step's own procedure manages its own
  `BEGIN TRAN/COMMIT/ROLLBACK` internally) rather than legacy's single `Begin Tran` opened near
  the top of `sp_Calculate_Ranking` and held open across the *entire* run until one final
  `commit tran` at the very end — meaning in legacy, **no step's writes are visible to any other
  connection until the whole run finishes**, which is exactly the design tradeoff this
  prototype's step-runner model (see README "Design decisions") was built to avoid, so a live
  dashboard reader can see completed steps land in real time.
- **Return contract**: legacy communicates outcome via `OUTPUT` parameters
  (`@SpResultMessage`/`@SpErrorNo`) and a numeric `RETURN` code; this prototype returns one
  final `SELECT` row instead (`ranking_run_id, status, failed_step_seq, failed_step_name,
  error_message`), specifically because `pyodbc` cannot reliably read T-SQL `OUTPUT` parameters
  back through `{CALL}` syntax.

### sp_Calculate_Ranking_YOU (STORED PROCEDURE)

**Purpose**: The Youth master procedure — same pattern as `sp_Calculate_Ranking_SEN`, with the
dependency guard as Step 1 (branching to `ABORTED_DEPENDENCY` on the `THROW 51001` sentinel)
and 11 steps total (an extra age-category-positions step for Youth).

**Current SQL**:
```sql
-- Master T-SQL procedure for the Youth ranking calculation. Same pattern as
-- sp_Calculate_Ranking_SEN, with two structural differences: (a) step 1 is the dependency
-- guard, whose CATCH branches on the sentinel error number 51001 to set status=
-- ABORTED_DEPENDENCY instead of the generic FAILED; (b) two extra/renamed steps (best-of-10,
-- ZPP event_count=5, plus the extra age-category-positions step).
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_Ranking_YOU
    @ranking_year INT, @ranking_month INT, @ranking_week INT,
    @triggered_by NVARCHAR(100), @run_mode NVARCHAR(10) = 'normal', @run_id INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @category_code NVARCHAR(3) = 'YOU';
    DECLARE @step_id INT, @step_start DATETIME2(3);
    DECLARE @ri INT, @ru INT, @rd INT, @msg NVARCHAR(400);
    DECLARE @final_status NVARCHAR(20), @failed_step_seq INT = NULL,
            @failed_step_name NVARCHAR(100) = NULL, @failed_error_message NVARCHAR(MAX) = NULL;

    IF @run_id IS NULL
        EXEC dbo.sp_RankingRun_Create @category_code=@category_code, @ranking_year=@ranking_year,
            @ranking_month=@ranking_month, @ranking_week=@ranking_week, @triggered_by=@triggered_by,
            @run_mode=@run_mode, @run_id=@run_id OUTPUT;
    ELSE
        EXEC dbo.sp_RankingRun_StartScheduled @run_id=@run_id;

    -- ===== Step 1: PreRequisitesValidation - Senior dependency guard =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 1, 'PreRequisitesValidation', 'Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun
            @year=@ranking_year, @month=@ranking_month, @week=@ranking_week, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        DECLARE @dep_err_num INT = ERROR_NUMBER();
        DECLARE @dep_err_msg NVARCHAR(MAX) = ERROR_MESSAGE();
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=1; SET @failed_step_name='Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun';
        SET @failed_error_message = @dep_err_msg;
        IF @dep_err_num = 51001
        BEGIN
            EXEC dbo.sp_RankingRun_Finalize @run_id=@run_id, @status='ABORTED_DEPENDENCY', @notes=@failed_error_message;
            SET @final_status = 'ABORTED_DEPENDENCY';
        END
        ELSE
        BEGIN
            EXEC dbo.sp_RankingRun_Finalize @run_id=@run_id, @status='FAILED', @notes=@failed_error_message;
            SET @final_status = 'FAILED';
        END
        GOTO return_result;
    END CATCH

    -- ===== Step 2: Orchestration - Data preparation =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 2, 'Orchestration', 'sp_Calculate_Ranking_Step2_DataPreparationforNewRun', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_Step2_DataPreparationforNewRun
            @category_code=@category_code, @year=@ranking_year, @month=@ranking_month, @week=@ranking_week, @run_id=@run_id,
            @rows_inserted=@ri OUTPUT, @rows_updated=@ru OUTPUT, @rows_deleted=@rd OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()),
            rows_inserted=@ri, rows_updated=@ru, rows_deleted=@rd, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=2; SET @failed_step_name='sp_Calculate_Ranking_Step2_DataPreparationforNewRun';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 3: Orchestration - Seed main_ranking =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 3, 'Orchestration', 'sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking
            @category_code=@category_code, @year=@ranking_year, @month=@ranking_month, @week=@ranking_week, @run_id=@run_id,
            @rows_inserted=@ri OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_inserted=@ri, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=3; SET @failed_step_name='sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 4: ResultsSelection - Manual modifications =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 4, 'ResultsSelection', 'sp_Rules_Set_Weekly_Events_ManualModifications', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_Set_Weekly_Events_ManualModifications
            @category_code=@category_code, @run_id=@run_id, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=4; SET @failed_step_name='sp_Rules_Set_Weekly_Events_ManualModifications';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 5: ResultsSelection - Results expiry =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 5, 'ResultsSelection', 'sp_Rules_UpdateEventsResultExpiry', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_UpdateEventsResultExpiry
            @category_code=@category_code, @year=@ranking_year, @week=@ranking_week, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=5; SET @failed_step_name='sp_Rules_UpdateEventsResultExpiry';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 6: ResultsSelection - Olympic expiry =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 6, 'ResultsSelection', 'sp_Rules_UpdateOlympicResultExpiry', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_UpdateOlympicResultExpiry @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=6; SET @failed_step_name='sp_Rules_UpdateOlympicResultExpiry';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 7: ResultsSelection - Best-of-10 selection =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 7, 'ResultsSelection', 'sp_Calculate_WTT_YOU_Ranking_BestResults', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_YOU_Ranking_BestResults @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=7; SET @failed_step_name='sp_Calculate_WTT_YOU_Ranking_BestResults';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 8: ResultsSelection - Zero-Point-Penalty (event_count=5) =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 8, 'ResultsSelection', 'sp_Calculate_WTT_Ranking_ZeroPointPenalty', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_Ranking_ZeroPointPenalty
            @category_code=@category_code, @event_count=5, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=8; SET @failed_step_name='sp_Calculate_WTT_Ranking_ZeroPointPenalty';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 9: RankingResultPositions - positions (Mandatory) =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 9, 'RankingResultPositions', 'sp_Calculate_WTT_Ranking_RankingPositions', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_Ranking_RankingPositions
            @category_code=@category_code, @run_id=@run_id, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=9; SET @failed_step_name='sp_Calculate_WTT_Ranking_RankingPositions';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 10: RankingResultPositions - age-category positions (Youth-only) =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 10, 'RankingResultPositions', 'Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory
            @run_id=@run_id, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=10; SET @failed_step_name='Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 11: Orchestration - Finalize =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 11, 'Orchestration', 'sp_Calculate_Ranking_FinalizeRun', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_FinalizeRun
            @category_code=@category_code, @run_id=@run_id, @rows_deleted=@rd OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_deleted=@rd, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=11; SET @failed_step_name='sp_Calculate_Ranking_FinalizeRun';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    EXEC dbo.sp_RankingRun_Finalize @run_id=@run_id, @status='SUCCEEDED', @notes=NULL;
    SET @final_status = 'SUCCEEDED';
    GOTO return_result;

    finalize_failed:
        EXEC dbo.sp_RankingRun_Finalize @run_id=@run_id, @status='FAILED', @notes=@failed_error_message;
        SET @final_status = 'FAILED';

    return_result:
        SELECT @run_id AS ranking_run_id, @final_status AS status, @failed_step_seq AS failed_step_seq,
               @failed_step_name AS failed_step_name, @failed_error_message AS error_message;
END
GO
```

**Legacy correspondence**: Same structural relationship to legacy `sp_Calculate_Ranking` as
`sp_Calculate_Ranking_SEN` (same source procedure — legacy calls it with `@CategoryCode='YOU'`,
same all-in-one-procedure caveats and Step 5 bug apply equally). Two things specific to this
Youth variant:
- **Step 1's `ABORTED_DEPENDENCY` branch has no legacy equivalent whatsoever** — see
  `Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun`'s notes: legacy's dependency guard cannot
  even reliably signal a distinct error number to its caller, so there is no legacy code path
  that could branch on "dependency not met" vs "any other failure" the way this `IF
  @dep_err_num = 51001` check does.
  Verified directly against the `youth_dependency_failure` sample fixture:
  `sp_Calculate_Ranking_YOU` lands the run at `ABORTED_DEPENDENCY` with zero business-table
  writes when no prior SEN run exists.
- Step count is 11 (vs SEN's 10) purely because of the extra Step 10 age-category-positions
  step — `docs/legacy_rule_mapping.md`'s verified rule table shows this exact extra step in the
  legacy Youth rule sequence too (`Calculate_WTT_YOU_Ranking_RankingPositions` (Mandatory) then
  `Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory` as its own additional rule).

---

## Part 7 — Stored Procedures: `db/procedures/import/`

### sp_ImportNewEventsResults (STORED PROCEDURE)

**Purpose**: Bulk-imports an entire parsed result CSV in one call via a table-valued parameter —
upserts competitors and events, then inserts every result row into `new_events_results` with
points computed via `fn_ComputeRankingPoints`.

**Current SQL**:
```sql
-- Bulk import via table-valued parameter (dbo.NewEventsResultTVP, see db/procedures/types/):
-- one network round trip and one server-side transaction regardless of file size. Points
-- computed via fn_ComputeRankingPoints (an unpivot of ranking_calc_main, see db/procedures/types/).
CREATE OR ALTER PROCEDURE dbo.sp_ImportNewEventsResults
    @rows dbo.NewEventsResultTVP READONLY, @imported_by NVARCHAR(100),
    @competitors_upserted INT OUTPUT, @events_upserted INT OUTPUT, @results_inserted INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        MERGE dbo.competitors AS tgt
        USING (SELECT DISTINCT competitor_id, player_name, dob, gender, country_code, age_category_code, is_retired FROM @rows) AS src
          ON tgt.competitor_id = src.competitor_id
        WHEN NOT MATCHED THEN
            INSERT (competitor_id, player_name, dob, gender, country_code, nationality_code, age_category_code, is_retired)
            VALUES (src.competitor_id, src.player_name, src.dob, src.gender, src.country_code, src.country_code, src.age_category_code, src.is_retired);
        SET @competitors_upserted = @@ROWCOUNT;

        MERGE dbo.events AS tgt
        USING (SELECT DISTINCT event_id, event_name, event_type_general_code, event_type_code, ranking_year, ranking_month, ranking_week FROM @rows) AS src
          ON tgt.event_id = src.event_id
        WHEN NOT MATCHED THEN
            INSERT (event_id, event_name, event_type_general_code, event_type_code, ranking_year, ranking_month, ranking_week)
            VALUES (src.event_id, src.event_name, src.event_type_general_code, src.event_type_code, src.ranking_year, src.ranking_month, src.ranking_week);
        SET @events_upserted = @@ROWCOUNT;

        INSERT INTO dbo.new_events_results
            (event_id, competitor_id, sub_event_code, result_position, matches_played, matches_won, matches_lost,
             qualifier, zero_point_penalty, ranking_category_code, age_category_code, category_code, ranking_points)
        SELECT r.event_id, r.competitor_id, r.sub_event_code, r.result_position, r.matches_played, r.matches_won, r.matches_lost,
               r.qualifier, r.zero_point_penalty, r.ranking_category_code, r.age_category_code, r.category_code,
               CASE WHEN r.zero_point_penalty = 1 THEN 0 ELSE ISNULL(pts.ranking_points, 0) END
        FROM @rows r
        OUTER APPLY dbo.fn_ComputeRankingPoints(r.category_code, r.age_category_code, r.ranking_category_code,
                                                 r.event_type_general_code, r.result_position, r.zero_point_penalty) pts;
        SET @results_inserted = @@ROWCOUNT;

        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH

    -- pyodbc cannot reliably read back OUTPUT parameters through {CALL} syntax -- see
    -- sp_RankingRun_lifecycle.sql notes -- so also surface the counts via a trailing SELECT.
    SELECT @competitors_upserted AS competitors_upserted, @events_upserted AS events_upserted,
           @results_inserted AS results_inserted;
END
GO
```

**Legacy correspondence**: Reimplemented with no single legacy source (see also
`NewEventsResultTVP` and `fn_ComputeRankingPoints` above). Legacy's import path is
`sp_Import_Web_EventsResults` (one `@EventId` at a time) → `ufnGetEventResultsForRanking_stat`
(the unexported points/position TVF). This procedure replaces that whole chain with one
whole-CSV bulk call: `MERGE ... WHEN NOT MATCHED` upserts for competitors/events (legacy uses
separate, per-event `SP_Import_Step3_Web_NewRankingPlayers`/`SP_Import_Step4_Web_NewDoubles`
procedures for this, not visible in this call), and `fn_ComputeRankingPoints` instead of the
unexported TVF for points. Legacy's `sp_Import_Web_EventsResults` also **excludes team events**
(`WHERE SubEventCode NOT IN ('WT','MT')`) at import time — this procedure has no equivalent
filter; team-coded rows would import here if present in a source file.

### sp_MirrorCrossCategoryResult (STORED PROCEDURE)

**Purpose**: SEN↔YOU cross-award mirroring — copies an eligible result into the other category
at a multiplier (5× Senior→Youth, 1× Youth→Senior). Deployed and tested, but **not wired into
`sp_ImportNewEventsResults` or any live web route** — matching the SQLite prototype's original
documented status as a tested-but-dormant function, preserved intentionally rather than
silently activated.

**Current SQL**:
```sql
-- Port of importer/cross_award.py::mirror_cross_category_result. Direct set-based port of
-- the SEN<->YOU cross-award mirroring. Preserved as-is: NOT wired into sp_ImportNewEventsResults
-- or any live route in this migration (matching the prototype, where it exists as a tested but
-- dormant function) -- flagged for a follow-up decision, not silently activated.
CREATE OR ALTER PROCEDURE dbo.sp_MirrorCrossCategoryResult
    @source_category_code NVARCHAR(3), @rows_inserted INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @target_category_code NVARCHAR(3), @multiplier DECIMAL(10,2);
    IF @source_category_code = 'SEN' BEGIN SET @target_category_code = 'YOU'; SET @multiplier = 5; END
    ELSE IF @source_category_code = 'YOU' BEGIN SET @target_category_code = 'SEN'; SET @multiplier = 1; END
    ELSE THROW 51200, 'source_category_code must be SEN or YOU', 1;

    BEGIN TRAN;
    BEGIN TRY
        INSERT INTO dbo.new_events_results
            (event_id, competitor_id, sub_event_code, result_position, matches_played, matches_won, matches_lost,
             qualifier, result_type, zero_point_penalty, last_phase_win, ranking_category_code, age_category_code,
             category_code, organization_code, ranking_points, cross_awarded_from_event_id)
        SELECT n.event_id, n.competitor_id, n.sub_event_code, n.result_position, n.matches_played, n.matches_won, n.matches_lost,
               n.qualifier, n.result_type, n.zero_point_penalty, n.last_phase_win, n.ranking_category_code, n.age_category_code,
               @target_category_code, n.organization_code, ISNULL(n.ranking_points, 0) * @multiplier, n.event_id
        FROM dbo.new_events_results n
        JOIN dbo.competitors c ON c.competitor_id = n.competitor_id
        WHERE n.category_code = @source_category_code AND n.cross_awarded_from_event_id IS NULL
          AND (
                (@source_category_code = 'SEN' AND c.age_category_code IS NOT NULL AND c.age_category_code <> 'SEN')
             OR (@source_category_code = 'YOU' AND c.age_category_code = 'U19')
          )
          AND NOT EXISTS (
              SELECT 1 FROM dbo.new_events_results m
              WHERE m.cross_awarded_from_event_id = n.event_id AND m.competitor_id = n.competitor_id AND m.category_code = @target_category_code
          );
        SET @rows_inserted = @@ROWCOUNT;
        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH

    SELECT @rows_inserted AS rows_inserted;
END
GO
```

**Legacy correspondence**: Direct read of legacy `sp_Import_Step2_Web_OVRResultsToNewEventResults`
(the SP that contains this mirroring logic inline — there is no separately-named legacy
procedure for it) confirms the ×5/U19 concept matches, but with real, specific differences:
- **The ×5 multiplier and `RankingPoints > 0` gate match exactly** (`n.[RankingPoints] * 5`,
  `c.AgeCategoryCode NOT IN ('SEN')`), but legacy's SEN→YOU mirror is **restricted to
  `RankingCategoryCode IN ('MS','WS','MDI','WDI','XDI')`** (singles and individual-doubles only —
  no `MD`/`WD`/`XD` pair mirroring); this port applies to any `ranking_category_code` with no
  such restriction.
- Legacy also has a **`SENYSC19` special case** entirely absent from this port: for events typed
  `EventTypeGeneralCode='SENYSC19'` (WTT Youth Star Contender), it overrides
  `RankingPoints` for group-stage losers directly (`ResultPosition='G2L' → 2 points`,
  `'GL' → 1 point`) before the ×5 mirror runs — a documented, one-off event-type rule this port
  does not replicate.
- **The YOU→SEN direction is fundamentally different logic, not just a different multiplier.**
  Legacy does **not** simply copy a Youth U19 result's points at 1× — it looks up the
  SEN-equivalent points via `vw_WTT_RankingCalcMain` joined through `EventAgeCategeory` (mapping
  the same event/phase/ranking-category to its Senior-scale points), restricted to events
  explicitly flagged `EventAgeCategeory.AgeCategoryCode='SEN'` for that `EventId`. **This port's
  `@multiplier=1` for the YOU→SEN direction is a simplification** — it copies the Youth result's
  already-computed points verbatim rather than recomputing them against the Senior points scale,
  because `EventAgeCategeory` (the legacy mapping table) isn't part of this prototype's schema.
- **Deployment/wiring**: legacy runs this inline, automatically, as part of every single-event
  import (`sp_Import_Web_EventsResults` → `sp_Import_Step2_Web_OVRResultsToNewEventResults`);
  this port is a standalone, independently callable procedure that nothing currently calls
  automatically — a deliberate scope decision carried forward unchanged from the SQLite version
  of this prototype.

### sp_SearchNewEventsResults (STORED PROCEDURE)

**Purpose**: Filterable search over `new_events_results` (by category/player-name/country) for
the Manual Modifications screen.

**Current SQL**:
```sql
-- Ports of importer/modify_new_events_results.py: search + single-row edit for the Manual
-- Modifications screen.
CREATE OR ALTER PROCEDURE dbo.sp_SearchNewEventsResults
    @category_code NVARCHAR(3) = NULL, @player_name NVARCHAR(200) = NULL, @country_code NVARCHAR(5) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SELECT n.new_event_result_id, n.competitor_id, c.player_name, c.country_code, n.event_id, e.event_name,
           e.event_type_general_code, n.sub_event_code, n.ranking_category_code, n.category_code, n.age_category_code,
           n.result_position, n.ranking_points, n.zero_point_penalty
    FROM dbo.new_events_results n
    JOIN dbo.competitors c ON c.competitor_id = n.competitor_id
    JOIN dbo.events e ON e.event_id = n.event_id
    WHERE (@category_code IS NULL OR n.category_code = @category_code)
      AND (@player_name IS NULL OR c.player_name LIKE '%' + @player_name + '%')
      AND (@country_code IS NULL OR c.country_code LIKE '%' + @country_code + '%')
    ORDER BY n.new_event_result_id;
END
GO
```

**Legacy correspondence**: NEW — no legacy equivalent. The Manual Modifications
pre-calculation-edit feature this powers was added to this prototype at the user's explicit
request during the SQLite-prototype phase of this project; the legacy system's *own*
manual-modification mechanism (`PlayersEventsResultsMaster_Modified`, applied mid-calculation —
see `sp_Rules_Set_Weekly_Events_ManualModifications`) is a different table/workflow entirely
with no equivalent search screen or procedure in the exported source.

### sp_UpdateNewEventResultPosition (STORED PROCEDURE)

**Purpose**: Applies one manual edit to a `new_events_results` row's result position, recomputes
its points via `fn_ComputeRankingPoints`, and logs the before/after to
`new_events_results_modification_log`.

**Current SQL**:
```sql
CREATE OR ALTER PROCEDURE dbo.sp_UpdateNewEventResultPosition
    @new_event_result_id INT, @new_result_position NVARCHAR(10), @modified_by NVARCHAR(100),
    @old_result_position NVARCHAR(10) OUTPUT, @new_ranking_points DECIMAL(10,2) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    -- Same 19-code allow-list as fn_ComputeRankingPoints covers (importer.EDITABLE_RESULT_POSITIONS).
    IF @new_result_position NOT IN ('W','F','SF','QF','R16','R32','R64','R128','R256','QUAL','QER','QR1','QR2','QR3','QR4','GL','G2L','G3L','G4L')
        THROW 51300, 'Unrecognized result position', 1;

    DECLARE @competitor_id INT, @event_id INT, @category_code NVARCHAR(3), @age_category_code NVARCHAR(10),
            @ranking_category_code NVARCHAR(10), @event_type_general_code NVARCHAR(10), @zpp BIT, @old_points DECIMAL(10,2);

    SELECT @competitor_id = n.competitor_id, @event_id = n.event_id, @category_code = n.category_code,
           @age_category_code = n.age_category_code, @ranking_category_code = n.ranking_category_code,
           @event_type_general_code = e.event_type_general_code, @zpp = n.zero_point_penalty,
           @old_result_position = n.result_position, @old_points = n.ranking_points
    FROM dbo.new_events_results n JOIN dbo.events e ON e.event_id = n.event_id
    WHERE n.new_event_result_id = @new_event_result_id;

    IF @competitor_id IS NULL THROW 51301, 'new_events_results row not found', 1;

    IF @zpp = 1
        SET @new_ranking_points = 0;
    ELSE
        SELECT @new_ranking_points = ISNULL(pts.ranking_points, 0)
        FROM dbo.fn_ComputeRankingPoints(@category_code, @age_category_code, @ranking_category_code, @event_type_general_code, @new_result_position, @zpp) pts;
    IF @new_ranking_points IS NULL SET @new_ranking_points = 0;

    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.new_events_results SET result_position = @new_result_position, ranking_points = @new_ranking_points
        WHERE new_event_result_id = @new_event_result_id;

        INSERT INTO dbo.new_events_results_modification_log
            (new_event_result_id, competitor_id, event_id, old_result_position, new_result_position,
             old_ranking_points, new_ranking_points, modified_by, modified_at)
        VALUES (@new_event_result_id, @competitor_id, @event_id, @old_result_position, @new_result_position,
                @old_points, @new_ranking_points, @modified_by, SYSUTCDATETIME());
        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH

    -- pyodbc cannot reliably read back OUTPUT parameters through {CALL} syntax -- see
    -- sp_RankingRun_lifecycle.sql notes -- so also surface the before/after via a trailing SELECT.
    SELECT @old_result_position AS old_result_position, @new_result_position AS new_result_position,
           @old_points AS old_ranking_points, @new_ranking_points AS new_ranking_points;
END
GO
```

**Legacy correspondence**: NEW — no legacy equivalent, same reasoning as
`sp_SearchNewEventsResults`. The `THROW 51300`/`51301` sentinel guards (unrecognized position /
row not found) are new validation this feature required and legacy has no equivalent for, since
no legacy procedure edits `NewEventsResults` interactively pre-calculation at all.

---

## Part 8 — Stored Procedures: `db/procedures/validation/`

### SP_Ranking_DataValidation (STORED PROCEDURE)

**Purpose**: Orchestrates the individual validation-check procedures for either
`PreRankingValidation` or `PostRankingValidation`, then returns the findings just recorded via a
trailing `SELECT`.

**Current SQL**:
```sql
-- Port of validation/run_validation.py::SP_Ranking_DataValidation. Orchestrates the checks
-- above (kept as separate procedures, mirroring validation/checks/*.py 1:1 for testability),
-- then returns the findings just recorded via a final SELECT for direct rendering.
CREATE OR ALTER PROCEDURE dbo.SP_Ranking_DataValidation
    @category_code NVARCHAR(3), @run_id INT, @validation_category NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;
    IF @validation_category NOT IN ('PreRankingValidation','PostRankingValidation')
        THROW 51400, 'validation_category must be PreRankingValidation or PostRankingValidation', 1;

    IF @validation_category = 'PreRankingValidation'
    BEGIN
        EXEC dbo.sp_ValidateNullPoints @category_code=@category_code, @run_id=@run_id, @validation_category=@validation_category;
        EXEC dbo.sp_ValidateDuplicateResults @category_code=@category_code, @run_id=@run_id, @validation_category=@validation_category;
    END
    ELSE
    BEGIN
        EXEC dbo.sp_ValidateDuplicateResults @category_code=@category_code, @run_id=@run_id, @validation_category=@validation_category;
        EXEC dbo.sp_ValidatePointsPositionMismatch @run_id=@run_id, @validation_category=@validation_category;
    END

    SELECT * FROM dbo.ranking_validation_result WHERE ranking_run_id = @run_id AND validation_category = @validation_category
    ORDER BY ranking_validation_result_id;
END
GO
```

**Legacy correspondence**: Direct read of legacy `SP_Ranking_DataValidation` confirms this is a
deliberate, documented, large reduction in scope, not a syntax-level port.
- Legacy's `PreRankingValidation` branch runs **5 distinct checks**: null-points-in-log,
  DT_RANKING-vs-`NewEventsResults` completeness, `NewEventsResults`↔`OVRResultPositions`
  mapping validity, and 4 separate "missing player/pair details" checks (singles competitor,
  doubles pair, doubles player1, doubles player2) — populated into a `#tempprereqvalidation`
  temp table. **This port runs 2**: `sp_ValidateNullPoints`, `sp_ValidateDuplicateResults`.
- Legacy's `PostRankingValidation` branch runs **4 distinct checks**: a "Missing YOU
  RANKINGPOINTS" check (a Senior result with no corresponding cross-awarded Youth mirror, joined
  through `EventTypeGeneral`), a null-`RANKINGPOINTS` check, a duplicate-results check (in both
  `PlayersEventsResultsMaster` and `MainRanking` separately), and the
  points-vs-breakdown reconciliation check (with an additional retired-doubles-pair exclusion
  and an age-category `sen`/`you` inference this port's version doesn't have). **This port runs
  2**: `sp_ValidateDuplicateResults` (a single combined check, not two separate table checks) and
  `sp_ValidatePointsPositionMismatch` (against `main_ranking` only, not
  `PlayersEventsResultsMaster`'s own internal duplicate check).
- Legacy **wipes and re-populates** `Ranking_Validation_Summary` for the period at the top of
  every call (`DELETE FROM [Ranking_Validation_Summary] WHERE rankingyear=... AND
  rankingWeek=...`); this port's `ranking_validation_result` table is append-only per `run_id`
  (see that table's notes) — no delete happens here at all.
- Legacy is parametrized by `@RankingYear, @RankingWeek, @Categorycode`; this port is
  parametrized by `@run_id` directly — a stronger, unambiguous key for "which run's findings",
  consistent with the same design change made throughout the run/audit model.

### sp_ValidateNullPoints (STORED PROCEDURE)

**Purpose**: PreRankingValidation check — flags any `new_events_results` row with a NULL
`ranking_points` value.

**Current SQL**:
```sql
CREATE OR ALTER PROCEDURE dbo.sp_ValidateNullPoints
    @category_code NVARCHAR(3), @run_id INT, @validation_category NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM dbo.new_events_results WHERE category_code = @category_code AND ranking_points IS NULL)
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, competitor_id, event_id, created_at)
        SELECT @run_id, @validation_category, 'Null Points Validation', 0,
               'new_events_results row has a NULL ranking_points value', 'new_events_results', competitor_id, event_id, SYSUTCDATETIME()
        FROM dbo.new_events_results WHERE category_code = @category_code AND ranking_points IS NULL;
    ELSE
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, created_at)
        VALUES (@run_id, @validation_category, 'Null Points Validation', 1, 'No NULL ranking_points found', 'new_events_results', SYSUTCDATETIME());
END
GO
```

**Legacy correspondence**: Direct/near-direct port of one specific check inside legacy
`SP_Ranking_DataValidation`'s `PreRankingValidation` branch (the `RANKINGPOINTS IS NULL` `SELECT`
against `PlayersEventsResultsMaster_log`/`_log_Archives`, year-gated by whether `@Rankingyear =
YEAR(GETDATE())`). This port checks `new_events_results` directly (this prototype has no
`_log`/`_log_Archives` distinction) and always records a pass/fail summary row regardless of
outcome, unlike legacy's version which only ever emits a raw result set for this specific
sub-check, with no explicit "passed" row recorded when clean.

### sp_ValidateDuplicateResults (STORED PROCEDURE)

**Purpose**: Flags duplicate active `players_events_results_master` rows for the same
competitor/event/ranking-category key.

**Current SQL**:
```sql
CREATE OR ALTER PROCEDURE dbo.sp_ValidateDuplicateResults
    @category_code NVARCHAR(3), @run_id INT, @validation_category NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM dbo.players_events_results_master
        WHERE category_code = @category_code AND active = 1
        GROUP BY competitor_id, event_id, ranking_category_code
        HAVING COUNT(*) > 1
    )
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, competitor_id, event_id, created_at)
        SELECT @run_id, @validation_category, 'Duplicated Results Validation', 0,
               CONCAT(COUNT(*), ' active rows share this (competitor, event, ranking_category) key'),
               'players_events_results_master', competitor_id, event_id, SYSUTCDATETIME()
        FROM dbo.players_events_results_master
        WHERE category_code = @category_code AND active = 1
        GROUP BY competitor_id, event_id, ranking_category_code
        HAVING COUNT(*) > 1;
    ELSE
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, created_at)
        VALUES (@run_id, @validation_category, 'Duplicated Results Validation', 1, 'No duplicate active results found', 'players_events_results_master', SYSUTCDATETIME());
END
GO
```

**Legacy correspondence**: Direct/near-direct port, but **collapses two separate legacy checks
into one**. Legacy runs this duplicate-detection logic **twice, independently**: once against
`PlayersEventsResultsMaster` (partitioned by `CompetitorId, EventId, SubEventCode,
RankingCategoryCode, AgeCategoryCode, CategoryCode, RankingYear, RankingMonth, RankingWeek,
Active, ResultPosition`) and once against `MainRanking` (partitioned by `CompetitorId,
RankingCategory, AgeCategoryCode, CategoryCode, RankingYear, RankingMonth, RankingWeek`), each
producing its own separate `Ranking_Validation_Summary` row set. This port checks only
`players_events_results_master`, with a simpler partition key (`competitor_id, event_id,
ranking_category_code`) — the equivalent `main_ranking` duplicate check does not exist here.

### sp_ValidatePointsPositionMismatch (STORED PROCEDURE)

**Purpose**: PostRankingValidation check — verifies each `main_ranking` row's total points
exactly matches the sum of its counted `players_events_results_master` breakdown rows.

**Current SQL**:
```sql
-- Port of validation/checks/points_position_mismatch.py. With DECIMAL(10,2) points (see
-- db/schema_mssql.sql), the reconciliation is an EXACT comparison -- no 1e-9 float tolerance
-- needed, unlike the SQLite/Python original.
CREATE OR ALTER PROCEDURE dbo.sp_ValidatePointsPositionMismatch
    @run_id INT, @validation_category NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM dbo.main_ranking mr
        WHERE mr.ranking_run_id = @run_id
          AND mr.ranking_points <> ISNULL((
              SELECT SUM(p.ranking_points) FROM dbo.players_events_results_master p
              WHERE p.competitor_id = mr.competitor_id AND p.ranking_category_code = mr.ranking_category
                AND p.category_code = mr.category_code AND p.active = 1 AND p.best_result_no_sen_you = 1
          ), 0)
    )
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, competitor_id, total_points, main_ranking_points, created_at)
        SELECT @run_id, @validation_category, 'MainRanking vs BreakDown Validation', 0,
               CONCAT('main_ranking.ranking_points (', mr.ranking_points, ') != breakdown sum (', x.breakdown, ')'),
               'main_ranking', mr.competitor_id, x.breakdown, mr.ranking_points, SYSUTCDATETIME()
        FROM dbo.main_ranking mr
        CROSS APPLY (SELECT ISNULL((
            SELECT SUM(p.ranking_points) FROM dbo.players_events_results_master p
            WHERE p.competitor_id = mr.competitor_id AND p.ranking_category_code = mr.ranking_category
              AND p.category_code = mr.category_code AND p.active = 1 AND p.best_result_no_sen_you = 1
        ), 0) AS breakdown) x
        WHERE mr.ranking_run_id = @run_id AND mr.ranking_points <> x.breakdown;
    ELSE
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, created_at)
        VALUES (@run_id, @validation_category, 'MainRanking vs BreakDown Validation', 1,
                'All main_ranking row(s) reconcile with their points breakdown', 'main_ranking', SYSUTCDATETIME());
END
GO
```

**Legacy correspondence**: Direct/near-direct port of the "validate playereventresultmaster
total against mainranking" check inside legacy `SP_Ranking_DataValidation`'s
`PostRankingValidation` branch (the `#temp3`/`#temp4` blocks).
- **This port's comparison is an exact `<>`** (both sides are `DECIMAL(10,2)`); legacy's
  original SQLite/Python prototype this was ported from needed a `1e-9` float-tolerance
  workaround for the equivalent check — no longer necessary here since points are `DECIMAL`
  throughout this schema, not `FLOAT`.
- Legacy's version additionally **excludes retired doubles pairs**
  (`t.competitorid NOT IN (SELECT doublesid FROM players_doubles d JOIN Competitors c1... WHERE
  c1.IsRetired=1 OR c2.IsRetired=1)`) and infers whether a competitor is being checked as
  `'sen'` or `'you'` from their own `agecategorycode` (`CASE WHEN agecategorycode IS NULL OR ''
  THEN '' WHEN <> 'sen' THEN 'you' ELSE 'sen' END = t.categorycode`) as an extra correctness
  gate — this port has neither the retired-doubles exclusion nor the age-category cross-check;
  it reconciles every `main_ranking` row unconditionally.
- Legacy computes the "breakdown" sum gated by `PlayerBestRankingResultNumber > 0 AND
  ExcludedDuetoZeroPointPenalty IS NULL`; this port's equivalent gate is `active = 1 AND
  best_result_no_sen_you = 1` — matching in spirit (only counted, non-excluded rows contribute)
  but expressed against this schema's own flag set rather than legacy's exact column names/NULL
  semantics.

---

## Part 9 — Stored Procedures: `db/procedures/admin/`

### sp_ResetDemoData (STORED PROCEDURE)

**Purpose**: Powers the Dashboard's "Clear Database (Demo Reset)" button — wipes every import,
run, and manual modification so the app can be demoed repeatedly from a clean slate, without
touching reference data or user accounts.

**Current SQL**:
```sql
-- Powers the dashboard's "Clear Database (Demo Reset)" button. Clears every import, run, and
-- manual modification so the app can be demoed from a clean slate repeatedly -- but,
-- deliberately unlike the old SQLite prototype's full schema rebuild, this does NOT touch
-- reference data (categories/ranking_calc_main/etc, which are static) or the RBAC tables
-- (app_role/app_user/app_user_audit_log): resetting demo data must never delete user accounts
-- or their audit history.
CREATE OR ALTER PROCEDURE dbo.sp_ResetDemoData
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        DELETE FROM dbo.new_events_results_modification_log;
        DELETE FROM dbo.new_events_results;
        DELETE FROM dbo.ranking_validation_result;
        DELETE FROM dbo.main_ranking;
        DELETE FROM dbo.players_events_results_master_modified;
        DELETE FROM dbo.players_events_results_master;
        DELETE FROM dbo.ranking_run_error;
        DELETE FROM dbo.ranking_run_step;
        DELETE FROM dbo.ranking_run;
        DELETE FROM dbo.players_doubles;
        DELETE FROM dbo.events;
        DELETE FROM dbo.competitors;

        UPDATE dbo.ranking_engine_info SET current_ranking_year = 2026, current_ranking_month = 1, current_ranking_week = 1;
        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
```

**Legacy correspondence**: NEW — no legacy equivalent (a production ranking system has no
"reset the demo" concept). This also has no equivalent in the earlier SQLite version of this
prototype either, which reset by fully rebuilding the schema from `schema.sql`/`views.sql`/seed
data (`db/init_db.py`, now removed) — a much heavier operation that would also have deleted RBAC
data. This procedure is deliberately narrower: it clears only business/audit/run tables and
explicitly leaves reference data (`categories`, `ranking_calc_main`, etc.) and the RBAC tables
(`app_role`/`app_user`/`app_user_audit_log`) untouched, so a demo reset can never delete user
accounts or lock an operator out.

---

## Summary

| Category | Count |
|---|---|
| Tables | 29 (26 core/audit + 3 RBAC) |
| Views | 7 |
| Table types | 1 |
| Inline functions | 1 |
| Stored procedures | 30 (10 steps-folder files defining 14 procedures + 4 master-folder files defining 7 procedures + 3 import-folder files defining 4 procedures + 4 validation-folder files defining 4 procedures + 1 admin-folder file defining 1 procedure) |

Every object with a plausible legacy correspondence was verified by directly reading the
matching file under `C:\vatsan\ranking\RANKINGS2026\SPS\` or `...\views\`, not inferred from
naming alone. The only objects without a specific legacy source to compare against are, by
design, the ones with no legacy analogue at all (the RBAC subsystem, the audit/orchestration
tables and views, the master procedures' shared helpers, and the demo-reset procedure) — these
are clearly marked "NEW" above rather than guessed at.
