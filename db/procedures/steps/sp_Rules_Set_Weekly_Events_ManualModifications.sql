-- Port of engine/procedures/manual_modifications.py. Applies operator-staged corrections
-- from players_events_results_master_modified onto players_events_results_master via a
-- set-based correlated UPDATE...FROM (the Python original looped per-row only because SQLite
-- makes multi-table UPDATE joins awkward, not because the logic is inherently row-by-row).
CREATE OR ALTER PROCEDURE dbo.sp_Rules_Set_Weekly_Events_ManualModifications
    @category_code NVARCHAR(3), @run_id INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @pending_count INT;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE p
        SET result_position = COALESCE(m.modified_result_position, p.result_position),
            ranking_points   = COALESCE(m.modified_ranking_points, p.ranking_points),
            expiry_year      = COALESCE(m.modified_expiry_year, p.expiry_year),
            expiry_month     = COALESCE(m.modified_expiry_month, p.expiry_month),
            expiry_week      = COALESCE(m.modified_expiry_week, p.expiry_week),
            active           = COALESCE(m.modified_active, p.active)
        FROM dbo.players_events_results_master p
        JOIN dbo.players_events_results_master_modified m
          ON m.competitor_id = p.competitor_id AND m.event_id = p.event_id
         AND m.ranking_category_code = p.ranking_category_code AND m.category_code = p.category_code
        WHERE m.category_code = @category_code AND m.applied = 0;
        SET @rows_updated = @@ROWCOUNT;

        UPDATE dbo.players_events_results_master_modified
        SET applied = 1, applied_in_ranking_run_id = @run_id
        WHERE category_code = @category_code AND applied = 0;
        SET @pending_count = @@ROWCOUNT;

        COMMIT TRAN;
        SET @result_message = CONCAT('applied ', @pending_count, ' manual modification(s), ', @rows_updated, ' row(s) updated');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
