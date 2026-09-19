"""In-memory fakes for app.application.ports. FakePolicyRepository
implements the real WHERE-clause semantics from HANDOFF.md §5 so the
revision-in-force acceptance tests exercise real resolution logic, not a
mocked-out shortcut.
"""

from __future__ import annotations

from datetime import date

from app.application.ports import AuditLog, DocumentationJudge, FhirStore, PolicyRepository
from app.domain.entities import AuditRecord, Decision, DecisionStatus, PolicyRevision


class FakeFhirStore:
    def __init__(self, coverage: dict[str, tuple[str, str]]) -> None:
        self._coverage = coverage

    def get_coverage(self, patient_id: str) -> tuple[str, str]:
        return self._coverage[patient_id]


class MissingAsOfDate(Exception):
    pass


class FakePolicyRepository:
    """No default for as_of_date: calling resolve() without it is a
    TypeError at the call site (it's a required keyword arg), which is
    the Python-level equivalent of the "errors, does not silently
    default to today" contract in HANDOFF.md §5 and acceptance test 3.
    """

    def __init__(self, revisions: list[PolicyRevision]) -> None:
        self._revisions = revisions

    def resolve(
        self,
        *,
        plan_id: str,
        region: str,
        service_codes: list[str],
        as_of_date: date,
    ) -> list[PolicyRevision]:
        matches = [
            r
            for r in self._revisions
            if r.plan_id == plan_id
            and r.region == region
            and any(code in r.service_codes for code in service_codes)
            and r.effective_from <= as_of_date
            and (r.effective_to is None or r.effective_to > as_of_date)
        ]
        return matches


class FakeUnfilteredPolicyRepository(FakePolicyRepository):
    """Control fixture (HANDOFF.md §5, acceptance test 6): the same
    corpus with the date/scope filter removed, proving the filter — not
    an accident of the fixture data — is what excludes superseded
    revisions.
    """

    def resolve(
        self,
        *,
        plan_id: str,
        region: str,
        service_codes: list[str],
        as_of_date: date,
    ) -> list[PolicyRevision]:
        return [
            r
            for r in self._revisions
            if r.plan_id == plan_id
            and r.region == region
            and any(code in r.service_codes for code in service_codes)
        ]


class FakeDocumentationJudge:
    def __init__(self, decision: Decision | None = None) -> None:
        self._decision = decision or Decision(
            status=DecisionStatus.APPROVED, reasoning="fake judge default approval"
        )
        self.calls: list[tuple[str | None, PolicyRevision | None, list[str]]] = []

    def judge(
        self,
        *,
        attachment_text: str | None,
        policy: PolicyRevision | None,
        service_codes: list[str],
    ) -> Decision:
        self.calls.append((attachment_text, policy, service_codes))
        return self._decision


class FakeAuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditRecord] = []

    def record(self, entry: AuditRecord) -> None:
        self.entries.append(entry)
