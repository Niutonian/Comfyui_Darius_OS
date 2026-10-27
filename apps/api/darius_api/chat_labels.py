"""Human-facing labels; storage paths and provenance IDs remain unchanged."""
import re

UUID = r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"


def readable_name(value, fallback="Generation"):
    text = str(value or "")[:1000]
    text = re.sub(UUID, "", text, flags=re.I)
    text = re.sub(r"\b(?:task|assistant|job|asset)-[a-f0-9]{16,64}\b", "", text, flags=re.I)
    text = re.sub(r"[-_][a-f0-9]{8}(?=[-_]\d{1,3}(?:\.[a-z0-9]+)?$)", "", text, flags=re.I)
    text = re.sub(r"\.(?:png|jpe?g|webp|gif|mp4|webm|mov|wav|mp3)$", "", text, flags=re.I)
    text = text.replace("_", " ")
    text = re.sub(r"^(?:(?:please|could you|can you|would you|generate|create|render|make|a|an|image of|video of)\s+)+", "", text, flags=re.I)
    text = " ".join(text.split()).strip(" -·,.")
    words = text.split()[:10]
    text = " ".join(words)[:85].rstrip(" ,;:-")
    return text[:1].upper() + text[1:] if text else fallback


def output_label(prompt, kind, index):
    return f"{readable_name(prompt, kind.title())} · {kind.title()} {index}"


def intent_label(context, prompt):
    intent = context.get("resolved_intent") or {}
    scene, shot = intent.get("scene"), intent.get("shot")
    subjects = [item["name"] for item in context.get("characters", []) if item.get("id") in intent.get("subject_ids", [])]
    parts = [*subjects, *([scene.get("title") or f"Scene {scene['number']}"] if scene else []),
             *([f"Shot {shot['number']}"] if shot else [])]
    return readable_name(" — ".join(parts) if parts else prompt)


def job_label(job, generation=None):
    payload = job.input_payload or {}
    return readable_name(payload.get("render_name") or (generation.prompt if generation else None),
                         "Timeline export" if job.job_type == "timeline_render" else "Generation")


def render_receipt(jobs):
    """Only call with database-confirmed jobs, never model-provided IDs."""
    states = {"queued": "queued", "running": "rendering", "completed": "ready", "failed": "failed",
              "cancelled": "cancelled", "cancelling": "cancelling"}
    parts = [f"{item.get('name') or 'Generation'} — {states.get(item['status'], 'status unavailable')}" for item in jobs]
    return "; ".join(parts) + ". Follow progress in Background jobs."
