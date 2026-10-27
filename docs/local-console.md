# Local diagnostic console

Click the terminal icon beside Settings. Unlock it using the code in
`data/diagnostics/access-code.txt` on the Darius computer. The API creates this
file at startup; the code is not exposed by a public endpoint, put in a URL,
or included in reports. It is remembered only for the current browser session.
Do not share this code. Use **Lock** to remove it from the browser session.

After unlocking, local services and recent failed replies/jobs in the active project are checked
every 15 seconds, with a console badge and dismissible notification. The open
console refreshes every 5 seconds. **Check now**, **Live**, and **Follow logs**
let you inspect or freeze a snapshot. Closing the console does not stop a task.

- Backend: rotating technical request, local context-check and MCP/tool activity.
- ComfyUI: actual terminal output from its optional `/internal/logs` endpoint.
  Installations without that endpoint show an availability notice instead.
- Worker: worker lifecycle/job events and recent project worker log tails.
- Failures: current-project reply/render errors with message/job IDs.

Service checks use bounded loopback metadata calls, not model generation. No
cloud requests, model wakes for generation, workflow execution, cancellation,
or automatic render retries are initiated by the console. Read-only llama.cpp
context checks have a 30-second timeout and one transient-timeout retry. Console
events identify the endpoint, time taken, token count and HTTP error type.
Workflow-result compaction happens before tokenization, and older background
records are removed in batches to avoid repeated expensive checks.

Use **Copy report** or **Download** and paste the report when asking for help.
Project failures are scoped, but service logs are machine-wide. API-key/password
patterns are redacted as a best-effort safeguard; prompts, local paths and other
private content may still appear. Always review a report before sharing it.
The console does not send logs to a model automatically.

If the backend is offline, previously loaded data can still be exported. Recent
technical logs are also stored locally in `data/diagnostics/backend.jsonl`
(bounded rotation); per-job logs live in `data/jobs/<job-id>/worker.log`.
