# Refreshing AI model lists

In Settings → AI model, select OpenAI or OpenCode Free and click **Refresh models** / **Refresh free models**. Refreshing updates only the catalog. Selecting a different model still requires **Save AI model**.

OpenAI discovery calls the official `GET https://api.openai.com/v1/models` endpoint with the existing server-side API key. The picker filters text-model candidates and sorts by creation time, newest first. The model-list endpoint does not certify every model's tool or structured-output compatibility. Image, audio, transcription, and other specialized models are excluded from the Talk selector. A 401 refresh error means the server key needs updating; no key is sent to the browser.

OpenCode discovery uses `opencode models opencode --verbose`; explicit refresh adds `--refresh` so both OpenCode's cache and Darius's cache update. Free models are identified by zero input/output/cache prices in the CLI metadata, including entries whose names do not end in `-free`. Older CLI output without cost metadata uses the `-free` suffix. Available vision and tool labels come from the same catalog metadata.

Successful catalogs are cached for five minutes. Normal settings loading can retain a prior catalog or configured fallback if a provider is unreachable. Explicit refresh reports failure rather than presenting fallback data as newly fetched. A model removed from the latest list stays visible as the current selection, marked unavailable for saving; refreshing never silently switches models.

No model response or media generation is requested during catalog refresh.

## OpenAI thinking levels

Select **Settings → AI model → OpenAI → Thinking level**, then save. The server publishes only reasoning levels verified in the official documentation for that exact model family and dated snapshots. Unknown and non-reasoning models retain **Model default**. Pro variants have their own restricted levels rather than inheriting the base model's options.

**Model default** omits the parameter; explicit levels set Responses `reasoning.effort` for ordinary chat, visual briefing, and tool-planning requests. Higher levels can increase token use and latency. The preference survives restarting Darius and switching providers. Other providers, media-generation models, and GPT-Live retain their existing configuration. When switching to an incompatible model the selector resets to default; explicit invalid API settings return 422 before a provider request.

The additive Alembic migration `f94e5a3c162b` stores this preference. An optional `OPENAI_REASONING_EFFORT` environment setting applies before a saved model preference exists.

Reasoning reference: https://developers.openai.com/api/docs/guides/reasoning#reasoning-effort

Sources: https://developers.openai.com/api/reference/resources/models/methods/list and https://opencode.ai/docs/cli/#models
