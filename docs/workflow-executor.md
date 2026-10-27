# Workflow Executor

Chat and voice share a deterministic execution path for selected local base
recipes. The selected model resolves the creative brief; it no longer chooses
the inspect/prepare/queue sequence or rewrites the graph for each request.
Cloud/BFL operations retain their existing contracts and approval path.

## Execution

1. Route the current request to an explicit selection, project default, or global
   default. Local bases come only from the configured default-workflow folder.
2. Inspect/convert the base and register its input contract before requesting a
   model-generated visual brief. Unusable recipes stop before that model call.
3. Resolve the current subject and per-shot project references using the existing
   visual-plan validator. Counts remain limited to one through six outputs.
4. Fill only declared scene fields and supported scalar settings in a copied
   graph. System instructions, negative conditioning, and preserved template
   text are protected. Template image/video examples are never fallback assets.
5. Validate through ComfyUI and create project-owned drafts. Automatic local
   rendering still requires project permission, verified local node origins,
   subject checks, and billing restrictions. Otherwise drafts await approval.
6. Queue through the persisted message/shot idempotency layer. Only returned job
   IDs count as confirmed submissions. Progress and blockers appear in task
   activity and the diagnostic console (`workflow_executor`).

The LangGraph checkpoint retains completed steps. Temporary inspect/preparation
failures can retry once; submission failures never automatically retry. Resume a
saved interrupted request rather than creating a new request if a job might
already exist. A completed blocked reply needs a new request after its mapping,
references, or base workflow are corrected.

## Registering inputs

Open **Create → Trusted workflows → Register inputs** on a folder recipe.
Simple recipes register automatically on first use. Ambiguous descriptions need
explicit roles:

- **Scene / shot description:** receive the current shot's visual prompt.
- **Preserve template text:** keep the base's fixed description or style text.
- **Needs mapping:** block execution until resolved.

System and negative fields are shown read-only. **Save input map** persists the
roles for that base version; **Reinspect base** forces conversion again. Neither
operation renders an image or starts an LLM request. After adding files, use
**Refresh workflows** and associate the recipe with an action as before.

Registration records are stored in `data/workflow-recipes`. Their source hash,
compiled-graph hash, role-contract hash, and ComfyUI URL prevent stale mappings
from silently binding a different base. Converted graphs are reused for at most
five minutes; role mappings survive reconversion when graph slots are unchanged.
Source edits invalidate registration. Atomic writes use directory-inherited
permissions and bounded replacement retries on Windows.

API endpoints:

- `POST /api/v1/workflow-recipes/register`: `{workflow_id, force?}`.
- `PUT /api/v1/workflow-recipes/registration`:
  `{workflow_id, source_digest, roles}`. Stale sources return 409; protected or
  invalid mappings return 422. Cache write failures return a controlled 503.

## Boundaries

### Video auto mode and reviewed chat jobs

Full auto is project-scoped permission, not blanket trust of custom nodes.
The video helper audit now includes `MiniMaxH3SigmaShift`,
`ModelAttentionBackend`, `ImageScaleToTotalPixels`, `H3LocalCameraEditor`,
`ShowText|pysssss`, and `ModelPreviewOverrideKJ`. Their installed implementations
were inspected on 2026-10-18: model patches, image resampling, camera trajectory
compilation, UI text and local previews. Only these exact class/module pairs
are allowed; runtime metadata must still match and must not mark an API node.
Other classes in the same extensions remain untrusted. Changes to extension
code warrant a new audit; this allowlist is not a sandbox or a code signature.

New jobs record `approval_source` as `manual_review` or
`project_local_rendering`. A `local_render_message_id` is a conversation/result
association, not an approval type. Legacy reviewed jobs retain manual approval
when their stored graph digest matches. A standing-permission job's
`local_render_contract` always keeps it on the stricter automatic path, even if
it also has a reviewed digest. Graph changes after review still block execution.
The fix never automatically retries failed jobs or drains unrelated work.

This reduces orchestration mistakes; it cannot guarantee that third-party nodes,
models, network services, or drivers never fail. Live graph validation remains
mandatory. Active video-loader inputs currently block until project-media binding
is supported; their saved example files are not reused. Image references must
match the active image inputs exactly. Graphs without detectable prompt/output
inputs need a compatible base setup. Unknown settings are not guessed from scene
descriptions, and no alternate graph is silently invented after a failure.
