from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


def _load_root_env(root: Path) -> None:
    """Load root .env values without overriding the process environment.

    This intentionally avoids logging values and accepts only simple KEY=VALUE lines.
    """
    path = root / ".env"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _path_from_env(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else None


@dataclass(frozen=True, slots=True)
class Settings:
    repository_root: Path
    data_dir: Path
    database_url: str
    workflow_definitions_dir: Path
    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_output_dir: Path | None = None
    comfy_workflow_root: Path | None = None
    comfy_workflow_defaults_root: Path | None = None
    block_party_comfy_root: Path | None = None
    comfy_mcp_command: str = "comfy"
    comfy_mcp_args: tuple[str, ...] = ()
    comfy_job_timeout_seconds: int = 2400
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    max_upload_bytes: int = 1024 * 1024 * 1024
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_planner_model: str = ""
    openai_reasoning_effort: str = "auto"
    openai_live_model: str = "gpt-live-1"
    deepseek_api_key: str = ""
    deepseek_model: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:14b"
    ollama_gpu_wait_seconds: int = 3600
    ollama_context_tokens: int = 16384
    ollama_model_contexts: str = ""
    ollama_unload_idle_comfy: bool = True
    llamacpp_base_url: str = "http://127.0.0.1:8080"
    llamacpp_model: str = "unsloth/Qwen3.5-9B-GGUF:Q6_K"
    llamacpp_sleep_timeout_seconds: int = 30
    llamacpp_unload_idle_comfy: bool = False
    opencode_command: str = "opencode"
    opencode_model: str = "nemotron-3.5-lightning-free"
    bfl_api_key: str = ""
    bfl_api_base_url: str = ""
    tts_provider: str = ""
    tts_service_url: str = "http://127.0.0.1:8002"
    tts_model_path: Path | None = None
    transcription_provider: str = ""
    transcription_model: str = ""
    transcription_model_path: Path | None = None
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        repository_root = Path(__file__).resolve().parents[3]
        _load_root_env(repository_root)
        raw_data_dir = Path(os.getenv("DARIUS_DATA_DIR", str(repository_root / "data")))
        if not raw_data_dir.is_absolute():
            raw_data_dir = repository_root / raw_data_dir
        data_dir = raw_data_dir.resolve()
        database_url = os.getenv(
            "DARIUS_DATABASE_URL", f"sqlite:///{(data_dir / 'darius.db').as_posix()}"
        )
        # Resolve the common relative SQLite URL against the repository, not cwd.
        if database_url.startswith("sqlite:///./"):
            database_path = (repository_root / database_url.removeprefix("sqlite:///./")).resolve()
            database_url = f"sqlite:///{database_path.as_posix()}"
        settings = cls(
            repository_root=repository_root,
            data_dir=data_dir,
            database_url=database_url,
            workflow_definitions_dir=_path_from_env("DARIUS_WORKFLOW_DEFINITIONS_DIR") or repository_root / "workflows" / "definitions",
            comfyui_base_url=os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/"),
            comfyui_output_dir=_path_from_env("COMFYUI_OUTPUT_DIR"),
            comfy_workflow_root=_path_from_env("COMFY_WORKFLOW_ROOT"),
            comfy_workflow_defaults_root=_path_from_env("DARIUS_WORKFLOW_DEFAULTS_DIR") or repository_root / "workflows" / "defaults",
            block_party_comfy_root=_path_from_env("BLOCK_PARTY_COMFY_ROOT"),
            comfy_mcp_command=os.getenv("COMFY_MCP_COMMAND", "comfy"),
            comfy_mcp_args=tuple(shlex.split(os.getenv("COMFY_MCP_ARGS", ""), posix=False)),
            comfy_job_timeout_seconds=int(os.getenv("COMFY_JOB_TIMEOUT_SECONDS", "2400")),
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
            ffprobe_path=os.getenv("FFPROBE_PATH", "ffprobe"),
            max_upload_bytes=int(os.getenv("DARIUS_MAX_UPLOAD_BYTES", str(1024 * 1024 * 1024))),
            llm_provider=os.getenv("DARIUS_LLM_PROVIDER", "openai").strip().lower() or "openai",
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_planner_model=os.getenv("OPENAI_PLANNER_MODEL", "").strip(),
            openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "auto").strip() or "auto",
            openai_live_model=os.getenv("OPENAI_LIVE_MODEL", "gpt-live-1").strip() or "gpt-live-1",
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "").strip(),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:14b").strip() or "qwen3:14b",
            ollama_gpu_wait_seconds=int(os.getenv("OLLAMA_GPU_WAIT_SECONDS", "3600")),
            ollama_context_tokens=int(os.getenv("OLLAMA_CONTEXT_TOKENS", "16384")),
            ollama_model_contexts=os.getenv("OLLAMA_MODEL_CONTEXTS", "").strip(),
            ollama_unload_idle_comfy=os.getenv("OLLAMA_UNLOAD_IDLE_COMFY", "true").strip().lower() in {"1", "true", "yes"},
            llamacpp_base_url=os.getenv("LLAMACPP_BASE_URL", "http://127.0.0.1:8080").strip().rstrip("/"),
            llamacpp_model=os.getenv("LLAMACPP_MODEL", "unsloth/Qwen3.5-9B-GGUF:Q6_K").strip()
            or "unsloth/Qwen3.5-9B-GGUF:Q6_K",
            llamacpp_sleep_timeout_seconds=int(os.getenv("LLAMACPP_SLEEP_TIMEOUT_SECONDS", "30")),
            llamacpp_unload_idle_comfy=os.getenv("LLAMACPP_UNLOAD_IDLE_COMFY", "false").strip().lower() in {"1", "true", "yes"},
            opencode_command=os.getenv("OPENCODE_COMMAND", "opencode").strip() or "opencode",
            opencode_model=os.getenv("OPENCODE_MODEL", "nemotron-3.5-lightning-free").strip()
            or "nemotron-3.5-lightning-free",
            bfl_api_key=os.getenv("BFL_API_KEY", "").strip(),
            bfl_api_base_url=os.getenv("BFL_API_BASE_URL", "").strip().rstrip("/"),
            tts_provider=os.getenv("TTS_PROVIDER", "").strip(),
            tts_service_url=os.getenv("TTS_SERVICE_URL", "http://127.0.0.1:8002").strip().rstrip("/"),
            tts_model_path=_path_from_env("TTS_MODEL_PATH"),
            transcription_provider=os.getenv("TRANSCRIPTION_PROVIDER", "").strip(),
            transcription_model=os.getenv("TRANSCRIPTION_MODEL", "").strip(),
            transcription_model_path=_path_from_env("TRANSCRIPTION_MODEL_PATH"),
            cors_origins=tuple(
                origin.strip().rstrip("/")
                for origin in os.getenv(
                    "DARIUS_CORS_ORIGINS",
                    "http://127.0.0.1:3000,http://localhost:3000",
                ).split(",")
                if origin.strip()
            ),
        )
        from .comfy_connection import effective_settings
        return effective_settings(settings)

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "jobs").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "projects").mkdir(parents=True, exist_ok=True)
