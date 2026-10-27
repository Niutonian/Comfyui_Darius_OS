"""One-time downloads; the running voice service uses local files only."""
import json
import os
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data" / "models"
os.environ["HF_HOME"] = str(MODELS / "hf-cache")
from huggingface_hub import HfApi, snapshot_download

MODELS.mkdir(parents=True, exist_ok=True)
manifest = {}
REVISIONS = {
    "k2-fsa/OmniVoice": "c5fdb5ccb189668d56333f77ba2629f4cd7535f4",
    "Systran/faster-whisper-base.en": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
}
for repo, folder in [("k2-fsa/OmniVoice", "omnivoice")]:
    revision = REVISIONS[repo]
    snapshot_download(repo, revision=revision, local_dir=MODELS / folder,
                      ignore_patterns=["*.pt", "*.bin", "*.wav", "*.mp3"])
    manifest[repo] = revision
if not (MODELS / "omnivoice" / "audio_tokenizer" / "config.json").exists():
    repo = "eustlb/higgs-audio-v2-tokenizer"
    revision = HfApi().model_info(repo).sha
    snapshot_download(repo, revision=revision, local_dir=MODELS / "omnivoice" / "audio_tokenizer",
                      ignore_patterns=["*.pt", "*.bin", "*.wav", "*.mp3"])
    manifest[repo] = revision

vosk = MODELS / "vosk-model-small-en-us-0.15"
if not (vosk / "am" / "final.mdl").exists():
    archive = MODELS / "vosk-small-en.zip"
    urllib.request.urlretrieve("https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip", archive)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not (MODELS / name).resolve().is_relative_to(MODELS.resolve()):
                raise ValueError("Unsafe model archive path")
        bundle.extractall(MODELS)
manifest["vosk"] = "vosk-model-small-en-us-0.15"
repo = "Systran/faster-whisper-base.en"
revision = REVISIONS[repo]
snapshot_download(repo, revision=revision, local_dir=MODELS / "whisper-base-en")
manifest[repo] = revision
(MODELS / "voice-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("Local voice model downloads complete.")
