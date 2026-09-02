-- Port of engine/procedures/dependency.py. THROW 51001 is a sentinel error number: the
-- sp_Calculate_Ranking_YOU master procedure's CATCH for this step tests ERROR_NUMBER()=51001
-- to set the run's final status to ABORTED_DEPENDENCY instead of the generic FAILED.
CREATE OR ALTER PROCEDURE dbo.Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun
    @year INT, @month INT, @week INT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @sen_run_id INT;
    SELECT TOP 1 @sen_run_id = ranking_run_id FROM dbo.ranking_run
    WHERE category_code = 'SEN' AND ranking_year = @year AND ranking_month = @month AND ranking_week = @week
      AND status = 'SUCCEEDED'
    ORDER BY ranking_run_id DESC;

    IF @sen_run_id IS NULL
    BEGIN
        DECLARE @msg NVARCHAR(400) = CONCAT(
            'Senior Category Ranking Run should be completed for ', @year, '-', RIGHT('0' + CAST(@month AS VARCHAR(2)), 2),
            ' week ', @week, ' before the Youth run can proceed.');
        THROW 51001, @msg, 1;
    END
    SET @result_message = CONCAT('Senior run ', @sen_run_id, ' confirmed SUCCEEDED for this period');
END
GO
