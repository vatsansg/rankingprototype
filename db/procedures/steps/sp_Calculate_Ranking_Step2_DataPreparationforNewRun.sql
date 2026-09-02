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
