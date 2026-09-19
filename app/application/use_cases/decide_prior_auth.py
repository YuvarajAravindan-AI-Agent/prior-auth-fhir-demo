from __future__ import annotations

from dataclasses import dataclass

from app.application.ports import AuditLog, DocumentationJudge, FhirStore, PolicyRepository
from app.domain.entities import (
    AuditRecord,
    Decision,
    DecisionStatus,
    PriorAuthRequest,
)


@dataclass
class DecidePriorAuth:
    """Acceptance test 5 (honest refusal) and test 3 (no default as_of_date)
    live here: this is the only place that calls PolicyRepository.resolve,
    and it always passes request.date_of_service explicitly — there is no
    code path in this use case that can omit it.
    """

    fhir_store: FhirStore
    policy_repository: PolicyRepository
    documentation_judge: DocumentationJudge
    audit_log: AuditLog
    model_version: str

    def decide(self, request: PriorAuthRequest) -> Decision:
        plan_id, region = self.fhir_store.get_coverage(request.patient_id)

        revisions = self.policy_repository.resolve(
            plan_id=plan_id,
            region=region,
            service_codes=request.service_codes,
            as_of_date=request.date_of_service,
        )

        policy = revisions[0] if revisions else None

        if policy is None:
            decision = Decision(
                status=DecisionStatus.NEEDS_MORE_INFO,
                reasoning=(
                    f"No governing policy found for service codes "
                    f"{request.service_codes} under plan {plan_id!r}, "
                    f"region {region!r}, as of {request.date_of_service}. "
                    "Refusing to fabricate a requirement list."
                ),
            )
        else:
            decision = self.documentation_judge.judge(
                attachment_text=request.attachment_text,
                policy=policy,
                service_codes=request.service_codes,
            )

        self.audit_log.record(
            AuditRecord(
                claim_id=request.claim_id,
                policy_id=policy.policy_id if policy else None,
                revision_id=policy.revision_id if policy else None,
                date_of_service=request.date_of_service,
                retrieval_scores={},
                model_version=self.model_version,
                decision=decision.status,
                reasoning=decision.reasoning,
            )
        )

        return decision
