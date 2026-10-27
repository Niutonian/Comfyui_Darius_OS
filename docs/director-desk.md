# Director's Desk — first release

Implemented 2026-10-18. Open **Edit** and reload once after deployment.

## Included

- Searchable project media, named shots/takes, chosen-take badges and visual previews. Previewing does not insert media. Add or drag a take onto the timeline; repeated use of the same asset gets independent clip IDs.
- Large sequence preview with real native-media playback, trimmed-source seeking, play/pause, clip navigation, image timing, fullscreen where the browser supports it and explicit load/codec errors. The project resolution determines the picture frame's aspect ratio. Background tabs pause playback.
- A time-scaled thumbnail timeline with real gaps, visible playhead, seek controls and independent clip selection. Video poster extraction is lazy, queued one decoder at a time and cached in a bounded browser-memory cache; existing managed thumbnail derivatives are preferred.
- Collapsible clip inspector, trim/reorder/mute/delete, immutable saved versions, retained cross-device dirty-cut protection and approved CPU FFmpeg rendering. New timelines start empty rather than adding every generated asset automatically.
- Collapsible Darius project chat/voice drawer using the existing assistant, not a second session. Chat stays in Edit. Its composer sits inside the drawer instead of floating over the timeline. A stable movable portal preserves unsent composer text when switching Talk/Edit; closing the drawer stops listening but does not cancel a running task.
- Responsive layout and existing light/dark theme variables. On narrow screens, panels stack and the timeline scrolls horizontally rather than widening the page.

## Preview/export contract

The editor supports one picture track (video/stills), black gaps, embedded video sound and separate audio tracks with source trims, offsets, mute, volume and fades. CPU FFmpeg output preserves gaps and mixes both embedded and separate sound. Embedded sound stays part of the picture clip: moving, reordering, trimming or splitting cannot independently desynchronize its audio. Silent video is detected rather than treated as a failed audio stream.

Volume is 0–100%, with linear fade-in/out controls in the clip inspector. Preview and render share source-relative envelope semantics. Splitting a clip retains its envelope origin, including a split inside a fade, so the fade does not restart at the cut. Changing a split piece's fade controls intentionally resets that piece's envelope to its own source range. FFmpeg limits summed audio to avoid hard clipping; this is not a professional loudness/mastering mixer. OTIO retains these Darius settings as metadata, not native external-editor audio automation.

Unsupported multiple-picture, dialogue/subtitle or missing-source cases display an explanation and block the normal render action; server preflight also rejects unsupported track layouts. This is not a multi-layer compositor. No new generation/model integrations or external editor dependencies were added.

Save new version commits the current cut. OTIO exports the last saved version, not unsaved changes. Original media is never edited in place. Saving does not start a render; **Approve & render** remains explicit.

### Starting a render from the UI

Render receipts now read the live shared job cache in both Edit implementations, chat/fullscreen voice and Background jobs. Terminal status replaces obsolete queued/worker instructions; failed refreshes are labeled as potentially outdated and can be refreshed explicitly. Completed jobs expose **Open result**, which loads the original on click with an active-project check. Merely opening history never starts/retries a job or automatically opens media. Saved message records are preserved; only receipt-only assistant prose is replaced for display, not user quotes or normal narrative. Multi-shot/local render receipts include each distinct related job.

**Approve & render** now queues the accepted cut and automatically starts a hidden worker scoped to that job. Background jobs opens to show its progress. For an older queued cut, open **Background jobs → Start render**. Retrying a failed/cancelled timeline job also starts only the new retry. No continuously running general worker is enabled, and unrelated generation/cloud jobs remain queued.

Startup checks explicit approval, accepted timeline version, project ownership, supported tracks and source availability. Duplicate requests share a short launch reservation and the worker's atomic claim prevents duplicate execution. If process startup fails, the same approved job stays queued with an actionable message; Start render can retry without creating another cut. A queued worker that never claimed its job can be relaunched after 30 seconds. Existing renders are not started merely by loading or deploying the app.

Render-start verification: ten backend tests include a real isolated one-second child-worker render, two-device duplicate-start protection, approval/project/cancellation guards and scoped retries. Browser verification with `DARIUS_TEST_RENDER_START=1` covers Approve & render and the older-job Start render button while a fixture generation stays queued. No existing user render was executed during deployment.

## Cut safety and precision editing

- Undo/redo covers adds, source trims, mute, reorder, split and both delete modes. Up to 100 edit steps are retained while the editor is mounted. Playback, seeking, filters and zoom are not edit steps. Ctrl/Command-Z, Shift-Z and Ctrl/Command-Y work when focus is on the desk; chat and numeric/text inputs keep their native text undo.
- Dirty cuts are checkpointed in browser local storage, scoped to project, timeline and a unique document/tab owner. Leaving Edit and returning in the same document restores its cut automatically; after a reload, recovery is offered explicitly. Other tabs' checkpoints appear as recovery choices and never overwrite the open cut. Malformed or foreign-project records are ignored; unavailable/full storage produces an explicit warning. Browser unload also warns while a cut is unsaved.
- Recovery stores the current cut and its original saved-version baseline, not the undo stack. Restoring an older cut preserves the existing newer-version warning and allows saving a separate immutable version. A restored checkpoint is retired after saving that exact cut, unless its original tab has since updated it. Discarding recovery asks for confirmation.
- Browser recovery is **not cross-device autosave**: it belongs to that browser profile and site address, and clearing site data removes it. Use **Save new version** for durable server storage and handoff to laptop/phone. Saving and recovery never submit a render or call a model.
- Split at a frame-snapped playhead, previous/next-frame nudges at project FPS, playhead source trims and timeline zoom are available. Existing numeric source trims use frame-sized input increments. Splits retain source offsets and clip metadata; endpoints and sub-frame slivers are disabled.
- **Ripple delete** closes just the removed interval on the selected track. **Delete leaving gap** preserves all remaining positions. Trim changes shift later clips by only the duration delta, preserving leading/interior gaps. Other tracks intentionally stay in place; this is not linked all-track ripple editing. Reorder remains an explicit contiguous reassembly.

Verification: 18 targeted timeline/history/editor tests passed, including recovery/remount, original-base remote conflicts, storage quota failure, native input undo and exact split/ripple save payloads. Build/typecheck and changed-module lint passed. `DARIUS_TEST_EDIT_SAFETY=1` extends the Chromium fixture check with split, undo/redo, Talk/Edit retention, reload recovery, commit cleanup and independent-tab checkpoints. Full frontend regression: 151 passed; the same previously documented unrelated model-settings argument-count test still fails.

## Not included yet

Detached/grouped A/V tracks, multi-track drag transfers, automatic collaborative merging, server-backed live drafts and direct AI/voice edit operations are later steps. The drawer currently supports the existing project conversation/voice capabilities, not commands that automatically change timeline clips. Save a version before changing devices; local recovery supplements rather than replaces server saves.

## Timeline dragging, sound and keyboard controls

- Drag the clip body in **Move** mode to change its position on the same track while preserving gaps. Overlaps are rejected with a visible explanation; no clips are overwritten. **Reorder** mode instead inserts into a contiguous assembly and explicitly closes gaps on that track.
- Drag either edge for a non-ripple source trim. Neighbors stay fixed; bounds prevent source overrun, overlap and shorter-than-frame remnants. Snap aligns to clip boundaries/playhead within eight screen pixels; Shift temporarily disables it and N toggles it. Touch pointers use the same gesture path. Esc, pointer cancellation/capture loss or a changed cut cancels safely. Only the final drop is committed as one undo step; drag previews are not saved or rendered.
- Clip DOM order stays stable until drop to preserve pointer capture during reorder previews. Horizontal edge scrolling retains the drag's timeline coordinate mapping. Selecting the timeline gives it keyboard focus; text/numeric fields, content-editable elements, media library and chat keep their native keys.
- **?** opens the in-app shortcut guide. **Space/K** play/pause; **←/→** step frames (Shift: ten); **S** splits; **Q/W** ripple-trim start/end to playhead; **[/]** edge-trim the start by one frame (Shift: end); **Alt+←/→** nudges a clip (Shift: ten frames); **Delete** leaves a gap and **Shift+Delete** ripples; **M** mutes; **Home/End** seek boundaries; **Ctrl/Command-S** saves a draft version, never renders; standard undo/redo remains supported. Space on a focused button preserves native activation. Paused media seeks with frame-appropriate accuracy rather than playback's drift tolerance.
- Lazy waveform previews use CPU FFmpeg only, one bounded decoder at a time, with 64 immutable-source memory cache entries. The API requires the exact asset project and a file within managed data. Responses contain at most 512 peaks; extraction is limited to the first 30 source minutes with an explicit partial marker and 12-second decode timeout. The client displays only decoded source regions and applies clip level/fade envelopes to the waveform. Failed/busy waveforms show an unavailable hint; editing/playback remain usable. No GPU, model, cloud or render job is started by waveform display.

Update verification: 25 targeted frontend editor/history/motion/shortcut tests passed; real Chromium checks cover mouse move, overlap rejection, reorder, edge trim, Esc cancellation, native touch trim/cancel, source-offset frame seeking, keyboard split/trim/save, waveforms and video audio gain. Existing draft recovery, independent-tab checkpoints, render-start, chat and mobile/theme checks remain covered. CPU media tests verify actual embedded sound onset after source trimming/moving, fade levels, split continuity, mute, waveform/cache/project/path guards and rejected invalid controls. Full frontend suite: 158 passed; the same previously documented unrelated model-settings argument-count assertion still fails.

The old bench remains available in code as `LegacyEditView` in `edit-view.tsx`; the main Edit entry exports the separate `DirectorDesk` implementation. Existing project records and timeline versions were not migrated or replaced.

## Verification

- Build compilation, TypeScript and lint for new editor/playback/surface modules passed.
- Targeted UI/editor/chat/voice/sync tests: 32 passed.
- Backend suites for render, media, sync, conversation management and asset presentation: 37 passed. A real CPU FFmpeg fixture verifies red video → black gap → blue video → green still, source trims, total duration and delayed audio/silence; another test verifies muted audio omission.
- `scripts/check-director-desk.cjs`: native Chromium play/pause, correct source offsets, clip changes, still duration, fullscreen, named takes, version save, one shared Edit chat/composer, typed-draft retention across Talk/Edit, mobile drawer close and actual light/dark layouts. Fixture-only API and tiny synthetic media; no user project writes or real model/render requests.
- `scripts/check-device-sync.cjs`: independent desktop/phone browsers still receive chat, rename and reconnect updates while retaining an unsent draft.
- Production media endpoint was checked for HTTP 206 byte-range responses, required for reliable video seeking.
- After deployment on the authorized localhost origin, the real Pipecat browser loop passed synthetic microphone → CPU transcription → fixture assistant reply → audio playback → listening, including full-size asset navigation and voice continuation. Voice/model/ComfyUI/gateway services were not restarted.
- Full UI suite after the render-start update: 140 passed, one previously reported unrelated `llm-setting.test.tsx` argument-count assertion still fails (optional third `undefined` argument versus an expected two-argument call). Model settings were not changed.

Screenshots from browser verification: `data/director-desk-check/desktop-dark.png`, `desktop-light.png`, and `phone-dark.png`. Tiny synthetic playback fixtures are retained in the OS temporary directory, separate from real project media.
