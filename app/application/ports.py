"""Ports the domain/use-cases depend on. The GCP adapter (Cloud Healthcare
API, pgvector on Netcup, Vertex Gemini, Document AI) implements these in
app/adapters/gcp and app/adapters/postgres — no port here may import a
cloud SDK. See docs/architecture.md.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.domain.entities import (
    AuditRecord,
    Decision,
    PolicyRevision,
    PriorAuthRequest,
)


class FhirStore(Protocol):
    """Cloud Healthcare API FHIR R4 store. Read-only from this service's
    point of view — Synthea seeding is a one-off load script, not a
    runtime write path.
    """

    def get_coverage(self, patient_id: str) -> tuple[str, str]:
        """Returns (plan_id, region) resolved from the patient's Coverage."""
        ...


class PolicyRepository(Protocol):
    """A caller-supplied plan_id/region/as_of_date is ANDed against a
    server-pinned policy scope — never a free-text search over the whole
    corpus. as_of_date has no default; omitting it is a caller error, not
    a fallback to today(). See HANDOFF.md §5.
    """

    def resolve(
        self,
        *,
        plan_id: str,
        region: str,
        service_codes: list[str],
        as_of_date: date,
    ) -> list[PolicyRevision]: ...


class DocumentationJudge(Protocol):
    """The one genuinely agentic seam: comparing the submitted attachment
    text against the resolved policy's documentation_required list.
    Everything upstream (coverage lookup, revision resolution) is
    deterministic. See app/adapters/gcp/gemini_judge.py.
    """

    def judge(
        self,
        *,
        attachment_text: str | None,
        policy: PolicyRevision | None,
        service_codes: list[str],
    ) -> Decision: ...


class AuditLog(Protocol):
    def record(self, entry: AuditRecord) -> None: ...


class PriorAuthUseCase(Protocol):
    def decide(self, request: PriorAuthRequest) -> Decision: ...
