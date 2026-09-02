-- Port of engine/procedures/positions.py -- both position procedures, pure set-based
-- ROW_NUMBER(). Both share the exact same deterministic tiebreak (ranking_points DESC,
-- counted results ASC, NULL-dob-last, dob DESC = younger wins, competitor_id ASC as the final
-- deterministic tiebreak) -- fixing the legacy inconsistency where the age-category sibling
-- used NEWID() (non-deterministic), while the main positions SP used a deterministic
-- CHECKSUM(CompetitorId). Both now share the same deterministic key.
CREATE OR ALTER PROCEDURE dbo.sp_Calculate_WTT_Ranking_RankingPositions
    @category_code NVARCHAR(3), @run_id INT,
    @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        UPDATE mr
        SET ranking_points = ISNULL(agg.total_points, 0)
        FROM dbo.main_ranking mr
        OUTER APPLY (
            SELECT SUM(p.ranking_points) AS total_points
            FROM dbo.players_events_results_master p
            WHERE p.competitor_id = mr.competitor_id AND p.ranking_category_code = mr.ranking_category
              AND p.category_code = mr.category_code AND p.active = 1 AND p.best_result_no_sen_you = 1
        ) agg
        WHERE mr.ranking_run_id = @run_id;

        ;WITH counted AS (
            SELECT competitor_id, ranking_category_code, COUNT(*) AS n
            FROM dbo.players_events_results_master
            WHERE category_code = @category_code AND active = 1 AND best_result_no_sen_you = 1
            GROUP BY competitor_id, ranking_category_code
        ),
        ranked AS (
            SELECT mr.main_ranking_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY mr.ranking_category
                       ORDER BY mr.ranking_points DESC,
                                ISNULL(c.n, 0) ASC,
                                CASE WHEN cp.dob IS NULL THEN 1 ELSE 0 END ASC,
                                cp.dob DESC,
                                mr.competitor_id ASC
                   ) AS pos
            FROM dbo.main_ranking mr
            JOIN dbo.competitors cp ON cp.competitor_id = mr.competitor_id
            LEFT JOIN counted c ON c.competitor_id = mr.competitor_id AND c.ranking_category_code = mr.ranking_category
            WHERE mr.ranking_run_id = @run_id
        )
        UPDATE mr SET ranking_pos = r.pos
        FROM dbo.main_ranking mr JOIN ranked r ON r.main_ranking_id = mr.main_ranking_id;

        SET @rows_updated = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('assigned ranking positions for run ', @run_id);
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO

CREATE OR ALTER PROCEDURE dbo.Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory
    @run_id INT, @rows_updated INT OUTPUT, @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRAN;
    BEGIN TRY
        ;WITH counted AS (
            SELECT competitor_id, ranking_category_code, COUNT(*) AS n
            FROM dbo.players_events_results_master
            WHERE category_code = 'YOU' AND active = 1 AND best_result_no_sen_you = 1
            GROUP BY competitor_id, ranking_category_code
        ),
        ranked AS (
            SELECT mr.main_ranking_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY mr.ranking_category, mr.age_category_code
                       ORDER BY mr.ranking_points DESC,
                                ISNULL(c.n, 0) ASC,
                                CASE WHEN cp.dob IS NULL THEN 1 ELSE 0 END ASC,
                                cp.dob DESC,
                                mr.competitor_id ASC
                   ) AS pos
            FROM dbo.main_ranking mr
            JOIN dbo.competitors cp ON cp.competitor_id = mr.competitor_id
            LEFT JOIN counted c ON c.competitor_id = mr.competitor_id AND c.ranking_category_code = mr.ranking_category
            WHERE mr.ranking_run_id = @run_id AND mr.category_code = 'YOU'
        )
        UPDATE mr SET ranking_pos_age_category = r.pos
        FROM dbo.main_ranking mr JOIN ranked r ON r.main_ranking_id = mr.main_ranking_id;

        SET @rows_updated = @@ROWCOUNT;
        COMMIT TRAN;
        SET @result_message = CONCAT('assigned age-category ranking positions for run ', @run_id);
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN; THROW;
    END CATCH
END
GO
