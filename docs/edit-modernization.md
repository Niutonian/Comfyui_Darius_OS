# Darius Edit: research and concepts

Research checked 2026-10-18 against the projects' own repositories/docs. This is a proposal, not an installed editor replacement. No external editor dependency was added.

## Recommendation

Keep Darius's project/asset/version model and create a focused, voice-capable web editor. Prototype a browser preview adapter with WebAV, with native-media/proxy fallback and server-side FFmpeg rendering. Use OpenCut as a design reference, not an immediate wholesale dependency. Treat Kdenlive as the desktop finishing reference/optional export target rather than trying to embed a Qt application in Next.js.

This recommendation is an engineering judgment based on Darius's existing Next/React + FastAPI architecture, LAN clients, working voice mode and the need to leave VRAM available for ComfyUI. Browser video decode may still use GPU resources: low-resolution proxies and bounded concurrent decoders are important; zero GPU usage should not be promised.

## Repository shortlist

| Project | Verified facts | Fit for Darius |
| --- | --- | --- |
| [Kdenlive](https://github.com/KDE/kdenlive) | C++/Qt/KDE application, MLT core, GPL-3.0 repository; development is on KDE Invent. | My standalone-editor pick for this project: mature editing reference and possible desktop finishing target, not an embeddable React component. |
| [Shotcut](https://github.com/mltframework/shotcut) | Qt/MLT/FFmpeg desktop application, GPLv3. [Feature list](https://shotcut.org/features/) documents proxy editing, filmstrip/waveform timelines, undo, autosave, markers and scrubbing. | Strong reliability/interaction reference; also not a drop-in browser editor. |
| [OpenCut](https://github.com/OpenCut-app/OpenCut) | MIT. Main README explicitly describes an ongoing Rust-core rewrite; editor API, plugins, MCP and headless mode are announced plans, not capabilities to assume ready. [Classic](https://github.com/OpenCut-app/opencut-classic) is Next-based but archived and unmaintained. | Closest product/design inspiration. Do not base Darius's reliable production path on an unfinished rewrite or silently fork archived infrastructure. |
| [WebAV](https://github.com/WebAV-Tech/WebAV) | [MIT](https://github.com/WebAV-Tech/WebAV/blob/main/LICENSE) SDK built on WebCodecs; core clip/compositor/canvas modules. README targets Chrome/Edge/Electron and distinguishes separate Pro features. | Best small proof-of-concept candidate from this shortlist for browser media processing. It is not a finished editor UI. Test codec/browser/device support and preview/export parity before adopting. |
| [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) | [Apache-2.0](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/LICENSE.txt), timeline interchange API/format, not a renderer or media container. | Keep and validate the existing interchange path; package media references/manifest for real portability. Test each external editor/adapter and supported effect subset rather than promising universal round-trip fidelity. |

[Olive](https://github.com/olive-editor/olive) was also reviewed; its own README warns that it is highly unstable alpha software, so it is not my reliability-first foundation recommendation.

Licenses above identify upstream repositories, not a complete dependency/distribution audit. Before copying or bundling code, pin a version and review its actual license files, dependencies and attribution requirements. Nothing was copied or installed in this research phase.

## Existing Edit gaps

The current `edit-view.tsx` already has project assets, version saving, basic trim/reorder/mute/delete, explicit FFmpeg render approval and OTIO export. These are useful foundations to preserve.

However, its playhead advances with a timer independently of the media preview; the preview inspects one selected asset rather than playing the actual edited sequence. The fullscreen control has no action. Clip widths are proportional flex items, not a time-scaled, seekable NLE timeline. Real sequence playback, clear editing feedback and recovery should come before decorative transitions or a large effect library. The sync update already removed destructive version-based remounts and protects unsaved cuts.

## One editor, three complementary experiences

### 1. Director's Desk — recommended starting point

A calm assembly workspace: project shots/takes on the left, a large sequence preview in the center, a collapsible inspector on the right and a filmstrip timeline below. Reuse Darius's sage/dark themes and icon system. Show shot names and take thumbnails rather than truncated asset IDs. Drag or tap to place media, compare takes and assemble scenes. The chat/voice drawer operates on an explicit selected clip or range.

```text
Project / sequence       Saved version / sync        Review / Export
+----------------+---------------------------+----------------------+
| Shots / takes  |                           | Selected clip        |
| Project media  |     Sequence preview      | Trim / sound / text  |
| Search / tags  |                           | Collapsible chat     |
+----------------+---------------------------+----------------------+
| Time ruler / filmstrip video / audio waveform / playhead          |
+------------------------------------------------------------------+
```

On narrow laptops, panels become drawers. On a phone, use the review experience below instead of shrinking all four columns.

### 2. Precision Cut — expand only when needed

The same sequence opens into a larger time-scaled timeline: zoom, snapping, split/ripple trim, frame nudges, keyboard shortcuts, audio waveforms, track lock/mute and reliable undo/redo. A shared time model ties preview and exports to real source ranges; frame rates and variable-frame-rate sources need explicit normalization. Add simple fades, captions and audio levels only after a preview/export parity test passes for each feature.

### 3. Pocket Review — phone and fullscreen voice

Full-size sequence playback, a horizontal shot strip and large touch targets. Voice/text commands such as “mark this moment” or “use take two for shot four” resolve to stable shot/clip IDs. Put proposed structural changes in an understandable diff with Apply/Undo. Markers and saved versions synchronize to desktop; merely playing a review does not remotely move another device's playhead or start its microphone. Render approval stays explicit.

## Technical direction

- One typed, validated edit-operation model used by mouse, keyboard and voice. Models propose bounded operations; they do not invent arbitrary renderer code. Check project ownership, clip IDs, ranges, duration and available sources before applying.
- Separate project timeline document, UI selection and playback state. Preserve immutable committed versions; add debounced draft checkpoints with a base version and conflict detection. Concurrent-device edits must branch or ask, never silently overwrite.
- Use low-resolution media proxies, cached filmstrips/waveforms and a bounded preview decode budget. Keep originals for export. Native server FFmpeg handles dependable final renders; hardware encoding can be an explicit optional performance choice, not a default VRAM competitor with ComfyUI.
- Wrap any browser SDK behind a preview interface. Feature-detect codecs/HTTPS/WebCodecs and provide proxy/native playback on unsupported devices. In particular, do not assume a Chrome-targeted SDK works identically on iPhone/Safari.
- Maintain a supported-feature matrix so preview and render cannot disagree silently. Unknown effects block export or warn explicitly. Export resolves original assets by project-scoped IDs, not transient browser object URLs.
- Continue using the project event channel for committed versions and media. Add optimistic version checks before collaborative autosave; the current sync layer deliberately does not claim full collaborative merging.

## Suggested implementation sequence

1. Playback spike: two videos + a still + audio, real sequence seeking, source trims, pause/resume, fullscreen and mobile fallback. Compare a short FFmpeg output with the preview. No model required.
2. Director's Desk layout, named shots/takes, filmstrip/waveform caches, correct scaled timeline and drag/touch insertion.
3. Undo/redo, draft recovery and concurrent-version safety before enabling automatic draft saves.
4. Deterministic voice edit commands with visible targets, proposed changes and Apply/Undo; then phone review markers and take selection.
5. A small tested set of fades/captions/audio controls, export presets, render progress/cancel, portable media manifest and verified OTIO exchange.

Definition of a useful first release: reopen a project on another device, play the same saved cut, make/revert a trim, recover an interrupted draft, and render exactly the sequence shown in preview without needing an AI model for basic editing.
