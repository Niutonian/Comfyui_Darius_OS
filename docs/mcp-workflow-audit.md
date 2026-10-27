# MCP workflow audit

Audited 2026-09-11 from the configured ComfyUI `user/default/workflows` directory. Discovery was limited to JSON filenames beginning with `MCP` (case-insensitive). Each workflow was converted with Comfy MCP `run --print-prompt`; **nothing was queued or generated**.

| Workflow file | Inferred capability | Converted nodes | Registration status |
|---|---|---:|---|
| `MCP_image_krea2_turbo_t2i.json` | Text to image (Krea 2 Turbo) | 22 | Registered as `krea2-turbo-text-to-image` |
| `mcp_ideogram4_t2i.json` | Text to image (Ideogram 4) | 39 | Audited; semantic wrapper mapping still needs verification |
| `mcp_flux2_klein_9b_img2img.json` | Image to image (FLUX.2 Klein 9B) | 21 | Audited; not yet registered |
| `mcp_H3_CharSheetMaker_6_Panel.json` | Character sheet from references | 36 | Audited; not yet registered |
| `mcp_Minimax H3 I2V (with Larryvrh Turbo Nodes).json` | Image to video | 36 | Audited; not yet registered |
| `mcp_Minimax_H3_Keyframes.json` | Multi-keyframe image to video | 19 | Audited; not yet registered |
| `MCP_Minimax_H3_Seamless_Chain_CORE.json` | Multi-shot text to video | 11 | Registered as `minimax-h3-seamless-core` |
| `mcp_ref_image to video_minimax_h3_r2v.json` | Reference images to video | 26 | Audited; not yet registered |
| `mcp_video_minimax_h3_t2v.json` | Text to video | 24 | Audited; not yet registered |
| `mcp_video_minimax_h3_t2v_llm_slow.json` | LLM-assisted text to video | 28 | Audited; not yet registered |

## Verified Krea semantic mapping

- `prompt` → `30/19.value` (`Text String (User Prompt)`)
- `refine_prompt` → `30/24.value` (`Boolean (Refine Prompt?)`)
- `aspect_ratio` → `49.aspect_ratio` (`Resolution Selector`)
- generated filename prefix → `29.filename_prefix` (`Save Image`)

## Other useful mappings discovered

- FLUX.2 Klein image-to-image: source image `76.image`, positive prompt `107.text`, seed `104.noise_seed`, steps `100.steps`, output `132.filename_prefix`.
- H3 keyframes: prompt `8.prompt`, keyframes `5.image`, `6.image`, `7.image`, output `18.filename_prefix`.
- H3 reference-to-video: prompt `138.value`, references `137.image` and `139.image`, aspect ratio `115.aspect_ratio`, output `92.filename_prefix`.
- H3 Seamless Chain: script `8.script`, controls under node `2`, aspect ratio `15.aspect_ratio`, video output `11.filename_prefix`.

Only mappings with a clear, minimal input/output contract are registered automatically. The remaining workflows stay untouched until their required reference semantics and expected outputs are validated, preventing Darius from presenting an unsafe or misleading action.
