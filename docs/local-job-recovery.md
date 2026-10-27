# Abandoned local generation recovery

The API checks local ComfyUI generation receipts every 30 seconds, starting
30 seconds after startup. It does not start a worker or submit any render.

A receipt is eligible only when its heartbeat is more than five minutes old
(falling back to its start/creation time when no heartbeat exists), its state
is `running` or `cancelling`, and ComfyUI explicitly reports **both** its running
and pending queues empty. Unavailable, busy, redirected, oversized, or malformed
queue responses leave the receipt unchanged. The queue probe is loopback-only,
read-only, and has a two-second timeout.

- An abandoned cancellation becomes `cancelled`.
- An abandoned running generation becomes `failed` with `WorkerLost`. Its run
  details ask the user to inspect ComfyUI history and output files before an
  explicit retry. It is never automatically requeued.
- Related action plans and chat task metadata are updated transactionally, and
  a `job.recovered` project event and diagnostic receipt are emitted.

Recovery compares the observed status, heartbeat, start time, attempt count,
and cancellation flag at write time. A worker that refreshes its heartbeat,
finishes, or receives a cancellation during the queue check wins the race.
Workers continue heartbeating while cancellation is pending, and late provider
results/errors cannot overwrite a recovered terminal receipt or ingest outputs.

The persistent worker uses this same conservative path for local generations.
Its existing cloud/timeline restart behavior is unchanged. Job-scoped child
workers still claim only their requested job; recovery never drains the queue,
retries a workflow, interrupts ComfyUI, or deletes output files.

This resolves stale UI state; a missing heartbeat alone cannot establish why a
worker exited. Use the job's worker log and backend diagnostics to investigate
the original execution failure. A busy queue deliberately defers recovery even
when that activity belongs to another job.

Regression coverage: `tests/test_job_recovery.py` and `tests/test_recovery.py`.
