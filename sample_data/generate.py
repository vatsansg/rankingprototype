"""
Generates the 5 sample fixture sets under sample_data/<name>/. Fully deterministic (no RNG)
so fixtures are reviewable in a diff and reproducible on every run. Each fixture folder gets:
  - result_file.csv : a "result import file" in the flat format importer/load_new_events_results.py
                       expects (structurally faithful to legacy NewEventsResults, not a literal
                       OVR export -- see sample_data/README.md).
  - setup.sql        : optional extra DB state a scenario needs beyond a plain import
                        (e.g. a doubles pair row, a deliberately duplicated result row).

Run: python sample_data/generate.py
"""

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent

FIELDS = [
    "event_id", "event_name", "event_type_general_code", "event_type_code",
    "ranking_year", "ranking_month", "ranking_week",
    "competitor_id", "player_name", "dob", "gender", "country_code", "age_category_code", "is_retired",
    "sub_event_code", "ranking_category_code", "category_code", "result_position",
    "matches_played", "matches_won", "matches_lost", "qualifier", "zero_point_penalty",
]

COUNTRIES = ["CHN", "JPN", "GER", "FRA", "BRA", "USA", "SWE", "KOR", "EGY", "IND", "ROU", "POL", "NGR", "AUS", "CAN"]


def _row(**kwargs) -> dict:
    row = {f: "" for f in FIELDS}
    row.update(kwargs)
    return row


def _write(fixture_dir: Path, rows: list[dict], setup_sql: str | None = None) -> None:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    with (fixture_dir / "result_file.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    if setup_sql is not None:
        (fixture_dir / "setup.sql").write_text(setup_sql, encoding="utf-8")
    print(f"wrote {fixture_dir.name}: {len(rows)} row(s)" + (" + setup.sql" if setup_sql else ""))


# ---------------------------------------------------------------------------------------
# 1. Senior happy path: 15 competitors, 10 events (8 WCH + 2 Con/continental), each player
#    gets a result in all 10 -> best-of-8 trimming exercised, and every player has exactly
#    2 continental results -> max-1-continental cap exercised. Player 90001's 5th event is
#    swapped for an active ZPP entry to exercise the zero-point-penalty pipeline.
# ---------------------------------------------------------------------------------------
def senior_happy_path() -> None:
    rows = []
    event_types = ["WCH"] * 8 + ["Con", "Con"]
    positions_cycle = ["W", "F", "SF", "QF", "R16", "R32", "QF", "SF", "F", "R16"]

    for i in range(15):
        competitor_id = 90001 + i
        gender = "M" if i < 10 else "F"
        ranking_category = "MS" if gender == "M" else "WS"
        rotated = positions_cycle[i % len(positions_cycle):] + positions_cycle[: i % len(positions_cycle)]

        for e in range(10):
            event_id = 80001 + e
            event_type = event_types[e]
            zpp = 1 if (competitor_id == 90001 and e == 4) else 0
            rows.append(_row(
                event_id=event_id, event_name=f"{event_type} Event {e + 1}",
                event_type_general_code=event_type, event_type_code=event_type,
                ranking_year=2026, ranking_month=1, ranking_week=1,
                competitor_id=competitor_id, player_name=f"SEN Player {i + 1}",
                dob=f"{1995 + (i % 8)}-0{1 + (i % 9) % 9}-15", gender=gender,
                country_code=COUNTRIES[i % len(COUNTRIES)], age_category_code="SEN", is_retired=0,
                sub_event_code=ranking_category, ranking_category_code=ranking_category, category_code="SEN",
                result_position=rotated[e], matches_played=3, matches_won=2, matches_lost=1, qualifier=0,
                zero_point_penalty=zpp,
            ))

    _write(HERE / "senior_happy_path", rows)


# ---------------------------------------------------------------------------------------
# 2. Youth happy path: 12 singles competitors (U17), 11 events (WCDR64) -> best-of-10
#    trimming exercised. Plus a doubles pair (91013/91014) whose players_doubles row is
#    deliberately drifted to age_category_code='SEN' (the documented legacy bug) even though
#    both individual players are U17 -- exercises the Step3 age-category-derivation fix.
#    Requires a prior SUCCEEDED Senior run for the same period (set up by the test/demo
#    driver, not baked into this fixture) to satisfy the Youth dependency guard.
# ---------------------------------------------------------------------------------------
def youth_happy_path() -> None:
    rows = []
    positions_cycle = ["W", "F", "SF", "QF", "R16", "R32", "R64", "QF", "SF", "F", "R16"]

    for i in range(12):
        competitor_id = 91001 + i
        gender = "M" if i < 6 else "F"
        ranking_category = "MS" if gender == "M" else "WS"
        rotated = positions_cycle[i % len(positions_cycle):] + positions_cycle[: i % len(positions_cycle)]

        for e in range(11):
            event_id = 81001 + e
            rows.append(_row(
                event_id=event_id, event_name=f"WCDR64 Event {e + 1}",
                event_type_general_code="WCDR64", event_type_code="WCDR64",
                ranking_year=2026, ranking_month=1, ranking_week=1,
                competitor_id=competitor_id, player_name=f"YOU Player {i + 1}",
                dob=f"{2009 + (i % 2)}-0{1 + (i % 9) % 9}-10", gender=gender,
                country_code=COUNTRIES[i % len(COUNTRIES)], age_category_code="U17", is_retired=0,
                sub_event_code=ranking_category, ranking_category_code=ranking_category, category_code="YOU",
                result_position=rotated[e], matches_played=3, matches_won=2, matches_lost=1, qualifier=0,
                zero_point_penalty=0,
            ))

    # Doubles pair exercising the age-category-drift fix (see step3.py _effective_age_category).
    # Uses U15/COC (age_category_code='U15', event_type='COC') because ranking_calc_main has no
    # MD points row for U17 (a genuine legacy reference-data gap, not a prototype bug) -- U15/COC
    # does have one, so this row carries real points and survives the end-of-run zero-point purge,
    # giving a meaningful end-to-end assertion instead of a row that gets purged either way.
    rows.append(_row(
        event_id=81012, event_name="COC Event", event_type_general_code="COC", event_type_code="COC",
        ranking_year=2026, ranking_month=1, ranking_week=1,
        competitor_id=91013, player_name="YOU Doubles Player A", dob="2011-03-01", gender="M",
        country_code="CHN", age_category_code="U15", is_retired=0,
        sub_event_code="MD", ranking_category_code="MD", category_code="YOU",
        result_position="W", matches_played=2, matches_won=1, matches_lost=1, qualifier=0, zero_point_penalty=0,
    ))

    setup_sql = (
        "-- Player B of the doubles pair (Player A, 91013, is registered via the CSV import above).\n"
        "INSERT INTO competitors (competitor_id, player_name, dob, gender, country_code, nationality_code, "
        "age_category_code, is_retired) VALUES (91014, 'YOU Doubles Player B', '2011-05-20', 'M', 'JPN', 'JPN', "
        "'U15', 0);\n"
        "-- Deliberately drifted age_category_code='SEN' on the pair row, mirroring the documented legacy bug.\n"
        "INSERT INTO players_doubles (doubles_id, player1_id, player2_id, sub_event_code, age_category_code) "
        "VALUES (1, 91013, 91014, 'MD', 'SEN');\n"
    )
    _write(HERE / "youth_happy_path", rows, setup_sql)


def youth_dependency_failure() -> None:
    # Same shape as youth_happy_path, but the test/demo driver must NOT run Senior first --
    # that omission is what exercises Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun.
    rows = []
    for i in range(6):
        competitor_id = 94001 + i
        gender = "M" if i < 3 else "F"
        ranking_category = "MS" if gender == "M" else "WS"
        rows.append(_row(
            event_id=84001 + i, event_name=f"WCDR64 Event {i + 1}", event_type_general_code="WCDR64",
            event_type_code="WCDR64", ranking_year=2026, ranking_month=2, ranking_week=5,
            competitor_id=competitor_id, player_name=f"YOU NoDep Player {i + 1}",
            dob="2009-06-01", gender=gender, country_code=COUNTRIES[i % len(COUNTRIES)],
            age_category_code="U17", is_retired=0,
            sub_event_code=ranking_category, ranking_category_code=ranking_category, category_code="YOU",
            result_position="QF", matches_played=2, matches_won=1, matches_lost=1, qualifier=0, zero_point_penalty=0,
        ))
    _write(HERE / "youth_dependency_failure", rows)


# ---------------------------------------------------------------------------------------
# 3. Validation failure: a normal small import, plus a setup.sql that injects a duplicate
#    players_events_results_master row directly (bypassing step2's own dedupe guard) --
#    exercises the post-ranking duplicate-results validation check.
# ---------------------------------------------------------------------------------------
def validation_failure() -> None:
    rows = [
        _row(
            event_id=82001, event_name="WCH Event", event_type_general_code="WCH", event_type_code="WCH",
            ranking_year=2026, ranking_month=3, ranking_week=10,
            competitor_id=92001, player_name="Validation Test Player", dob="1998-01-01", gender="M",
            country_code="CHN", age_category_code="SEN", is_retired=0,
            sub_event_code="MS", ranking_category_code="MS", category_code="SEN",
            result_position="QF", matches_played=3, matches_won=2, matches_lost=1, qualifier=0, zero_point_penalty=0,
        ),
    ]
    setup_sql = (
        "-- Injected AFTER a run has seeded players_events_results_master, to simulate a\n"
        "-- data-integrity problem (duplicate result row) for SP_Ranking_DataValidation to catch.\n"
        "-- The test driver runs this against the already-populated table (competitor 92001, event 82001).\n"
        "INSERT INTO players_events_results_master (competitor_id, event_id, sub_event_code, "
        "ranking_category_code, result_position, ranking_points, ranking_year, ranking_month, ranking_week, "
        "expiry_year, expiry_month, expiry_week, active, category_code, age_category_code) "
        "SELECT competitor_id, event_id, sub_event_code, ranking_category_code, result_position, ranking_points, "
        "ranking_year, ranking_month, ranking_week, expiry_year, expiry_month, expiry_week, active, category_code, "
        "age_category_code FROM players_events_results_master "
        "WHERE competitor_id=92001 AND event_id=82001 AND ranking_category_code='MS';\n"
    )
    _write(HERE / "validation_failure", rows, setup_sql)


# ---------------------------------------------------------------------------------------
# 4. Calculation failure: one row carries an unrecognized ranking_category_code ('ZZ'),
#    which imports fine (importer does not validate against ranking_categories) but makes
#    sp_Calculate_Ranking_Step2_DataPreparationforNewRun raise during Run Now.
# ---------------------------------------------------------------------------------------
def calculation_failure() -> None:
    rows = [
        _row(
            event_id=83001, event_name="Bad Category Event", event_type_general_code="WCH", event_type_code="WCH",
            ranking_year=2026, ranking_month=4, ranking_week=15,
            competitor_id=93001, player_name="Calc Failure Player", dob="1999-01-01", gender="M",
            country_code="CHN", age_category_code="SEN", is_retired=0,
            sub_event_code="ZZ", ranking_category_code="ZZ", category_code="SEN",
            result_position="QF", matches_played=3, matches_won=2, matches_lost=1, qualifier=0, zero_point_penalty=0,
        ),
    ]
    _write(HERE / "calculation_failure", rows)


if __name__ == "__main__":
    senior_happy_path()
    youth_happy_path()
    youth_dependency_failure()
    validation_failure()
    calculation_failure()
