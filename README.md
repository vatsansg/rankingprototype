# WTT Ranking Engine — SQLite Prototype

A from-scratch, fully auditable reimplementation of the WTT (World Table Tennis) Senior and
Youth ranking calculation, replacing the legacy SQL Server dynamic-SQL rule engine
(`RulesSet`/`RulesGroup`/`Rules`/`RulesAlias` → `sp_Rules_ExecuteRule` builds and executes a
SQL string per rule) with two fixed, explicit, directly-callable "stored procedures" —
`sp_Calculate_Ranking_SEN()` and `sp_Calculate_Ranking_YOU()` — backed by SQLite and full
step-by-step audit logging.

The legacy system under `C:\vatsan\ranking\RANKINGS2026` (outside this `prototype/` folder)
was reverse-engineered but never modified. See `..\..\` (the repo root) for the original
documentation, stored-procedure source, and table exports this prototype was built from.

## Why this exists

The legacy system works but is hard to audit: run/step status is free text, no row counts are
captured, several procedures have no error handling at all, at least three call sites silently
swallow child-procedure failures (dead output-variable bindings), one position-tiebreak
procedure uses `NEWID()` (non-reproducible), and the alias-resolution mechanism is invisible to
static analysis — you cannot tell what actually ran without querying live configuration data.
This prototype makes every calculation run fully traceable: a unique run ID, a unique step ID
per procedure call, real start/end timestamps, row counts, persisted errors, and a failed step
that can never masquerade as a successful run.

## Architecture

```
Flask UI (web/app.py)
  │
  ├─ Import Results ──────► importer/load_new_events_results.py ──► new_events_results
  ├─ Start Calculation ───► engine/master.py::sp_Calculate_Ranking_SEN() / _YOU()
  │                            │
  │                            ├─ engine/step_runner.py::step()   (per-step commit + audit)
  │                            ├─ engine/procedures/*.py           (one function per legacy SP)
  │                            └─ engine/run_registry.py           (ranking_run lifecycle)
  ├─ Dashboard ────────────► db/views.sql (vw_RankingRunSummary, vw_RankingRunProgress, ...)
  └─ Rankings ─────────────► vw_RankingResult
```

Every legacy stored procedure in the calculation path became exactly one Python function,
**named identically to the legacy procedure it replaces** (e.g.
`sp_Calculate_WTT_SEN_Ranking_BestResults`), living in `engine/procedures/`. `master.py` calls
these functions **directly, in a fixed, hardcoded sequence** — there is no rules-table config
layer and no dynamic dispatch of any kind. See `docs/legacy_rule_mapping.md` for the full
legacy-SP → prototype-function mapping and the verified real execution order (derived from
`data/dbo_Rules.csv`, not guessed).

## Design decisions worth knowing before reading the code

1. **No rules-config tables.** `RulesSet`/`RulesGroup`/`Rules`/`RulesAlias` are not ported into
   the SQLite schema. Changing the calculation sequence means editing `engine/master.py`
   directly. This was an explicit, deliberate choice: total transparency over runtime
   configurability.

2. **Per-step transactions, not one giant per-run transaction.** Each step in
   `engine/step_runner.py` is its own `BEGIN...COMMIT`/`ROLLBACK`. A naive "one transaction for
   the whole run" design was considered and rejected: SQLite writes inside an open transaction
   are invisible to any other connection until `COMMIT`, so a live progress dashboard (a
   separate Flask request polling the database while a run is `RUNNING`) could never see
   intermediate step completions under a single run-long transaction. The tradeoff: **"a failed
   run never looks successful" is enforced at the query layer**, not via whole-run rollback —
   `vw_RankingResult` only ever surfaces `main_ranking` rows belonging to a run with
   `status='SUCCEEDED'`. A `FAILED` run's earlier, already-committed steps remain in the
   business tables (tagged with that run's `ranking_run_id`) for forensic inspection, but are
   never presented as published ranking output.

3. **Scheduling records intent; it does not auto-fire.** The Flask UI's "Schedule" action
   inserts a `ranking_run` row at `status='PENDING'` with `trigger_type='scheduled'` and a
   `scheduled_for` timestamp, visible on the Dashboard. A human clicks **Run Now** to actually
   execute it. There is no background scheduler/cron in this prototype, and no recurring
   weekly schedules — both were explicitly scoped out in favor of the simpler "record + manual
   fire" model.

4. **Synchronous execution.** `sp_Calculate_Ranking_SEN`/`_YOU` run inside the Flask request
   that triggers them — there is no background worker. For the small sample datasets this
   completes in well under a second, so in practice a run is usually already `SUCCEEDED`/`FAILED`
   by the time the browser reaches the Run Detail page. The per-step-commit model means the
   architecture is still correct for a longer-running dataset (a concurrent request would see
   completed steps land in real time) — a background worker (Celery, RQ, or a plain thread) is
   the natural next step for that, not a schema or transaction-model change.

5. **Trimmed schema.** ~25 tables are implemented (the ones actually on the Senior/Youth
   calculation + audit path); the other ~65 legacy tables (TTU raw mirrors, historical/reporting,
   OVR export tables, etc.) are catalogued below but not built. See the full inventory appendix.

## Setup

```
cd prototype/rankingapp
pip install flask pytest
python db/init_db.py          # builds rankingapp.db from schema.sql + views.sql + seed data
python sample_data/generate.py  # regenerates the 5 sample fixtures (idempotent, no RNG)
python -m pytest -q           # 15 tests
python web/app.py             # http://127.0.0.1:5000/
```

## Using it

1. **Import Results** — pick a sample fixture (`senior_happy_path`, `youth_happy_path`, etc.)
   and import it into `new_events_results`.
2. **Start Calculation** — choose Senior / Youth / Both, a ranking year/month/week, and either
   **Run Now** or **Schedule**. Youth requires a prior successful Senior run for the same period
   (enforced by `Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun`, called explicitly before any
   write transaction opens).
3. **Dashboard** — every run, its status, step counts, and duration; a **Run Now** button on any
   still-`PENDING` scheduled run.
4. **Run Detail** — the full step-by-step trace (`vw_RankingRunStepAudit`), row counts, timing,
   and — on failure — the exact error message and traceback (`vw_RankingRunErrors`). A **Run
   Post-Ranking Validation** button invokes `SP_Ranking_DataValidation`.
5. **Rankings** — the published ranking output (`vw_RankingResult`), filterable by category.

## The two master "stored procedures"

```python
from engine.master import sp_Calculate_Ranking_SEN, sp_Calculate_Ranking_YOU

run_id = sp_Calculate_Ranking_SEN(2026, 1, 1, triggered_by="you@example.com")
run_id = sp_Calculate_Ranking_YOU(2026, 1, 1, triggered_by="you@example.com")  # requires SEN success first
```

Senior sequence (10 steps) / Youth sequence (11 steps) — see `docs/legacy_rule_mapping.md` for
the full table with legacy rule names and the CSV evidence each step order was derived from.

## Audit model

- `ranking_run` — one row per calculation, with `status` (`PENDING`/`RUNNING`/`SUCCEEDED`/
  `FAILED`/`ABORTED_DEPENDENCY`), real `started_at`/`finished_at`, `trigger_type`,
  `scheduled_for`, `input_snapshot_hash` (sha256 of the in-scope `new_events_results` rows, for
  reproducibility), and `current_active`/`superseded_by_run_id` for re-run history.
- `ranking_run_step` — one row per executed prototype procedure: sequence number, group label,
  the exact function name, status, timestamps, duration, and rows inserted/updated/deleted.
- `ranking_run_error` — tied to both the run **and** the specific step, with the Python
  exception type, message, and full traceback.
- `ranking_run_metric` — free-form named metrics per step (available for future use).
- `ranking_validation_result` — post-run data-quality findings, retained as history (the legacy
  equivalent table was wiped and re-populated every run).

## Known limitations (documented, not silently glossed over)

- **Missing alias-resolution UDFs.** The legacy `@#TOKEN#@` string-substitution engine lives in
  SQL Server UDFs (`ufnrule_General_EvaluateAlias`, `ufnGeneral_EvaluateRulesConfig`, etc.) not
  present in the exported `SPS/` folder — only the calling pattern in `sp_Rules_ExecuteRule` was
  visible. Irrelevant to this prototype's architecture (no dynamic dispatch), but means the
  *exact* legacy substitution semantics could not be verified byte-for-byte.
- **Missing import TVF.** `ufnGetEventResultsForRanking_stat`, which derives points/positions
  during the legacy import, is not present in the exported source. `importer/load_new_events_results.py`
  computes points directly from `result_position` + `ranking_calc_main` instead — a reasonable,
  tested reconstruction, not a guaranteed match to the unseen original.
- **13 of ~16 validation sub-checks not ported** — see `validation/README.md`.
- **No live TTU sync** — `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU` is a documented stub.
- **No `Sp_Process_ScheduledtoPublish` equivalent** — the prototype has `PENDING`/`RUNNING`/
  `SUCCEEDED`/`FAILED`/`ABORTED_DEPENDENCY` run states but no separate "Published" workflow
  state; `current_active` tracks the latest successful run per period instead.
- **Reference-data gaps inherited from the legacy export**: e.g. `ranking_calc_main` has no
  Youth-U17 `MD` (mixed doubles) points row — a genuine gap in the source CSV, not a prototype
  bug (see `sample_data/README.md`'s youth fixture notes for how this was worked around).
- **No recurring/weekly auto-scheduling** — see Design decision 3 above.

## Testing

`tests/` (15 tests, `python -m pytest -q`) covers: the step-runner's commit/rollback/audit
behavior, full Senior and Youth end-to-end runs against the sample fixtures (best-of-X trimming,
the continental-event cap, ZPP handling, the doubles age-category fix), the Youth dependency
guard, a controlled mid-calculation failure, validation checks, tie-break determinism, the
import loader, and the SEN↔YOU cross-award mirroring.

## Project layout

```
rankingapp/
  README.md, docs/legacy_rule_mapping.md
  db/schema.sql, db/views.sql, db/init_db.py, db/seed/
  engine/master.py, engine/step_runner.py, engine/run_registry.py, engine/constants.py,
        engine/procedures/*.py
  importer/load_new_events_results.py, importer/cross_award.py
  validation/run_validation.py, validation/checks/*.py, validation/README.md
  web/app.py, web/templates/*.html
  sample_data/generate.py, sample_data/README.md, sample_data/<5 fixtures>/
  tests/*.py
```

## Full legacy table inventory (catalogued; ✅ = implemented in this prototype)

Categorized per the reverse-engineering brief. ~25 of ~87 legacy tables are implemented; the
rest are listed here for completeness of the audit trail but were judged out of scope for a
calculation-and-audit-focused prototype (mostly TTU raw-import mirrors and historical/reporting
tables with no bearing on the Senior/Youth calculation itself).

**1. Master / reference data** — `Countries` ✅(as reference within `competitors.country_code`,
no separate table), `Countries_TTU`, `Continents`, `Organization`, `Organization_TTU`,
`Categories` ✅, `Age_Categories` ✅, `RankingCategories` ✅, `EventTypes`, `EventTypeGeneral`,
`EventTypeCategories`, `EventTypeCategories_PointsDrawType`, `EventCoreTypes_TTU`,
`SubEventTypes`, `SubeventsCodes`, `SubeventsCodes_Description`, `EventPenaltyTypes`,
`ModificationType` ✅, `ReasonType` ✅, `ResultPosition` ✅, `RankingCalcMain`,
`RankingCalcMain_New` ✅ (source for `ranking_calc_main`)

**2. Configuration** — `RulesSet`, `RulesGroup`, `Rules`, `RulesAlias` (all catalogued only —
see "No rules-config tables" above), `AvailableRankingRuns` ✅, `AvailableRankingRunsCategories` ✅,
`RankingEngineInfo` ✅, `Schedule` ✅, `EventCategoryCode_Mapping`, `SubEventDependentCategories`

**3. Event data** — `Events` ✅ (trimmed columns), `Events_TTU`, `EventBasics`,
`EventCompetitions_TTU`, `EventAgeCategeory`, `EventAgeCategory_New`,
`EventTournamentAgeCategoriesLinked_TTU`, `EventTournamentCategories_TTU`,
`EventTournamentCategoriesLinked_TTU`, `EventTournamentCategoryGroup_TTU`,
`EventTournamentPrizeMoney_TTU`, `EventTournamentRestrictions_TTU`,
`EventTournamentSubEventAgeCategoriesLinked_TTU`, `SubEvents`, `SubEvents_TTU`, `tournaments`,
`TournamentAgeCategories_TTU`, `TournamentPlayers`, `TournamentPlayersGroup`, `OVRSubEvents`

**4. Player data** — `Individuals`, `Individuals_Translation`, `Individuals_Organization`,
`Individual_Eligibility`, `Individuals_EventPenalties`, `Profiles`, `Competitors` ✅ (trimmed),
`Players_Singles`, `Players_Doubles` ✅ (trimmed), `LuckyLoosers`

**5. Result data** — `NewEventsResults` ✅, `NewEventsResults_Imported`, `matchresults`,
`OVRExportResults`, `OVRResultPositions`, `OVRResultPositions_MAP`,
`PlayersEventsResultsMaster_Modified` ✅, `ResultsImportDiscrepancyLogs`

**6. Ranking calculation (book of record)** — `PlayersEventsResultsMaster` ✅, `SingleGroupRanking`

**7. Intermediate / staging / historical** — `PlayersEventsResultsMaster_Log`,
`PlayerseventsResultsMaster_log_Archives`, `View_Fetcher_Individuals_Ranking`,
`vw_EventRankingCategories`, `vw_GetCountries`

**8. Ranking output** — `MainRanking` ✅

**9. Audit tables** — `RankingRunsLog` → superseded by `ranking_run` ✅,
`RankingRunsStepLog` → superseded by `ranking_run_step` ✅, `LogTable_RankingRunsLog`,
`Ranking_Validation_Summary` → superseded by `ranking_validation_result` ✅,
`RankingCSVGenerationLog`

**10. Error / log tables** — `DB_Errors` → superseded by `ranking_run_error` ✅, `Export_Errors`,
`Export_Summary`
