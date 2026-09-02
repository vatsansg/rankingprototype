-- Table type for bulk-importing a parsed result CSV in one round trip (see
-- db/procedures/import/sp_ImportNewEventsResults.sql and importer/load_new_events_results.py).
-- NOTE: table types cannot be ALTERed and cannot be dropped while any procedure references
-- them as a parameter type. On a from-scratch deploy (the normal case -- see db/deploy_db.py)
-- this CREATE runs once against an empty database. If you need to change this type's shape
-- later, drop dbo.sp_ImportNewEventsResults first, then this type, then redeploy both.
CREATE TYPE dbo.NewEventsResultTVP AS TABLE (
    event_id INT NOT NULL, event_name NVARCHAR(300) NOT NULL,
    event_type_general_code NVARCHAR(10) NOT NULL, event_type_code NVARCHAR(10) NULL,
    ranking_year INT NOT NULL, ranking_month INT NOT NULL, ranking_week INT NOT NULL,
    competitor_id INT NOT NULL, player_name NVARCHAR(200) NOT NULL, dob DATE NULL, gender NVARCHAR(10) NULL,
    country_code NVARCHAR(5) NULL, age_category_code NVARCHAR(10) NOT NULL, is_retired BIT NOT NULL DEFAULT 0,
    sub_event_code NVARCHAR(10) NOT NULL, ranking_category_code NVARCHAR(10) NOT NULL, category_code NVARCHAR(3) NOT NULL,
    result_position NVARCHAR(10) NOT NULL, matches_played INT NULL, matches_won INT NULL, matches_lost INT NULL,
    qualifier BIT NOT NULL DEFAULT 0, zero_point_penalty BIT NOT NULL DEFAULT 0
);
GO
