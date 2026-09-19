"""Acceptance tests from HANDOFF.md §8, run against the domain use case
with in-memory fakes — no GCP, no network, no cost. These are meant to
fail if the revision-in-force claim breaks; that's the whole point of
this build (HANDOFF.md §1).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.application.use_cases.decide_prior_auth import DecidePriorAuth
from app.domain.entities import DecisionStatus, PolicyRevision, PriorAuthRequest
from tests.unit.fakes import (
    FakeAuditLog,
    FakeDocumentationJudge,
    FakeFhirStore,
    FakePolicyRepository,
    FakeUnfilteredPolicyRepository,
)

R2 = PolicyRevision(
    policy_id="MP-0042",
    revision_id="MP-0042-r2",
    effective_from=date(2026, 1, 1),
    effective_to=date(2026, 6, 1),
    plan_id="plan-a",
    region="asia-south1",
    service_codes=["64483"],
    documentation_required=["6-week conservative therapy trial"],
    text="r2 text",
)

R3 = PolicyRevision(
    policy_id="MP-0042",
    revision_id="MP-0042-r3",
    effective_from=date(2026, 6, 1),
    effective_to=None,
    plan_id="plan-a",
    region="asia-south1",
    service_codes=["64483"],
    documentation_required=["12-week conservative therapy trial"],
    text="r3 text",
)

PLAN_B_POLICY = PolicyRevision(
    policy_id="MP-9001",
    revision_id="MP-9001-r1",
    effective_from=date(2026, 1, 1),
    effective_to=None,
    plan_id="plan-b",
    region="asia-south1",
    service_codes=["64483"],
    documentation_required=["plan B requirement"],
    text="plan B text — a better semantic match for the plan A query, by construction",
)


def make_use_case(policy_repository):
    return DecidePriorAuth(
        fhir_store=FakeFhirStore({"patient-1": ("plan-a", "asia-south1")}),
        policy_repository=policy_repository,
        documentation_judge=FakeDocumentationJudge(),
        audit_log=FakeAuditLog(),
        model_version="test-fixture",
    )


def make_request(dos: date, patient_id: str = "patient-1") -> PriorAuthRequest:
    return PriorAuthRequest(
        claim_id="claim-1",
        patient_id=patient_id,
        plan_id="plan-a",
        region="asia-south1",
        service_codes=["64483"],
        date_of_service=dos,
        attachment_text="conservative therapy notes",
    )


def test_revision_in_force_uses_r2_while_r3_is_live():
    repo = FakePolicyRepository([R2, R3])
    use_case = make_use_case(repo)

    use_case.decide(make_request(date(2026, 2, 15)))

    [entry] = use_case.audit_log.entries
    assert entry.revision_id == "MP-0042-r2"
    assert entry.policy_id == "MP-0042"


def test_superseded_revision_never_cited_after_its_effective_to():
    repo = FakePolicyRepository([R2, R3])
    use_case = make_use_case(repo)

    use_case.decide(make_request(date(2026, 7, 1)))

    [entry] = use_case.audit_log.entries
    assert entry.revision_id == "MP-0042-r3"
    assert entry.revision_id != "MP-0042-r2"


def test_missing_as_of_date_is_a_caller_error_not_a_default_to_today():
    repo = FakePolicyRepository([R2, R3])

    with pytest.raises(TypeError):
        repo.resolve(plan_id="plan-a", region="asia-south1", service_codes=["64483"])  # type: ignore[call-arg]


def test_cross_plan_isolation_never_leaks_a_better_matching_plan_b_policy():
    repo = FakePolicyRepository([R2, R3, PLAN_B_POLICY])
    use_case = make_use_case(repo)

    use_case.decide(make_request(date(2026, 2, 15)))

    [entry] = use_case.audit_log.entries
    assert entry.policy_id == "MP-0042"
    assert entry.policy_id != "MP-9001"


def test_honest_refusal_when_no_governing_policy_exists():
    repo = FakePolicyRepository([])  # empty corpus for this plan/service
    use_case = make_use_case(repo)

    decision = use_case.decide(make_request(date(2026, 2, 15)))

    assert decision.status == DecisionStatus.NEEDS_MORE_INFO
    assert "no governing policy" in decision.reasoning.lower()
    assert "fabricate" in decision.reasoning.lower()


def test_control_fixture_unfiltered_view_does_return_superseded_revision():
    repo = FakeUnfilteredPolicyRepository([R2, R3])

    results = repo.resolve(
        plan_id="plan-a", region="asia-south1", service_codes=["64483"], as_of_date=date(2026, 7, 1)
    )

    revision_ids = {r.revision_id for r in results}
    assert revision_ids == {"MP-0042-r2", "MP-0042-r3"}


def test_audit_completeness_records_revision_model_and_decision():
    repo = FakePolicyRepository([R2, R3])
    use_case = make_use_case(repo)

    use_case.decide(make_request(date(2026, 2, 15)))

    [entry] = use_case.audit_log.entries
    assert entry.claim_id == "claim-1"
    assert entry.revision_id == "MP-0042-r2"
    assert entry.model_version == "test-fixture"
    assert entry.decision == DecisionStatus.APPROVED
