/** HTTPS uses the LAN gateway; existing HTTP localhost connections stay direct. */
export function voiceServiceUrl(engine: "pipecat" | "classic", location?: Pick<Location, "protocol" | "hostname" | "origin">): string {
  const current = location ?? (typeof window === "undefined" ? undefined : window.location);
  const port = engine === "pipecat" ? 8003 : 8002;
  if (current?.protocol === "https:") return `${current.origin}/voice/${engine}`;
  const host = !current || ["localhost", "127.0.0.1"].includes(current.hostname) ? "127.0.0.1" : current.hostname;
  return `http://${host}:${port}`;
}

export function microphoneProblem(): string | null {
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    return `Microphone access requires secure LAN access. Open https://${window.location.hostname}:3443 after trusting the Darius certificate. Instructions: ${window.location.origin}/lan-setup.html`;
  }
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return "Microphone access is unavailable. Use a supported browser over HTTPS or localhost and allow microphone access.";
  }
  return null;
}
