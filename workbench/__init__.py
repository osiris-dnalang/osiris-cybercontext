"""DNA-Lang Evidence Workbench.

Package computational and dense-retrieval experiments into inspectable, replayable evidence capsules.
"""

from .schema import ExperimentSpec, ExecutionPolicy, AuthorizationGrant
from .engine import EvidenceWorkbenchEngine, GovernanceAuthorizationViolation, QuotaExceededViolation
from .capsule import EvidenceCapsule
from .replay import ReplayEngine, ReplayVerdict, ReplayStatus

__all__ = [
    "ExperimentSpec",
    "ExecutionPolicy",
    "AuthorizationGrant",
    "EvidenceWorkbenchEngine",
    "GovernanceAuthorizationViolation",
    "QuotaExceededViolation",
    "EvidenceCapsule",
    "ReplayEngine",
    "ReplayVerdict",
    "ReplayStatus",
]
