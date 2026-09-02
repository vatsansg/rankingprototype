-- Powers the dashboard's "Clear Database (Demo Reset)" button. Clears every import, run, and
-- manual modification so the app can be demoed from a clean slate repeatedly -- but,
-- deliberately unlike the old SQLite prototype's full schema rebuild, this does NOT touch
-- reference data (categories/ranking_calc_main/etc, which are static) or the RBAC tables
-- (app_role/app_user/app_user_audit_log): resetting demo data must never delete user accounts
-- or their audit history.
CREATE OR ALTER PROCEDURE dbo.sp_ResetDemoData
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        DELETE FROM dbo.new_events_results_modification_log;
        DELETE FROM dbo.new_events_results;
        DELETE FROM dbo.ranking_validation_result;
        DELETE FROM dbo.main_ranking;
        DELETE FROM dbo.players_events_results_master_modified;
        DELETE FROM dbo.players_events_results_master;
        DELETE FROM dbo.ranking_run_error;
        DELETE FROM dbo.ranking_run_step;
        DELETE FROM dbo.ranking_run;
        DELETE FROM dbo.players_doubles;
        DELETE FROM dbo.events;
        DELETE FROM dbo.competitors;

        UPDATE dbo.ranking_engine_info SET current_ranking_year = 2026, current_ranking_month = 1, current_ranking_week = 1;
        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
