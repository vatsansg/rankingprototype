-- Master T-SQL procedure for the Senior ranking calculation. Direct, category-split successor
-- of the legacy parameterized sp_Calculate_Ranking. Internally EXECs each step's own stored
-- procedure in the fixed, verified order (see docs/legacy_rule_mapping.md), writing its own
-- step-audit rows via T-SQL, with TRY/CATCH per step replicating the exact per-step-atomic-
-- commit + audit-survives-rollback + live-visibility-to-a-concurrent-reader guarantee the
-- SQLite prototype's engine/step_runner.py established.
--
-- Return contract: rather than fight pyodbc OUTPUT-parameter quirks, this procedure never lets
-- an expected failure propagate as a raw exception -- it catches it, finalizes the run itself
-- (FAILED), and returns one final SELECT row (ranking_run_id, status, failed_step_seq,
-- failed_step_name, error_message). Python's thin wrapper just EXECs and reads that one row.
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_Ranking_SEN
    @ranking_year INT, @ranking_month INT, @ranking_week INT,
    @triggered_by NVARCHAR(100), @run_mode NVARCHAR(10) = 'normal', @run_id INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @category_code NVARCHAR(3) = 'SEN';
    DECLARE @step_id INT, @step_start DATETIME2(3);
    DECLARE @ri INT, @ru INT, @rd INT, @msg NVARCHAR(400);
    DECLARE @final_status NVARCHAR(20), @failed_step_seq INT = NULL,
            @failed_step_name NVARCHAR(100) = NULL, @failed_error_message NVARCHAR(MAX) = NULL;

    IF @run_id IS NULL
        EXEC dbo.sp_RankingRun_Create @category_code=@category_code, @ranking_year=@ranking_year,
            @ranking_month=@ranking_month, @ranking_week=@ranking_week, @triggered_by=@triggered_by,
            @run_mode=@run_mode, @run_id=@run_id OUTPUT;
    ELSE
        EXEC dbo.sp_RankingRun_StartScheduled @run_id=@run_id;

    -- ===== Step 1: PreRequisitesValidation =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 1, 'PreRequisitesValidation', 'SP_Calculate_Ranking_UpdatePlayersInfoFromTTU', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.SP_Calculate_Ranking_UpdatePlayersInfoFromTTU @organization_code='WTT', @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=1; SET @failed_step_name='SP_Calculate_Ranking_UpdatePlayersInfoFromTTU';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 2: Orchestration - Data preparation =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 2, 'Orchestration', 'sp_Calculate_Ranking_Step2_DataPreparationforNewRun', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_Step2_DataPreparationforNewRun
            @category_code=@category_code, @year=@ranking_year, @month=@ranking_month, @week=@ranking_week, @run_id=@run_id,
            @rows_inserted=@ri OUTPUT, @rows_updated=@ru OUTPUT, @rows_deleted=@rd OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()),
            rows_inserted=@ri, rows_updated=@ru, rows_deleted=@rd, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=2; SET @failed_step_name='sp_Calculate_Ranking_Step2_DataPreparationforNewRun';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 3: Orchestration - Seed main_ranking =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 3, 'Orchestration', 'sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking
            @category_code=@category_code, @year=@ranking_year, @month=@ranking_month, @week=@ranking_week, @run_id=@run_id,
            @rows_inserted=@ri OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_inserted=@ri, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=3; SET @failed_step_name='sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 4: ResultsSelection - Manual modifications =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 4, 'ResultsSelection', 'sp_Rules_Set_Weekly_Events_ManualModifications', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_Set_Weekly_Events_ManualModifications
            @category_code=@category_code, @run_id=@run_id, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=4; SET @failed_step_name='sp_Rules_Set_Weekly_Events_ManualModifications';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 5: ResultsSelection - Results expiry =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 5, 'ResultsSelection', 'sp_Rules_UpdateEventsResultExpiry', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_UpdateEventsResultExpiry
            @category_code=@category_code, @year=@ranking_year, @week=@ranking_week, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=5; SET @failed_step_name='sp_Rules_UpdateEventsResultExpiry';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 6: ResultsSelection - Olympic expiry =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 6, 'ResultsSelection', 'sp_Rules_UpdateOlympicResultExpiry', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Rules_UpdateOlympicResultExpiry @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=6; SET @failed_step_name='sp_Rules_UpdateOlympicResultExpiry';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 7: ResultsSelection - Best-of-8 selection =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 7, 'ResultsSelection', 'sp_Calculate_WTT_SEN_Ranking_BestResults', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_SEN_Ranking_BestResults @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=7; SET @failed_step_name='sp_Calculate_WTT_SEN_Ranking_BestResults';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 8: ResultsSelection - Zero-Point-Penalty =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 8, 'ResultsSelection', 'sp_Calculate_WTT_Ranking_ZeroPointPenalty', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_Ranking_ZeroPointPenalty
            @category_code=@category_code, @event_count=8, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=8; SET @failed_step_name='sp_Calculate_WTT_Ranking_ZeroPointPenalty';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 9: RankingResultPositions - positions (Mandatory) =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 9, 'RankingResultPositions', 'sp_Calculate_WTT_Ranking_RankingPositions', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_WTT_Ranking_RankingPositions
            @category_code=@category_code, @run_id=@run_id, @rows_updated=@ru OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_updated=@ru, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=9; SET @failed_step_name='sp_Calculate_WTT_Ranking_RankingPositions';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    -- ===== Step 10: Orchestration - Finalize =====
    INSERT INTO dbo.ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at)
    VALUES (@run_id, 10, 'Orchestration', 'sp_Calculate_Ranking_FinalizeRun', 'RUNNING', SYSUTCDATETIME());
    SET @step_id = SCOPE_IDENTITY(); SET @step_start = SYSUTCDATETIME();
    BEGIN TRY
        EXEC dbo.sp_Calculate_Ranking_FinalizeRun
            @category_code=@category_code, @run_id=@run_id, @rows_deleted=@rd OUTPUT, @result_message=@msg OUTPUT;
        UPDATE dbo.ranking_run_step SET status='SUCCEEDED', finished_at=SYSUTCDATETIME(),
            duration_ms=DATEDIFF(MILLISECOND,@step_start,SYSUTCDATETIME()), rows_deleted=@rd, result_message=@msg
        WHERE ranking_run_step_id=@step_id;
    END TRY
    BEGIN CATCH
        EXEC dbo.sp__RecordStepFailure @run_id=@run_id, @step_id=@step_id, @step_start=@step_start;
        SET @failed_step_seq=10; SET @failed_step_name='sp_Calculate_Ranking_FinalizeRun';
        SET @failed_error_message=ERROR_MESSAGE();
        GOTO finalize_failed;
    END CATCH

    EXEC dbo.sp_RankingRun_Finalize @run_id=@run_id, @status='SUCCEEDED', @notes=NULL;
    SET @final_status = 'SUCCEEDED';
    GOTO return_result;

    finalize_failed:
        EXEC dbo.sp_RankingRun_Finalize @run_id=@run_id, @status='FAILED', @notes=@failed_error_message;
        SET @final_status = 'FAILED';

    return_result:
        SELECT @run_id AS ranking_run_id, @final_status AS status, @failed_step_seq AS failed_step_seq,
               @failed_step_name AS failed_step_name, @failed_error_message AS error_message;
END
GO
