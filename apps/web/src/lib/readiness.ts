import type { Health } from "./types";
import type { BoardSetup, ComfyConnection } from "./board-setup";
export type ReadinessItem = { name: string; state: string; hint: string; action?: "connection" | "dependencies" | "model" | "voice" };
export function readinessItems(health?: Health | null, setup?: BoardSetup | null, connection?: ComfyConnection | null): ReadinessItem[] {
 const parts = health?.components ?? {};
 const core = parts.api?.ready && parts.database?.ready;
 const rows: ReadinessItem[] = [
  { name: "Darius", state: !health ? "Checking" : core ? "Ready" : "Needs attention", hint: !health ? "Waiting for the API health check." : core ? "API and project database are available." : "Check the server in the Darius manager." },
  { name: "ComfyUI", state: !health ? "Checking" : connection && !connection.configured ? "Not configured" : parts.comfyui?.ready ? "Ready" : "Not running", hint: connection && !connection.configured ? "Detect or save the installation folder below." : parts.comfyui?.ready ? "The configured server responds." : "Start your ComfyUI installation, then check again.", action: "connection" },
 ];
 if (setup) {
  const blocked = (setup.blocked ?? []).join(" ") + " " + (setup.message ?? "");
  const access = /HF_TOKEN|CIVITAI_API_KEY|gated|unauthorized|authentication|401|403/i.test(blocked);
  const conflict = /revision|conflict|incompatible|built-in|source changed/i.test(blocked);
  const state = setup.state === "ready" ? "Ready" : setup.state === "needs_setup" ? "Not installed" : access ? "Access required" : conflict ? "Incompatible" : setup.state === "preparing" ? "Installing" : setup.state === "checking" ? "Checking" : "Needs attention";
  rows.push({ name: "Selected board", state, hint: setup.state === "ready" ? "This board's dependency check passed. Generate remains an explicit action." : access ? "Add your own model token in the server .env and accept the publisher's terms, then restart Darius and check again." : conflict ? "Review the node conflict below. Darius will not replace existing revisions automatically." : "Review the download sizes and blockers below; preparation progress is retained.", action: "dependencies" });
 }
 rows.push({ name: "Chat (optional)", state: !health ? "Not checked" : parts.llm?.ready ? "Configured" : parts.llm?.configured ? "Unavailable" : "Not configured", hint: "Choose a local or cloud model in Settings. Ollama is optional and is not required for board rendering.", action: "model" });
 rows.push({ name: "Voice (optional)", state: "Check in Voice settings", hint: "Use Test microphone, Test speaker and Check service. Voice is not required for rendering.", action: "voice" });
 return rows;
}
