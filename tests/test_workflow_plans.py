import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from darius_api.visual_plan import normalize_plan, response_object
from darius_api.visual_subject import SubjectToolGuard
from darius_api.providers import OpenAIPlannerProvider
from darius_api.workflows import WorkflowRegistry
from darius_api.database import Message, Job, GenerationRecord
from darius_api.agent_harness import verify_project_result
from test_local_render import local_setup
from test_comfy_assistant import GRAPH
from test_media_backend import settings_for


def test_reasoning_item_before_visual_brief_is_not_a_parse_failure(tmp_path, monkeypatch):
    provider = OpenAIPlannerProvider(settings_for(tmp_path))
    answer = {"reply": "", "generation_prompt": "Ellie and Giorgio talking at the shop counter.", "workflow_id": None, "shots": []}
    calls = []
    def respond(*args, **kwargs):
        calls.append(args)
        return {"output": [{"type": "reasoning", "summary": []}, {"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]}
    monkeypatch.setattr(provider, "_visual_brief_response", respond)
    body = {"input": [{"role": "user", "content": json.dumps({"request": "generate this image", "context": {}})}]}
    assert provider._resolve_visual_prompt(body, 20)[0] == answer["generation_prompt"]
    assert provider._resolve_visual_prompt(body, 20)[0] == answer["generation_prompt"]
    assert len(calls) == 1


def test_incomplete_brief_gets_one_bounded_repair(tmp_path, monkeypatch):
    provider = OpenAIPlannerProvider(settings_for(tmp_path))
    calls = []
    def respond(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
        return {"output": [{"content": [{"text": '{"generation_prompt":"Ellie enters the sunlit corner shop.","reply":""}'}]}]}
    monkeypatch.setattr(provider, "_visual_brief_response", respond)
    body = {"input": [{"role": "user", "content": json.dumps({"request": "generate an image", "context": {}})}]}
    assert provider._resolve_visual_prompt(body, 20)[0].startswith("Ellie")
    assert len(calls) == 2


def test_plan_keeps_two_character_identities_and_reference_sets_separate():
    context = {"characters": [{"id": "ellie", "name": "Ellie", "canonical_prompt": "Red coat", "approved_reference_asset_ids": ["ellie-sheet"]},
                              {"id": "giorgio", "name": "Giorgio", "canonical_prompt": "Blue apron", "approved_reference_asset_ids": ["giorgio-sheet"]}]}
    answer = {"generation_prompt": "Ellie and Giorgio at the counter.", "shots": [{"prompt": "Ellie and Giorgio at the counter.", "subject_ids": ["ellie", "giorgio"], "reference_asset_ids": ["ellie-sheet", "giorgio-sheet"]}]}
    plan = normalize_plan(answer, context, "Generate an image of Ellie and Giorgio")
    subjects = plan["shots"][0]["subjects"]
    assert subjects[0]["reference_asset_ids"] == ["ellie-sheet"]
    assert subjects[1]["canonical_prompt"] == "Blue apron"
    answer["shots"][0]["reference_asset_ids"] = ["foreign-project-image"]
    with pytest.raises(ValueError, match="active project"):
        normalize_plan(answer, context, "Generate an image")


def test_multiple_positive_slots_require_explicit_roles_and_support_dotted_node_ids():
    graph = {"text.encoder": {"class_type": "CLIPTextEncodeSDXL", "inputs": {"text_l": "old subject", "text_g": "old scene", "prompt_mode": "literal"}},
             "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
             "sampler": {"class_type": "KSampler", "inputs": {"positive": ["text.encoder", 0], "negative": ["negative", 0]}}}
    captured = []
    guard = SubjectToolGuard(lambda envelope, timeout: captured.append(envelope) or {}, lambda _: "Ellie and Giorgio at the corner shop.", OpenAIPlannerProvider._prompt_slot)
    args = {"graph": graph}
    result = guard({"operation": "prepare_graph", "arguments": args}, 10)
    assert result["error_code"] == "prompt_mapping_required"
    assert not captured
    args["prompt_bindings"] = {"text.encoder.text_l": "shot", "text.encoder.text_g": "shot"}
    guard({"operation": "prepare_graph", "arguments": args}, 10)
    assert captured[0]["arguments"]["graph"]["text.encoder"]["inputs"]["text_l"].startswith("Ellie")
    assert captured[0]["arguments"]["graph"]["negative"]["inputs"]["text"] == "blurry"
    assert graph["text.encoder"]["inputs"]["text_l"] == "old subject"
    assert captured[0]["arguments"]["graph"]["text.encoder"]["inputs"]["prompt_mode"] == "literal"


def test_registry_recovers_changed_files_and_isolates_broken_definition(tmp_path):
    source = WorkflowRegistry(settings_for(tmp_path).workflow_definitions_dir)
    source.load()
    contract = source.get("qwen-image-2-1-text-to-image")
    definitions = tmp_path / "catalog"
    definitions.mkdir()
    target = definitions / "valid.json"
    target.write_text(contract.model_dump_json())
    (definitions / "broken.json").write_text('{"id":')
    registry = WorkflowRegistry(definitions)
    registry.load()
    assert registry.get(contract.id).name == contract.name
    assert len(registry.issues) == 1
    target.write_text(contract.model_copy(update={"name": "Updated workflow"}).model_dump_json())
    assert registry.get(contract.id).name == "Updated workflow"
    (definitions / "duplicate.json").write_text(contract.model_dump_json())
    assert registry.enabled() == []


def test_three_distinct_shots_queue_independently_and_retry_only_reuses_its_slot(canvas_client):
    from test_canvas import create_canvas
    from darius_api.database import CanvasGenerationRecord
    client,app,project,launches=canvas_client
    prompts=['Ellie enters the sunlit corner shop.','Ellie selects a drink at the fridge.','Giorgio waits at the wooden counter.']
    documents=[]
    for prompt in prompts:
        doc=create_canvas(client,project)
        base=f"/api/v1/projects/{project}/canvases/{doc['id']}"
        saved=client.post(base+'/save',json={'revision':1,'content':{**doc['content'],'globalPrompt':prompt}})
        assert saved.status_code==200
        documents.append(base)
    ids=[]
    for i in [1,0,2]:
        body={'revision':2,'idempotencyKey':f'shot-{i}-render','approved':True}
        first=client.post(documents[i]+'/generate',json=body)
        assert first.status_code==200,first.text
        assert client.post(documents[i]+'/generate',json=body).json()==first.json()
        ids.append(first.json()['jobId'])
    assert len(set(ids))==3 and len(launches)==3
    with app.state.session_factory() as session:
        records=session.scalars(select(CanvasGenerationRecord)).all()
        assert len(records)==3
        assert {r.prompt for r in session.scalars(select(GenerationRecord))}==set(prompts)
        jobs=session.scalars(select(Job)).all()
        assert len(jobs)==3
        from pathlib import Path
        compiled=[json.loads(Path(app.state.registry.get(j.input_payload['workflow_id']).workflow_reference).read_text(encoding='utf-8')) for j in jobs]
        assert {g['27']['inputs']['prompt'] for g in compiled}==set(prompts)


def test_agent_continues_after_premature_final_reply_for_first_shot(local_setup):
    from test_assistant import FakeAssistant
    settings,app,client,project,cid,message,bridge,contract,launched=local_setup
    provider=FakeAssistant()
    provider.answer={'reply':'Here are three scene ideas.','generation_prompt':'A scene','workflow_id':contract.id}
    app.state.planner_provider=provider
    base=f'/api/v1/conversations/{cid}/reply'
    result=client.post(base,json={'message_id':message})
    assert result.status_code==200,result.text
    assert client.post(base,json={'message_id':message}).json()['id']==result.json()['id']
    assert len(provider.calls)==1 and not launched
    assert result.json()['metadata']['task']['engine']=='creative-helper'
    assert client.get(f'/api/v1/jobs?project_id={project}').json()==[]

from test_canvas import canvas_client
