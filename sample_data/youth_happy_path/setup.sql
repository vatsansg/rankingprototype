-- Player B of the doubles pair (Player A, 91013, is registered via the CSV import above).
INSERT INTO competitors (competitor_id, player_name, dob, gender, country_code, nationality_code, age_category_code, is_retired) VALUES (91014, 'YOU Doubles Player B', '2011-05-20', 'M', 'JPN', 'JPN', 'U15', 0);
-- Deliberately drifted age_category_code='SEN' on the pair row, mirroring the documented legacy bug.
INSERT INTO players_doubles (doubles_id, player1_id, player2_id, sub_event_code, age_category_code) VALUES (1, 91013, 91014, 'MD', 'SEN');
