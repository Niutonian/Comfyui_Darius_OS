"""HassIL command recognition; execution remains in Darius's scoped handlers.

The bundled grammar is trusted code. Transcripts and asset names are data, never
templates. No network, embeddings, model inference or unbounded result search.
"""
from functools import lru_cache
from importlib.metadata import version
from itertools import islice
from pathlib import Path
import re

from hassil.intents import Intents, TextSlotList
from hassil.recognize import recognize_all

ENGINE_VERSION = version("hassil")
CATALOG_PATH = Path(__file__).with_name("command_intents") / "en.yaml"
_ORDINALS = "zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split()
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}
# Wildcards may identify saved media, not swallow another instruction/question.
_UNSAFE_TARGET = re.compile(r"\b(?:generate|create|make|edit|delete|remove|replace|describe|analy[sz]e|workflow|prompt|node|code|how|why|settings|console|project|chat|session|then|also|and|or|before|after|not|never|don['’]?t|do not|instead|except)\b", re.I)
_MEDIA_TARGET = re.compile(r"\b(?:images?|pictures?|photos?|videos?|clips?|assets?|renders?|results?|media|it|this|that|them|full[ -]?(?:size|screen))\b|[a-f0-9]{8}-[a-f0-9-]{27}", re.I)


def normalize(text):
    text = text.strip().rstrip(".!?").strip()
    text = re.sub(r"[,\s]+please$", "", text, flags=re.I)
    text = re.sub(r"^(?:(?:ok(?:ay)?|yes|hey(?:\s+darius)?|darius)[,\s]+)*", "", text, flags=re.I)
    text = re.sub(r"^(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text)


def _ordinal_aliases():
    for number in range(100):
        tail = number % 10
        suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(tail, "th")
        yield f"{number}{suffix}", number
        if number < 20:
            yield _ORDINALS[number], number
        elif not tail:
            yield _TENS[number][:-1] + "ieth", number
        else:
            text = _TENS[number - tail] + " " + _ORDINALS[tail]
            yield text, number
            yield text.replace(" ", "-"), number


@lru_cache(maxsize=1)
def catalog():
    with CATALOG_PATH.open(encoding="utf-8") as stream:
        intents = Intents.from_yaml(stream)
    intents.slot_lists["ordinal_number"] = TextSlotList.from_tuples(_ordinal_aliases(), allow_template=False)
    # Compile every sentence at startup; a broken package must not first fail in voice.
    for intent in intents.intents.values():
        for data in intent.data:
            _ = data.sentences
    return intents


def _convert(result):
    name = result.intent.name
    slots = {key: entity.value for key, entity in result.entities.items()}
    if name == "OpenGallery":
        return {"action": "gallery", "kind": slots.get("kind")}
    if name == "ReturnGallery":
        return {"action": "back"}
    if name == "CloseViewer":
        return {"action": "close"}
    if name in {"SelectNumber", "PlayNumber"}:
        return {"action": "select", "index": int(slots["gallery_number"]) - 1, "autoplay": name == "PlayNumber"}
    if name in {"Playback", "BarePlayback"}:
        return {"action": slots["playback"], "bare": name == "BarePlayback"}
    if name in {"SeekForward", "SeekBackward"}:
        return {"action": "seek", "seconds": int(slots["seconds"]) * (-1 if name == "SeekBackward" else 1)}
    if name == "NavigateViewer":
        return {"action": slots["direction"]}
    target = slots.get("target", slots.get("name", "")).strip()
    if not target or _UNSAFE_TARGET.search(target):
        return None
    if name == "SelectName":
        return {"action": "select_name", "name": target}
    if not _MEDIA_TARGET.search(target):
        return None
    if name == "PlayTarget":
        return {"action": "play_target", "text": "open " + target}
    if name == "OpenTarget":
        return {"action": "open", "target": target}
    return None


@lru_cache(maxsize=512)
def _recognize(text):
    candidates = []
    for count, result in enumerate(islice(recognize_all(text, catalog(), allow_unmatched_entities=False), 65)):
        if count == 64:
            return {"action": "clarify", "intent": "AmbiguousCommand", "engine": "hassil"}
        command = _convert(result)
        if command is not None:
            # A numbered/finite command wins over a broad saved-name wildcard.
            priority = (0 if result.intent.name in {"OpenTarget", "PlayTarget", "SelectName"} else 1,
                        getattr(result, "text_chunks_matched", 0))
            candidates.append((priority, command, result.intent.name))
    if not candidates:
        return None
    best = max(priority for priority, _, _ in candidates)
    matches = [(command, intent) for priority, command, intent in candidates if priority == best]
    first, intent = matches[0]
    if any(command != first for command, _ in matches[1:]):
        return {"action": "clarify", "intent": "AmbiguousCommand", "engine": "hassil"}
    return {**first, "intent": intent, "engine": "hassil"}


def route_command(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 350:
        return None
    result = _recognize(normalize(text))
    return dict(result) if result else None # Callers cannot mutate the cached decision.
