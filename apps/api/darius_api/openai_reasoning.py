"""Documented Responses reasoning levels; unknown models keep API defaults."""
import re


def reasoning_levels(model: str) -> list[str]:
    name = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model)
    levels = {
        "gpt-6-astra": ["low", "medium", "high", "xhigh", "max"],
        "gpt-6.1-sol": ["low", "medium", "high", "xhigh", "max"],
        "gpt-6-sol": ["none", "low", "medium", "high", "xhigh", "max"],
        "gpt-6-luna": ["none", "low", "medium", "high", "xhigh", "max"],
        "gpt-5.6": ["none", "low", "medium", "high", "xhigh", "max"],
        "gpt-5.6-sol": ["none", "low", "medium", "high", "xhigh", "max"],
        "gpt-5.6-terra": ["none", "low", "medium", "high", "xhigh", "max"],
        "gpt-5.6-luna": ["none", "low", "medium", "high", "xhigh", "max"],
        "gpt-5.5": ["none", "low", "medium", "high", "xhigh"],
        "gpt-5.4": ["none", "low", "medium", "high", "xhigh"],
        "gpt-5.4-mini": ["none", "low", "medium", "high", "xhigh"],
        "gpt-5.4-nano": ["none", "low", "medium", "high", "xhigh"],
        "gpt-5.5-pro": ["medium", "high", "xhigh"],
        "gpt-5.4-pro": ["medium", "high", "xhigh"],
        "gpt-5.3-codex": ["low", "medium", "high", "xhigh"],
        "gpt-5.2-pro": ["medium", "high", "xhigh"],
        "gpt-5-pro": ["high"],
        "gpt-5.2": ["none", "low", "medium", "high", "xhigh"],
        "gpt-5.1": ["none", "low", "medium", "high"],
        "gpt-5": ["minimal", "low", "medium", "high"],
        "gpt-5-mini": ["minimal", "low", "medium", "high"],
        "gpt-5-nano": ["minimal", "low", "medium", "high"],
    }.get(name, [])
    return ["auto", *levels]
