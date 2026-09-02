# Validation — scope and known limitations

`SP_Ranking_DataValidation` in the legacy system is orchestrated further by
`sp_Validation_MasterRankingValidation`, which calls 16 named sub-procedures (per the
reverse-engineering research). None of those 16 were read in this project's research pass —
only their names and the shape of `dbo_Ranking_Validation_Summary.csv` sample rows were
available.

## Ported (3 checks)

- **`checks/null_points.py`** — "Null RANKINGPOINTS Validation". Checked against
  `new_events_results.ranking_points` (nullable); `players_events_results_master.ranking_points`
  is `NOT NULL` at the schema level and can never carry a null value, so this check can only
  ever fire pre-import.
- **`checks/duplicate_results.py`** — "Duplicated Results Validation". Flags
  `players_events_results_master` rows sharing the same `(competitor_id, event_id,
  ranking_category_code)` while `active=1`. Structurally prevented by `sp_Calculate_Ranking_Step2`'s
  own `NOT EXISTS` guard during normal operation — this check exists to catch data that
  bypassed that guard (e.g. a direct manual `INSERT`).
- **`checks/points_position_mismatch.py`** — reconciliation of `main_ranking.ranking_points`
  against the sum of that competitor's counted `players_events_results_master` rows, mirroring
  `sp_Validation_MainRankingVsBreakDown_CurrentweekRanking.sql`.

## Not ported (documented gap, not a silent assumption)

The other ~13 named sub-procedures (`sp_Validation_ZPP_Revoke_CurrentweekRanking`,
`sp_Validation_DuplicatedResultsinBreakDown_CurrentweekRanking`,
`sp_Validation_YOU_RANKINGPOINTS_CurrentweekRanking`,
`sp_Validation_RankingIndividualsCount_CurrentweekRanking`,
`sp_Validation_getTop10StatusCurrentweekRanking`,
`sp_Validation_getTotalPlayers_MainDraw_CurrentweekRanking`,
`sp_Validation_getTotalPlayers_Phase_CurrentweekRanking`,
`sp_Validation_getTotalSubEventPointsCurrentweekRanking`,
`sp_Validation_getTotalEventPointsCurrentweekRanking`,
`sp_Validation_getTotalPointsCurrentweekRanking`,
`sp_Validation_TotalPlayersvsResultPosition_CurrentweekRanking`,
`sp_Validation_getInactivePlayersinEvents_CurrentweekRanking`,
`sp_Validation_PlayerNonParticipationPenalty_CurrentweekRanking`) were not read and are not
implemented here. Porting them would require reading their source under
`C:\vatsan\ranking\RANKINGS2026\SPS\` and is a natural next-step extension, not attempted in
this prototype.

## Design difference from the legacy table

The legacy `Ranking_Validation_Summary` table is cleared and re-populated on every call — no
history is retained. The prototype's `ranking_validation_result` table instead **appends**,
tagged with `ranking_run_id`, so past validation results for a run remain queryable after the
fact.
