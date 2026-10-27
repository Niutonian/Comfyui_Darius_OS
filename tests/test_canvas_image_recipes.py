from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from darius_api import canvas_images as im
from darius_api.database import Asset, CanvasGenerationRecord as Generation
from test_canvas import canvas_client
from test_moss_workspace import add, root
from test_media_backend import settings_for


def config(profile):
    c=im.Config(activeProfile=profile);c.drafts[profile].prompt='A blue ceramic owl. Exact lettering: "OWL".'
    if profile==im.EDIT:
        c.drafts[profile].inputs=[im.ImageInput(id='source',assetId='a',assetVersionId='a'*64)]
    return c


@pytest.mark.parametrize('profile',im.PROFILES)
def test_promoted_defaults_and_pinned_source_artifacts(tmp_path,profile):
    settings=settings_for(tmp_path);graph,manifest=im.artifacts(settings,profile)
    assert manifest['sourceUiDigest'] and manifest['promotedBindings']
    sampler=graph[manifest['sampler']]['inputs']
    assert sampler['steps']==(50 if profile==im.FLUX else 8 if profile==im.KREA else 25)
    if profile==im.FLUX:
        assert sampler['cfg']==3.5 and sampler['sampler_name']=='euler'
        assert graph['18:16']['inputs']['switch'] is True
        assert graph['18:5']['inputs']['text']=='out of frame head'
        assert not {'25','26','27'} & graph.keys()
    if profile==im.KREA:assert graph['30:16']['inputs']['thinking'] is False
    if profile==im.EDIT:assert graph['459:474']['inputs']['resolution']==0
    graph[manifest['sampler']]['inputs']['steps']=99
    assert im.artifacts(settings,profile)[0][manifest['sampler']]['inputs']['steps']!=99


@pytest.mark.parametrize('profile',im.PROFILES)
def test_prompt_identity_and_disabled_branches_are_not_loaded(tmp_path,profile):
    c=config(profile);draft=c.drafts[profile];draft.enhance=False
    g,p=im.compile_graph(settings_for(tmp_path),c,2**64-1,{'source':'pinned/source.png'})
    assert p['seed']==str(2**64-1) and g[p['sampler']]['inputs']['seed']==2**64-1
    assert not any(n['class_type']=='TextGenerate' for n in g.values())
    assert all(n['class_type']!='ComfySwitchNode' for n in g.values())
    assert p['conditioningPrompt']==draft.prompt
    assert g['darius_conditioning']['inputs']['source']==draft.prompt or profile in {im.FLUX,im.KREA}
    assert 'passport style' not in json.dumps(g) and 'martini' not in json.dumps(g)
    if profile==im.KREA:assert not any(n['class_type']=='LoraLoaderModelOnly' for n in g.values())
    if profile==im.EDIT:
        assert g['459:458']['inputs']['latent_image']==['459:474',2]
        assert g['459:474']['inputs']['images.image_1']==['darius_input_1',0]
        assert '470' not in g and '475' not in g


def test_edit_reference_tokens_and_source_size(tmp_path):
    c=config(im.EDIT);draft=c.drafts[im.EDIT]
    draft.inputs.append(im.ImageInput(id='ref',assetId='b',assetVersionId='b'*64,token=2));draft.prompt='Change <image1> using <image2>.'
    g,p=im.compile_graph(settings_for(tmp_path),c,42,{'source':'pinned/a.png','ref':'pinned/b.png'})
    assert [b['label'] for b in p['mediaTokenMap']]==['<image1>','<image2>']
    assert im.output_size(im.EDIT,draft,{'width':1360,'height':768})==(1344,768)
    draft.followSource=False;draft.preset='wide'
    g,_=im.compile_graph(settings_for(tmp_path),c,42,{'source':'pinned/a.png','ref':'pinned/b.png'})
    assert g['459:458']['inputs']['latent_image']==['459:456',0]
    assert im.output_size(im.EDIT,draft)==(1376,768)
    draft.inputs[1].token=3
    with pytest.raises(ValueError,match='gap'):im.compile_graph(settings_for(tmp_path),c,42,{'source':'a','ref':'b'})


def test_krea_enabled_style_and_enhancement_reach_real_inputs(tmp_path):
    c=config(im.KREA);d=c.drafts[im.KREA];d.styleEnabled=True;d.styleStrength=.6;d.styleText='monochrome ink wash style'
    g,p=im.compile_graph(settings_for(tmp_path),c,42,{})
    assert g['30:3']['inputs']['model']==['30:15',0]
    assert g['30:15']['inputs']['strength_model']==.6
    assert g['30:27']['inputs']['string_b']=='monochrome ink wash style'
    assert g['darius_conditioning']['inputs']['source']==['30:27',0]
    assert any(n['class_type']=='TextGenerate' for n in g.values())
    assert g['30:16']['inputs']['thinking'] is False


@pytest.mark.parametrize('profile',[im.FLUX,im.KREA,im.QWEN])
def test_input_images_cannot_be_silently_ignored_on_t2i(tmp_path,profile):
    c=config(profile);c.drafts[profile].inputs=[im.ImageInput(id='source',assetId='a',assetVersionId='a'*64)]
    with pytest.raises(ValueError,match='Only the Qwen Edit'):im.compile_graph(settings_for(tmp_path),c,42,{'source':'a'})


def test_image_recipe_drafts_duplicate_and_project_scoping(canvas_client):
    client,app,project,launches=canvas_client
    c=config(im.FLUX);b=add(client,project,settings={'adapterVersion':im.FLUX,'image':c.model_dump()})
    settings=deepcopy(b['settings']);settings['adapterVersion']=im.EDIT;settings['image']['activeProfile']=im.EDIT;settings['image']['drafts'][im.EDIT]['prompt']='Edit draft'
    r=client.post(root(project)+'/boards/'+b['id'],json={'revision':b['revision'],'settings':settings});assert r.status_code==200,r.text
    saved=r.json();copy=add(client,project,duplicateBoardId=b['id']);assert copy['settings']==saved['settings'] and copy['id']!=b['id']
    assert copy['settings']['image']['drafts'][im.FLUX]['prompt']==c.drafts[im.FLUX].prompt
    assert not launches
    settings['image']['drafts'][im.EDIT]['inputs']=[{'id':'bad','assetId':'not-owned','assetVersionId':'a'*64}]
    r=client.post(root(project)+'/boards/'+b['id'],json={'revision':saved['revision'],'settings':settings});assert r.status_code==422


def test_image_job_retry_and_late_mode_change_keep_original_snapshot(canvas_client,monkeypatch):
    monkeypatch.setattr(im,'readiness',lambda *args,**kwargs:{'ready':True,'issues':[]})
    client,app,project,launches=canvas_client
    c=config(im.FLUX);c.drafts[im.FLUX].enhance=False
    b=add(client,project,settings={'adapterVersion':im.FLUX,'image':c.model_dump()})
    url=f"/api/v1/projects/{project}/canvases/{b['documentId']}/generate"
    payload={'revision':1,'boardRevision':1,'boardId':b['id'],'profileId':im.FLUX,'idempotencyKey':'recipe-job-snapshot','seed':str(2**64-1),'approved':True}
    r=client.post(url,json=payload);assert r.status_code==200,r.text;first=r.json()
    updated=deepcopy(b['settings']);updated['adapterVersion']=im.KREA;updated['image']['activeProfile']=im.KREA
    assert client.post(root(project)+'/boards/'+b['id'],json={'revision':1,'settings':updated}).status_code==200
    r=client.post(url,json=payload);assert r.status_code==200 and r.json()['id']==first['id']
    assert len(launches)==1 and first['seed']==str(2**64-1)
    with app.state.session_factory() as session:
        g=session.get(Generation,first['id']);assert g.provenance_json['profileId']==im.FLUX
        assert g.provenance_json['imageConfig']['drafts'][im.FLUX]['prompt']==c.drafts[im.FLUX].prompt


def test_disconnected_regions_are_not_advertised_as_conditioning(tmp_path):
    c=config(im.FLUX)
    with pytest.raises(ValueError,match='does not accept drawn regions'):
        im.compile_graph(settings_for(tmp_path),c,42,{},content={'regions':[{'id':'region'}]})


def test_edit_chat_command_targets_the_existing_board_without_rewriting():
    from darius_api.moss_workspace import chat_command
    assert chat_command("Please generate edit")
    assert chat_command("Generate image")
    assert not chat_command("Generate an image of a different subject")
