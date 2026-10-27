# Secure LAN microphones

The existing `http://localhost:3000` address stays available. Remote browsers need a trusted secure context for microphone capture, so use the optional local HTTPS gateway at **https://YOUR-LAN-IP:3443**. This does not enable microphone access automatically: each device must trust the verified public CA certificate and explicitly allow Darius's microphone.

## Host setup (Windows)

Run `scripts/setup-lan-https.ps1 -Address 192.168.50.10` from the checkout. The installer pins official Caddy 2.11.7, verifies its published SHA-512 archive checksum, extracts only the executable into ignored `data/tools`, and records an executable SHA-256 check for later launches. It does not modify system package installations or trust stores.

The gateway binds only the selected assigned private IPv4 address and loopback, on TCP 3443. Its admin API, public certificate issuance, HTTP redirects, and HTTP/3/UDP listener are disabled. Caddy's local CA rotates the leaf certificates automatically. Keys/configuration stay under `data/lan-https`, with Windows ACLs restricted to the current user, SYSTEM, and Administrators. Do not delete this directory casually: replacing the CA requires trusting its replacement on every device.

If the host firewall blocks port 3443, **separate approval/admin access is required** to run `scripts/enable-lan-https-firewall.ps1`. That helper permits only the gateway executable, TCP 3443, the configured local address, and remote `LocalSubnet`; it blocks edge traversal and does not change the Windows network profile. It uses all profiles because some trusted home LANs are currently classified Public. No router forwarding, public DNS, cloud tunnel, certificate trust installation, or broad inbound rule is performed.

After setup, the normal `scripts/start-local.ps1` launcher starts/reuses the gateway. Run `scripts/start-lan-https.ps1` to start it separately. It verifies the executable/config and refuses to replace another service on port 3443 or silently run a changed config. To change the IP or gateway configuration, stop only its verified process (printed at startup), then rerun it. Active HTTPS voice sessions disconnect when that gateway is restarted. Reserve the host address in your router to avoid changing URLs.

## Device onboarding

On the device, open **http://YOUR-LAN-IP:3000/lan-setup.html**. It includes Windows, macOS/Firefox, iPhone/iPad, and Android instructions, the public certificate download, the SHA-256 fingerprint, and the secure link. Verify the fingerprint with the host's startup output or `Get-FileHash apps/web/public/darius-lan-ca.cer -Algorithm SHA256` over a trusted channel **before** trusting the CA; downloading a CA over HTTP alone does not establish its authenticity. Alternatively transfer the certificate directly from the host using trusted removable media.

Only `darius-lan-ca.cer` (DER public certificate) and non-secret connection information are published in `apps/web/public`. No CA or leaf private keys are served. Installing any root CA is a trust decision with broad scope; install only your own verified Darius CA and remove it from device trust settings if you stop using this installation. Never disable browser certificate verification as a client setup shortcut.

After trusting it, open the HTTPS link. There must be no certificate warning. Start fullscreen voice with Pipecat, then allow microphone access in the browser. HTTPS is a different site origin from HTTP: choose your project/voice settings again if needed; server chats/assets are unchanged. Microphone permissions and preferences are per device/browser. Guest Wi-Fi/AP client isolation can prevent LAN connections even after firewall configuration.

## Routing and safety

HTTPS voice uses same-origin `/voice/pipecat/*` and `/voice/classic/*` proxies, including WSS. Plain HTTP localhost retains the existing direct ports. The gateway preserves the browser Origin and checks exact permitted HTTPS origins before forwarding; voice services also check their own allowlist from the validated local settings. Foreign and `null` origins are rejected. No wildcard CORS, browser insecure-origin flags, or disabled TLS verification is enabled in the app.

The web/API/model/workflow routes, render approvals and keys remain unchanged. This is intended for trusted LAN devices, not public hosting; Darius's existing LAN access is not a multi-user authentication system. Existing raw HTTP ports remain unchanged for compatibility.

## Verification

Run `.venv-pipecat/Scripts/python.exe scripts/check-lan-https.py` for CA-verified TLS, health/proxy routes, origin rejection, public certificate digest and live WSS handshakes without a microphone, model request or render.

The synthetic browser loop supports `DARIUS_UI_URL=https://YOUR-LAN-IP:3443 node scripts/check-pipecat-browser.cjs`. Its isolated test context ignores self-issued certificate errors; production browsers do not. The separate TLS check validates the real CA and hostname. Actual device trust, browser permission prompts, microphone hardware, and router isolation need testing on the remote device itself.

References: [browser microphone requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [Caddy internal TLS](https://caddyserver.com/docs/caddyfile/directives/tls), [Caddy WebSocket proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [Apple certificate trust](https://support.apple.com/en-us/102390), [Android certificate installation](https://support.google.com/pixelphone/answer/2844832?hl=en).
