"""
Named constants extracted from the legacy rule configuration data (dbo_Rules.csv, RulesId
9/29/83/84 - Calculate_WTT_SEN/YOU_Ranking_BestResults and WTT_SEN/YOU_APPLY_ZPP), so that
values previously embedded as magic numbers/strings inside SQL Server stored procedures and
JSON rule parameters are visible and named in one place.
"""

ORGANIZATION_CODE = "WTT"

# Best-of-X result counts (RulesId 9 param BestXResults=8, RulesId 29 param BestXResults=10).
SEN_BEST_X_RESULTS = 8
YOU_BEST_X_RESULTS = 10

# Max continental/regional events counted toward best-of-X (RulesId 9/29 param
# BestXResultsForContinantalEvents=1, identical for both categories).
BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS = 1

# Continental/regional event type codes (RulesId 9/29 param ContinentalEventTypeCodes).
CONTINENTAL_EVENT_TYPE_CODES = [
    "CS", "CCH", "Con", "YCCH", "WCC", "CC", "UCC", "ICG", "IE", "YIE",
    "YOUICG", "CCH21", "IEV", "YIEV", "IMS",
]

# Zero-Point-Penalty waiver event counts (RulesId 83 param EventCount=8 for SEN,
# RulesId 84 param EventCount=5 for YOU).
SEN_ZPP_EVENT_COUNT = 8
YOU_ZPP_EVENT_COUNT = 5

# Event types that count toward the ZPP waiver window (RulesId 83/84 param EventType,
# identical for both categories).
ZPP_EVENT_TYPE_CODES = [
    "CC", "CCH", "CE", "IEV", "IMS", "IOE", "OG", "UCC", "WCC", "YIEV",
    "YOG", "YOL", "YCCH", "ICG", "YOUICG", "Con",
]

# Legacy sp_Calculate_WTT_Ranking_ZeroPointPenalty hardcoded WHILE loop ceiling.
MAX_ZPP_PER_PLAYER = 10

# SEN<->YOU cross-award multiplier applied at import time (sp_Import_Step2_Web_OVRResultsToNewEventResults).
CROSS_AWARD_MULTIPLIER = 5

# Point validity: results expire after this many years (sp_Rules_UpdateEventsResultExpiry).
RESULT_VALIDITY_YEARS = 1

# Continental Championships/Games/Cups get this extension (in weeks) if fewer than 2 events
# from that continent are already counted toward the player's best-of-X (Senior only).
CONTINENTAL_EXPIRY_EXTENSION_WEEKS = 26
CONTINENTAL_EXPIRY_MAX_ALREADY_COUNTED = 2

# Olympic Games results expire this many years after being awarded, or when a newer OG event
# exists (sp_Rules_UpdateOlympicResultExpiry).
OLYMPIC_RESULT_VALIDITY_YEARS = 4
