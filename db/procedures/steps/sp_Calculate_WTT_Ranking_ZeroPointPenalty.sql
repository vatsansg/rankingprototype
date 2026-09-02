-- Port of engine/procedures/zpp.py. A genuine per-row cursor is the right translation here --
-- each ZPP row needs its own correlated subquery against a different point in time (its own
-- ranking_year/ranking_week), which is not a group-boundary problem like best-results, just a
-- bounded per-row scan. Called with @event_count=8 for SEN, 5 for YOU -- one procedure,
-- category-parametrized, matching the Python original (no separate SEN/YOU variant).
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_WTT_Ranking_ZeroPointPenalty
    @category_code NVARCHAR(3), @event_count INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @expired INT = 0, @kept_active INT = 0, @total INT = 0;
    BEGIN TRAN;
    BEGIN TRY
        DECLARE @player_event_result_id INT, @competitor_id INT, @ranking_category_code NVARCHAR(10),
                @ranking_year INT, @ranking_week INT, @subsequent_count INT;

        -- TOP 10000 mirrors the Python sanity bound (MAX_ZPP_PER_PLAYER * 1000): a bound on
        -- total ZPP rows scanned per run, not a per-player cap.
        DECLARE zpp_cur CURSOR LOCAL FORWARD_ONLY READ_ONLY FOR
            SELECT TOP (10000) player_event_result_id, competitor_id, ranking_category_code, ranking_year, ranking_week
            FROM dbo.players_events_results_master
            WHERE category_code = @category_code AND active = 1 AND zero_point_penalty = 1
            ORDER BY player_event_result_id;

        OPEN zpp_cur;
        FETCH NEXT FROM zpp_cur INTO @player_event_result_id, @competitor_id, @ranking_category_code, @ranking_year, @ranking_week;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            SET @total += 1;
            SELECT @subsequent_count = COUNT(*)
            FROM dbo.players_events_results_master p
            JOIN dbo.events e ON e.event_id = p.event_id
            WHERE p.competitor_id = @competitor_id AND p.category_code = @category_code
              AND p.ranking_category_code = @ranking_category_code AND p.active = 1 AND p.zero_point_penalty = 0
              AND (p.ranking_year > @ranking_year OR (p.ranking_year = @ranking_year AND p.ranking_week > @ranking_week))
              AND e.event_type_code IN (SELECT event_type_code FROM dbo.zpp_event_type_code);

            IF @subsequent_count >= @event_count
            BEGIN
                UPDATE dbo.players_events_results_master SET active = 0, mandatory_inclusion_for_best_results = 0
                WHERE player_event_result_id = @player_event_result_id;
                SET @expired += 1;
            END
            ELSE
            BEGIN
                UPDATE dbo.players_events_results_master SET mandatory_inclusion_for_best_results = 1
                WHERE player_event_result_id = @player_event_result_id;
                SET @kept_active += 1;
            END

            FETCH NEXT FROM zpp_cur INTO @player_event_result_id, @competitor_id, @ranking_category_code, @ranking_year, @ranking_week;
        END
        CLOSE zpp_cur; DEALLOCATE zpp_cur;

        SET @rows_updated = @expired + @kept_active;
        COMMIT TRAN;
        SET @result_message = CONCAT(@total, ' ZPP row(s) evaluated: ', @expired, ' waived/expired, ', @kept_active, ' still active');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
