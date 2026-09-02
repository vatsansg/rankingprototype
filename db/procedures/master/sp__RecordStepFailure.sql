-- Shared helper called from every step's CATCH block inside the master procedures (avoids
-- duplicating this block 10-11 times per master procedure). Runs with NO open transaction at
-- the point it's called (the failing step's own BEGIN TRAN already rolled back and re-threw
-- before this point), so its UPDATE/INSERT commit immediately (autocommit) -- this is what
-- preserves "audit survives rollback" and "a concurrent dashboard reader sees FAILED as soon
-- as it's recorded", matching engine/step_runner.py's behavior in the SQLite prototype.
CREATE OR ALTER PROCEDURE dbo.sp__RecordStepFailure
    @run_id INT, @step_id INT, @step_start DATETIME2(3)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @err_msg NVARCHAR(MAX) = ERROR_MESSAGE(), @err_proc NVARCHAR(200) = ISNULL(ERROR_PROCEDURE(),'T-SQL');
    UPDATE dbo.ranking_run_step
    SET status='FAILED', finished_at=SYSUTCDATETIME(),
        duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), result_message=LEFT(@err_msg,400)
    WHERE ranking_run_step_id=@step_id;

    INSERT INTO dbo.ranking_run_error (ranking_run_id, ranking_run_step_id, error_type, error_message, traceback, occurred_at)
    VALUES (@run_id, @step_id, @err_proc, @err_msg,
            CONCAT('Line ', ERROR_LINE(), '; State ', ERROR_STATE(), '; Number ', ERROR_NUMBER()), SYSUTCDATETIME());
END
GO
