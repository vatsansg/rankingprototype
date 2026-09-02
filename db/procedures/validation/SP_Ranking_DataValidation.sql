-- Port of validation/run_validation.py::SP_Ranking_DataValidation. Orchestrates the checks
-- above (kept as separate procedures, mirroring validation/checks/*.py 1:1 for testability),
-- then returns the findings just recorded via a final SELECT for direct rendering.
CREATE OR ALTER PROCEDURE dbo.SP_Ranking_DataValidation
    @category_code NVARCHAR(3), @run_id INT, @validation_category NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;
    IF @validation_category NOT IN ('PreRankingValidation','PostRankingValidation')
        THROW 51400, 'validation_category must be PreRankingValidation or PostRankingValidation', 1;

    IF @validation_category = 'PreRankingValidation'
    BEGIN
        EXEC dbo.sp_ValidateNullPoints @category_code=@category_code, @run_id=@run_id, @validation_category=@validation_category;
        EXEC dbo.sp_ValidateDuplicateResults @category_code=@category_code, @run_id=@run_id, @validation_category=@validation_category;
    END
    ELSE
    BEGIN
        EXEC dbo.sp_ValidateDuplicateResults @category_code=@category_code, @run_id=@run_id, @validation_category=@validation_category;
        EXEC dbo.sp_ValidatePointsPositionMismatch @run_id=@run_id, @validation_category=@validation_category;
    END

    SELECT * FROM dbo.ranking_validation_result WHERE ranking_run_id = @run_id AND validation_category = @validation_category
    ORDER BY ranking_validation_result_id;
END
GO
