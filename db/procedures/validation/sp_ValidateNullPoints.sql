-- Port of validation/checks/null_points.py.
CREATE OR ALTER PROCEDURE dbo.sp_ValidateNullPoints
    @category_code NVARCHAR(3), @run_id INT, @validation_category NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM dbo.new_events_results WHERE category_code = @category_code AND ranking_points IS NULL)
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, competitor_id, event_id, created_at)
        SELECT @run_id, @validation_category, 'Null RANKINGPOINTS Validation', 0, 'ranking_points is NULL', 'new_events_results',
               n.competitor_id, n.event_id, SYSUTCDATETIME()
        FROM dbo.new_events_results n WHERE n.category_code = @category_code AND n.ranking_points IS NULL;
    ELSE
        INSERT INTO dbo.ranking_validation_result
            (ranking_run_id, validation_category, check_name, passed, remarks, table_name, created_at)
        VALUES (@run_id, @validation_category, 'Null RANKINGPOINTS Validation', 1,
                'No null ranking_points found in new_events_results', 'new_events_results', SYSUTCDATETIME());
END
GO
