# Sample data fixtures

Generated deterministically (no RNG) by `generate.py` — re-run it any time to regenerate all
five fixtures identically. Every player/event ID and name is synthetic; no real WTT player
data is used anywhere in this prototype.

Each fixture folder contains:
- `result_file.csv` — a "result import file" in the flat format `importer/load_new_events_results.py`
  expects: one row per player-per-event result, columns matching the legacy
  `NewEventsResults`/`PlayersEventsResultsMaster` shape (event/competitor identity + result +
  category fields combined into one row for prototype simplicity — not a literal reproduction
  of the multi-file legacy OVR export format).
- `setup.sql` (where needed) — extra DB state a scenario requires beyond a plain CSV import
  (a doubles pair row, a deliberately duplicated result row), applied via
  `conn.executescript(...)` after the CSV import.

## The five fixtures

1. **`senior_happy_path/`** — 15 Senior competitors × 10 events (8 `WCH` + 2 `Con`/continental).
   Every player has exactly 10 results, exercising best-of-8 trimming; every player also has
   exactly 2 continental results, exercising the max-1-continental-event cap. Player 90001's
   5th event is swapped for an active Zero-Point-Penalty entry, exercising the ZPP pipeline
   end to end.

2. **`youth_happy_path/`** — 12 Youth (U17) singles competitors × 11 `WCDR64` events, exercising
   best-of-10 trimming. `setup.sql` adds a doubles pair (competitors 91013/91014) whose
   `players_doubles.age_category_code` is deliberately drifted to `'SEN'` — mirroring the
   documented legacy bug — even though both individual players are registered as youth age
   categories, to exercise the Step3 age-category-derivation fix. Requires a prior **successful**
   Senior run for the same (year, month, week) — run `senior_happy_path` first, or the Youth
   dependency guard will correctly block it.

3. **`youth_dependency_failure/`** — 6 Youth competitors for a period (2026-02 wk5) with
   deliberately **no** matching Senior run. Exercises
   `Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun` raising and the run landing at
   `ABORTED_DEPENDENCY` with zero business-table writes.

4. **`validation_failure/`** — one clean result, plus `setup.sql` which — after a run has seeded
   `players_events_results_master` — directly inserts a second, duplicate row for the same
   `(competitor, event, ranking_category)` key (bypassing Step2's own dedupe guard), so
   `SP_Ranking_DataValidation`'s duplicate-results check has something real to catch.

5. **`calculation_failure/`** — one result row carrying an unrecognized `ranking_category_code`
   (`'ZZ'`). This imports without error (the importer does not validate against
   `ranking_categories`), but makes `sp_Calculate_Ranking_Step2_DataPreparationforNewRun`'s
   defensive check raise during the actual run — a controlled mid-calculation failure, distinct
   from the import-time and dependency-time failure modes above.

## Regenerating

```
python sample_data/generate.py
```
