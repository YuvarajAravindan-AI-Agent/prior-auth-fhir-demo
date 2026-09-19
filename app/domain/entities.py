"""Domain entities. No FHIR SDK, no GCP SDK imports here — this module
must stay importable with nothing but the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class DecisionStatus(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"
    NEEDS_MORE_INFO = "needs-more-info"


@dataclass(frozen=True)
class PriorAuthRequest:
    claim_id: str
    patient_id: str
    plan_id: str
    region: str
    service_codes: list[str]
    date_of_service: date
    attachment_text: str | None = None


@dataclass(frozen=True)
class PolicyRevision:
    """One row resolved by the date-of-service WHERE clause in
    app/adapters/postgres/policy_repository.py — never assembled by
    ranking a similarity score.
    """

    policy_id: str
    revision_id: str
    effective_from: date
    effective_to: date | None
    plan_id: str
    region: str
    service_codes: list[str]
    documentation_required: list[str]
    text: str


@dataclass(frozen=True)
class DocumentationGap:
    requirement: str
    satisfied: bool
    reasoning: str


@dataclass(frozen=True)
class Decision:
    status: DecisionStatus
    reasoning: str
    gaps: list[DocumentationGap] = field(default_factory=list)


@dataclass(frozen=True)
class AuditRecord:
    claim_id: str
    policy_id: str | None
    revision_id: str | None
    date_of_service: date
    retrieval_scores: dict[str, float]
    model_version: str
    decision: DecisionStatus
    reasoning: str
