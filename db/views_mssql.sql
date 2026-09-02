-- WTT Ranking Engine Prototype - Azure SQL (T-SQL) views.
-- Ported from db/views.sql. julianday() duration math -> DATEDIFF(SECOND, ...).
-- Views drop ORDER BY (not meaningful in T-SQL views); callers add their own.

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

CREATE OR ALTER VIEW dbo.vw_RankingRunProgress AS
SELECT s.ranking_run_id, s.step_seq, s.step_group, s.step_name, s.status, s.started_at, s.finished_at,
       s.duration_ms, s.rows_inserted, s.rows_updated, s.rows_deleted, s.result_message
FROM dbo.ranking_run_step s;
GO

CREATE OR ALTER VIEW dbo.vw_RankingRunStepAudit AS
SELECT r.ranking_run_id, r.category_code, r.ranking_year, r.ranking_month, r.ranking_week,
       r.status AS run_status, s.step_seq, s.step_group, s.step_name, s.status AS step_status,
       s.started_at, s.finished_at, s.duration_ms, s.rows_inserted, s.rows_updated, s.rows_deleted, s.result_message
FROM dbo.ranking_run_step s
JOIN dbo.ranking_run r ON r.ranking_run_id = s.ranking_run_id;
GO

CREATE OR ALTER VIEW dbo.vw_RankingRunErrors AS
SELECT e.ranking_run_error_id, e.ranking_run_id, r.category_code, r.ranking_year, r.ranking_month, r.ranking_week,
       s.step_seq, s.step_name, e.error_type, e.error_message, e.traceback, e.occurred_at
FROM dbo.ranking_run_error e
JOIN dbo.ranking_run r ON r.ranking_run_id = e.ranking_run_id
LEFT JOIN dbo.ranking_run_step s ON s.ranking_run_step_id = e.ranking_run_step_id;
GO

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

CREATE OR ALTER VIEW dbo.vw_NewEventsResultsModificationLog AS
SELECT l.modification_log_id, l.new_event_result_id, c.player_name, c.country_code, e.event_name,
       l.old_result_position, l.new_result_position, l.old_ranking_points, l.new_ranking_points,
       l.modified_by, l.modified_at
FROM dbo.new_events_results_modification_log l
JOIN dbo.competitors c ON c.competitor_id = l.competitor_id
JOIN dbo.events e ON e.event_id = l.event_id;
GO

CREATE OR ALTER VIEW dbo.vw_RankingCalculationTrace AS
SELECT p.competitor_id, c.player_name, p.event_id, ev.event_name, p.ranking_category_code, p.result_position,
       p.ranking_points, p.best_result_no_sen_you, p.player_best_ranking_result_number, p.zero_point_penalty,
       p.excluded_due_to_zero_point_penalty, p.active, p.expiry_year, p.expiry_month, p.expiry_week, p.ranking_run_id_created
FROM dbo.players_events_results_master p
JOIN dbo.competitors c ON c.competitor_id = p.competitor_id
JOIN dbo.events ev ON ev.event_id = p.event_id;
GO
