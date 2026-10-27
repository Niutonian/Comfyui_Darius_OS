# H3 keyframe compatibility repair — 2026-09-14

Failed jobs: `3c78c170`, `633ca3e1`, `586a15c5`. All used workflow `assistant-f4f8442717700fd082ba4cff4c30a1d3`, with anchors at 0%, 50%, 100% (frames 0, 121, 242).

The H3-Multishot extension rejected interior anchors because its string-based detection did not recognize current ComfyUI native support (`cursor + FRAME_RESCALE * kf["resolved_frame_index"]`). This was an extension compatibility guard failure, before sampling.

Updated the installed `ComfyUI-H3-Multishot/h3_interior_patch.py` to recognize that implementation only after testing native PackedLayout positions at the first, middle, and last frames with tiny CPU tensors. The native constructor is unchanged. Self-test passed using ComfyUI's embedded Python. Backup: `data/h3_interior_patch.before-fix.py`; installed candidate: `data/h3_interior_patch.fixed.py`.

ComfyUI was restarted with its original `--use-sage-attention` option after confirming both running and pending queues were empty. Failed jobs were not resubmitted or rewritten. Full rendering acceptance is still pending. Future extension updates may replace this local compatibility fix.

Darius now extracts the structured MCP error message before falling back to raw process output, avoiding tensor dumps in future job errors. Regression test: `tests/test_comfy_error_reporting.py`.
