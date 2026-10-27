# Darius task harness

Implemented September 14, 2026 using LangGraph 1.2.11 and its SQLite checkpointer.

## Execution

The conversational assistant executes a graph of model, individual tool, and result-verification steps through the selected OpenAI or DeepSeek Responses API provider. Each saved user message identifies a task scoped to its project. Checkpoints live under `data/agent-checkpoints/`, one SQLite file per task. They contain request context, model/tool responses, step counts, and inspected/reference asset IDs. API keys and live service objects are not part of graph state. DeepSeek's API is stateless, so Darius supplies the complete bounded request and tool history on every model call.

The conversational `comfyui` tool can also create or update characters, scenes, and shots in the active project's production bible when the user explicitly asks. These operations apply the same validation and project ownership checks as the Create page and emit project events so the UI refreshes.

The existing project database remains authoritative for assets, permissions, generation records and jobs. The graph does not replace ComfyUI workers or enable new rendering permissions. Manual/Full auto continue to use the existing execution gates.

## Recovery

Use Retry reply or Resume saved task after a failure or API restart. A new provider instance loads the checkpoint and continues at its unfinished step. Completed model/tool steps are reused. A completed reply checkpoint can also be retrieved if delivery to the browser failed.

An interruption inside a tool can cause that in-flight tool to execute again. Render queueing relies on its existing persisted user-message/job association to avoid duplicate jobs. This is not an exactly-once guarantee for every MCP operation. API request serialization remains scoped to the supported single API process.

The graph retains the bounded 16-tool exploration budget and a 165-second per-attempt time limit. Retry resumes saved work rather than resetting completed steps. Exhausting the total tool budget calls for a new focused request. There is no automatic startup scan that resumes every unfinished conversation.

## Progress and results

Talk acknowledges a submission immediately, distinguishing message saving from
saved work. Its task card reads a bounded 64-event activity history stored on the
source message, so fast operations are not lost between browser polls. Completed
steps and failures are expandable; this is execution status, not model reasoning
or a claim that a queued render has finished.

Within one attempt, identical failed tool requests are not executed again. The
model can correct arguments or choose another supported approach within the
existing call/time limits. An explicit retry clears this failure guard while
retaining completed checkpoints. Generation permissions, retry-safe per-message batch slots
protection, and the background worker remain authoritative. This does not add
automatic paid-provider switching, visual quality review, or voice barge-in.

Model planning, tool operations, verification and task pauses update user-message metadata and durable project events. Existing Talk polling displays these milestones. The event stream now advances beyond 500 events and accepts Last-Event-ID on reconnect.

The verification step checks queued job ownership; if rendering has already completed, it also checks output presence, project ownership, job provenance and files. Longer renders remain owned by the job worker; ingestion updates the source task to completed/failed. Live job cards remain authoritative when a saved assistant reply describes an earlier queue state. The model's full answer is still delivered at the end of its reply; token streaming is not implemented here.

## Validation

Synthetic tests cover checkpoint recovery after model failure, isolated project namespaces, per-tool checkpoints, completed-result replay, invalid reply recovery, API retry with one queue/worker launch, event-stream reconnect, and a mocked image-to-video flow with image binding, seed preservation, naming, ingestion and provenance verification. No paid AI request or live MiniMax render was submitted for this migration.

This first slice improves durable execution. General project-edit tools, broader creative memory, automatic abandoned-task recovery, and live video-quality acceptance remain follow-up work.
