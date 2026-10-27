import json
from dataclasses import replace

from fastapi.testclient import TestClient

from darius_api.main import create_app
from darius_api.render_preview import preview_contract
from darius_api.services import JobWorker, register_workflows
from darius_api.workflows import WorkflowContract
from test_media_backend import settings_for, create_project


def setup_preview(tmp_path):
    graph = {
        "1": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "A hedgehog wearing a party hat"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ["1", 0], "clip": ["4", 0]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 0]}, "_meta": {"title": "Negative prompt"}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen.safetensors"}},
        "5": {"class_type": "KSampler", "inputs": {"positive": ["2", 0], "negative": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "fixture"}},
        "unused": {"class_type": "PrimitiveString", "inputs": {"value": "Disconnected template example"}},
    }
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    contract = WorkflowContract.model_validate({
        "id": "assistant-fixture", "name": "Scene draft", "version": "1", "capability": "text-to-image",
        "execution_provider": "local-comfyui", "workflow_reference": str(path),
        "required_inputs": [
            {"key": "positive", "type": "string", "default": graph["1"]["inputs"]["value"], "maps_to": {"slot": "1.value"}},
            {"key": "negative", "type": "string", "required": False, "default": "", "maps_to": {"slot": "3.text"}},
        ], "output": {"kind": "image", "count": 1}, "runtime_mapping": {"api_format": True, "filename_prefix_slot": "9.filename_prefix"},
    })
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "assistant-fixture.json").write_text(contract.model_dump_json(), encoding="utf-8")
    return replace(settings_for(tmp_path), workflow_definitions_dir=definitions), contract, graph, path


def test_preview_uses_execution_overrides_and_connected_models_without_mutation(tmp_path):
    _, contract, original, path = setup_preview(tmp_path)
    preview = preview_contract(contract, {"positive": "Garvin in the spaceship vat bay"}, "Garvin in the spaceship vat bay")
    assert preview["positive"] == [{"slot": "1.value", "label": "PrimitiveStringMultiline", "value": "Garvin in the spaceship vat bay"}]
    assert preview["negative"][0]["value"] == ""
    assert preview["models"][0]["value"] == "qwen.safetensors"
    assert not preview["blocked"]
    assert json.loads(path.read_text()) == original


def test_preview_detects_hedgehog_positive_scene_negative_mismatch(tmp_path):
    _, contract, _, _ = setup_preview(tmp_path)
    preview = preview_contract(contract, {"negative": "Garvin in the spaceship vat bay"}, "Garvin in the spaceship vat bay")
    assert "hedgehog" in preview["positive"][0]["value"]
    assert preview["blocked"]
    assert "negative conditioning" in preview["warnings"][0]


def test_preview_endpoint_is_read_only_scoped_and_action_plan_freezes_evidence(tmp_path):
    settings, contract, graph, path = setup_preview(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project = create_project(client)
        other = create_project(client, "Other")
        owned = contract.model_copy(update={"id": "assistant-owned", "project_id": project})
        app.state.registry.add(owned)
        register_workflows(app.state.session_factory, app.state.registry)
        body = {"project_id": project, "request_text": "Garvin in the spaceship vat bay", "inputs": {"positive": "Garvin in the spaceship vat bay"}}
        route = "/api/v1/workflows/assistant-owned"
        preview = client.post(route + "/preview", json=body)
        assert preview.status_code == 200, preview.text
        assert client.get("/api/v1/jobs").json() == []
        assert client.post(route + "/preview", json={**body, "project_id": other}).status_code == 409
        plan = client.post(route + "/propose", json=body)
        assert plan.status_code == 201, plan.text
        snapshot = plan.json()["expected_output"]["render_preview"]
        assert snapshot["graph_digest"] == preview.json()["graph_digest"]
        graph["4"]["inputs"]["clip_name"] = "different-model.safetensors"
        path.write_text(json.dumps(graph), encoding="utf-8")
        approve = client.post(f"/api/v1/action-plans/{plan.json()['id']}/approve")
        assert approve.status_code == 409, approve.text
        assert "changed since review" in approve.text
        assert client.get("/api/v1/jobs").json() == []


def test_corrupted_prompt_cannot_be_proposed_even_without_ui(tmp_path):
    settings, _, _, _ = setup_preview(tmp_path)
    with TestClient(create_app(settings)) as client:
        project = create_project(client)
        response = client.post("/api/v1/workflows/assistant-fixture/propose", json={
            "project_id": project, "request_text": "Garvin in a spaceship", "inputs": {"negative": "Garvin in a spaceship"}})
        assert response.status_code == 409
        assert "negative conditioning" in response.text
        assert client.get("/api/v1/jobs").json() == []


def test_changed_graph_after_queuing_is_rejected_before_provider_execution(tmp_path):
    settings, contract, graph, path = setup_preview(tmp_path)
    app = create_app(settings)
    class NoExecution:
        calls = 0
        def execute(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("A changed reviewed graph must never reach the provider")
    provider = NoExecution()
    with TestClient(app) as client:
        project = create_project(client)
        app.state.registry.add(contract.model_copy(update={"id": "assistant-worker", "project_id": project}))
        register_workflows(app.state.session_factory, app.state.registry)
        response = client.post("/api/v1/workflows/assistant-worker/propose", json={
            "project_id": project, "request_text": "Garvin in a spaceship", "inputs": {"positive": "Garvin in a spaceship"}})
        assert response.status_code == 201, response.text
        plan = response.json()
        approved = client.post(f"/api/v1/action-plans/{plan['id']}/approve")
        assert approved.is_success, approved.text
        job_id = approved.json()["job_id"]
        graph["4"]["inputs"]["clip_name"] = "swapped-model.safetensors"
        path.write_text(json.dumps(graph), encoding="utf-8")
        worker = JobWorker(app.state.session_factory, app.state.registry, settings, provider)
        assert worker.run_once() == job_id
        assert provider.calls == 0
        failed = client.get(f"/api/v1/jobs/{job_id}").json()
        assert failed["status"] == "failed"
        assert "changed after approval" in failed["error_detail"]


def test_cloud_preview_does_not_claim_final_graph_verification(tmp_path):
    _, contract, _, _ = setup_preview(tmp_path)
    cloud = contract.model_copy(update={"id": "cloud-fixture", "execution_provider": "bfl", "model_dependencies": ["FLUX.2 Pro"]})
    preview = preview_contract(cloud, {"positive": "Garvin in a spaceship"})
    assert preview["verification"] == "contract"
    assert preview["graph_digest"] is None
    assert preview["positive"][0]["value"] == "Garvin in a spaceship"
    assert preview["models"][0]["value"] == "FLUX.2 Pro"
    assert any("final provider graph" in warning for warning in preview["warnings"])


def test_review_links_source_reply_and_completion_and_reapproval_is_idempotent(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import select
    from darius_api.database import Job, Message, ActionPlanTransition
    from darius_api.services import approve_action_plan, update_agent_task
    settings, contract, _, _ = setup_preview(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project = create_project(client)
        chat = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
        source = client.post(f"/api/v1/conversations/{chat}/messages", json={
            "role": "user", "content": "Generate Albert in a desert",
            "metadata": {"task": {"engine": "langgraph", "state": "draft"}}}).json()
        reply = client.post(f"/api/v1/conversations/{chat}/messages", json={
            "role": "assistant", "content": "Ready for review. No render was submitted.",
            "metadata": {"reply_to": source["id"], "generation_prompt": "Albert in a desert"}}).json()
        linked = contract.model_copy(update={"id": "assistant-linked", "project_id": project, "generation_task_id": source["id"]})
        app.state.registry.add(linked)
        register_workflows(app.state.session_factory, app.state.registry)
        body = {"project_id": project, "request_text": "Albert in a desert", "inputs": {"positive": "Albert in a desert"}}
        response = client.post("/api/v1/workflows/assistant-linked/propose", json=body)
        assert response.status_code == 409
        assert client.get(f'/api/v1/jobs?project_id={project}').json() == []
        # Current manual review is independent of chat. Historical message
        # associations below are persisted fixtures, not chat execution grants.
        app.state.registry.add(contract.model_copy(update={'id':'standalone-reviewed','project_id':project}))
        register_workflows(app.state.session_factory,app.state.registry)
        response = client.post('/api/v1/workflows/standalone-reviewed/propose',json=body)
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan['conversation_id'] is None
        assert 'source_message_id' not in plan['expected_output']
        with ThreadPoolExecutor(max_workers=2) as pool:
            approved = list(pool.map(lambda _: approve_action_plan(app.state.session_factory, app.state.registry, plan["id"]), range(2)))
        assert approved[0].job_id == approved[1].job_id
        with app.state.session_factory.begin() as session:
            historical=session.get(Job,approved[0].job_id)
            historical.input_payload={**historical.input_payload,'local_render_message_id':source['id']}
            old_reply=session.get(Message,reply['id'])
            old_reply.metadata_json={**old_reply.metadata_json,'job_id':historical.id,'reviewed_generation':True}
        # A manual review linked to a chat must reach the renderer as manual;
        # the source message association is not standing auto-run permission.
        from darius_api.providers import ComfyMcpProvider, ProviderResult
        approval_flags = []
        class ReviewedRenderer(ComfyMcpProvider):
            def execute(self, contract, inputs, project_id, job_id, *, manual_approval=False):
                approval_flags.append(manual_approval)
                return ProviderResult(None, (), {}, mocked=True)
        worker = JobWorker(app.state.session_factory, app.state.registry, settings, ReviewedRenderer(settings))
        # The shared dispatcher checks ComfyUI capacity before executing. Keep
        # this approval test offline while exercising that readiness check.
        import io
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: io.BytesIO(
            b'{"queue_running": [], "queue_pending": []}'))
        assert worker.run_once(approved[0].job_id) == approved[0].job_id
        assert approval_flags == [True]
        with app.state.session_factory.begin() as session:
            jobs = list(session.scalars(select(Job)))
            assert len(jobs) == 1
            job = jobs[0]
            assert job.input_payload["local_render_message_id"] == source["id"]
            assert session.get(Message, reply["id"]).metadata_json["job_id"] == job.id
            assert session.get(Message, reply["id"]).metadata_json["reviewed_generation"] is True
            assert session.get(Message, reply["id"]).content == reply["content"]
            job.status, job.output_asset_ids = "completed", ["result-asset"]
            update_agent_task(session, job)
            task = session.get(Message, source["id"]).metadata_json["task"]
            assert task["state"] == "completed" and task["output_asset_ids"] == ["result-asset"]
            transitions = list(session.scalars(select(ActionPlanTransition)))
            # Three review/approval transitions plus worker start and finish.
            assert len(transitions) == 5
            assert sum(item.to_state == "approved" for item in transitions) == 1
            assert sum(item.to_state == "queued" for item in transitions) == 1


def test_review_rejects_foreign_source_or_conversation_before_job_creation(tmp_path):
    settings, contract, _, _ = setup_preview(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project, other = create_project(client), create_project(client, "Other")
        app.state.registry.add(contract.model_copy(update={"id": "assistant-scoped", "project_id": project}))
        register_workflows(app.state.session_factory, app.state.registry)
        foreign_chat = client.post(f"/api/v1/projects/{other}/conversations", json={}).json()["id"]
        source = client.post(f"/api/v1/conversations/{foreign_chat}/messages", json={"role": "user", "content": "Generate an image"}).json()
        body = {"project_id": project, "request_text": "Albert", "inputs": {"positive": "Albert"}}
        for extra in ({"source_message_id": source["id"]}, {"conversation_id": foreign_chat}, {"source_message_id": "missing"}):
            response = client.post("/api/v1/workflows/assistant-scoped/propose", json={**body, **extra})
            assert response.status_code == 409, response.text
            assert "source message" in response.text or "conversation" in response.text
        assert client.get("/api/v1/jobs").json() == []
