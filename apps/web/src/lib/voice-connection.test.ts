import { afterEach, expect, it, vi } from "vitest";
import { microphoneProblem, voiceServiceUrl } from "./voice-connection";

afterEach(() => vi.unstubAllGlobals());
it("keeps existing localhost HTTP speech endpoints", () => {
  expect(voiceServiceUrl("pipecat", { protocol: "http:", hostname: "localhost", origin: "http://localhost:3000" })).toBe("http://127.0.0.1:8003");
  expect(voiceServiceUrl("classic", { protocol: "http:", hostname: "127.0.0.1", origin: "http://127.0.0.1:3000" })).toBe("http://127.0.0.1:8002");
});
it("uses HTTPS and WSS on the same LAN origin, never raw voice ports", () => {
  const location = { protocol: "https:", hostname: "192.168.50.10", origin: "https://192.168.50.10:3443" };
  expect(voiceServiceUrl("pipecat", location)).toBe(location.origin + "/voice/pipecat");
  expect(voiceServiceUrl("pipecat", location).replace(/^http/, "ws")).toBe("wss://192.168.50.10:3443/voice/pipecat");
  expect(voiceServiceUrl("classic", location)).toBe(location.origin + "/voice/classic");
});
it("also routes HTTPS localhost through the secure gateway", () => {
  expect(voiceServiceUrl("pipecat", { protocol: "https:", hostname: "localhost", origin: "https://localhost:3443" })).toBe("https://localhost:3443/voice/pipecat");
});
it("gives insecure LAN pages actionable setup guidance", () => {
  vi.stubGlobal("isSecureContext", false);
  expect(microphoneProblem()).toContain("3443");
  expect(microphoneProblem()).toContain("lan-setup.html");
});
