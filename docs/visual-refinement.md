# Visual refinement · 21 October 2026

Authority: `data/screenshots/DARIUS_OS_VISUAL_HANDOFF.md`. The 20 October screenshot tour is the before baseline, not proof of live voice or rendering behavior.

## Scope

This pass reuses Next.js 16.3.4, React 19.1.1, Zustand, React Flow, Motion, the desktop/dock/window chrome, and the existing semantic light/dark tokens. It does not change provider contracts, workflow execution, approval gates, ownership checks, graph semantics or editing capabilities. No new service integration or deployment.

## Implemented concerns

- Composer allocation: compact command access in non-Talk desktop apps, an in-flow expandable footer, bounded composer growth, and graph/workspace resizing rather than added bottom padding.
- Editing space: bounded preview, independently scrolling material bin and clip inspector, a directly accessible timeline, concise no-selection state, and phone Preview / Media bin / Clip details controls. Existing trim, drag, undo, render and export actions remain.
- Preferences: category rail on desktop; categories and back navigation on phones. Existing global workflow defaults and project overrides remain distinct; model/services, browser appearance, voice and project execution controls retain their existing save behavior. Hidden panes stay mounted and pending changes/errors remain visible.
- Create: distinct Characters and Scenes emphasis using the same production records, readable library cards with secondary actions under disclosure, existing media viewer, and a return action from shot details.
- Continuity: document-local, project/record-scoped UI state for filters, selections, graph viewport, editor playhead/zoom and drafts. No files, media or credentials are added to browser storage. Existing timeline recovery remains unchanged.
- Project isolation: restore each destination project's selected references and selection; snapshot outgoing message references before awaiting conversation creation. Merely selecting a Home folder no longer retargets the assistant; Open, double-click, and the project switcher activate projects.
- Status: summarize issues before activity and local availability, while a disclosure retains independent sync, agent, job and provider states. Background jobs separate active work from history; existing supported actions are retained.
- Voice presentation: leaving fullscreen returns to chat; the separately labeled End action ends the voice session. Existing pause/listen controls remain separate.
- Motion: small inspector transition, existing window motion, preserved focus during composer reparenting, reduced-motion behavior and no graph/grid/timeline flying animations.

## Verification record

- `npm run typecheck`: passed.
- `npm run build`: passed (Next production build). Next still emits its existing experimental localStorage warning while prerendering.
- `npm run lint`: no errors; five existing dependency warnings in the Classic/Pipecat voice hooks. They were not changed as part of this visual task.
- `npm test -- --maxWorkers=2`: 55 files, **219 tests passed**. Added coverage includes conversation/project draft ownership, attachments surviving remount without duplicate upload, asynchronous owner updates, scroll restoration, selection/reference restoration, preference panes with unsaved changes, focus preservation, separate voice exit/end/pause actions, shared fullscreen drafts, attachment review, independent status priority and an in-flight project-switch race.
- `scripts/check-workspace-refinement.cjs`: **134 after screenshots**, 81 successful checks (including repeated support-panel verification), no browser errors or attempted writes. Real saved Camera_Movements project; all six apps, Create destinations, expanded assistant, shot return, graph selection, project inspector, active/history jobs and status. Sizes: 1600×1100, 1440×900, 1280×720, 1024×900, 412×915; both themes; reduced motion. Semantic text/secondary-text contrast ≥4.5:1 and control-border contrast ≥3:1 against the workspace surface. This is targeted contrast testing, not a blanket accessibility certification.
- `scripts/check-director-desk.cjs`: populated synthetic assembly, actual Chromium playback, pause, source trims, clip changes, still frames, fullscreen, saved versions, shared Edit chat, phone width and both themes passed. Explicitly checks playhead, zoom, selected clip and cut state across app switches. Fixture writes never reach real projects.
- `scripts/check-mobile.cjs`: **60 phone/theme/view cases passed**, including 320px width and short landscape, touch hit targets, sheet closing, retained draft, edge-to-edge Create and simulated VisualViewport keyboard resizing. Updated the older test to account for the already-existing conversation context strip and to navigate the new Settings categories.
- `scripts/check-fullscreen-voice.cjs`: **8 viewport/theme fixture cases passed**, no real microphone/model/render calls.
- `scripts/check-voice-gallery.cjs`: **6 desktop/phone/landscape/theme cases passed**, with simulated continuous Pipecat speech commands, gallery numbers, selection, native video playback/pause/seek/mute/stop and returning to the session.

Evidence: `data/screenshots/2026-10-21-visual-refinement/index.html`, `comparison.html` (24 matched before/after pairs), and `manifest.json`. The comparison page includes copies of the original reference images for portable offline browsing. `scripts/build-refinement-gallery.cjs` regenerates it.

Actual services were not exercised for speech or rendering. At handoff, the original API health endpoint responds on both localhost and LAN; it reports llama.cpp and Classic transcription unavailable, with ComfyUI, FFmpeg and the selected OpenAI provider available. Availability/configuration is not proof of a successful generation or microphone session.

The normal port-3000 web process and LAN API process were not restarted or reconfigured. A separate local preview runs at **http://127.0.0.1:3001**. The temporary localhost audit API was removed; the original 0.0.0.0:8000 listener remains. No deployment, model downloads, real chat submissions, renders or preference changes were performed by the audits.

Browser geometry tests are not substitutes for a physical Android keyboard, microphone, cloud billing, generation or GPU tests. Validate a normal live session before broad rollout.

## Intentional boundaries

No independent tracks, effects, titles, new graph relationships, docking framework, credential storage, destructive close semantics, provider capability assumptions or static replacement screens. Timeline playback deliberately does not continue off-screen. Browser-session UI state lasts until reload; saved project data and existing timeline recovery retain their established persistence.

Unsubmitted new-record creation forms retain their existing save/reset semantics; this pass preserves existing-record editor drafts and timeline recovery but does not add general form autosave. Fullscreen text uses the chat draft; if files are staged, it requires returning to chat to review/send rather than silently sending text without those files. Small desktop editing windows remain dense and independently scrollable; regions are not newly resizable.
