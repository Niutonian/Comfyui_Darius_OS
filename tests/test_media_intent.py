import pytest
from darius_api.media_intent import is_media_request, output_kind, requested_count, resolve_request


@pytest.mark.parametrize("text", ["Generate three separate 10 second videos of Garvin", "Make 3 clips of Garvin", "Render two pictures of the scene"])
def test_plural_media(text):
    assert is_media_request(text)
    assert requested_count(text) in (2, 3)
    assert output_kind(text) == ("image" if "pictures" in text else "video")


@pytest.mark.parametrize("ratio", ["16 by 9", "16:9", "16/9", "16 x 9", "16×9", "4 to 3"])
def test_aspect_ratio_is_not_an_output_count(ratio):
    assert requested_count(f"Create a {ratio} image of a burger with Moss workflow") == 1
    assert requested_count(f"Create three {ratio} images of a burger") == 3


@pytest.mark.parametrize("selection", ['this one Darius_Moss_image', 'the workflow is called "Darius_Moss_image"', 'use the Moss workflow'])
def test_workflow_name_answer_continues_an_unfinished_request(selection):
    original = "Create a 16 by 9 image of a burger with Moss workflow"
    context = {"messages": [{"role": "user", "content": original},
        {"role": "assistant", "content": "Which workflow?", "task": {"state": "needs_input"}}]}
    resolved = resolve_request(selection, context)
    assert original in resolved and selection in resolved and requested_count(resolved) == 1


@pytest.mark.parametrize("barrier", [
    {"role": "assistant", "content": "Queued", "job_id": "actual-job"},
    {"role": "user", "content": "Cancel that"},
    {"role": "user", "content": "Let's write a new story instead"},
])
def test_workflow_name_answer_never_crosses_execution_cancellation_or_new_topic(barrier):
    text = 'this one Darius_Moss_image'
    context = {"messages": [{"role": "user", "content": "Generate a burger image"}, barrier]}
    assert resolve_request(text, context) == text


@pytest.mark.parametrize("approval", ["ok, proceed", "use the tools and launch them", "yes do it please"])
def test_pending_followup(approval):
    prior = "Generate three separate 10 second videos of Garvin"
    context = {"messages": [{"role": "user", "content": prior}, {"role": "assistant", "content": "Ready to generate."}, {"role": "user", "content": approval}]}
    assert prior in resolve_request(approval, context)
    assert is_media_request(resolve_request(approval, context))


def test_followup_does_not_replay_queued_or_cancelled_request():
    prior = {"role": "user", "content": "Generate three clips of Garvin"}
    for terminal in [{"role": "assistant", "content": "Queued", "job_id": "actual-job"}, {"role": "user", "content": "cancel that"}]:
        assert resolve_request("ok, proceed", {"messages": [prior, terminal]}) == "ok, proceed"
    assert resolve_request("thanks", {"messages": [prior]}) == "thanks"
    assert resolve_request("ok, proceed", {"messages": [{"role": "assistant", "content": "I will generate three clips"}]}) == "ok, proceed"


def test_questions_are_not_media_execution():
    assert not is_media_request("Why did you generate videos?")


@pytest.mark.parametrize("text", [
    "Okay, which workflow can you use to generate images?",
    "Hey Darius, what workflow generates videos?",
    "Please explain how to generate an image using Flux3",
    "Generate a workflow that renders images",
    "Create a new ComfyUI workflow for video",
    "Only prepare an image draft",
    "Do not generate images yet",
    "Create a prompt for an image of Albert",
    "Write some new scenes",
    "Create a storyboard for this video",
    "Don't create an image",
    "I do not want you to generate images",
    "Describe the scene without rendering an image",
])
def test_workflow_questions_and_drafts_never_authorize_render(text):
    from darius_api.local_render import requests_render
    assert not requests_render(text)


@pytest.mark.parametrize("text", [
    "Okay, use the workflow Flux3 to generate an image of an angel",
    "Can you generate an image using the Flux3 workflow?",
    "Please render a video with the minimax workflow",
])
def test_explicit_generation_can_select_an_existing_workflow(text):
    from darius_api.local_render import requests_render
    assert is_media_request(text)
    assert requests_render(text)


@pytest.mark.parametrize("text", [
    "Create a bakery layout without people",
    "Create only one shot of Albert",
    "Create a fullbody i,age of Albert",
    "Generate a 16:9 version of this image",
])
def test_visual_constraints_are_not_stop_commands(text):
    from darius_api.local_render import requests_render
    assert requests_render(text)


def test_scene_change_and_explicit_workflow_test_preserve_intent():
    from darius_api.local_render import requests_render
    prior = "Generate 4 examples of Albert in a bakery"
    context = {"messages": [{"role": "user", "content": prior, "job_id": "completed-job"}]}
    changed = resolve_request("Could you do something very different, Albert on a motorcycle in the desert?", context)
    assert requests_render(changed)
    assert "desert" in changed and "bakery" not in changed
    repeated = resolve_request("Test the same prompt with Flux3", context)
    assert requests_render(repeated) and requested_count(repeated) == 4
    assert "Albert in a bakery" in repeated
    assert not requests_render(resolve_request("Write some new scenes", context))
    assert resolve_request("Put that in the project notes", context) == "Put that in the project notes"
    assert resolve_request(repeated, {**context, "resolved_media_request": repeated}) == repeated
