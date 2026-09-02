-- Port of SP_Calculate_Ranking_UpdatePlayersInfoFromTTU (documented stub -- no live TTU feed
-- in this prototype; simply reports the current competitors table size).
CREATE OR ALTER PROCEDURE dbo.SP_Calculate_Ranking_UpdatePlayersInfoFromTTU
    @organization_code NVARCHAR(10) = 'WTT', @result_message NVARCHAR(400) OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @cnt INT = (SELECT COUNT(*) FROM dbo.competitors);
    SET @result_message = CONCAT('stub: no live TTU feed in prototype; ', @cnt, ' competitor(s) already on file');
END
GO
