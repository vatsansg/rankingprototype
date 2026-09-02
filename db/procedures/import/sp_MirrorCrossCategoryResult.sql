-- Port of importer/cross_award.py::mirror_cross_category_result. Direct set-based port of
-- the SEN<->YOU cross-award mirroring. Preserved as-is: NOT wired into sp_ImportNewEventsResults
-- or any live route in this migration (matching the prototype, where it exists as a tested but
-- dormant function) -- flagged for a follow-up decision, not silently activated.
CREATE OR ALTER PROCEDURE dbo.sp_MirrorCrossCategoryResult
    @source_category_code NVARCHAR(3), @rows_inserted INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @target_category_code NVARCHAR(3), @multiplier DECIMAL(10,2);
    IF @source_category_code = 'SEN' BEGIN SET @target_category_code = 'YOU'; SET @multiplier = 5; END
    ELSE IF @source_category_code = 'YOU' BEGIN SET @target_category_code = 'SEN'; SET @multiplier = 1; END
    ELSE THROW 51200, 'source_category_code must be SEN or YOU', 1;

    BEGIN TRAN;
    BEGIN TRY
        INSERT INTO dbo.new_events_results
            (event_id, competitor_id, sub_event_code, result_position, matches_played, matches_won, matches_lost,
             qualifier, result_type, zero_point_penalty, last_phase_win, ranking_category_code, age_category_code,
             category_code, organization_code, ranking_points, cross_awarded_from_event_id)
        SELECT n.event_id, n.competitor_id, n.sub_event_code, n.result_position, n.matches_played, n.matches_won, n.matches_lost,
               n.qualifier, n.result_type, n.zero_point_penalty, n.last_phase_win, n.ranking_category_code, n.age_category_code,
               @target_category_code, n.organization_code, ISNULL(n.ranking_points, 0) * @multiplier, n.event_id
        FROM dbo.new_events_results n
        JOIN dbo.competitors c ON c.competitor_id = n.competitor_id
        WHERE n.category_code = @source_category_code AND n.cross_awarded_from_event_id IS NULL
          AND (
                (@source_category_code = 'SEN' AND c.age_category_code IS NOT NULL AND c.age_category_code <> 'SEN')
             OR (@source_category_code = 'YOU' AND c.age_category_code = 'U19')
          )
          AND NOT EXISTS (
              SELECT 1 FROM dbo.new_events_results m
              WHERE m.cross_awarded_from_event_id = n.event_id AND m.competitor_id = n.competitor_id AND m.category_code = @target_category_code
          );
        SET @rows_inserted = @@ROWCOUNT;
        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH

    SELECT @rows_inserted AS rows_inserted;
END
GO
