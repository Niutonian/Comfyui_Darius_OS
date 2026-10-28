# Darius static showcase

A separate, backend-free interactive demo for GitHub Pages or Vercel. It does not change or run the installed Darius application.

## Run locally

Requires Node.js 20 or newer. There are no packages to install.

```powershell
npm run dev --prefix apps/showcase
```

Open `http://127.0.0.1:4310`. The development server supports byte-range media playback. Set `PORT` to use a different port.

```powershell
npm run check --prefix apps/showcase
npm run build --prefix apps/showcase
```

The build verifies the media hashes and rejects files outside its public asset allowlist, then copies the static public files into `dist/`, which is ignored by Git. No environment file, credentials, API, database or model runtime is needed.

## GitHub Pages

The public demo lives at **https://niutonian.github.io/Comfyui_Darius_OS/**.

The root `.github/workflows/demo-pages.yml` workflow builds this folder and uploads **only `apps/showcase/dist`**. It runs on changes to the showcase or its deployment workflow on `main`, or by manual dispatch. Repository **Settings → Pages → Build and deployment → Source** must be **GitHub Actions**. The workflow uses the built-in GitHub token; no API keys or deployment secrets are needed.

All interactive asset URLs are relative, and the security policy is included in HTML so it also applies on Pages. Vercel's response-header configuration adds its host-specific headers. To preview the Pages subpath locally:

```powershell
$env:PORT = '4311'
$env:SHOWCASE_BASE_PATH = '/Comfyui_Darius_OS'
npm run dev --prefix apps/showcase
```

Open `http://127.0.0.1:4311/Comfyui_Darius_OS/`.

## Vercel (optional)

Create a Vercel project from the reviewed repository and choose **apps/showcase** as its Root Directory, with **Other** as its Framework Preset. The included `vercel.json` selects `npm run build` and `dist` output. These are standard [Vercel build settings](https://vercel.com/docs/builds/configure-a-build). No environment variables are needed.

Only this folder is needed for the site. Vercel hosting is optional; the GitHub Pages deployment remains independent.

## What visitors can do

- Browse fictional projects or create browser-local projects.
- Move, zoom, pan, duplicate and remove Canvas boards; edit their prompts. Touch devices support pinch-to-zoom and a board picker.
- Add MOSS/FIBO composition boards or image/video boards; use focused editors, drag/resize regions, change artboard ratios and explore FIBO's Dev/Turbo preset controls.
- Replay clearly labelled prepared examples and inspect local demo jobs/history.
- View the project's original images, video clips, opening film and product demo.
- Try guided, prepared chat replies; save ideas and apply reviewed prompts to a board.
- Open fullscreen chat or play the recorded voice interaction without microphone access.
- Explore a sample story map and inspect the prepared clips in Edit.
- Change theme, reduce decorative motion and reset the demo workspace.

The site does not synthesize new images, generate AI replies or make API requests. It does not pretend that changed prompts or model settings produced the prepared media. Video duration and resolution controls illustrate the full application's interface; example media stays unchanged.

Browser edits use the dedicated `darius-showcase-v1` storage key. They are separate from the actual application's storage. Reset only affects this showcase. No analytics, remote fonts, microphone capture or cloud model connection is included.

## Media and provenance

`public/media/manifest.json` lists the ten explicitly selected assets and their hashes. All scenes belong to the fictional I AM ALIVE demo project. Images/video came from the owner's approved Darius project; composited screen graphics and the narrated film are labelled. The thumbnail was created with imagegen from the approved scene. The orb is the existing Darius mark. The voice example uses the original prerecorded speech input and actual captured Pipecat reply.

No personal project exports, console logs, API responses, machine paths, databases, certificates, model files or credentials belong in the public folder. Keep future additions explicit and reviewed.

Original site code uses the repository's 0BSD license. See the root ATTRIBUTIONS.md and THIRD_PARTY_NOTICES.md for upstream application/workflow/model components.

## Review completed

The 2026-10-28 local review used Chromium at desktop, phone, tablet and landscape sizes (320–1600px wide). It covered board drag/zoom/pinch, edited-state persistence, prepared preview completion, idea saving, reviewed prompt handoff, fullscreen chat, recorded voice playback, video playback/seeking, themes, reset, and HTML escaping. The refinement review also covered the Pages subpath, board search, focused editors, independent duplicates, composition region drag/resize, artboard ratios, FIBO presets and chat context selection. Browser checks found no runtime errors, failed responses, external requests or backend calls under the deployment security policy. Native Safari and Android browser testing remains useful before launch.
