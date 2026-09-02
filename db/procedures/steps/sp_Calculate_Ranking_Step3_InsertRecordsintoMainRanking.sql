-- Port of engine/procedures/step3.py::sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking.
-- Fully set-based doubles age-category-derivation fix (no cursor): a CTE with OUTER APPLY +
-- a VALUES-based priority table picks the most-restrictive (youngest) age category from both
-- players of a doubles pair, instead of trusting players_doubles.age_category_code (which
-- drifts to 'SEN' for youth pairs -- the documented legacy bug).
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking
    @category_code NVARCHAR(3), @year INT, @month INT, @week INT, @run_id INT,
    @rows_inserted INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        ;WITH candidates AS (
            SELECT DISTINCT p.competitor_id, p.ranking_category_code, c.age_category_code AS stored_age_category
            FROM dbo.players_events_results_master p
            JOIN dbo.competitors c ON c.competitor_id = p.competitor_id
            WHERE p.category_code = @category_code AND p.active = 1
              AND c.is_retired = 0 AND c.wtt_eligibility = 1
        ),
        doubles_pair AS (
            SELECT cand.competitor_id, cand.ranking_category_code, cand.stored_age_category, pd.player1_id, pd.player2_id
            FROM candidates cand
            OUTER APPLY (
                SELECT TOP 1 player1_id, player2_id FROM dbo.players_doubles pd
                WHERE pd.player1_id = cand.competitor_id OR pd.player2_id = cand.competitor_id
                ORDER BY pd.doubles_id
            ) pd
            WHERE cand.ranking_category_code IN ('MD','WD','XD','MDI','WDI','XDI')
        ),
        pair_ages AS (
            SELECT dp.competitor_id, dp.ranking_category_code, dp.stored_age_category,
                   c1.age_category_code AS age1, c2.age_category_code AS age2
            FROM doubles_pair dp
            LEFT JOIN dbo.competitors c1 ON c1.competitor_id = dp.player1_id
            LEFT JOIN dbo.competitors c2 ON c2.competitor_id = dp.player2_id
        ),
        priority(rank_no, code) AS ( SELECT * FROM (VALUES (1,'U11'),(2,'U13'),(3,'U15'),(4,'U17'),(5,'U19'),(6,'SEN')) v(rank_no,code) ),
        effective AS (
            SELECT pa.competitor_id, pa.ranking_category_code,
                   COALESCE(
                       (SELECT TOP 1 pr.code FROM priority pr WHERE pr.code IN (pa.age1, pa.age2) ORDER BY pr.rank_no),
                       pa.stored_age_category
                   ) AS effective_age_category
            FROM pair_ages pa
        )
        INSERT INTO dbo.main_ranking
            (competitor_id, ranking_pos, ranking_points, ranking_category, ranking_year, ranking_month, ranking_week,
             category_code, age_category_code, ranking_run_id)
        SELECT
            cand.competitor_id, NULL, 0, cand.ranking_category_code, @year, @month, @week, @category_code,
            COALESCE(eff.effective_age_category, cand.stored_age_category, @category_code), @run_id
        FROM candidates cand
        LEFT JOIN effective eff ON eff.competitor_id = cand.competitor_id AND eff.ranking_category_code = cand.ranking_category_code;

        SET @rows_inserted = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('seeded ', @rows_inserted, ' main_ranking placeholder rows');
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
