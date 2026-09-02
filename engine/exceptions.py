class DependencyNotMetError(Exception):
    """Raised by Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun when the required prior
    Senior run has not completed successfully. Caught specifically by master.py to mark the
    Youth run ABORTED_DEPENDENCY rather than the generic FAILED."""
