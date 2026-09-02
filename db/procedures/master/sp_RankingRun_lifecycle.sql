-- T-SQL analogue of engine/run_registry.py: create/schedule/start/finalize a ranking_run row.
-- HASHBYTES('SHA2_256', ...) replaces Python's hashlib.sha256 for the input-snapshot hash.

CREATE OR ALTER PROCEDURE dbo.sp_RankingRun_Create
    @category_code NVARCHAR(3), @ranking_year INT, @ranking_month INT, @ranking_week INT,
    @triggered_by NVARCHAR(100), @run_mode NVARCHAR(10) = 'normal', @run_id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    -- STRING_AGG truncates its input/output to the 8000-byte nvarchar limit unless the input
    -- expression is already an nvarchar(max)/LOB type -- with enough imported rows the plain
    -- CONCAT(...) here silently overflowed that limit and errored (9829). Casting each row's
    -- concatenated string to NVARCHAR(MAX) forces STRING_AGG's result to be MAX-typed too.
    DECLARE @hash NVARCHAR(64) = CONVERT(NVARCHAR(64), HASHBYTES('SHA2_256', ISNULL((
        SELECT STRING_AGG(CAST(CONCAT(new_event_result_id,'|',event_id,'|',competitor_id,'|',sub_event_code,'|',result_position,'|',ranking_points) AS NVARCHAR(MAX)), '|')
            WITHIN GROUP (ORDER BY new_event_result_id)
        FROM dbo.new_events_results WHERE category_code = @category_code
    ), '')), 2);

    INSERT INTO dbo.ranking_run
        (category_code, ranking_year, ranking_month, ranking_week, run_mode, trigger_type, status, started_at, triggered_by, input_snapshot_hash)
    VALUES (@category_code, @ranking_year, @ranking_month, @ranking_week, @run_mode, 'on_demand', 'RUNNING', SYSUTCDATETIME(), @triggered_by, @hash);
    SET @run_id = SCOPE_IDENTITY();
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_RankingRun_Schedule
    @category_code NVARCHAR(3), @ranking_year INT, @ranking_month INT, @ranking_week INT,
    @scheduled_for DATETIME2(3), @triggered_by NVARCHAR(100), @run_mode NVARCHAR(10) = 'normal', @run_id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO dbo.ranking_run
        (category_code, ranking_year, ranking_month, ranking_week, run_mode, trigger_type, scheduled_for, status, triggered_by)
    VALUES (@category_code, @ranking_year, @ranking_month, @ranking_week, @run_mode, 'scheduled', @scheduled_for, 'PENDING', @triggered_by);
    SET @run_id = SCOPE_IDENTITY();

    -- pyodbc cannot reliably read back T-SQL OUTPUT parameters through {CALL} syntax (a known
    -- driver limitation), so -- matching the return-contract pattern used by the master
    -- procedures -- also surface @run_id via a trailing SELECT for Python callers.
    SELECT @run_id AS run_id;
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_RankingRun_StartScheduled
    @run_id INT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @status NVARCHAR(20), @category_code NVARCHAR(3);
    SELECT @status = status, @category_code = category_code FROM dbo.ranking_run WHERE ranking_run_id = @run_id;
    IF @status IS NULL THROW 51002, 'ranking_run not found', 1;
    IF @status <> 'PENDING' THROW 51003, 'ranking_run is not PENDING', 1;

    -- STRING_AGG truncates its input/output to the 8000-byte nvarchar limit unless the input
    -- expression is already an nvarchar(max)/LOB type -- with enough imported rows the plain
    -- CONCAT(...) here silently overflowed that limit and errored (9829). Casting each row's
    -- concatenated string to NVARCHAR(MAX) forces STRING_AGG's result to be MAX-typed too.
    DECLARE @hash NVARCHAR(64) = CONVERT(NVARCHAR(64), HASHBYTES('SHA2_256', ISNULL((
        SELECT STRING_AGG(CAST(CONCAT(new_event_result_id,'|',event_id,'|',competitor_id,'|',sub_event_code,'|',result_position,'|',ranking_points) AS NVARCHAR(MAX)), '|')
            WITHIN GROUP (ORDER BY new_event_result_id)
        FROM dbo.new_events_results WHERE category_code = @category_code
    ), '')), 2);

    UPDATE dbo.ranking_run SET status = 'RUNNING', started_at = SYSUTCDATETIME(), input_snapshot_hash = @hash WHERE ranking_run_id = @run_id;
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_RankingRun_Finalize
    @run_id INT, @status NVARCHAR(20), @notes NVARCHAR(MAX) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE dbo.ranking_run SET status = @status, finished_at = SYSUTCDATETIME(), notes = @notes WHERE ranking_run_id = @run_id;

        IF @status = 'SUCCEEDED'
        BEGIN
            DECLARE @cat NVARCHAR(3), @y INT, @mo INT, @wk INT;
            SELECT @cat = category_code, @y = ranking_year, @mo = ranking_month, @wk = ranking_week
            FROM dbo.ranking_run WHERE ranking_run_id = @run_id;

            UPDATE dbo.ranking_run SET current_active = 0, superseded_by_run_id = @run_id
            WHERE category_code = @cat AND ranking_year = @y AND ranking_month = @mo AND ranking_week = @wk
              AND current_active = 1 AND ranking_run_id <> @run_id;

            UPDATE dbo.ranking_run SET current_active = 1 WHERE ranking_run_id = @run_id;

            UPDATE dbo.ranking_engine_info
            SET current_ranking_year = @y, current_ranking_month = @mo, current_ranking_week = @wk
            WHERE category_code = @cat;
        END
        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
