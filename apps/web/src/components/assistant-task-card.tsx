type Activity = { operation: string; state: string };

const labels: Record<string, string> = {
  planning_reply: "Working out the next step",
  discover_workflows: "Finding a suitable workflow",
  inspect_workflow: "Checking workflow inputs",
  list_assets: "Finding project references",
  view_assets: "Inspecting reference images",
  prepare_workflow: "Preparing the generation",
  prepare_graph: "Preparing the generation",
  validate_graph: "Validating the workflow",
  queue_local_render: "Submitting the render",
  job_status: "Checking render progress",
  verifying_result: "Checking the result",
  register_workflow: "Checking the registered base recipe",
  compile_workflow: "Filling the recipe’s declared inputs",
  workflow_retry: "Retrying a temporary preparation failure",
  workflow_blocked: "Generation needs attention",
  task_blocked: "Generation needs attention",
  workflow_queued: "Render jobs confirmed",
  workflow_awaiting_approval: "Validated draft ready for review",
};

export function AssistantTaskCard({ history, elapsed, slow, saved }: { history: unknown; elapsed: number; slow: boolean; saved: boolean }) {
  const steps: Activity[] = Array.isArray(history) ? history.filter((item): item is Activity => Boolean(item && typeof item.operation === "string" && typeof item.state === "string")) : [];
  const latest = steps.at(-1);
  const title = latest ? labels[latest.operation] ?? latest.operation.replaceAll("_", " ") : "Darius is thinking";
  return <div className="assistant-request-progress assistant-task-card">
    <div role="status"><strong>{title}{latest?.state === "failed" ? " · step failed" : latest?.state === "complete" ? " · done" : ""}</strong>
      <p>{!saved ? "Got it — saving your message…" : slow ? "Your request is saved. I’m continuing through the available steps." : "Got it — I’m working on your request."}</p></div>
    <small>Existing generation permissions still apply. Queued renders continue in Background jobs.</small>
    {steps.length > 0 ? <details><summary>Task activity · {steps.filter((step) => step.state === "complete").length} completed steps</summary><ol>{steps.map((step, index) => <li key={index}>{labels[step.operation] ?? step.operation.replaceAll("_", " ")} · {step.state === "complete" ? "completed" : step.state}</li>)}</ol></details> : null}
    <small aria-live="off">{elapsed}s elapsed</small>
  </div>;
}
