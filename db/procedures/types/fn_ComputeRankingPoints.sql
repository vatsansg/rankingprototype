-- Port of importer/load_new_events_results.py::compute_points(). Inline table-valued function
-- (inlined into the query plan, not a per-row scalar UDF): unpivots ranking_calc_main's 19
-- round columns via CROSS APPLY VALUES. Returns zero rows when zero_point_penalty=1, or no
-- matching ranking_calc_main row, or an unrecognized result_position -- callers always
-- ISNULL(...,0) the result, exactly as compute_points() does.
CREATE OR ALTER FUNCTION dbo.fn_ComputeRankingPoints
(
    @category_code NVARCHAR(3), @age_category_code NVARCHAR(10), @ranking_category_code NVARCHAR(10),
    @event_type_general_code NVARCHAR(10), @result_position NVARCHAR(10), @zero_point_penalty BIT
)
RETURNS TABLE
AS
RETURN
(
    SELECT TOP 1 CAST(pts.points AS DECIMAL(10,2)) AS ranking_points
    FROM dbo.ranking_calc_main rcm
    CROSS APPLY (VALUES
        ('W', rcm.w), ('F', rcm.f), ('SF', rcm.sf), ('QF', rcm.qf),
        ('R16', rcm.r16), ('R32', rcm.r32), ('R64', rcm.r64), ('R128', rcm.r128), ('R256', rcm.r256),
        ('QUAL', rcm.qual), ('QER', rcm.qer),
        ('QR4', rcm.qr4), ('QR3', rcm.qr3), ('QR2', rcm.qr2), ('QR1', rcm.qr1),
        ('G4L', rcm.g4l), ('G3L', rcm.g3l), ('G2L', rcm.g2l), ('GL', rcm.gl)
    ) AS pts(code, points)
    WHERE rcm.category_code = @category_code AND rcm.age_category_code = @age_category_code
      AND rcm.ranking_category_code = @ranking_category_code AND rcm.event_type = @event_type_general_code
      AND pts.code = UPPER(@result_position) AND @zero_point_penalty = 0
);
GO
