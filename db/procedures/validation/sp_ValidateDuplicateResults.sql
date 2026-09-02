-- Port of validation/checks/duplicate_results.py.
CREATE OR ALTER PROCEDURE dbo.sp_ValidateDuplicateResults
    @category_code NVARCHAR(3), @run_id INT, @validation_category NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM dbo.players_events_results_master WHERE category_code = @category_code AND active = 1
        GROUP BY competitor_id, event_id, ranking_category_code HAVING COUNT(*) > 1
    )
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, competitor_id, event_id, created_at)
        SELECT @run_id, @validation_category, 'Duplicated Results Validation', 0,
               CONCAT(x.n, ' active rows share this (competitor, event, ranking_category) key'),
               'players_events_results_master', x.competitor_id, x.event_id, SYSUTCDATETIME()
        FROM (
            SELECT competitor_id, event_id, ranking_category_code, COUNT(*) AS n
            FROM dbo.players_events_results_master WHERE category_code = @category_code AND active = 1
            GROUP BY competitor_id, event_id, ranking_category_code HAVING COUNT(*) > 1
        ) x;
    ELSE
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, created_at)
        VALUES (@run_id, @validation_category, 'Duplicated Results Validation', 1,
                'No duplicate (competitor, event, ranking_category) rows found', 'players_events_results_master', SYSUTCDATETIME());
END
GO
