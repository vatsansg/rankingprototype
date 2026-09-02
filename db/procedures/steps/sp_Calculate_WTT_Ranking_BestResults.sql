-- Port of engine/procedures/best_results.py. Membership selection (which rows count) needs a
-- bounded procedural pass because the continental-cap "skip without consuming a slot" rule
-- cannot be expressed as a pure ROW_NUMBER()/RANK() predicate -- the Nth point-ranked row is
-- not necessarily the Nth *selected* row once skips happen. A single, non-nested, forward-only
-- cursor, ordered once by (competitor_id, ranking_category_code, ranking_points DESC), tracks
-- per-group state across the group boundary. Rank *assignment* is then pure set-based
-- ROW_NUMBER(), since all mandatory/ZPP rows carry exactly 0 points by construction, so
-- ranking selected rows by points DESC has no cap logic left to apply.
CREATE OR ALTER PROCEDURE dbo.sp__ApplyBestResults
    @category_code NVARCHAR(3), @best_x_results INT, @best_x_results_for_continental_events INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.players_events_results_master
        SET player_best_ranking_result_number = 0, best_result_no_sen_you = 0
        WHERE category_code = @category_code AND active = 1;

        SELECT p.competitor_id, p.ranking_category_code, COUNT(*) AS mandatory_count
        INTO #mandatory_count
        FROM dbo.players_events_results_master p
        WHERE p.category_code = @category_code AND p.active = 1
          AND (p.zero_point_penalty = 1 OR p.mandatory_inclusion_for_best_results = 1)
        GROUP BY p.competitor_id, p.ranking_category_code;

        UPDATE p SET best_result_no_sen_you = 1
        FROM dbo.players_events_results_master p
        WHERE p.category_code = @category_code AND p.active = 1
          AND (p.zero_point_penalty = 1 OR p.mandatory_inclusion_for_best_results = 1);

        DECLARE @competitor_id INT, @ranking_category_code NVARCHAR(10), @player_event_result_id INT, @is_continental BIT;
        DECLARE @cur_competitor INT = NULL, @cur_category NVARCHAR(10) = NULL;
        DECLARE @remaining_slots INT, @chosen_count INT, @continental_count INT, @mand_count INT;

        DECLARE best_cur CURSOR LOCAL FORWARD_ONLY READ_ONLY FOR
            SELECT p.competitor_id, p.ranking_category_code, p.player_event_result_id,
                   CAST(CASE WHEN e.event_type_general_code IN (SELECT event_type_general_code FROM dbo.continental_event_type_code)
                             THEN 1 ELSE 0 END AS BIT)
            FROM dbo.players_events_results_master p
            JOIN dbo.events e ON e.event_id = p.event_id
            WHERE p.category_code = @category_code AND p.active = 1
              AND p.zero_point_penalty = 0 AND p.mandatory_inclusion_for_best_results = 0
            ORDER BY p.competitor_id, p.ranking_category_code, p.ranking_points DESC, p.player_event_result_id ASC;

        OPEN best_cur;
        FETCH NEXT FROM best_cur INTO @competitor_id, @ranking_category_code, @player_event_result_id, @is_continental;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            IF @cur_competitor IS NULL OR @competitor_id <> @cur_competitor OR @ranking_category_code <> @cur_category
            BEGIN
                SET @cur_competitor = @competitor_id; SET @cur_category = @ranking_category_code;
                -- SELECT @var = col FROM ... WHERE <no match> leaves @var at its PREVIOUS
                -- value instead of NULL -- reset explicitly or a competitor/category group with
                -- no mandatory/ZPP rows silently inherits the prior group's mandatory_count,
                -- under-counting @remaining_slots by that amount for every group after the
                -- first one that had a mandatory row.
                SET @mand_count = NULL;
                SELECT @mand_count = mandatory_count FROM #mandatory_count
                WHERE competitor_id = @cur_competitor AND ranking_category_code = @cur_category;
                SET @remaining_slots = IIF(@best_x_results - ISNULL(@mand_count,0) > 0, @best_x_results - ISNULL(@mand_count,0), 0);
                SET @chosen_count = 0; SET @continental_count = 0;
            END

            IF @chosen_count < @remaining_slots
            BEGIN
                IF NOT (@is_continental = 1 AND @continental_count >= @best_x_results_for_continental_events)
                BEGIN
                    UPDATE dbo.players_events_results_master SET best_result_no_sen_you = 1
                    WHERE player_event_result_id = @player_event_result_id;
                    SET @chosen_count += 1;
                    IF @is_continental = 1 SET @continental_count += 1;
                END
                -- else: continental cap reached -- skip, does not consume a slot, row stays unselected
            END

            FETCH NEXT FROM best_cur INTO @competitor_id, @ranking_category_code, @player_event_result_id, @is_continental;
        END
        CLOSE best_cur; DEALLOCATE best_cur;

        ;WITH ranked AS (
            SELECT player_event_result_id,
                   ROW_NUMBER() OVER (PARTITION BY competitor_id, ranking_category_code
                                       ORDER BY ranking_points DESC, player_event_result_id ASC) AS rn
            FROM dbo.players_events_results_master
            WHERE category_code = @category_code AND active = 1 AND best_result_no_sen_you = 1
        )
        UPDATE p SET player_best_ranking_result_number = r.rn
        FROM dbo.players_events_results_master p JOIN ranked r ON r.player_event_result_id = p.player_event_result_id;

        SET @rows_updated = @@ROWCOUNT;
        DROP TABLE #mandatory_count;
        COMMIT TRAN;
        SET @result_message = CONCAT('selected best-of-', @best_x_results, ' results per player/category group for ', @category_code);
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN;
        IF OBJECT_ID('tempdb..#mandatory_count') IS NOT NULL DROP TABLE #mandatory_count;
        THROW;
    END CATCH
END
GO

-- SEN_BEST_X_RESULTS=8, BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS=1 (engine/constants.py)
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_WTT_SEN_Ranking_BestResults
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    EXEC dbo.sp__ApplyBestResults @category_code='SEN', @best_x_results=8, @best_x_results_for_continental_events=1,
        @rows_updated=@rows_updated OUTPUT, @result_message=@result_message OUTPUT;
END
GO

-- YOU_BEST_X_RESULTS=10, BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS=1 (engine/constants.py)
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_WTT_YOU_Ranking_BestResults
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    EXEC dbo.sp__ApplyBestResults @category_code='YOU', @best_x_results=10, @best_x_results_for_continental_events=1,
        @rows_updated=@rows_updated OUTPUT, @result_message=@result_message OUTPUT;
END
GO
