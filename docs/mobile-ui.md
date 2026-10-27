# Phone interface

Darius uses an Android-inspired mobile web interface below 760px, including
wide landscape touchscreens up to 1000px. Open the existing LAN HTTPS address;
there is no separate APK, login, model configuration or voice backend.

- A compact app bar provides project switching, jobs, settings, console and inspector.
- The hamburger opens the five app destinations without reserving a bottom tab
  bar. Switching destinations retains the same project and unsent chat draft.
- Projects open with one tap; finger scrolling does not reorder desktop folders.
- Talk has readable messages, a collapsible conversation sheet and an inline
  composer. The Android visual viewport keeps it above the keyboard.
- Mobile section title banners are hidden outside Home. Talk's hamburger holds
  conversations and project context. The text composer stays hidden until the
  keyboard button is tapped, collapses after sending or leaving an empty field,
  and preserves drafts when explicitly hidden. Voice controls remain available.
- Other workspaces have no overlaid chat input. “Ask Darius” returns to Talk.
- Project, conversation, job and inspector sheets have touch-sized close actions,
  backdrop dismissal and keyboard focus management.
- Safe-area insets, light/dark themes and reduced motion are respected.

The desktop interface, project sync, render approvals and audio engines are
unchanged. Validate real microphone permission, keyboard behavior and audio
routing on the user's actual phone; headless tests cannot establish those.

## Checks

After building/starting the web app, run:

```powershell
$env:DARIUS_PLAYWRIGHT_MODULE = "C:/path/to/playwright"
$env:DARIUS_UI_URL = "http://127.0.0.1:3000"
node scripts/check-mobile.cjs
```

The audit uses fixture APIs only: no user project writes, microphone requests,
model calls or renders. It checks five phone/landscape sizes in both themes and
all six views, retained drafts, overlay hit targets and simulated keyboard
geometry. Screenshots are saved under ignored `data/mobile-audit/`.
