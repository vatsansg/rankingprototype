"""
Every function in this package is a direct, literal Python+SQL port of a legacy WTT
ranking-engine stored procedure, named identically to that procedure (case preserved
from the legacy SPS/*.sql filename). Re-exported here so engine/master.py can do:

    from engine.procedures import sp_Calculate_WTT_SEN_Ranking_BestResults, ...

See docs/legacy_rule_mapping.md for the full legacy-SP -> prototype-function mapping.
"""

from engine.procedures.step2 import sp_Calculate_Ranking_Step2_DataPreparationforNewRun
from engine.procedures.step3 import sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking
from engine.procedures.finalize import sp_Calculate_Ranking_FinalizeRun
from engine.procedures.manual_modifications import sp_Rules_Set_Weekly_Events_ManualModifications
from engine.procedures.expiry import sp_Rules_UpdateEventsResultExpiry, sp_Rules_UpdateOlympicResultExpiry
from engine.procedures.best_results import (
    sp_Calculate_WTT_SEN_Ranking_BestResults,
    sp_Calculate_WTT_YOU_Ranking_BestResults,
)
from engine.procedures.zpp import sp_Calculate_WTT_Ranking_ZeroPointPenalty
from engine.procedures.positions import (
    sp_Calculate_WTT_Ranking_RankingPositions,
    Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory,
)
from engine.procedures.dependency import Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun
from engine.procedures.ttu_sync import SP_Calculate_Ranking_UpdatePlayersInfoFromTTU

__all__ = [
    "sp_Calculate_Ranking_Step2_DataPreparationforNewRun",
    "sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking",
    "sp_Calculate_Ranking_FinalizeRun",
    "sp_Rules_Set_Weekly_Events_ManualModifications",
    "sp_Rules_UpdateEventsResultExpiry",
    "sp_Rules_UpdateOlympicResultExpiry",
    "sp_Calculate_WTT_SEN_Ranking_BestResults",
    "sp_Calculate_WTT_YOU_Ranking_BestResults",
    "sp_Calculate_WTT_Ranking_ZeroPointPenalty",
    "sp_Calculate_WTT_Ranking_RankingPositions",
    "Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory",
    "Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun",
    "SP_Calculate_Ranking_UpdatePlayersInfoFromTTU",
]
