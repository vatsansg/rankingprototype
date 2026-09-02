class DependencyNotMetError(Exception):
    """Raised by Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun when the required prior
    Senior run has not completed successfully. Caught specifically by master.py to mark the
    Youth run ABORTED_DEPENDENCY rather than the generic FAILED."""


class RankingRunFailed(Exception):
    """Raised by engine.master when the T-SQL master procedure's returned status is not
    SUCCEEDED; carries the run/step context from the procedure's final result row."""

    def __init__(self, run_id: int, step_seq, step_name, original: Exception):
        super().__init__(f"Run {run_id} failed at step {step_seq} ({step_name}): {original}")
        self.run_id = run_id
        self.step_id = step_seq
        self.step_name = step_name
        self.original = original
