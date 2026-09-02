-- Reference data seeded verbatim from the legacy production CSV exports under
-- C:\vatsan\ranking\RANKINGS2026\data\ (read-only source, not modified).
-- Source files: dbo_Categories.csv, dbo_Age_Categories.csv, dbo_RankingCategories.csv,
-- dbo_ResultPosition.csv, dbo_ModificationType.csv, dbo_ReasonType.csv,
-- dbo_AvailableRankingRuns.csv, dbo_AvailableRankingRunsCategories.csv.
-- ranking_calc_main (366 rows) is seeded separately by db/seed/load_ranking_calc_main.py
-- directly from dbo_RankingCalcMain_New.csv to avoid manual transcription of a large table.

INSERT INTO categories (category_code, category_description, organization_code) VALUES
    ('SEN', 'Senior', 'WTT'),
    ('YOU', 'YOUTH', 'WTT');

-- NOTE: two rows in the legacy CSV carry OrganizationCode='3' instead of 'WTT' for U21 --
-- a documented data-quality anomaly in the source, preserved here verbatim rather than
-- silently "corrected", per the prototype's documented-limitations principle.
INSERT INTO age_categories (age_category_code, age_category_description, min_age_inclusive, max_age_inclusive, category_code, organization_code) VALUES
    ('U19', 'U19', 18, 19, 'YOU', 'WTT'),
    ('U17', 'U17', 16, 17, 'YOU', 'WTT'),
    ('U15', 'U15', 14, 15, 'YOU', 'WTT'),
    ('U13', 'U13', 12, 13, 'YOU', 'WTT'),
    ('U11', 'U11', 9, 11, 'YOU', 'WTT'),
    ('SEN', 'SENIOR', 22, 999, 'SEN', 'WTT');
    -- U21 / U21-Youth anomaly rows (OrganizationCode='3') intentionally excluded from the
    -- prototype's active reference set -- see docs/legacy_rule_mapping.md "Known data anomalies".

INSERT INTO ranking_categories (ranking_category_id, ranking_category_code, category_code, ranking_category_desc, ranking_order) VALUES
    (2, 'MD', 'SEN', 'MEN DOUBLES', 3),
    (3, 'MDI', 'SEN', 'MEN DOUBLES INDIVIDUAL', 4),
    (4, 'MS', 'SEN', 'MEN SINGLES', 1),
    (5, 'MT', 'SEN', 'TEAM MEN', 9),
    (6, 'WD', 'SEN', 'WOMEN DOUBLES', 5),
    (7, 'WDI', 'SEN', 'WOMEN DOUBLES INDIVIDUAL', 6),
    (8, 'WS', 'SEN', 'WOMEN SINGLES', 2),
    (9, 'WT', 'SEN', 'TEAM WOMEN', 10),
    (10, 'XD', 'SEN', 'MIXED DOUBLES', 7),
    (11, 'XDI', 'SEN', 'MIXED DOUBLES INDIVIDUAL', 8),
    (12, 'XT', 'SEN', 'Mixed Doubles Team', 11),
    (13, 'MD', 'YOU', 'Boys DOUBLES', 3),
    (14, 'MDI', 'YOU', 'Boys DOUBLES INDIVIDUAL', 4),
    (15, 'MS', 'YOU', 'Boys SINGLES', 1),
    (16, 'MT', 'YOU', 'TEAM Boys', 9),
    (17, 'WD', 'YOU', 'Girls DOUBLES', 5),
    (18, 'WDI', 'YOU', 'Girls DOUBLES INDIVIDUAL', 6),
    (19, 'WS', 'YOU', 'Girls SINGLES', 2),
    (20, 'WT', 'YOU', 'TEAM Girls', 10),
    (21, 'XD', 'YOU', 'Youth MIXED DOUBLES', 7),
    (22, 'XDI', 'YOU', 'Youth MIXED DOUBLES INDIVIDUAL', 8),
    (23, 'XT', 'YOU', 'Youth Mixed Doubles Team', 11);

-- result_position: PositionValue (draw-size denominator) is category-specific --
-- SEN and YOU each have their own numbering, per the legacy dbo_ResultPosition.csv.
INSERT INTO result_position (result_position_id, position, phase, position_order, phase_type, round_number, position_value, category_code, organization_code) VALUES
    (1, 'W', 'F', 1, 'KO', 8, 1, 'SEN', 'WTT'),
    (2, 'F', 'F', 2, 'KO', 8, 2, 'SEN', 'WTT'),
    (3, 'QF', 'QF', 4, 'KO', 6, 5, 'SEN', 'WTT'),
    (4, 'QR1', 'QR1', 4, 'QUAL', 1, 25, 'SEN', 'WTT'),
    (5, 'QR2', 'QR2', 3, 'QUAL', 2, 49, 'SEN', 'WTT'),
    (7, 'QR3', 'QR3', 2, 'QUAL', 3, 57, 'SEN', 'WTT'),
    (8, 'QR4', 'QR4', 1, 'QUAL', 4, 73, 'SEN', 'WTT'),
    (9, 'R128', 'R128', 8, 'KO', 2, 65, 'SEN', 'WTT'),
    (10, 'R16', 'R16', 5, 'KO', 5, 9, 'SEN', 'WTT'),
    (12, 'R256', 'R256', 9, 'KO', 1, 129, 'SEN', 'WTT'),
    (13, 'R32', 'R32', 6, 'KO', 4, 17, 'SEN', 'WTT'),
    (15, 'R64', 'R64', 7, 'KO', 3, 33, 'SEN', 'WTT'),
    (17, 'SF', 'SF', 3, 'KO', 7, 3, 'SEN', 'WTT'),
    (35, 'W', 'F', 1, 'KO', 8, 1, 'YOU', 'WTT'),
    (36, 'F', 'F', 2, 'KO', 8, 2, 'YOU', 'WTT'),
    (37, 'QF', 'QF', 4, 'KO', 6, 4, 'YOU', 'WTT'),
    (38, 'QR1', 'QR1', 4, 'QUAL', 1, 13, 'YOU', 'WTT'),
    (39, 'QR2', 'QR2', 3, 'QUAL', 2, 12, 'YOU', 'WTT'),
    (40, 'QR3', 'QR3', 2, 'QUAL', 3, 11, 'YOU', 'WTT'),
    (41, 'QR4', 'QR4', 1, 'QUAL', 4, 10, 'YOU', 'WTT'),
    (42, 'R128', 'R128', 8, 'KO', 2, 8, 'YOU', 'WTT'),
    (43, 'R16', 'R16', 5, 'KO', 5, 5, 'YOU', 'WTT'),
    (44, 'R256', 'R256', 9, 'KO', 1, 9, 'YOU', 'WTT'),
    (45, 'R32', 'R32', 6, 'KO', 4, 6, 'YOU', 'WTT'),
    (46, 'R64', 'R64', 7, 'KO', 3, 7, 'YOU', 'WTT'),
    (47, 'SF', 'SF', 3, 'KO', 7, 3, 'YOU', 'WTT');

INSERT INTO modification_type (modification_type_id, modification_type) VALUES
    (1, 'Points_Modification'),
    (2, 'Position_Modification'),
    (3, 'Insert'),
    (4, 'Deactivate_Players_Event_Results');

INSERT INTO reason_type (reason_type_id, reason_type) VALUES
    (1, 'Late Cancellation'),
    (2, 'Others'),
    (3, 'Injury'),
    (4, 'Anti_Doping_Sanction');

INSERT INTO available_ranking_runs (available_ranking_runs_id, ranking_run_name, ranking_run_description, organization_code) VALUES
    (1, 'SeniorAndYouth', 'Senior and Youth', 'WTT'),
    (3, 'Senior', 'Senior', 'WTT'),
    (4, 'Youth', 'Youth', 'WTT');

INSERT INTO available_ranking_runs_categories (available_ranking_runs_categories_id, available_ranking_runs_id, category_code, run_order) VALUES
    (1, 1, 'SEN', 1),
    (2, 1, 'YOU', 2),
    (3, 3, 'SEN', 1),
    (4, 4, 'YOU', 1);

-- Singleton current-state pointer per category (legacy RankingEngineInfo). Seed with a
-- reasonable baseline; the prototype updates this at the end of a successful run.
INSERT INTO ranking_engine_info (ranking_info_id, category_code, organization_code, current_ranking_year, current_ranking_month, current_ranking_week) VALUES
    (1, 'SEN', 'WTT', 2026, 1, 1),
    (2, 'YOU', 'WTT', 2026, 1, 1);
