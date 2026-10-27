# Chat stabilization and readable media names

The shared chat/voice execution path now has four clearer boundaries:

1. Resolve explicit saved scene/shot numbers before planning. Ambiguous numbers
   ask which scene, rather than picking an unrelated shot. An adjacent answer
   such as “scene 2” continues the unfinished request. Chat-proposed shots remain
   usable without first creating a Production Bible record. Explicit character
   names are checked in the visual brief; separate shots keep separate subjects.
2. Use trusted project/global defaults and reject an explicitly incompatible
   workflow. Several configured recipes without a default ask for a choice.
   Inspected input mappings, image counts and unsupported video inputs are checked
   before paying for a creative visual brief. Explicit attachments take precedence
   over pinned references; current-conversation previews can identify “this image.”
3. Render receipts use database-confirmed jobs, never model promises. Planning,
   clarification, approval and rendering stay distinct. Batch status remains active
   while any render is running/queued, even when another failed. Worker updates
   synchronize the saved user task and assistant task metadata.
4. Blockers are saved replies with contextual recovery controls in Talk and
   fullscreen. Retry saved request reuses the original user message and attachments,
   rechecks current setup and permissions, and uses a new preparation checkpoint.
   Previous blockers are retained as superseded history, not deleted. Recovery
   acknowledgements are idempotent. Existing associated jobs in **any** state block
   this preparation retry; use Background jobs for render-level recovery instead.
   Partial or uncertain submissions never automatically retry.

The retry endpoint is
`POST /api/v1/conversations/{conversation_id}/messages/{message_id}/retry-preparation`.
It only accepts the latest recoverable request, checks ownership, takes the
conversation lock and checks persisted job associations before allowing preparation.
It does not start a worker, submit a render, grant approval or change workflow
defaults. The subsequent normal reply path keeps all existing billing, provenance,
node-trust and queue-idempotency checks.

## Naming and speech

New generations get short display names based on the explicitly resolved character,
scene and shot where available, otherwise a bounded descriptive prompt title. Jobs
expose a computed `display_name`; IDs and private payloads are not display labels.
Asset library, viewer, reference-picker and chat job status use readable names.
Legacy filename/hash suffixes are cleaned at display time. Renaming an asset still
uses the existing project-scoped rename operation.

Storage filenames, IDs, provenance links and existing records are **not renamed or
migrated**. Classic/Pipecat speech chunks remove UUIDs, opaque hashes and technical
filename suffixes before synthesis, including replies streamed in multiple pieces.
Saved text and diagnostic IDs remain unchanged. Normal assistant prompting also
asks for human names; technical identifiers remain available on explicit request.
The speech filter is intentionally separate from diagnostic text.

## Verification and limits

`tests/test_chat_stabilization.py` covers clarification, subject preservation,
separate shots, safe retry, worker status and all five planner transports. UI tests
cover saved-message recovery, streamed speech sanitization and readable labels.
Existing workflow/approval/Block Party/device-sync tests remain applicable.

These checks prevent common orchestration mistakes; they do not guarantee semantic
model quality or eliminate third-party service, GPU, driver or custom-node failures.
No additional naming model call is made. Cloud approval requirements are unchanged.
