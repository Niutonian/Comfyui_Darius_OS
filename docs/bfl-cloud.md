# Black Forest Labs cloud generation

Open **Create → Cloud / FLUX 3**, select an operation and write the visual prompt
or edit instruction. Select only the project references you want to send, then
choose **Review cloud generation**. Inspect the parameters, create an action plan,
and explicitly **Approve & queue**. The persistent worker calls BFL directly;
ComfyUI, local GPU memory and local auto-render permission are not involved.

The server reuses BFL_API_KEY from the root .env. BFL_API_BASE_URL is optional
(default https://api.bfl.ai/v1); the existing configured official URL is preserved.
Check connection performs only GET /credits and reports authentication / whether
credits are available. It does not return the key or account balance to the UI.

## Operations and controls

- FLUX 3 Image: generation, editing and combining up to ten image references;
  aspect ratios, resolution through 4k, grounding and moderation settings.
  Bounding boxes and layout instructions are expressed in the visual prompt.
- FLUX 3 Video: text-to-video, keyframes-to-video, video continuation, synchronized
  audio, durations, aspect ratios, resolution through uhd, and draft previews.
- Draft enhancement: select a saved FLUX draft. The encrypted draft-cache bundle
  is downloaded immediately and retained locally so enhancement is not dependent
  on the original signed URL's expiry. The bundle preserves the original generation.
- FLUX Video Edit [fast]: source video plus an edit instruction; the provider fixes
  duration, resolution and audio to the source, so unsupported knobs are not invented.
- FLUX Video Upscale: source video, precise/creative behavior, scale and moderation.

Generation settings expose the current documented fields. Structured references
use JSON, e.g. ["asset:IMAGE_ID", "asset:OTHER_IMAGE_ID"] or timed keyframes
[[0, "asset:FIRST_FRAME_ID"], [8, "asset:LAST_FRAME_ID"]] with duration 8.
Single-video fields offer project assets or explicit API URLs/base64. References
are project-scoped and checked again before submission; managed files are encoded
only after approval. Nothing silently selects another project's media.

## Billing and recovery

Video estimates use documented per-second USD rates for an explicit duration.
Auto duration, image requests, enhancement and tools show price not estimated,
never local/unmetered. BFL's actual reported cost in credits is saved in provenance.
The account remains responsible for provider billing; estimates are not spending caps.

Remote IDs and polling URLs are persisted immediately. Retries resume polling and
downloads instead of submitting another paid request. If the submission response
was lost before its ID was saved, retry is blocked: check the BFL dashboard before
making a fresh approved request. Cancelling locally does not cancel/refund BFL's
already submitted request. Completed outputs are promptly ingested into the active
project's library, including embedded video audio.

Darius uses durable polling rather than exposing provider webhook callbacks.
No new credential-management UI, automatic paid batches, or robotics/action runtime
is included; FLUX 3 Action is an open-weights robotics model, not a hosted image/video
generation endpoint. Existing local and other cloud providers are unchanged.

Official sources checked 2026-10-08:

- https://docs.bfl.ai/flux_3/flux3_overview
- https://docs.bfl.ai/api-reference/utility/generate-an-image-with-flux-3
- https://docs.bfl.ai/api-reference/utility/generate-a-video-with-flux-3
- https://api.bfl.ai/openapi.json

The relevant public request schemas are bundled in bfl-schema.json, avoiding live
schema drift during planning, approval and worker execution. Tests mock all paid
submissions; only a read-only key/credit-availability check was performed live.
