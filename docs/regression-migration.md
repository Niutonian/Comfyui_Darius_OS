# Regression coverage for the creative-helper release

Chat is a text-only creative helper. Canvas Generate is the supported rendering
entry point. Tests must not restore retired chat execution through a mode flag,
subclass or monkeypatch of the production capability guards.

The old suite expected chat to prepare and submit workflows. Its clean v8 baseline
had 1,086 passes, 21 failures, 42 setup errors and one optional-runtime skip.
The migration replaces obsolete success expectations with the current policy
and retains the generation safety checks through supported paths or persisted
historical job fixtures. No test was skipped or xfailed to obtain a passing run.

| Previous expectation / responsibility | Current coverage |
| --- | --- |
| Chat queues batches under standing project permission | `test_local_render`: every former mutation operation is rejected with permission both enabled and disabled, including malformed envelopes and repeated attempts; no jobs, workflow files or worker launches |
| Direct queue helper can launch from chat | `test_local_render`: direct submission rejects single, multiple, oversized, mixed-subject, video and continuation requests |
| Three distinct subjects survive preparation and retries | `test_workflow_plans`: three independent Canvas documents retain their individual prompts in generation records and compiled graphs; out-of-order submission and repeated idempotency keys create exactly three jobs |
| Chat retry resumes rendering | Chat/provider tests assert stable replies and no rendering. Canvas generation tests verify explicit approval, immutable snapshots and idempotency. `test_job_recovery` verifies interrupted/stale work without resubmission |
| Workflow executor resumes after persisted steps | `test_workflow_executor`: a new executor consumes serialized prepare/queue receipts and does not repeat those operations |
| Worker rechecks authorization | Persisted historical jobs include real generation records and snapshot contracts; revoked permission, modified graph hashes and unverified node origins fail before renderer execution |
| Manual approval differs from standing permission | Four linked/unlinked and manual/automatic job combinations assert the approval flag delivered to the renderer |
| Worker does not run unrelated jobs or replay completion | A targeted worker claims its requested persisted job once; another queued job remains queued |
| Custom H3 helpers must have verified origins | Known local H3 classes pass; external/API flags, unknown classes and changed module ownership fail |
| Generated video keeps its reference and seed | A reviewed job with a persisted historical message association executes through the worker and retains asset parentage, seed, readable name and completed task receipt |
| Legacy review can create another chat render | Chat-associated proposals are rejected. Independent manual review still supports concurrent approval with one job; persisted legacy receipt updates remain tested |
| Workflow setup is required to discuss a concept | Creative-helper tests make workflow routing fail if invoked; discussion, clarification history and prompt development continue without submitting work |
| Old conversation planning endpoint invokes a planner | `/plan` returns 410 without invoking the injected model; saved messages remain intact |
| Selected board context triggers generation | `test_moss_workspace`: selected board context is read-only, reply retry is stable, and no generation or prompt mutation occurs |
| Model-specific chat context includes executable workflow catalogs | OpenAI/local/DeepSeek and streaming tests verify creative-helper context and the absence of executable workflow catalog context |

Compile/recipe adaptation, subject binding and reference provenance also retain
their pure-function and Canvas board tests. Real ComfyUI renders are owner-tested
separately; the automated suite uses isolated databases, fake renderers and local
HTTP fixtures rather than GPU inference or paid provider calls.
