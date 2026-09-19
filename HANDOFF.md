# HANDOFF — Governed Prior Authorization API (CMS-0057-F)

Self-contained build spec. Read this instead of reconstructing context.
Written 2026-09-16. Target platform: Google Cloud. Budget: ~$100 of a $300 trial.

---

## 1. Why this exists

**CMS-0057-F** requires impacted payers — Medicare Advantage orgs, Medicaid/CHIP
managed care, state Medicaid agencies, and QHPs on federally facilitated
exchanges — to run four FHIR APIs by **1 January 2027**: Patient Access,
Provider Access, Payer-to-Payer, and **Prior Authorization**.

The Prior Authorization API must:
- identify covered items and services requiring authorization
- **surface documentation requirements**
- exchange requests and responses
- return approval / denial / additional-information-needed status

This build implements the Prior Authorization slice, with a governed policy
layer underneath it. The other three APIs are out of scope.

**The differentiating claim this project exists to test:**

> A prior authorization decision must be made against the medical policy
> revision **in force on the date of service** — not the revision in force
> today. A system that cannot prove which revision it used cannot be audited,
> and a system that silently uses today's revision is producing regulatory
> findings at scale.

Everything else here is scaffolding for that claim.

## 2. Scope and non-goals

**In scope:** Da Vinci PAS-shaped request/response; documentation-requirement
lookup resolved by date of service; reasoning over a clinical attachment
against the requirement list; an audit record citing the policy revision ID.

**Explicit non-goals:**
- No real PHI, ever. Synthetic data only (see §4).
- Not multi-tenant, not SaaS. Single-tenant demonstrator.
- Not X12 278 translation. FHIR-native only.
- No CRD (CDS Hooks) or DTR (CQL questionnaires) unless phase 7 is reached.
  These are separate Da Vinci IGs and each is a project in its own right.

**Verify before building:** the exact Da Vinci PAS IG version and profile
requirements. Do not trust this document's FHIR resource list as complete —
read the IG. `Claim` with `$submit`, `ClaimResponse`, `Coverage`, `Patient`,
`Practitioner`, `Organization`, `Bundle` are the expected core.

## 3. Architecture

```
  Simulated provider client (tests/client.py)
            │  POST /Claim/$submit   (FHIR Bundle)
            ▼
  ┌──────────────────────────────────────────────┐
  │  Cloud Run: pas-service (FastAPI)            │
  │                                              │
  │   1. validate Bundle, extract service + DOS  │
  │   2. resolve coverage → plan_id, region      │
  │   3. policy lookup  ── asOf=DOS ────────────┐│
  │   4. reason over attachment vs requirements ││
  │   5. emit ClaimResponse + audit record      ││
  └─────────────────────────────────────────────┼┘
       │              │              │          │
       ▼              ▼              ▼          ▼
  Cloud Healthcare  Policy View   Vertex AI   Document AI
  API (FHIR R4)     API           (Gemini)    (attachments)
                    │
                    └─ pgvector, date-versioned corpus
```

**Ports and adapters.** Domain logic (policy resolution, decisioning) must not
import GCP SDKs. Mirror the layout already used in `invoice-ocr-pipeline`:
`blueprint/` capability contract, `app/` domain, `iac/` provider-specific.
This is what keeps the build portable off GCP when credits expire.

## 4. Data

**Synthetic patients:** [Synthea](https://synthetichealth.github.io/synthea)
generates FHIR R4 bundles — patients, encounters, conditions, coverage. Free,
open source, zero PHI, zero compliance exposure. Generate ~200 patients.

**Policy corpus — this is the part that matters.** Hand-author a small corpus
of synthetic medical policies (~15 policies × 2–3 revisions each). Each record:

| column | notes |
|---|---|
| `policy_id` | stable across revisions, e.g. `MP-0042` |
| `revision_id` | unique, e.g. `MP-0042-r3` |
| `effective_from` | date, inclusive |
| `effective_to` | date, exclusive; NULL = current |
| `plan_id` | scoping |
| `region` | scoping |
| `service_codes[]` | CPT/HCPCS the policy governs |
| `documentation_required[]` | the requirement list |
| `text`, `embedding` | for retrieval |

**Revision resolution is a WHERE clause, not a ranking heuristic:**

```sql
WHERE policy_id = :pid
  AND effective_from <= :date_of_service
  AND (effective_to IS NULL OR effective_to > :date_of_service)
```

Deliberately author overlapping revisions where a requirement *changed* — e.g.
`MP-0042-r2` requires a 6-week conservative-therapy trial, `r3` requires 12.
A request with a February DOS must get r2's six weeks even though r3 is live.
**This pair is the core acceptance test.**

## 5. The policy view contract

Reuse the view model already proven in `external-kb`: a `knowledge_id` is a
**corpus plus a mandatory policy pinned server-side**. The caller's conditions
are ANDed with it — a caller can narrow, never widen.

Extend it with `as_of_date` as a **mandatory** parameter. There is no default.
A caller that omits it gets an error, not today's date. Defaulting to today is
precisely the bug this project exists to demonstrate the absence of.

Keep an unfiltered view (`-unfiltered`) out of production tokens, as the control
fixture proving the filter is what removes the superseded revision.

**Never port a score threshold across embedding models.** Recalibrate on change;
refuse to serve a corpus whose vectors came from a different model.

## 6. GCP services and cost

| Service | Use | Est. |
|---|---|---|
| Cloud Healthcare API | FHIR R4 store, Synthea seed | ~$10 |
| Cloud Run | pas-service, scales to zero | $0 |
| Vertex AI (Gemini) | reasoning over attachment vs requirements | $40–80 |
| Document AI | clinical attachment extraction (phase 6) | ~$15 |
| BigQuery | eval analytics, 1 TB/mo free | $0 |
| **Total** | | **~$100** |

### Burn traps — do not provision

- **Vertex AI Vector Search / Matching Engine.** Index endpoints bill
  continuously at roughly $0.50–1.00/hour (~$400–700/month) whether queried or
  not. This is the GCP analogue of the Bedrock → OpenSearch Serverless trap.
  **Use pgvector on the existing Netcup box, or BigQuery vector search**
  (serverless, per-query, no idle cost).
- **GKE** — ~$73/month control plane alone.
- **Cloud SQL** — always-on. Avoid; reuse existing Postgres.
- **Any persistent Vertex endpoint** — bills per hour deployed.

Set a **budget alert before the first deploy**, matching the AWS
`any-spend-tripwire` pattern: zero-spend template so it fires on the first
metered charge rather than reading $0 while credits drain.

## 7. Build order

Each phase ends in something demonstrable and testable.

1. **FHIR store + seed.** Cloud Healthcare API dataset, FHIR R4 store, Synthea
   bundles loaded. Verify by reading a Patient back through the API.
2. **Policy corpus.** Table, embeddings, the date-resolution query. No service
   yet — prove resolution with direct queries including the r2/r3 boundary.
3. **PAS skeleton.** Cloud Run + FastAPI, accepts a Claim Bundle, returns a
   hardcoded ClaimResponse. Contract shape correct, no intelligence.
4. **Wire policy lookup.** DOS extracted from the Claim, passed as `as_of_date`.
   Response now carries the requirement list and the revision ID used.
5. **Reasoning.** Gemini compares submitted documentation against the
   requirement list → approve / deny / needs-more-info, with the gap named.
6. **Document AI.** Parse an actual attachment (faxed clinical notes remain
   real in prior auth) instead of structured input.
7. *(stretch)* CRD via CDS Hooks, DTR questionnaires.

## 8. Acceptance tests

Written so they **can fail**. A test that cannot fail proves nothing.

1. **Revision-in-force.** Claim with DOS inside r2's window returns r2's
   requirements and cites `MP-0042-r2`, while r3 is live. Fails if today's
   revision leaks.
2. **Superseded exclusion.** No response ever cites a revision whose
   `effective_to` precedes the DOS.
3. **Missing as_of_date.** Policy view called without `as_of_date` errors.
   Does not silently default to today.
4. **Cross-plan isolation.** A Plan A request never retrieves a Plan B policy,
   including when Plan B's text is a better semantic match.
5. **Honest refusal.** A service with no governing policy returns
   needs-more-info with the reason — never a fabricated requirement list.
6. **Control fixture.** The same query against `-unfiltered` *does* return the
   superseded revision, proving the filter is doing the work.
7. **Audit completeness.** Every ClaimResponse has an audit record naming the
   policy revision, the retrieval scores, and the model version.

## 9. Deployment

Cloud Run, single region (`asia-south1` for latency, or `us-central1` for
price — decide and record). Container from Artifact Registry. No custom domain
needed for a demonstrator; Cloud Run's URL is sufficient.

`catalyst.json`-equivalent config committed; secrets via Secret Manager, never
in the image.

## 10. Open decisions

- **Vector store:** pgvector on Netcup (free, reuses existing) vs BigQuery
  vector search (GCP-native, serverless, small per-query cost). Recommend
  BigQuery if the goal is demonstrating GCP capability; Netcup if minimising
  spend.
- **Region:** `asia-south1` vs `us-central1`.
- **Gemini model:** Flash for cost vs Pro for reasoning quality on the
  documentation-gap analysis. Start Flash, measure, upgrade only if the golden
  set shows it failing.
- **Embedding model:** `gemini-embedding-001` (needs recalibration of the
  score threshold) vs whatever the existing corpus uses. Do not mix.

## 11. What this does not prove

State this in the README. It is a demonstrator on synthetic data, not a
certified product. It has no BAA, no SOC 2, no HITRUST, and has never seen
PHI. Claiming otherwise fails the first vendor questionnaire and costs more
credibility than the build earns.

---

## Progress log

**2026-09-19 — Phase 1 complete.** GCP project `prior-auth-fhir-demo`
(us-central1, billed to 011792-88ACE6-5A25BC) created with a budget
tripwire at ₹10/50/100/200. Cloud Healthcare API dataset
(`prior-auth-dataset`) + FHIR R4 store (`prior-auth-fhir-store`) created.
227 Synthea Massachusetts patients loaded (16 of 244 failed on
executeBundle's 4500-resource size cap — long-lived patients with deep
histories; skipped, not worth chasing for a demonstrator). Verified via
`Patient?_count=500` read-back.

Note: Synthea's default FHIR export nests Coverage as a `contained`
resource inside ExplanationOfBenefit, not as a standalone resource — and
its payer taxonomy (Medicare/Medicaid/commercial insurers) won't line up
with the synthetic policy corpus's plan_id/region scheme from §4 anyway.
Decision: the simulated provider client (tests/client.py, phase 3) will
construct its own top-level Coverage resources on submitted Claim
bundles, scoped to match the hand-authored policy corpus — not rely on
Synthea's.

Domain layer (app/domain, app/application) scaffolded with all 7 §8
acceptance tests passing against in-memory fakes (tests/unit/) before
any cloud resource existed.
