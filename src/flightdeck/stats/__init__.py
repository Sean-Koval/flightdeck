"""v0 statistics: intervals and paired comparisons over tasks (docs/statistics.md)."""

from flightdeck.stats.core import (
    Interval,
    clean_run_bound,
    dollars_per_resolved,
    mcnemar_discordant,
    paired_bootstrap,
    pass_at_k,
    pass_hat_k,
    pass_hat_k_suite,
    trial_bootstrap,
    wilson,
)

__all__ = ["Interval", "clean_run_bound", "dollars_per_resolved", "mcnemar_discordant", "paired_bootstrap",
           "pass_at_k", "pass_hat_k", "pass_hat_k_suite", "trial_bootstrap", "wilson"]
