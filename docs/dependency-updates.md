# Private preview dependency updates — 2026-10-24

Release preparation checks both the runtime and test dependency graphs. It updates lockfiles without installing into the running application's environments. New versions are installed and tested in the isolated preview.

| Component | Previous | Prepared version |
| --- | --- | --- |
| Next.js / matching ESLint configuration | 16.3.4 | 16.4.3 |
| Sharp | 0.35.4 | 0.35.5 |
| Source Map JS | 1.2.1 | 1.2.2 |
| Vitest | 5.0.0 | 5.0.5 |
| FastAPI | 0.116.1 | 0.162.0 |
| Starlette | 0.47.3 | 1.9.0 |
| Python Multipart | 0.0.20 | 0.0.32 |
| Certifi | 2026.7.22 | 2026.10.23 |
| urllib3 | 2.7.0 | 2.8.0 |

Compatible transitive npm updates are also recorded in `package-lock.json`. Audits use `npm audit` for the complete npm dependency graph and `pip-audit` for the exact Python runtime graph exported from `uv.lock`.

Relevant upstream notices include the [Next.js image-processing advisory](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw), [Sharp advisory](https://github.com/lovell/sharp/security/advisories/GHSA-wq5f-xc86-pv6w) and [Starlette advisories](https://github.com/Kludex/starlette/security/advisories). These reports describe affected conditions; an advisory in a dependency does not establish that this application's running configuration was exploited.

Audit results are a dated check against known advisories, not a security guarantee. Rerun them before publishing. Optional separately installed GPU/voice tools and model files are outside this source preview's dependency locks.
