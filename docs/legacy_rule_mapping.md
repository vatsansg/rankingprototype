# Legacy Rule/Alias/SP → Prototype Mapping

Static reference document. The prototype does **not** read `RulesSet`/`RulesGroup`/`Rules`/
`RulesAlias` at runtime — this table exists so the legacy alias → SP → prototype-function chain
stays traceable for audits, sourced from `data/dbo_Rules.csv`, `dbo_RulesGroup.csv`,
`dbo_RulesSet.csv`, `dbo_RulesAlias.csv` (all under `C:\vatsan\ranking\RANKINGS2026\data\`).

## Verified active rule sequence (source of truth for `engine/master.py`'s hardcoded order)

Derived by sorting `dbo_Rules.csv` `Active=True` rows by `(RulesGroupId → RulesGroup.RulesGroupOrder,
RulesOrder)`. Note the active rules sit in `RulesGroupId` 2, 3, and 4 — **not** where the group
*names* ("PointsAllocation"=1, "PostRankingResultPosition"=5) would imply; groups 1 and 5 have zero
active member rules today. This is real, observed production configuration drift, not a prototype
error.

### Senior (`RulesSetId=1`)
| Seq | Legacy RuleName | Legacy alias → SP | Prototype function |
|---|---|---|---|
| 1 | `Calculate_Ranking_UpdatePlayersInfoFromTTU` | `Calculate_Ranking_UpdatePlayersInfoFromTTU` → `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU` | `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU()` |
| 2 | `ManualModifications` | `ManualModifications` → `sp_Rules_Set_Weekly_Events_ManualModifications` | `sp_Rules_Set_Weekly_Events_ManualModifications()` |
| 3 | `WTT_SEN_ResultsExpiry` | `Events_Expiry` → `sp_Rules_UpdateEventsResultExpiry` | `sp_Rules_UpdateEventsResultExpiry()` |
| 4 | `Olympics_ResultExpiry` | `Olympic_Expiry` → `sp_Rules_UpdateOlympicResultExpiry` | `sp_Rules_UpdateOlympicResultExpiry()` |
| 5 | `Calculate_WTT_SEN_Ranking_BestResults` | `CalculateBestResultsSEN` → `sp_Calculate_WTT_SEN_Ranking_BestResults` | `sp_Calculate_WTT_SEN_Ranking_BestResults()` |
| 6 | `WTT_SEN_APPLY_ZPP` | `ApplyZeroPointPenalty` → `sp_Calculate_WTT_Ranking_ZeroPointPenalty` | `sp_Calculate_WTT_Ranking_ZeroPointPenalty()` |
| 7 | `Calculate_WTT_SEN_Ranking_RankingPositions` (Mandatory) | `CalculateRankingPositions` → `sp_Calculate_WTT_Ranking_RankingPositions` | `sp_Calculate_WTT_Ranking_RankingPositions()` |

### Youth (`RulesSetId=2`)
| Seq | Legacy RuleName | Legacy alias → SP | Prototype function |
|---|---|---|---|
| 1 | `Calculate_WTT_YOU_CheckDependencyForRankingRun` | `CheckDependencyForRankingRun` → `Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun` | `Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun()` — called as an explicit Python guard, before any write transaction opens |
| 2 | `ManualModifications` | `ManualModifications` → `sp_Rules_Set_Weekly_Events_ManualModifications` | `sp_Rules_Set_Weekly_Events_ManualModifications()` |
| 3 | `WTT_YOU_ResultsExpiry` | `Events_Expiry` → `sp_Rules_UpdateEventsResultExpiry` | `sp_Rules_UpdateEventsResultExpiry()` |
| 4 | `Olympics_ResultExpiry` | `Olympic_Expiry` → `sp_Rules_UpdateOlympicResultExpiry` | `sp_Rules_UpdateOlympicResultExpiry()` |
| 5 | `Calculate_WTT_YOU_Ranking_BestResults` | `CalculateBestResultsYOU` → `sp_Calculate_WTT_YOU_Ranking_BestResults` | `sp_Calculate_WTT_YOU_Ranking_BestResults()` |
| 6 | `WTT_YOU_APPLY_ZPP` | `ApplyZeroPointPenalty` → `sp_Calculate_WTT_Ranking_ZeroPointPenalty` | `sp_Calculate_WTT_Ranking_ZeroPointPenalty()` |
| 7 | `Calculate_WTT_YOU_Ranking_RankingPositions` (Mandatory) | `CalculateRankingPositions` → `sp_Calculate_WTT_Ranking_RankingPositions` | `sp_Calculate_WTT_Ranking_RankingPositions()` |
| 8 | `Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory` | `UpdateRankingPositionsForAgeCategory` → `Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory` | `Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory()` |

Both sequences also run the orchestration steps `sp_Calculate_Ranking_Step2_DataPreparationforNewRun`,
`sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking`, and the added `sp_Calculate_Ranking_FinalizeRun`
(the legacy end-of-run cleanup block of `sp_Calculate_Ranking`, extracted as its own named step) —
see `engine/master.py` for the exact sequence with step numbers.

## Full legacy SP → prototype mapping

| Legacy SP | Prototype | Status | Note |
|---|---|---|---|
| `sp_ProcessSelectedRankingRun` | `engine/master.py::run_combined()` | Reimplemented | Explicit SEN-then-YOU calls, not a cursor over config |
| `sp_Calculate_Ranking` | `sp_Calculate_Ranking_SEN()` / `sp_Calculate_Ranking_YOU()` | Reimplemented | Split into two literal, category-specific functions; real error propagation (legacy had 3 dead-output-variable bugs that silently swallowed child failures) |
| `sp_Calculate_Ranking_Step1_PreRequisites` | *(none)* | Not Required | Confirmed no-op stub in legacy source — all real logic commented out |
| `sp_Calculate_Ranking_Step2_DataPreparationforNewRun` | `engine/procedures/step2.py` | Reimplemented | Adds a defensive ranking_category_code check the legacy never had |
| `sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking` | `engine/procedures/step3.py` | Reimplemented | Fixes the `Players_Doubles.AgeCategoryCode` drift bug |
| `sp_Calculate_Ranking_Step4_UpdateRankingPointsforNewResults` | *(none)* | Not Required | Confirmed dead/commented-out since 2023-09-25 |
| `sp_Rules_RunRulesList` / `sp_Rules_ExecuteRule` / alias resolution UDFs | *(none — direct calls in master.py)* | Not Required | No dynamic dispatch; the missing `ufnrule_General_*` UDF bodies made faithfully replicating this layer impossible anyway |
| `sp_Rules_Set_Weekly_Events_ManualModifications` | `engine/procedures/manual_modifications.py` | Migrated | |
| `sp_Rules_UpdateEventsResultExpiry` | `engine/procedures/expiry.py` | Migrated | |
| `sp_Rules_UpdateOlympicResultExpiry` | `engine/procedures/expiry.py` | Migrated | |
| `sp_Calculate_WTT_SEN_Ranking_BestResults` | `engine/procedures/best_results.py` | Migrated | |
| `sp_Calculate_WTT_YOU_Ranking_BestResults` | `engine/procedures/best_results.py` | Migrated | |
| `sp_Calculate_WTT_Ranking_ZeroPointPenalty` | `engine/procedures/zpp.py` | Reimplemented | Simplified from the legacy's multi-#temp-table WHILE loop; `MaxZPPs` promoted to a named constant |
| `sp_Calculate_WTT_Ranking_RankingPositions` | `engine/procedures/positions.py` | Migrated | Deterministic tiebreak kept |
| `Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory` | `engine/procedures/positions.py` | Reimplemented | **Fixes the legacy `NEWID()` non-determinism bug** |
| `Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun` | `engine/procedures/dependency.py` | Reimplemented | Called as an explicit orchestration guard, not a swallowable rule |
| `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU` | `engine/procedures/ttu_sync.py` | Simplified | Documented stub — no live TTU feed in the prototype |
| `SP_Import_Step1..6`, `SP_SyncZPPNonParticipentPlayers`, `sp_Import_Web_EventsResults` | `importer/load_new_events_results.py`, `importer/cross_award.py` | Simplified | The missing TVF `ufnGetEventResultsForRanking_stat` is a documented limitation; points are derived directly from `result_position` + `ranking_calc_main` instead |
| `SP_Ranking_DataValidation` | `validation/run_validation.py` | Simplified | Only 3 of the ~16 legacy validation checks are ported (see `validation/README.md`) |
| `sp_Validation_MasterRankingValidation` and its 16 named sub-procedures | `validation/checks/*.py` (3 of them) | Partial | Not read in the reverse-engineering pass; documented as not-yet-ported |
| `Sp_Process_ScheduledtoPublish` | *(not implemented — see README known limitations)* | Pending | Scheduling in the prototype records intent (`ranking_run.scheduled_for`) but does not auto-fire; "Publish" as a distinct workflow state was out of scope per the approved plan |
| `sp_Calculate_CarryOverRankingPointsFromOldSystem` (generic) | *(none)* | Not Required | Confirmed superseded/incompatible with the SEN/YOU-split successors |
| `SP_EventExpiryValidityExtension` | *(none)* | Not Required | 2021-era one-time hardcoded data fix, not live business logic |

## Known legacy aliases NOT ported (inactive rules, historical hotfixes)

`WalkOver`, `LosingAfterBye`, `QualiferPoints`, `AddOlympicstoBestResults`, `AddWTTCtoBestResults`,
`ApplyZeroPointPenalty_GSandCS` / `_NON_GSandCS` (superseded by the combined `WTT_*_APPLY_ZPP`
rules), `Calculate_Rule_Ranking_InternationalEvents`, `UpdateCarryForwardPointstoMainRanking`,
`Apply_SEN/YOU_CancellationPenalty_EventRankingCategory`, `ZPPExpiration`, `EventExpiryValidityExtension`,
`Archive_PlayersEventsResultsMaster`, plus ~15 dated one-off `Corrections_Events_*`/`SuperAdmin_*`
2022-season hotfix rules — all confirmed `Active=False` in `dbo_Rules.csv`, excluded from the
prototype's live sequence.
