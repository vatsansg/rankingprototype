-- Port of engine/procedures/expiry.py -- both expiry procedures.
CREATE OR ALTER PROCEDURE dbo.sp_Rules_UpdateEventsResultExpiry
    @category_code NVARCHAR(3), @year INT, @week INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.players_events_results_master
        SET active = 0
        WHERE category_code = @category_code AND active = 1
          AND expiry_year IS NOT NULL AND expiry_week IS NOT NULL
          AND (expiry_year < @year OR (expiry_year = @year AND expiry_week <= @week));
        SET @rows_updated = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('expired ', @rows_updated, ' result(s)');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO

-- sp_Rules_UpdateOlympicResultExpiry has no category/organization parameter in the legacy SP
-- either -- it applies globally across categories, preserved here.
CREATE OR ALTER PROCEDURE dbo.sp_Rules_UpdateOlympicResultExpiry
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @latest_og INT;
    SELECT TOP 1 @latest_og = event_id FROM dbo.events
    WHERE event_type_general_code = 'OG' ORDER BY ranking_year DESC, event_id DESC;

    IF @latest_og IS NULL
    BEGIN
        SET @rows_updated = 0;
        SET @result_message = 'no Olympic Games event on file';
        RETURN;
    END

    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.players_events_results_master
        SET active = 0
        WHERE active = 1
          AND event_id IN (SELECT event_id FROM dbo.events WHERE event_type_general_code = 'OG' AND event_id <> @latest_og);
        SET @rows_updated = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('kept event ', @latest_og, ' active, expired ', @rows_updated, ' older Olympic result(s)');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
