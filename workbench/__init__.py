"""DNA-Lang Evidence Workbench.

Turn computational and dense retrieval experiments into reproducible, inspectable evidence packages.
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
