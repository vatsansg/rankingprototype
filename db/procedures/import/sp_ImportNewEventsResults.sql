-- Bulk import via table-valued parameter (dbo.NewEventsResultTVP, see db/procedures/types/):
-- one network round trip and one server-side transaction regardless of file size. Points
-- computed via fn_ComputeRankingPoints (an unpivot of ranking_calc_main, see db/procedures/types/).
CREATE OR ALTER PROCEDURE dbo.sp_ImportNewEventsResults
    @rows dbo.NewEventsResultTVP READONLY, @imported_by NVARCHAR(100),
    @competitors_upserted INT OUTPUT, @events_upserted INT OUTPUT, @results_inserted INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        MERGE dbo.competitors AS tgt
        USING (SELECT DISTINCT competitor_id, player_name, dob, gender, country_code, age_category_code, is_retired FROM @rows) AS src
          ON tgt.competitor_id = src.competitor_id
        WHEN NOT MATCHED THEN
            INSERT (competitor_id, player_name, dob, gender, country_code, nationality_code, age_category_code, is_retired)
            VALUES (src.competitor_id, src.player_name, src.dob, src.gender, src.country_code, src.country_code, src.age_category_code, src.is_retired);
        SET @competitors_upserted = @@ROWCOUNT;

        MERGE dbo.events AS tgt
        USING (SELECT DISTINCT event_id, event_name, event_type_general_code, event_type_code, ranking_year, ranking_month, ranking_week FROM @rows) AS src
          ON tgt.event_id = src.event_id
        WHEN NOT MATCHED THEN
            INSERT (event_id, event_name, event_type_general_code, event_type_code, ranking_year, ranking_month, ranking_week)
            VALUES (src.event_id, src.event_name, src.event_type_general_code, src.event_type_code, src.ranking_year, src.ranking_month, src.ranking_week);
        SET @events_upserted = @@ROWCOUNT;

        INSERT INTO dbo.new_events_results
            (event_id, competitor_id, sub_event_code, result_position, matches_played, matches_won, matches_lost,
             qualifier, zero_point_penalty, ranking_category_code, age_category_code, category_code, ranking_points)
        SELECT r.event_id, r.competitor_id, r.sub_event_code, r.result_position, r.matches_played, r.matches_won, r.matches_lost,
               r.qualifier, r.zero_point_penalty, r.ranking_category_code, r.age_category_code, r.category_code,
               CASE WHEN r.zero_point_penalty = 1 THEN 0 ELSE ISNULL(pts.ranking_points, 0) END
        FROM @rows r
        OUTER APPLY dbo.fn_ComputeRankingPoints(r.category_code, r.age_category_code, r.ranking_category_code,
                                                 r.event_type_general_code, r.result_position, r.zero_point_penalty) pts;
        SET @results_inserted = @@ROWCOUNT;

        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH

    -- pyodbc cannot reliably read back OUTPUT parameters through {CALL} syntax -- see
    -- sp_RankingRun_lifecycle.sql notes -- so also surface the counts via a trailing SELECT.
    SELECT @competitors_upserted AS competitors_upserted, @events_upserted AS events_upserted,
           @results_inserted AS results_inserted;
END
GO
