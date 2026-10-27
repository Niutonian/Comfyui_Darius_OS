# Trusted workflow recipes

Open **Create → Trusted workflows** (also available in Settings). Select the project's registered recipes, assign their task type, choose one default for each task, enable automatic selection, and save.

Supported purposes include image generation, image editing, image upscaling, video generation, image animation, video editing, character sheets, face consistency, and lip sync. Several recipes can share a purpose. A workflow with generation and upscaling already built into its graph can serve as the image-generation default; separate upscaling recipes require an image input.

The **Task type** selector lists every supported task and its assignable recipe count, including tasks with no available recipes. A recipe's **Use for** menu shows selectable routing actions. Local video folder bases can be assigned to generation, animation, or editing rather than being locked to one inferred mode. Choosing a task does not rewrite the recipe's graph or expose recipes owned by other projects.

Recipes are project-specific. Chat and voice use the same selection. Explicit selection in chat overrides defaults for that request. Requests with image references use image-editing or image-animation defaults; text-only requests use text-to-image or text-to-video defaults. Upscaling uses an image-upscale recipe.

The backend selects a recipe before calling the planner and sends a compact summary instead of the full registered catalog. Ollama/llama.cpp and the OpenCode deterministic tool path inspect that selected workflow directly, skipping discovery. Existing subject binding, asset ownership, validation, generation approval, and billing checks still apply.

When automatic selection is enabled, tool discovery returns only trusted recipes. Copied graphs may change scalar inputs but retain the inspected template's nodes and connections. A missing, incompatible, or failed recipe does not silently trigger a new graph or workflow substitution. Missing task defaults stop before a model request. Unavailable recipes remain visible for removal.

Preferences live in the project's existing assistant-memory JSON; no database migration is needed. Saving project notes preserves workflow preferences. Disabling trusted-only selection restores compatible defaults-folder routing, not generated-draft discovery.

## Folder bases and refresh

Local base recipes now come directly from `COMFY_WORKFLOW_DEFAULTS_ROOT` (normally `workflows/defaults`). Put a complete ComfyUI JSON workflow there, open **Create → Trusted workflows**, click **Refresh workflows**, choose its compatible action, mark the default, and save. Refresh preserves unsaved choices. Archived folders and incomplete downloads are excluded. Generated `assistant-*` project drafts and the custom-workflow directory are not automatic defaults.

The picker infers basic input/output capabilities from the saved graph; execution still inspects the actual graph, resolves its prompt slots, binds project references, validates it, and enforces local permissions or paid-provider approval. Refresh does not submit a render, make a paid model request, or mark a recipe tested. An unavailable action displays a clear error rather than exploring unrelated templates.

With trusted mappings disabled, Darius chooses a compatible local base from the default folder. Named workflow families constrain that choice; asking for Krea never silently switches to Qwen. With mappings enabled, the saved project defaults take precedence. Explicit user choices remain possible but are not promoted into base recipes.

Single-output generation uses a shared deterministic inspect → prepare → queue/review sequence across cloud and local planners, after the selected model resolves the visual brief. Temporary conversion failures expire (10 seconds for connection/timeout failures, five minutes for other failures); explicit refresh clears failure exclusions while preserving successful-render history.

Voice follow-ups such as “ok, generate it” inherit the latest unfinished user request, but cannot replay queued or cancelled work. “Okay, then create the first two scenes and then animate them” counts two image outputs in the first phase. Invalid model shot counts get one bounded correction attempt.

Spoken video references such as “generate a video of this angel,” “animate her,” and “use the last image” resolve a single image from the current conversation's recent render or user attachment. Explicit attachments/pinned references take precedence. Missing, unfinished, ambiguous, or foreign-project results ask for an attachment; routing never searches other conversations or reuses workflow sample images. Complete spoken workflow names (including “Mini Max”) count as explicit choices; a family-only request still uses the saved defaults/ranking. Fresh text-only video requests do not silently inherit an old image. Image-to-video bases still need a source image; a true text-only request needs a text-to-video base.

Comfy CLI subprocess input/output is UTF-8, including Windows. This prevents non-ASCII video workflow content from disappearing into the CLI renderer's encoding-error handler and returning an empty successful result. Registration/conversion previews do not submit renders or call an LLM.

A selected recipe containing custom/unverified nodes is still prepared and validated, but returns **Review generation** for explicit approval instead of attempting automatic queueing and failing. Trusting a recipe for an action does not grant blanket execution permission to its custom or external nodes. Verified local image/video recipes retain automatic rendering when the project permits it.

Local video folder recipes can be assigned to **Generate video**, **Animate image**, or **Edit video** even when discovery infers a single image-to-video mode. The inferred mode and possible input hints are advisory; the selected action is a user-owned routing label, not certification that every mode works without references. Actual graph inspection, project asset bindings, validation, and approvals remain required. Cloud operation capabilities remain fixed. The per-recipe menu shows selectable actions rather than a long disabled list.

## Global defaults and project overrides

Open **Settings → Global workflow defaults** to choose action mappings without selecting a project. Enable **Use global workflow defaults**, choose base recipes and defaults, and save. These defaults apply to existing and future projects on this Darius server.

Priority is **explicit workflow choice → enabled project action mapping → enabled global action mapping**. Project overrides apply per action, not to the entire global configuration: a project can override image generation while inheriting global video generation. Turn off **Use project workflow overrides** to inherit global mappings without deleting the saved project choices. Project panels list inherited global recipes.

Enabled scopes retain trusted-only behavior: actions missing from both mappings ask for a recipe, rather than silently selecting an unrelated workflow. Missing selected recipes never fall through to another scope. If both scopes are disabled, compatible defaults-folder routing applies. Global selections cannot contain project-generated drafts or project asset references. Sharing a base recipe never shares project media, prompts, render permissions, or paid-provider approvals.

Global preferences use the `global_workflow_preferences` table, introduced by migration `a05f6b4d273c`. Project mappings remain in project assistant memory and are not changed when saving global defaults. API: `GET/PUT /api/v1/settings/workflow-defaults`; project preference responses also include `global_defaults`.
