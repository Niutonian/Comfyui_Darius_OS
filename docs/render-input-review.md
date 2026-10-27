# Render input review

Generation review shows the compiled graph's connected positive/negative prompts,
models and image loader inputs after applying the current form settings. It is
read-only: POST /api/v1/workflows/{id}/preview never calls ComfyUI, an LLM or an
image/video provider, creates an action plan or queues a job. Project ownership
and source-asset checks run before inspecting a workflow.

Cloud contracts and non-API ComfyUI workflows are explicitly labelled as
contract-only previews. They are not presented as verified final provider graphs.
Missing previews disable review actions; inspect errors offer a retry.

A subject duplicated into negative conditioning blocks action-plan creation.
Other mismatches and unrecorded saved image inputs show warnings. Optional blank
text inputs can now be cleared, including negative prompts; required strings
still cannot be empty.

Action plans retain their preview and compiled graph fingerprint. Approval and
the worker reject a changed graph and require a fresh plan. Standing-permission
local renders retain graph evidence in their action plan and record effective
positive text in generation provenance. No generation has been run to test this
feature; regression tests use isolated offline fixtures.

## Workflow selection

All five planner providers now use the same request-scoped subject guard.
OpenAI/DeepSeek resolve a text-only brief just before preparing a visual workflow
or returning a generation draft, after any reference-image inspection. This
uses the selected provider/model and active-project context with user approval;
it may add latency and cloud usage cost. Local/OpenCode paths reuse their cached
brief. Ordinary chat and nonvisual audio requests retain their existing path.
Preparation injects the brief only into verified positive conditioning, retaining
negative prompts, seeds and reference bindings. Queuing verifies the saved
positive text matches the brief. Native tools, vision access and chosen workflow
remain available; unidentifiable conditioning requires correction, not guessing.

Local Ollama/llama.cpp and OpenCode now share subject resolution before the
bounded generation path. The selected model writes a text-only visual brief from
the active project's conversation and production context. Workflow/model commands
stay separate from pixel content. The brief is checkpointed across discovery,
inspection, preparation and retry; missing/ambiguous or command-echo briefs stop
without preparing or queuing. Old command-filled drafts cannot queue on retry.
Questions such as "what does the last image look like?" or "why is this prompt
wrong?" do not enter automatic workflow generation; ordinary tool-enabled replies
remain available without forcing a discovery call.

For the bounded OpenCode/Ollama/llama.cpp workflow path, a selected, authorized
registered workflow is inspected first. Incompatibility or failure stops with an
explanation instead of silently substituting a model. The general cloud planner
receives the same preference policy without restricting its existing tools.

Opening a saved draft for review is separate from choosing a preferred workflow
for future chat requests. Missing selections require an explicit replacement.
Generated drafts, unchanged failed conversions and archived directories are not
automatically ranked as new templates. Explicitly selected saved drafts remain
inspectable, but known subject-in-negative drafts must be rebuilt from an
original workflow.
