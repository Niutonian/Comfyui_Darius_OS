"""Exact voice origins, including only the explicitly configured LAN gateway."""
import ipaddress
import json
import os
from pathlib import Path
import socket


def voice_origins(root=None):
    origins = {"http://localhost:3000", "http://127.0.0.1:3000"}
    origins.update(value.strip().rstrip("/") for value in os.getenv("DARIUS_CORS_ORIGINS", "").split(",") if value.strip())
    try:
        origins.update(f"http://{item[4][0]}:3000" for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    try:
        settings = json.loads((root / "data/lan-https/settings.json").read_text(encoding="utf-8-sig"))
        address = ipaddress.IPv4Address(settings["address"])
        lan = any(address in ipaddress.IPv4Network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
        if settings.get("version") == 1 and lan and settings.get("port") == 3443:
            origins.update({f"https://{address}:3443", "https://localhost:3443", "https://127.0.0.1:3443"})
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return origins
