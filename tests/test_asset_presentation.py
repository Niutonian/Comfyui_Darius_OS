import json
from dataclasses import replace
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from darius_api.asset_presentation import command, presentation_action
from darius_api.media_controls import media_command
from darius_api.comfy_assistant import ComfyAssistantTools
from darius_api.database import Asset, Job, Message
from darius_api.main import create_app
from darius_api.providers import ProviderError
from test_assistant import FakeAssistant
from test_media_backend import settings_for, create_project


@pytest.fixture
def setup(tmp_path):
    settings = settings_for(tmp_path)
    provider = FakeAssistant(); provider.available = False
    app = create_app(settings, planner_provider=provider)
    with TestClient(app) as client:
        project, other = create_project(client), create_project(client, "Other project")
        chat = client.post(f"/api/v1/projects/{project}/conversations", json={}).json()["id"]
        media = []
        for index, owner in enumerate((project, project, other)):
            media.append(client.post('/api/v1/assets/upload', data={'project_id': owner}, files={'file': (f'asset-{index}.png', b'original-image', 'image/png')}).json())
        yield settings, app, client, provider, project, chat, media


def ask(client, chat, text, metadata=None):
    user = client.post(f'/api/v1/conversations/{chat}/messages', json={'role':'user', 'content':text, 'metadata':metadata or {}}).json()
    result = client.post(f'/api/v1/conversations/{chat}/reply', json={'message_id':user['id']})
    assert result.status_code == 200, result.text
    return user, result.json()


@pytest.mark.parametrize('text', ['Open the latest image full size', 'Could you please show me the last render?', 'Load it inside this conversation', 'Close the preview', 'Next image', 'Show the previous asset'])
def test_common_presentation_commands_are_recognized(text):
    assert command(text)


@pytest.mark.parametrize('text', ['Generate a video of this angel', 'Show me how to generate an image', 'Open the project settings', 'Describe this image', 'Close the chat', 'Why did you show that image?', 'Show this image then generate another image'])
def test_other_actions_are_not_misclassified_as_viewer_commands(text):
    assert command(text) is None


def test_original_full_size_request_works_without_any_ready_model_and_retry_is_idempotent(setup):
    settings, app, client, provider, project, chat, media = setup
    client.post(f'/api/v1/conversations/{chat}/messages', json={'role':'assistant','content':'The ninja pigeon is ready.', 'metadata':{'viewed_asset_ids':[media[0]['id']]}})
    user, reply = ask(client, chat, 'Could you open it full size?')
    action = reply['metadata']['presentation_actions'][0]
    assert action['asset_ids'] == [media[0]['id']]
    assert action['project_id'] == project
    assert action['action'] == 'open'
    assert client.post(f'/api/v1/conversations/{chat}/reply', json={'message_id':user['id']}).json()['id'] == reply['id']
    assert provider.calls == []
    assert client.get(f'/api/v1/jobs?project_id={project}').json() == []


def test_explicit_foreign_id_never_opens_another_project_asset(setup):
    _, _, client, provider, _, chat, media = setup
    _, reply = ask(client, chat, f'Open image {media[2]["id"]}')
    assert reply['metadata']['presentation_actions'] == []
    assert 'unavailable' in reply['content']
    assert not provider.calls


def test_streamed_viewer_command_and_navigation_preserve_chat(setup):
    _, _, client, provider, project, chat, _ = setup
    user = client.post(f'/api/v1/conversations/{chat}/messages', json={'role':'user','content':'Open the latest image'}).json()
    response = client.post(f'/api/v1/conversations/{chat}/reply/stream', json={'message_id':user['id']})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['type'] == 'done'
    assert events[-1]['message']['metadata']['presentation_actions'][0]['project_id'] == project
    for text, action in [('Next image','next'),('Previous asset','previous'),('Close the preview','close')]:
        _, reply = ask(client, chat, text)
        assert reply['metadata']['presentation_actions'][0]['action'] == action
    assert not provider.calls


def test_tool_receipt_validates_project_and_managed_original_file(setup):
    settings, app, _, _, project, _, media = setup
    tools = ComfyAssistantTools(settings, app.state.registry, app.state.session_factory, project_id=project)
    result = tools.call({'operation':'present_assets','arguments':{'asset_ids':[media[0]['id']]}})
    assert result['presentation_action']['asset_ids'] == [media[0]['id']]
    assert '_image_content' not in result
    assert tools.call({'operation':'present_assets','arguments':{'asset_ids':[media[2]['id']]}}).get('error')
    with app.state.session_factory.begin() as session:
        session.get(Asset,media[0]['id']).path = str(settings.repository_root / 'README.md')
    assert tools.call({'operation':'present_assets','arguments':{'asset_ids':[media[0]['id']]}}).get('error')


def test_unknown_implicit_reference_does_not_open_a_random_project_asset(setup):
    _, _, client, provider, _, chat, _ = setup
    _, reply = ask(client, chat, 'Open it full size')
    assert reply['metadata']['presentation_actions'] == []
    assert not provider.calls


def test_generated_image_anaphora_opens_job_output_not_attached_reference(setup):
    _, app, client, provider, project, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.add(Job(id="linked-render", project_id=project, provider="mock", status="completed",
            input_payload={}, output_asset_ids=[media[1]["id"]]))
    client.post(f"/api/v1/conversations/{chat}/messages", json={"role": "assistant", "content": "Ready.",
        "metadata": {"job_id": "linked-render", "viewed_asset_ids": [media[0]["id"]]}})
    _, reply = ask(client, chat, "Show me the image that was generated", {"asset_ids": [media[0]["id"]]})
    assert reply["metadata"]["presentation_actions"][0]["asset_ids"] == [media[1]["id"]]
    assert not provider.calls


def test_named_asset_search_and_video_presentation_stay_project_scoped(setup):
    _, app, client, _, project, chat, media = setup
    with app.state.session_factory.begin() as session:
        for key in (media[0]['id'], media[2]['id']):
            session.get(Asset,key).metadata_json = {'display_name':'Angelic ninja pigeon'}
        session.get(Asset,media[1]['id']).kind = 'video'
    _, reply = ask(client,chat,'Show me the ninja pigeon image')
    assert reply['metadata']['presentation_actions'][0]['asset_ids'] == [media[0]['id']]
    _, reply = ask(client,chat,'Open the latest video full size')
    assert reply['metadata']['presentation_actions'][0]['asset_ids'] == [media[1]['id']]


def test_pending_render_does_not_open_an_older_result(setup):
    _, app, client, _, project, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.add(Job(id='pending-render',project_id=project,provider='mock',status='running',input_payload={},output_asset_ids=[]))
    client.post(f'/api/v1/conversations/{chat}/messages',json={'role':'assistant','content':'Queued.', 'metadata':{'job_id':'pending-render'}})
    _, reply = ask(client,chat,'Open it full size')
    assert reply['metadata']['presentation_actions'] == []
    assert 'no saved output' in reply['content']


@pytest.mark.parametrize('text,action', [
    ('Could you open the gallery please?', 'gallery'), ('Show my video gallery', 'gallery'),
    ('Open image three', 'select'), ('Choose the second picture', 'select'),
    ('Open image twenty-one', 'select'), ('Choose the forty eighth image', 'select'),
    ('Play video 2', 'select'), ('Select Forest opening', 'select_name'),
    ('Open the latest video fullscreen and play it', 'play_target'),
    ('Play the latest video', 'play_target'), ('Pause the video', 'pause'),
    ('Stop video', 'stop'), ('Resume', 'play'), ('Restart the clip', 'restart'),
    ('Mute the video', 'mute'), ('Unmute it', 'unmute'),
    ('Skip forward ten seconds', 'seek'), ('Rewind 20 seconds', 'seek'),
    ('Back to the gallery', 'back'), ('Close gallery', 'close'),
])
def test_gallery_and_playback_commands(text, action):
    assert media_command(text)['action'] == action


def test_spoken_number_indices_cover_the_whole_bounded_gallery():
    assert media_command('Open image twenty-one')['index'] == 20
    assert media_command('Choose the forty eighth image')['index'] == 47


@pytest.mark.parametrize('text', ['Generate a video and play it', 'Open the video then delete it',
    'Show the gallery then generate another image', 'Select a workflow', 'Play a video and edit the image',
    'Why does the video stop?', 'Make the image move'])
def test_media_controls_do_not_steal_generation_or_compound_mutations(text):
    assert media_command(text) is None


def viewer_context(ids, index=0, mode='gallery'):
    return {'presentation_context': {'asset_ids': ids, 'index': index, 'mode': mode}}


def test_gallery_opens_only_project_originals_without_model_or_jobs(setup):
    _, app, client, provider, project, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.get(Asset, media[1]['id']).role = 'derivative'
    _, reply = ask(client, chat, 'Open the gallery')
    receipt = reply['metadata']['presentation_actions'][0]
    assert receipt['action'] == 'gallery' and receipt['asset_ids'] == [media[0]['id']]
    assert not provider.calls
    assert not client.get(f'/api/v1/jobs?project_id={project}').json()


def test_spoken_selection_uses_visible_order_not_database_order(setup):
    _, _, client, provider, _, chat, media = setup
    visible = [media[1]['id'], media[0]['id']]
    _, reply = ask(client, chat, 'Open image two', viewer_context(visible))
    receipt = reply['metadata']['presentation_actions'][0]
    assert receipt['asset_ids'] == visible and receipt['index'] == 1
    assert receipt['action'] == 'select'
    assert not provider.calls
    _, reply = ask(client, chat, 'Open image nine', viewer_context(visible))
    assert reply['metadata']['presentation_actions'] == []
    assert '1 to 2' in reply['content']


def test_named_gallery_selection_handles_ambiguity_without_guessing(setup):
    _, app, client, _, _, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.get(Asset, media[0]['id']).metadata_json = {'display_name': 'Forest opening'}
        session.get(Asset, media[1]['id']).metadata_json = {'display_name': 'Forest alternative'}
    context = viewer_context([item['id'] for item in media[:2]])
    _, reply = ask(client, chat, 'Select Forest opening', context)
    assert reply['metadata']['presentation_actions'][0]['index'] == 0
    _, reply = ask(client, chat, 'Select Forest', context)
    assert reply['metadata']['presentation_actions'] == []
    assert 'unique' in reply['content']


def test_playback_and_return_to_gallery_use_current_device_selection(setup):
    _, app, client, provider, _, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.get(Asset, media[1]['id']).kind = 'video'
    context = viewer_context([media[0]['id'], media[1]['id']], 1, 'viewer')
    for text, action in [('Play the video', 'play'), ('Pause', 'pause'), ('Stop video', 'stop'),
                         ('Restart', 'restart'), ('Mute', 'mute'), ('Unmute', 'unmute'),
                         ('Rewind ten seconds', 'seek')]:
        _, reply = ask(client, chat, text, context)
        receipt = reply['metadata']['presentation_actions'][0]
        assert receipt['action'] == action and receipt['asset_ids'] == [media[1]['id']]
        if action == 'seek':
            assert receipt['seconds'] == -10
    _, reply = ask(client, chat, 'Back to gallery', context)
    assert reply['metadata']['presentation_actions'][0]['action'] == 'gallery'
    assert not provider.calls


def test_open_video_and_play_keeps_fullsize_and_autoplay_in_same_receipt(setup):
    _, app, client, provider, _, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.get(Asset, media[1]['id']).kind = 'video'
    _, reply = ask(client, chat, 'Open the latest video fullscreen and play it')
    receipt = reply['metadata']['presentation_actions'][0]
    assert receipt['action'] == 'open' and receipt['autoplay'] is True
    assert receipt['asset_ids'] == [media[1]['id']]
    assert not provider.calls


@pytest.mark.parametrize('context', [
    lambda media: viewer_context([media[2]['id']]),
    lambda media: viewer_context([media[0]['id']], -1),
    lambda media: viewer_context([media[0]['id']], True),
    lambda media: {'presentation_context': {'asset_ids': 'https://bad', 'index': 0}},
])
def test_forged_visible_gallery_context_is_rejected(setup, context):
    _, _, client, provider, _, chat, media = setup
    _, reply = ask(client, chat, 'Open image one', context(media))
    assert reply['metadata']['presentation_actions'] == []
    assert not provider.calls


def test_gallery_skips_missing_media_and_control_receipts_are_bounded(setup):
    settings, app, client, _, project, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.get(Asset, media[0]['id']).path = str(settings.data_dir / 'missing.png')
        session.get(Asset, media[1]['id']).kind = 'video'
    _, reply = ask(client, chat, 'Open gallery')
    assert reply['metadata']['presentation_actions'][0]['asset_ids'] == [media[1]['id']]
    with app.state.session_factory() as session:
        for seconds in (float('nan'), float('inf'), -601, True):
            with pytest.raises(ProviderError):
                presentation_action(session, settings, project, 'seek', [media[1]['id']], seconds=seconds)
        with pytest.raises(ProviderError):
            presentation_action(session, settings, project, 'gallery', [f'media-{index}' for index in range(49)])


def test_hassil_reply_is_auditable_and_does_not_log_spoken_names(setup):
    settings, _, client, provider, _, chat, _ = setup
    _, reply = ask(client, chat, 'Bring up my photo gallery')
    assert reply['metadata']['command_router'] == {'engine': 'hassil', 'version': '3.12.1', 'intent': 'OpenGallery', 'action': 'gallery'}
    rows = [json.loads(line) for line in (settings.data_dir / 'diagnostics' / 'backend.jsonl').read_text(encoding='utf-8').splitlines()]
    events = [row for row in rows if row['event'] == 'local_command']
    assert events[-1]['engine'] == 'hassil'
    assert 'Bring up my photo gallery' not in json.dumps(events)
    assert not provider.calls


def test_unrecognized_or_negated_commands_preserve_the_conversation_provider(setup):
    _, _, client, provider, project, chat, _ = setup
    provider.available = True
    for text in ["Don't open the gallery", 'Let us write a short story together']:
        _, reply = ask(client, chat, text)
        assert reply['content'] == provider.answer['reply']
        assert not reply['metadata'].get('presentation_actions')
        assert not reply['metadata'].get('command_router')
    assert len(provider.calls) == 2
    assert not client.get(f'/api/v1/jobs?project_id={project}').json()


def test_hassil_new_playback_phrases_keep_exact_viewer_scope(setup):
    _, app, client, provider, _, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.get(Asset, media[1]['id']).kind = 'video'
    context = viewer_context([item['id'] for item in media[:2]], 1, 'viewer')
    for text, action in [('Continue playing the video', 'play'), ('Stop playing it', 'stop'),
                         ('Jump ahead by fifteen seconds', 'seek'), ('Go back thirty seconds', 'seek')]:
        _, reply = ask(client, chat, text, context)
        receipt = reply['metadata']['presentation_actions'][0]
        assert receipt['asset_ids'] == [media[1]['id']] and receipt['action'] == action
        assert reply['metadata']['command_router']['engine'] == 'hassil'
    assert not provider.calls


def test_hassil_keeps_asset_names_as_data_not_templates(setup):
    _, app, client, provider, _, chat, media = setup
    with app.state.session_factory.begin() as session:
        session.get(Asset, media[0]['id']).metadata_json = {'display_name': 'Forest [quiet] | river'}
    _, reply = ask(client, chat, 'Select Forest quiet river', viewer_context([item['id'] for item in media[:2]]))
    assert reply['metadata']['presentation_actions'][0]['index'] == 0
    assert not provider.calls
