# SECURE TOKENS — Project Context & Technical Handover

**Prepared:** 7 November 2026  
**Purpose:** Context package for Claude or another AI coding/research assistant.

> **Status warning:** Secure Tokens is described in the source material as a research/proposal-stage system. The documents describe proposed architecture and candidate technologies; they do not establish that the full platform is implemented or validated. Distinguish source-backed facts from recommendations and prototype assumptions.

## How to use this handover
Use this as working context before designing or coding. Inspect the repository first. Do not silently convert proposals into approved requirements. Label assumptions, mock behaviour and recommendations.

## 1. Executive summary
Secure Tokens (Secure-Token / ST) is a proposed framework to reduce wasted AI coding-agent token expenditure, verify AI-generated software changes, and compensate eligible failures through an internally funded pool of model-specific service credits.

It has three distinct responsibilities:
- **Optimization:** reduce avoidable model calls, repeated context, unnecessary retries and inefficient model selection.
- **Verification:** assess whether generated work satisfies requirements using tests, builds, static analysis, runtime behaviour, logs and performance evidence.
- **Insurance:** evaluate reported failures under explicit coverage rules and issue eligible internal credits. This is not an automatic refund from the LLM provider.

The research paper adds a team-scoped shared response cache to avoid repeated LLM computation for matching, validated requirements and project context.

## 2. Problem and motivation
Token use comes from repeated conversation/repository context, planning and reasoning, tool calls and tool results, repeated generation/debugging, multi-agent coordination and retries. Developers may pay even when output is incorrect, incomplete or unusable.

The project seeks to reduce unnecessary consumption, verify AI work against original requirements, investigate unsuccessful tasks, issue internal credits for qualifying failures, compare pre/post application behaviour and improve developer confidence.

## 3. Users and system concept
The research paper describes developers using a local IDE plugin connected to cloud services. Examples of client/provider integrations in the overview include OpenAI, Anthropic, Cursor, Copilot and Claude Code; actual coverage depends on integration capabilities and observability.

Actors: developer, IDE/coding agent, Secure Tokens platform, LLM provider, administrator/operator, team members and (for the webhook prototype) external webhook subscribers.

## 4. Architecture in source documents
The architecture PDF groups the system into six functional areas plus persistent storage:

1. **Access & API Gateway:** authentication/virtual developer keys, API gateway, request validation, IDE/agent integration adapter.
2. **Cost-Aware Model Routing:** prompt/task complexity analysis, model capability and cost profiles, routing objective, selected model/context and capability/cost estimates.
3. **Execution & Token Metering:** model execution coordinator, input/output/streaming token meter, verification/escalation controller, usage limits/rate/budget controls.
4. **Project State & Evidence:** pre-change snapshot, change/diff recorder, post-change snapshot, execution metadata/logs/test results, evidence vault.
5. **Quality Assurance & Claims:** claim trigger/evidence retrieval, fault diagnosis/quality evaluation, fault attribution/quality scoring, claim eligibility/coverage rules.
6. **Insurance, Reserve & Learning:** shared reserve pool, compensation calculator, service-credit settlement engine, failure learning/cache invalidation.
7. **Persistent storage grouping:** operational database, team-scoped response cache, snapshot/evidence store, token/credit ledger.

The diagram explicitly says evidence and snapshots are collected during normal work, while expensive diagnostic testing runs when a claim is raised. Claim eligibility and payment capacity are separate; partial settlement may apply.

The overview also presents three principal backend components: AI Proxy & Telemetry (Interceptor), Evaluation Engine (Judge), Ledger & Reimbursement (Insurance), plus a Developer Dashboard.

## 5. Components
### AI Proxy & Telemetry
Sits between supported AI clients and LLM providers; forwards supported requests/responses; captures prompt-response pairs and token usage; records provider/model/cost; associates calls with tasks/sessions. Candidate options include LiteLLM, Bifrost, Helicone, Zuplo, OpenTelemetry, Langfuse, Go, Rust and Python/FastAPI. These are not final selections.

### Cost-aware model routing
Research paper proposes choosing a cheaper open-weight model that clears a quality bar and recording justification. Objective: minimize expected cost per correct answer subject to quality and latency constraints, accounting for context-transfer overhead when switching models. Supplementary notes suggest benchmarking pass rate, tokens by category, retry rate and latency; serving selected tiers behind an OpenAI-compatible gateway; task classification; token estimates; metering; and periodic re-benchmarking. No validated routing algorithm exists in the source material.

### Execution and token metering
Coordinates model execution and captures input, output and streaming usage, with verification/escalation and rate/budget controls.

### Project state and evidence
Captures pre-change and post-change state, diffs, execution metadata, logs and test results, linked to task and execution.

### Evaluation Engine
May use tests/builds, static analysis, semantic similarity/LLM-as-judge, functional checks, user feedback and supporting evidence. Candidate frameworks: DeepEval, Braintrust, FutureAGI, Arize Phoenix. Candidate isolated environments: Firecracker, gVisor, Modal. Do not execute arbitrary project code in the main backend; isolate evaluation with restricted permissions, resource limits, timeouts and controlled networking.

### Ledger, claims and reimbursement
Records usage, claims, decisions and credits. Candidate technologies include PostgreSQL, Redis, Kafka and RabbitMQ. Internal service credits are not provider refunds. Keep actual provider charges, actual token savings, reserve allocations and credits issued as separate accounting quantities.

### Dashboard
Intended to display token use/cost, task/quality information, claims/status, credits and savings/quality trends.

## 6. Snapshot evaluation and fault attribution
Workflow:
1. Pre-integration baseline: repository revision, build/tests, logs/errors, CPU/memory, DB latency/performance and relevant app/DB state.
2. AI agent sandbox: controlled copy, task execution and proposed integration/PR.
3. Post-integration runner: comparable tests, logs, state and performance.
4. Delta analyzer: compare improvements/regressions, warnings/errors, test failures, CPU/memory and DB query/latency changes.

Baseline-aware regression: a test is a potential regression if it was PASS before and FAIL after. Previously failing tests that pass after the change are recorded as possible fixes. Fault categories: implementation defects, regression defects, pre-existing defects, requirement mismatches, environment-related failures and attribution uncertainty.

Quality dimensions proposed: requirement satisfaction, functional correctness, regression safety, code quality, project integrity and scope compliance. Weights sum to one but require empirical calibration. Evidence completeness and attribution confidence are separate. The evaluation report references snapshots, changes, test outcomes, fault classifications, scores and attribution. Evaluation does not determine reimbursement percentage.

## 7. Claims and compensation
Dissatisfaction, technical failure and compensation eligibility are different. Supplementary policy notes propose eligibility conditions: supported/instrumented execution; predefined requirement and signed contract version; mandatory requirement/criterion demonstrably failed; attribution to covered model execution; verifiable billed usage/pricing; active coverage; task-linked usage.

Candidate exclusions include ST internal model usage, successful/unrelated tasks, post-execution requirement changes, ambiguous/incomplete requirements, impossible/contradictory outcomes, external outages/infrastructure failures/unsupported tools, acceptance-compliant outputs challenged only on dissatisfaction, and unsubstantiated usage. Uncertain attribution goes to manual review.

Initial proposed compensation: model-specific internal service credits for future ST usage, not cash or transferable tokens. Versioned coverage terms include providers/models, task categories/integrations, claim window, severity factors, limits, monthly allocation, appeals/manual review, pricing version and conversion rules. Several are unresolved.

A low quality score alone does not prove eligibility. Policy considers evaluation evidence, verified usage, coverage, limits and reserve availability. Partial settlement may apply.

## 8. Optimization and shared cache
Proposals include task-aware model selection, task decomposition, persistent task/repository memory, dynamic model switching while accounting for context handoff, and team-scoped shared response cache.

Cache proposal: store response with project/version, validation status, team permissions, creation time and expiry. SHA-256 fingerprint can help match requirement/context. Check requirement, project version, context, permissions, validation and expiry before reuse. Expired or faulty responses must not be reused. Claims should add verified failure history and invalidate faulty cache entries. Fine-tuning is only a possible future option.

## 9. Illustrations and caveats
- Redis example: baseline 120 ms average DB latency and 1,000 connection events for 1,000 requests; proposed after-change 15 ms and one connection event, with a missing Redis timeout warning. These are illustrative proposal figures, not validated results.
- 500-token budget example (250 computation, 150 pool allocation) leaves 100 unexplained in one document and needs reconciliation.
- MVP targets include 60% reduction in human review time and detection of at least 90% of AI-introduced performance degradations. These are proposed targets, not achieved results.

## 10. Project status and unresolved questions
Conceptually described: underlying problem, token-insurance concept, main architecture, baseline/post-integration workflow, candidate technologies and proposed code-verification MVP.

Not fully specified/validated: scoring algorithm, eligibility/compensation formulas, pool funding/solvency, complete proxy coverage, memory and model-selection algorithms, relationship between delta analysis and claims, and effectiveness against success metrics.

Questions: What exactly is insured? How are requirements/acceptance criteria established? How is model fault separated from ambiguity/user preference/environment? How are savings separated from reserve and credits? How do evaluation and insurance share task identity/evidence? What belongs in MVP? How will metrics be validated?

## 11. Current assignment: webhook automation prototype
The source architecture does **not** specify a finalized webhook subsystem, event catalogue, endpoints or payload schema. Webhook automation is a proposed event-notification layer for this assignment, not an existing documented component.

Recommended prototype: demonstrate a simulated task/claim workflow with automatic event generation and external webhook delivery. Simulate AI execution, evaluation and settlement rather than implementing the full platform.

### Proposed flow
Developer/IDE -> API Gateway -> task record -> baseline snapshot reference -> simulated execution -> usage metadata -> execution complete/fail -> event persistence/publication -> internal queue -> signed HTTP webhook -> sample receiver verifies/records -> post-change snapshot -> claim submission -> evidence retrieval -> simulated evaluation -> adjudication -> mock settlement -> final events.

Important: completion event should not imply post-change evidence is captured unless ordering guarantees it.

### Proposed components
- Event Manager: event ID/type/timestamp/schema version, persistence and publication.
- Internal queue: decouple producers and delivery workers.
- Subscription service: endpoint, event filters and secret reference.
- Delivery worker: event filtering, signing, HTTP POST, logs and retry.
- Sample receiver: signature/timestamp verification, event deduplication and persistence.
- Dashboard: task, event, subscription, delivery, retry, claim and settlement visibility.

Use internal service calls/message queue for internal communication; use HTTP webhooks for external subscribers. Do not turn every internal service call into a webhook.

### Proposed event names (not source-defined)
`task.created`, `snapshot.baseline.created`, `execution.started`, `execution.completed`, `execution.failed`, `snapshot.post.created`, `claim.submitted`, `evaluation.completed`, `claim.adjudicated`, `claim.settled`.

### Suggested prototype stack (recommendation only)
Python/FastAPI, PostgreSQL, SQLAlchemy, Alembic, RabbitMQ, Python workers, HTTPX, Pydantic, HMAC-SHA256, React/Vite, Docker Compose, Pytest.

### Reliability/security
Persist events before delivery; use transactional outbox or equivalent. Deliver asynchronously. Use stable event IDs and idempotency. HTTPS in production; HMAC-SHA256 signatures and timestamp validation. Protect secrets. Validate subscriber URLs against SSRF. Retry transient failures with bounded backoff and dead-letter state. Keep payloads minimal; do not send prompts, source files, credentials or complete snapshots. Provide delivery logs, controlled retry/replay and metrics.

### Demonstration scenarios
1. Successful task and event delivery.
2. Subscriber outage followed by retry/recovery.
3. Invalid signature rejected.
4. Duplicate event deduplicated.
5. Claim/evaluation/adjudication/mock settlement workflow.
6. Insufficient evidence does not automatically approve settlement.

## 12. Design rules
- Keep optimization, verification and insurance distinct.
- Keep quality score, fault attribution, eligibility and payment capacity distinct.
- Do not blame AI for baseline failures.
- Separate environment failures and uncertain attribution.
- Do not treat webhook delivery as proof of business success.
- Separate actual billed usage, savings, reserve allocations and issued credits.
- Label mocks, examples, proposed rules and unvalidated metrics.
- Record assumptions and unresolved decisions.

## 13. Source-based phased plan
1. Project understanding.
2. Problem definition and scope.
3. End-to-end workflow.
4. Evaluation design.
5. Optimization and accounting.
6. Technical architecture.
7. MVP implementation and validation.

## 14. Source files represented
- `securetokens overview.docx`
- `Draft copy of Research paper .docx`
- `architecture.pdf`
- `evaluation.pdf`
- `The split (1).docx`
- `understandings of the solution (ST).docx`

The source files contain evolving and incomplete proposals. This handover does not resolve all inconsistencies or turn every idea into an approved specification.

## 15. Instructions to Claude
1. Restate your understanding of Secure Tokens and the webhook prototype assignment.
2. Separate source-backed facts, prior decisions and your own recommendations.
3. Inspect the repository before proposing edits.
4. Do not silently settle unresolved scoring, policy, model-routing or financial questions.
5. Focus the webhook prototype on durable event creation, internal async delivery, secure external webhooks, retries, idempotency, observability and an end-to-end demonstration.
6. Implement in phases and test each phase.
7. Clearly label simulated execution, mock snapshots, simulated evaluation and mock credits.
8. The immediate assignment is the webhook automation prototype, not the complete Secure Tokens platform.
