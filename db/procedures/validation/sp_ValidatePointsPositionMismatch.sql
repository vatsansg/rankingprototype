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
