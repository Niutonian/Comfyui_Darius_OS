from copy import deepcopy
import pytest
from darius_api.recipe_adaptation import adapt_references, apply_canvas, bind_references, requested_canvas
from darius_api.render_preview import graph_inputs


def recipe():
    return {
        "r1": {"class_type": "LoadImage", "inputs": {"image": "template-one.png"}},
        "r2": {"class_type": "LoadImage", "inputs": {"image": "template-two.png"}},
        "q": {"class_type": "TextEncodeQwenImage21", "inputs": {"prompt": "Albert in the desert",
            "negative_prompt": "", "images.image_1": ["r1", 0], "images.image_2": ["r2", 0]}},
        "canvas": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "switch": {"class_type": "ComfySwitchNode", "inputs": {"switch": False, "on_false": ["q", 2], "on_true": ["canvas", 0]}},
        "sample": {"class_type": "KSampler", "inputs": {"positive": ["q", 0], "negative": ["q", 1], "latent_image": ["switch", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["sample", 0], "filename_prefix": "fixture"}},
    }


def schema(minimum=0):
    return {"TextEncodeQwenImage21": {"input": {"required": {"images": ["COMFY_AUTOGROW_V3",
        {"template": {"min": minimum, "names": ["image_1", "image_2"]}}]}}}}


def test_one_reference_removes_only_optional_template_tail_from_copy():
    base = recipe()
    graph = deepcopy(base)
    bindings = bind_references(graph, ["r1.image", "r2.image"], ["project-albert"])
    assert bindings == {"r1.image": "project-albert"}
    prepared = adapt_references(graph, bindings, schema())
    assert "r2" not in prepared and "images.image_2" not in prepared["q"]["inputs"]
    assert prepared["q"]["inputs"]["images.image_1"] == ["r1", 0]
    assert base == recipe()
    assert bind_references(recipe(), ["r2.image", "r1.image"], ["albert"]) == {"r1.image": "albert"}


@pytest.mark.parametrize("live", [{}, schema(2)])
def test_unconfirmed_or_required_reference_is_never_dropped(live):
    graph = recipe()
    with pytest.raises(ValueError, match="optional"):
        adapt_references(graph, {"r1.image": "albert"}, live)
    assert graph == recipe()


def test_required_keyframes_and_shared_loader_cannot_be_omitted():
    graph = recipe()
    graph["video"] = {"class_type": "H3Keyframes", "inputs": {"end_image": ["r2", 0]}}
    with pytest.raises(ValueError, match="required"):
        bind_references(graph, ["r1.image", "r2.image"], ["albert"])


def test_explicit_canvas_selects_existing_empty_latent_branch_and_preserves_prompt():
    graph = recipe()
    assert apply_canvas(graph, "Generate a 16:9 image of Albert") == (1280, 720)
    assert graph["switch"]["inputs"]["switch"] is True
    assert graph["canvas"]["inputs"] == {"width": 1280, "height": 720, "batch_size": 1}
    assert graph["q"]["inputs"]["prompt"] == "Albert in the desert"
    prepared = adapt_references(graph, {"r1.image": "albert"}, schema())
    assert "on_false" not in prepared["switch"]["inputs"]
    assert graph_inputs(prepared)["positive"][0]["value"] == "Albert in the desert"


def test_canvas_is_opt_in_and_unsupported_recipe_never_claims_to_honor_ratio():
    graph = recipe()
    assert apply_canvas(graph, "Generate an image") is None
    assert graph == recipe()
    with pytest.raises(ValueError, match="single verified"):
        apply_canvas({"save": {"class_type": "SaveImage", "inputs": {}}}, "Generate a 16:9 image")
    assert requested_canvas("Generate a 9:16 image") == (720, 1280)
    with pytest.raises(ValueError, match="disagree"):
        requested_canvas("Generate a 16:9 image at 1024x1024")


def test_shared_prepare_bridge_adapts_registered_base_without_rendering(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from darius_api.main import create_app
    from darius_api.comfy_assistant import ComfyAssistantTools
    from test_media_backend import create_project
    from test_render_preview import setup_preview
    settings,_,_,_=setup_preview(tmp_path)
    with TestClient(create_app(settings)) as client:
        project=create_project(client)
        cid=client.post(f'/api/v1/projects/{project}/conversations',json={}).json()['id']
        user=client.post(f'/api/v1/conversations/{cid}/messages',json={'role':'user','content':'Generate a 16:9 image of Albert'}).json()
        app=client.app
        tools=ComfyAssistantTools(settings,app.state.registry,app.state.session_factory,project_id=project,message_id=user['id'])
        monkeypatch.setattr(tools,'_run',lambda *a:pytest.fail('Chat cannot upload or compile a workflow'))
        result=tools.call({'operation':'prepare_workflow','arguments':{'workflow_id':'qwen.json','name':'Albert desert','asset_bindings':{'r1.image':'forged'}}})
        assert result['error_code']=='chat_text_only'
        assert client.get(f'/api/v1/jobs?project_id={project}').json()==[]
