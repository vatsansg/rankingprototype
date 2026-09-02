-- Port of engine/procedures/finalize.py -- the business-cleanup step at the end of every
-- calculation run (distinct from sp_RankingRun_Finalize, the run-lifecycle status helper in
-- db/procedures/master/). Purges main_ranking rows that ended the run with 0 points, and
-- clears new_events_results for the category now that every row has been absorbed into
-- players_events_results_master. Without this, stale/bad rows accumulate in
-- new_events_results indefinitely and can permanently block future runs.
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_Ranking_FinalizeRun
    @category_code NVARCHAR(3), @run_id INT,
    @rows_deleted INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @deleted_zero INT, @deleted_staging INT;
    BEGIN TRAN;
    BEGIN TRY
        DELETE FROM dbo.main_ranking WHERE ranking_run_id = @run_id AND ranking_points = 0;
        SET @deleted_zero = @@ROWCOUNT;

        DELETE FROM dbo.new_events_results WHERE category_code = @category_code;
        SET @deleted_staging = @@ROWCOUNT;

        SET @rows_deleted = @deleted_zero + @deleted_staging;
        COMMIT TRAN;
        SET @result_message = CONCAT('purged ', @deleted_zero, ' zero-point main_ranking row(s), cleared ',
                                      @deleted_staging, ' consumed new_events_results row(s) for ', @category_code);
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
