-- Ports of importer/modify_new_events_results.py: search + single-row edit for the Manual
-- Modifications screen.
CREATE OR ALTER PROCEDURE dbo.sp_SearchNewEventsResults
    @category_code NVARCHAR(3) = NULL, @player_name NVARCHAR(200) = NULL, @country_code NVARCHAR(5) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SELECT n.new_event_result_id, n.competitor_id, c.player_name, c.country_code, n.event_id, e.event_name,
           e.event_type_general_code, n.sub_event_code, n.ranking_category_code, n.category_code, n.age_category_code,
           n.result_position, n.ranking_points, n.zero_point_penalty
    FROM dbo.new_events_results n
    JOIN dbo.competitors c ON c.competitor_id = n.competitor_id
    JOIN dbo.events e ON e.event_id = n.event_id
    WHERE (@category_code IS NULL OR n.category_code = @category_code)
      AND (@player_name IS NULL OR c.player_name LIKE '%' + @player_name + '%')
      AND (@country_code IS NULL OR c.country_code LIKE '%' + @country_code + '%')
    ORDER BY n.new_event_result_id;
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_UpdateNewEventResultPosition
    @new_event_result_id INT, @new_result_position NVARCHAR(10), @modified_by NVARCHAR(100),
    @old_result_position NVARCHAR(10) OUTPUT, @new_ranking_points DECIMAL(10,2) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    -- Same 19-code allow-list as fn_ComputeRankingPoints covers (importer.EDITABLE_RESULT_POSITIONS).
    IF @new_result_position NOT IN ('W','F','SF','QF','R16','R32','R64','R128','R256','QUAL','QER','QR1','QR2','QR3','QR4','GL','G2L','G3L','G4L')
        THROW 51300, 'Unrecognized result position', 1;

    DECLARE @competitor_id INT, @event_id INT, @category_code NVARCHAR(3), @age_category_code NVARCHAR(10),
            @ranking_category_code NVARCHAR(10), @event_type_general_code NVARCHAR(10), @zpp BIT, @old_points DECIMAL(10,2);

    SELECT @competitor_id = n.competitor_id, @event_id = n.event_id, @category_code = n.category_code,
           @age_category_code = n.age_category_code, @ranking_category_code = n.ranking_category_code,
           @event_type_general_code = e.event_type_general_code, @zpp = n.zero_point_penalty,
           @old_result_position = n.result_position, @old_points = n.ranking_points
    FROM dbo.new_events_results n JOIN dbo.events e ON e.event_id = n.event_id
    WHERE n.new_event_result_id = @new_event_result_id;

    IF @competitor_id IS NULL THROW 51301, 'new_events_results row not found', 1;

    IF @zpp = 1
        SET @new_ranking_points = 0;
    ELSE
        SELECT @new_ranking_points = ISNULL(pts.ranking_points, 0)
        FROM dbo.fn_ComputeRankingPoints(@category_code, @age_category_code, @ranking_category_code, @event_type_general_code, @new_result_position, @zpp) pts;
    IF @new_ranking_points IS NULL SET @new_ranking_points = 0;

    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.new_events_results SET result_position = @new_result_position, ranking_points = @new_ranking_points
        WHERE new_event_result_id = @new_event_result_id;

        INSERT INTO dbo.new_events_results_modification_log
            (new_event_result_id, competitor_id, event_id, old_result_position, new_result_position,
             old_ranking_points, new_ranking_points, modified_by, modified_at)
        VALUES (@new_event_result_id, @competitor_id, @event_id, @old_result_position, @new_result_position,
                @old_points, @new_ranking_points, @modified_by, SYSUTCDATETIME());
        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH

    -- pyodbc cannot reliably read back OUTPUT parameters through {CALL} syntax -- see
    -- sp_RankingRun_lifecycle.sql notes -- so also surface the before/after via a trailing SELECT.
    SELECT @old_result_position AS old_result_position, @new_result_position AS new_result_position,
           @old_points AS old_ranking_points, @new_ranking_points AS new_ranking_points;
END
GO
