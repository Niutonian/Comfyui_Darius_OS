# Visible context, result cards and thumbnail shot browsing

Talk and fullscreen now show a compact **Next message** context strip: project,
saved character/scene/shot, project-note presence and the effective selected or
pinned image references. A separate **Last request used** line shows resolved
production focus from the most recent reply, not a claim that saved preferences
were changed. Explicit instructions and attachments still take priority.

**Change context** opens the existing project editor. **Clear saved focus &
references** reads the latest server record, clears only focus/pinned references,
and clears this device's selected references for that project. Notes, workflow
defaults and chat history are preserved. Saved context updates synchronize across
devices; unsaved edits retain the editor's existing conflict protection. Selected
references remain device-local, as before, and are labelled separately.

Generated results have a single named media card with original-size viewing,
dimensions/duration, original-file download and contextual follow-up actions:

- **Use as reference** deliberately replaces this device's selected references
  with that image. It starts no model request or render; the context strip updates
  so the next voice/text message can use the selected image.
- **Edit / Animate / Upscale** open a separate editable draft. Existing composer
  text is not replaced. Only **Send follow-up** submits a request. It binds exactly
  the chosen project asset and uses the trusted defaults for the new action,
  rather than carrying an incompatible prior workflow. Normal execution mode,
  cloud approval, billing and workflow-validation rules remain authoritative.
- **Retry options** reads saved run guidance only. Uncertain submissions are not
  automatically retried. Actual render retry remains in the existing Background
  jobs/inspector controls. Fullscreen explains how to return to those controls.

Create → Shots is a thumbnail-first board. Each card shows its chosen take,
otherwise its latest take, otherwise a pinned reference, otherwise an honest empty
state. Detailed production controls expand underneath. Adding references and
linking takes use searchable, project-scoped thumbnails, not ID dropdowns. The
underlying Manage scenes & shots view also shows shot thumbnails, all shots rather
than a five-item truncation, and thumbnail media selection in new/edit shot forms.
No preview generation, model download, render or media migration is required.

The context strip sits outside the message scroller so it cannot cover result
buttons. Short landscape windows use the compact shell with either mouse or touch
input; fullscreen context is height-bounded so voice controls stay accessible.

UI tests cover saved focus, remote updates, preserved notes/defaults, asset scope,
explicit follow-up submission and retry guidance. `scripts/check-conversation-studio.cjs`
uses intercepted APIs only and checks Talk, fullscreen, drafts and shot thumbnail
interaction at mobile/tablet/desktop/landscape sizes in both themes. Screenshots
are written to ignored `data/conversation-studio-audit/`.

Verified with 198 frontend tests, TypeScript, targeted ESLint, a production build,
and 20 fixture browser cases across this UI plus existing chat/fullscreen flows.
Local web, API proxy and LAN HTTPS checks returned HTTP 200. No real generations
were submitted during these checks.
