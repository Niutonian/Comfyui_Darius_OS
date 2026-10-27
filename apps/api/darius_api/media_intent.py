"""Conservative media routing from the current conversation, never model promises."""
import re


def normalized(text):
    text = re.sub(r"\bi[, ]age\b|\bimgae\b", "image", text, flags=re.I).replace("’", "'")
    numbers = {word: str(index) for index, word in enumerate(("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"), 1)}
    return re.sub(r"\b(scene|shot)\s+(?:number\s+)?(" + "|".join(numbers) + r")\b", lambda match: match[1] + " " + numbers[match[2].lower()], text, flags=re.I)


def is_writing_request(text):
    text = normalized(initial_action(text))
    return bool(re.search(r"\b(?:write|outline|brainstorm|develop)\b.{0,100}\b(?:scenes?|stories|story|screenplay|dialogue|plot|scripts?|code)\b", text, re.I))


def draft_only(text):
    text = normalized(text)
    return bool(is_information_request(text) or is_writing_request(text)
        or re.search(r"\b(?:don't|do not|never|hold off|avoid|without)\s+(?:(?:want|you|to|start|starting|actually|yet|please|any|ever)\s+)*(?:generat\w*|render\w*|animat\w*|run\w*|execut\w*|queu\w*|creat\w*|mak\w*|produc\w*|upscal\w*)\b", text, re.I)
        or re.search(r"\b(?:not yet|not now|no rendering|no render)\b", text, re.I)
        or re.search(r"\b(?:only|just)\s+(?:prepare|draft|plan|explain|describe|write)\b", text, re.I)
        or re.match(r"\s*(?:hypothetically|if\b|when\b)", text, re.I)
        or re.search(r"\b(?:generate|create|make|build|prepare|write)\s+(?:(?:me|a|an|the|new|custom|comfyui|image|video)\s+)*(?:workflows?|prompts?|graphs?|scripts?|storyboards?)\b", text, re.I))


def execution_requested(text):
    """One authorization vocabulary; prompt constraints are not stop commands."""
    text = normalized(text)
    if draft_only(text):
        return False
    if re.search(r"\b(?:prepare|draft|write|explain)\b", text, re.I) and not re.search(r"\b(?:generate|render|animate|run|execute|queue)\b", text, re.I):
        return False
    return is_media_request(text)


def initial_action(text):
    # A conversational "Okay, then ..." introduces the action; it is not a
    # second phase. Later "then animate ..." must not change an image request.
    text = re.sub(r"^\s*(?:(?:ok(?:ay)?|yes|yeah)[,!\s]*)?(?:then\s+)?(?=let['’]s\b|(?:please\s+)?(?:create|generate|render|make|animate)\b)", "", text, flags=re.I)
    return re.split(r"\b(?:and\s+then|then|afterwards|later)\b", text, maxsplit=1, flags=re.I)[0]


def output_kind(text):
    text = initial_action(text)
    return "video" if re.search(r"\b(videos?|clips?|animate|animations?)\b", text, re.I) else "image"


def is_information_request(text):
    # Voice commonly prefixes questions with "Okay" or "Hey Darius".
    text = re.sub(r"^\s*(?:(?:ok(?:ay)?|yes|yeah|hey(?:\s+darius)?|darius|please|well)[,!\s]+)*", "", text, flags=re.I)
    return bool(re.match(r"(?:why|what|which|where|how|is|are|did|does|explain|describe|list|tell)\b", text, re.I)
                or re.match(r"(?:can|could|would)\s+you\s+(?:please\s+)?(?:tell|explain|list|describe)\b", text, re.I))


def is_media_request(text):
    text = normalized(text)
    if is_information_request(text) or is_writing_request(text):
        return False
    if re.search(r"\b(upscale|upscaling|enlarge|retouch)\b", text, re.I):
        return True
    if re.search(r"\b(?:generate|render|create|make|produce)\s+(?:all\s+(?:\d+|one|two|three|four|five|six)|both)\b", text, re.I):
        return True
    return bool(
        re.search(r"\b(?:animate|edit|retouch)\s+(?:it|this|that|her|him|them)\b", text, re.I)
        or re.search(r"\b(generate|regenerate|recreate|render|rerender|animate|create|make|produce|build|prepare|run|execute|launch)\b", text, re.I)
        and re.search(r"\b(images?|pictures?|photos?|videos?|clips?|animations?|workflows?|comfy|portraits?|views?|layouts?|shots?|stills?|versions?|examples?|variations?|fullbody)\b", text, re.I)
        or re.search(r"\b(generate|regenerate|recreate|render|rerender|animate)\b.*\b(?:it|this|that|them|scenes?|shots?|frames?|charact?hers?\s+sheets?)\b", text, re.I)
    )


def resolve_request(text, context):
    """Only a short explicit go-ahead can inherit an unfinished user request."""
    if isinstance(context.get("resolved_media_request"), str):
        return context["resolved_media_request"]
    text = normalized(text)
    if is_writing_request(text) or is_information_request(text):
        return text
    messages = context.get("messages", [])
    # A focused answer to our own clarification continues only that adjacent
    # unfinished request. It never revives an older job or crosses a new topic.
    prior = [m for m in messages if isinstance(m, dict) and normalized(m.get("content", "")).strip() != text.strip()]
    if (len(prior) >= 2 and prior[-1].get("role") == "assistant"
            and (prior[-1].get("task") or {}).get("state") == "needs_input"
            and prior[-2].get("role") == "user"
            and not (prior[-2].get("task") or {}).get("job_id")
            and re.fullmatch(r"\s*(?:scene\s*#?\s*\d+(?:\s*[,/-]?\s*shot\s*#?\s*\d+)?|shot\s*#?\s*\d+)[.!\s]*", text, re.I)):
        previous = prior[-2].get("content", "")
        if is_media_request(previous) and not draft_only(previous):
            return previous + "\nClarification: " + text
    # Explicit scene changes start a NEW render, not a replay of the old job.
    visual_context = bool(context.get("attached_asset_ids")) or any(
        m.get("role") == "user" and is_media_request(m.get("content", "")) for m in messages[-12:] if isinstance(m, dict))
    if visual_context and not is_media_request(text) and re.search(r"\b(?:place|put|depict|portray)\b|\bdo\s+something\s+(?:very\s+)?different\b", text, re.I) and not draft_only(text) and not re.search(r"\b(?:notes?|description|settings?|timeline|chat|editor|bible)\b", text, re.I):
        previous = next((m.get("content", "") for m in reversed(messages[-12:]) if isinstance(m, dict)
                         and m.get("role") == "user" and is_media_request(m.get("content", ""))), "")
        kind = output_kind(text if re.search(r"\b(?:video|clip|animate)\b", text, re.I) else previous)
        return f"Generate a new {kind}. Current visual instruction: " + text
    repeat = bool(re.search(r"\b(?:same\s+(?:prompt|shot|image|request)|test\s+.{0,30}\bwith)\b", text, re.I))
    selection_pattern = (r"\s*(?:(?:ok(?:ay)?|yes|please)[,.!\s]*)*(?:"
        r"(?:use|try|switch to)\s+(?:the\s+)?[\w. -]{1,100}\s+workflow|"
        r"(?:this one|the workflow is called|use the workflow)\s+[\w.\"' -]{1,120})[,!.\s]*")
    count_reply = r"\s*(?:(?:oh|ok(?:ay)?|yes|please|just)[,.!\s]*)*(?:[1-6]|one|two|three|four|five|six)\s+(?:outputs?|images?|videos?)(?:\s+please)?[,.!\s]*"
    selection = bool(re.fullmatch(selection_pattern, text, re.I))
    if repeat or selection:
        for message in reversed(messages[-20:]):
            if not isinstance(message, dict):
                continue
            if (message.get("task") or {}).get("state") == "cancelled":
                return text
            if not repeat and (message.get("job_id") or message.get("local_render_job_id") or (message.get("task") or {}).get("job_id")):
                return text
            if message.get("role") != "user" or message.get("content", "").strip() == text.strip():
                continue
            previous = message.get("content", "")
            if (message.get("task") or {}).get("state") == "cancelled" or re.search(r"\b(?:cancel|stop|never mind)\b", previous, re.I):
                break
            if is_media_request(previous) and not draft_only(previous):
                if not repeat and (message.get("job_id") or message.get("local_render_job_id") or (message.get("task") or {}).get("job_id")):
                    return text
                return previous + "\nCurrent instruction: " + text
            if selection and (re.fullmatch(selection_pattern, previous, re.I) or re.fullmatch(count_reply, previous, re.I)):
                continue
            if not is_information_request(previous) and not re.fullmatch(r"\s*(?:ok|okay|yes|please|proceed|go ahead)[,.!\s]*", previous, re.I):
                break
    if not re.fullmatch(r"\s*(?:(?:ok(?:ay)?|yes|yup|yeah|please)[,!.\s]*)*(?:proceed|go ahead|(?:do|run|generate|render|create|make|launch)\s+(?:it|this|that|them)|use the tools and launch them)(?:\s+please)?[.!\s]*", text, re.I):
        return text
    skipped_current = False
    for message in reversed(messages[-12:]):
        if not isinstance(message, dict):
            continue
        if message.get("job_id") or message.get("local_render_job_id") or (message.get("task") or {}).get("job_id"):
            return text  # Never replay an already queued operation on a vague approval.
        if message.get("role") != "user":
            continue
        previous = message.get("content", "")
        if previous.strip() == text.strip() and not skipped_current:
            skipped_current = True
            continue
        if (message.get("task") or {}).get("state") == "cancelled":
            return text
        if re.search(r"\b(cancel|stop|never mind|instead|not now)\b", previous, re.I):
            return text
        if re.fullmatch(r"\s*(?:(?:ok(?:ay)?|yes|yup|yeah|please)[,!.\s]*)*(?:proceed|go ahead|(?:do|run|generate|render|create|make|launch)\s+(?:it|this|that|them))(?:\s+please)?[.!\s]*", previous, re.I):
            continue
        if is_media_request(previous):
            return previous + "\nCurrent instruction: " + text
        return text  # Do not cross a different user request to revive an old render.
    return text


def requested_count(text):
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    text = initial_action(text)
    # Voice spells aspect ratios as "16 by 9 image". Neither dimension is an
    # output count. Keep the original request intact; normalize only this view.
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?::|/|[x×]|by|to)\s*\d+(?:\.\d+)?\b", " ", text, flags=re.I)
    all_match = re.search(r"\b(?:generate|render|create|make|produce)\s+all\s+(\d+|one|two|three|four|five|six)(?=\s*(?:$|[,.!?]|\b(?:using|with)\b))", text, re.I)
    if all_match:
        return words.get(all_match[1].lower()) or int(all_match[1])
    if re.search(r"\b(?:generate|render|create|make|produce)\s+(?:them\s+)?both(?=\s*(?:$|[,.!?]|\b(?:using|with)\b))", text, re.I):
        return 2
    match = re.search(r"\b(\d+|one|two|three|four|five|six)\s+(?:separate\s+|distinct\s+|different\s+)?(?:\d+(?:\.\d+)?[ -]*(?:second|sec|s)s?[ -]+)?(?:videos?|clips?|images?|pictures?|photos?|scenes?|shots?|frames?|examples?|variations?|options?|takes?)\b", text, re.I)
    return (words.get(match[1].lower()) or int(match[1])) if match else 1
