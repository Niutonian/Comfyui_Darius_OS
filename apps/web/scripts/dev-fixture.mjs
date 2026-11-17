// Run the web app against the fixture API: no backend, ComfyUI or models needed.
//   npm run dev:fixture            -> http://127.0.0.1:3000
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { startFixtureApi } from "./fixture-api.mjs";

const apiPort = Number(process.env.DARIUS_FIXTURE_PORT || 8765);
await startFixtureApi(apiPort);
console.log(`Fixture API on http://127.0.0.1:${apiPort}. Open http://127.0.0.1:3000/?app=create&project=p1`);
const next = createRequire(import.meta.url).resolve("next/dist/bin/next");
const child = spawn(process.execPath, [next, "dev", "--hostname", "127.0.0.1", "--port", "3000"], { stdio: "inherit", env: { ...process.env, DARIUS_API_URL: `http://127.0.0.1:${apiPort}` } });
child.on("exit", code => process.exit(code ?? 0));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
