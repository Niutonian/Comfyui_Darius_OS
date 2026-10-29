from copy import deepcopy
from pathlib import Path
import json
import hashlib

import pytest
from sqlalchemy import select
from pydantic import ValidationError

from darius_api import canvas_h3 as h3
from darius_api.database import Asset, Job, CanvasGenerationRecord as Generation
from darius_api.moss_workspace import BoardSettings
from test_canvas import canvas_client
from test_moss_workspace import add, root
from test_media_backend import settings_for


def config(mode="animate-image", count=1):
 c=h3.VideoConfig(activeMode=mode)
 c.modeDrafts[mode].prompt='A blue bowl. Exact dialogue: "Hello". No music.'
 c.modeDrafts[mode].inputs=[h3.MediaBinding(id=f'ref{i}',assetId=f'asset{i}',assetVersionId='a'*64,token=i+1) for i in range(count)]
 return c

@pytest.mark.parametrize('mode',h3.MODES)
def test_faithful_graph_bindings_and_audio_paths(tmp_path,mode):
 c=config(mode,3 if mode=='reference-video' else 1)
 c.modeDrafts[mode].camera='Slow dolly in'
 c.modeDrafts[mode].audio='Soft room tone'
 g,p=h3.compile_graph(settings_for(tmp_path),c,2**64-1,{i.id:f'pinned/{i.id}.png' for i in c.modeDrafts[mode].inputs})
 assert p['seed']==str(2**64-1) and 'Hello' in p['conditioningPrompt']
 assert p['timing']['frames']==(124 if mode=='camera-direction' else 243)
 assert all('__DARIUS' not in str(n['inputs']) for n in g.values())
 assert h3.artifacts(settings_for(tmp_path),p['profileId'])[1]['templateDigest']==h3.PINS[p['profileId']]
 if mode=='animate-image':
  assert g['8']['inputs']['model']==['34',0]
  assert g['native_decode']['inputs']['samples']==['26',1]
  assert g['36']['inputs']['audio']==['2',0]
  assert 'last_frame' not in g['16']['inputs']
 elif mode=='camera-direction':
  assert g['105:126']['inputs']['value'] is True
  assert g['105:125']['inputs']['value']==8
  assert g['105:104']['inputs']['prompt']==['193',0]
  assert g['105:10']['inputs']['samples']==['105:14',0]
  assert g['105:91']['inputs']['fps']==24
  assert '127' not in g
 else:
  assert g['289']['inputs']['step']==8 and g['261']['inputs']['steps']==12
  assert g['226']['inputs']['sigmas']==['289',0] and g['144']['inputs']['sigmas']==['289',1]
  assert g['142']['inputs']['audio_latent']==['139',1]
  assert list(p['outputs'])==['214','264']
  assert g['140']['inputs']['device']=='cuda' and g['140']['inputs']['precision']=='fp16'
  assert [i['label'] for i in p['mediaTokenMap']]==['Picture 1','Picture 2','Picture 3']


def test_mode_drafts_are_independent_and_template_is_immutable(tmp_path):
 c=config();original=deepcopy(c.modeDrafts['animate-image'].model_dump())
 c.activeMode='camera-direction';c.modeDrafts['camera-direction'].prompt='Different scene'
 c.activeMode='animate-image';assert c.modeDrafts[c.activeMode].model_dump()==original
 g,_=h3.compile_graph(settings_for(tmp_path),c,42,{'ref0':'x.png'});g['14']['inputs']['value']='mutated'
 assert h3.artifacts(settings_for(tmp_path),h3.ANIMATE)[0]['14']['inputs']['value']!='mutated'

@pytest.mark.parametrize('seconds,expected',[(5,124),(10,243),(5.020833333333333,124)])
def test_runtime_frame_grid(seconds,expected):
 assert h3.timing('animate-image',seconds)['frames']==expected
 assert h3.output_size('animate-image')==(1376,768)
 assert h3.output_size('reference-video')==(960,544)


def test_reference_gap_and_missing_tokens_are_not_silently_rebound(tmp_path):
 c=config('reference-video',2);c.modeDrafts[c.activeMode].inputs[1].token=3
 with pytest.raises(ValueError,match='gap'):h3.compile_graph(settings_for(tmp_path),c,1,{'ref0':'a','ref1':'b'})
 c.modeDrafts[c.activeMode].inputs[1].token=2;c.modeDrafts[c.activeMode].prompt='Use <Picture 3>'
 with pytest.raises(ValueError,match='unavailable media'):h3.compile_graph(settings_for(tmp_path),c,1,{'ref0':'a','ref1':'b'})


@pytest.mark.parametrize('mode', h3.MODES)
@pytest.mark.parametrize('preset', h3.PRESETS)
@pytest.mark.parametrize('resolution', h3.RESOLUTIONS)
def test_video_sizes_and_durations_bind_both_stages_without_changing_sources(tmp_path, mode, preset, resolution):
 c=config(mode)
 draft=c.modeDrafts[mode];draft.preset=preset;draft.resolution=resolution
 for seconds in (5, 8, 15):
  draft.seconds=seconds
  g,p=h3.compile_graph(settings_for(tmp_path),c,42,{'ref0':'pinned/image.png'})
  size=h3.video_dimensions(mode,preset,resolution)
  assert p['width']==size['width'] and p['height']==size['height']
  assert all(size[k]%32==0 for k in ('width','height','generationWidth','generationHeight'))
  assert p['timing']==h3.timing(mode,seconds)
  assert p['timing']['frames']%17==5 and p['timing']['frames']<=362
  main={'animate-image':'16','camera-direction':'105:104','reference-video':'265'}[mode]
  selector={'animate-image':'15','camera-direction':'157','reference-video':'252'}[mode]
  assert g[selector]['inputs']['aspect_ratio']==h3.PRESETS[preset][0]
  if resolution!='native':
   assert g[main]['inputs']['width']==size['generationWidth']
   assert g[main]['inputs']['height']==size['generationHeight']
  if mode=='camera-direction':assert g[main]['inputs']['length']==p['timing']['frames']
  else:assert g['20' if mode=='animate-image' else '259']['inputs']['value']==seconds
  if mode=='reference-video' and resolution!='native':
   assert g['140']['inputs']['mode']=='target dimensions'
   assert g['140']['inputs']['mode.width']==size['width']
   assert g['140']['inputs']['mode.height']==size['height']
   assert 'mode.scale' not in g['140']['inputs']
  assert h3.artifacts(settings_for(tmp_path),p['profileId'])[1]['templateDigest']==h3.PINS[p['profileId']]


@pytest.mark.parametrize('patch',[{'seconds':4},{'seconds':16},{'seconds':7.5},{'preset':'invalid'},{'resolution':'8k'}])
def test_video_controls_reject_unsupported_values(patch):
 with pytest.raises(ValidationError):h3.VideoDraft(**patch)


def test_video_engine_lists_real_final_sizes_and_all_camera_durations(canvas_client):
 client,app,project,_=canvas_client
 engine=client.get('/api/v1/canvas/video/engine').json()
 assert engine['durations']==list(range(5,16)) and engine['fps']==24
 ref=next(m for m in engine['modes'] if m['id']=='reference-video')
 assert (ref['width'],ref['height'])==(1440,832)
 camera=next(m for m in engine['modes'] if m['id']=='camera-direction')
 assert len(camera['timings'])==11 and camera['timings'][-1]['frames']==362
 cfg=config('reference-video',0)
 cfg.modeDrafts['reference-video'].preset='vertical'
 cfg.modeDrafts['reference-video'].resolution='720p'
 cfg.modeDrafts['reference-video'].seconds=12
 b=add(client,project,settings={'adapterVersion':'minimax-h3-reference-video-v1','video':cfg.model_dump()})
 assert b['artboard']=={'width':736,'height':1280,'preset':'vertical'}
 copy=add(client,project,duplicateBoardId=b['id'])
 assert copy['settings']==b['settings'] and copy['artboard']==b['artboard']


def test_legacy_camera_length_is_preserved_without_overwriting_saved_data(canvas_client):
 from darius_api.database import MossBoardRecord as Board
 client,app,project,_=canvas_client
 c=config('camera-direction',0)
 b=add(client,project,settings={'adapterVersion':'minimax-h3-camera-direction-v1','video':c.model_dump()})
 legacy=c.model_dump()
 for draft in legacy['modeDrafts'].values():draft.pop('preset');draft.pop('resolution')
 legacy['modeDrafts']['camera-direction']['seconds']=10
 with app.state.session_factory.begin() as session:
  row=session.get(Board,b['id']);row.settings_json={**row.settings_json,'video':legacy}
 read=next(row for row in client.get(root(project)).json()['boards'] if row['id']==b['id'])
 assert read['settings']['video']['modeDrafts']['camera-direction']['seconds']==5
 with app.state.session_factory() as session:
  assert session.get(Board,b['id']).settings_json['video']['modeDrafts']['camera-direction']['seconds']==10
 settings=deepcopy(read['settings']);settings['video']['modeDrafts']['camera-direction']['seconds']=10
 saved=client.post(root(project)+'/boards/'+b['id'],json={'revision':b['revision'],'settings':settings})
 assert saved.status_code==200,saved.text
 assert saved.json()['settings']['video']['modeDrafts']['camera-direction']['seconds']==10


def test_board_mode_save_duplicate_and_cross_project_media(canvas_client):
 client,app,project,launches=canvas_client
 c=config();binding=c.modeDrafts[c.activeMode].inputs[0]
 with app.state.session_factory.begin() as session:
  session.add(Asset(id=binding.assetId,project_id=project,kind='image',role='upload',path='/test.png',content_hash='a'*64,mime_type='image/png',provider='upload'))
 b=add(client,project,settings={'adapterVersion':h3.ANIMATE,'video':c.model_dump()})
 settings=deepcopy(b['settings']);settings['video']['activeMode']='camera-direction';settings['adapterVersion']='minimax-h3-camera-direction-v1'
 r=client.post(root(project)+'/boards/'+b['id'],json={'revision':b['revision'],'settings':settings});assert r.status_code==200,r.text
 saved=r.json();assert saved['settings']['video']['modeDrafts']['animate-image']['inputs'][0]['assetId']==binding.assetId
 copy=add(client,project,duplicateBoardId=b['id']);assert copy['settings']==saved['settings'] and copy['id']!=b['id']
 assert not launches
 settings['video']['modeDrafts']['animate-image']['inputs'][0]['assetVersionId']='b'*64
 r=client.post(root(project)+'/boards/'+b['id'],json={'revision':saved['revision'],'settings':settings});assert r.status_code==422


def test_video_queue_snapshot_and_retry_are_immutable(tmp_path,monkeypatch,canvas_client):
 monkeypatch.setattr(h3,'readiness',lambda *a,**k:{'ready':True,'issues':[]})
 monkeypatch.setattr(h3,'upload_inputs',lambda *a,**k:({'ref0':'pinned/test.png'},[{'id':'ref0','assetId':'asset0','sourceHash':'a'*64}]))
 client,app,project,launches=canvas_client
 c=config()
 with app.state.session_factory.begin() as session:
  p=tmp_path/'image.png';p.write_bytes(b'not-rendered');session.add(Asset(id='asset0',project_id=project,kind='image',role='upload',path=str(p),content_hash='a'*64,mime_type='image/png',provider='upload'))
 b=add(client,project,settings={'adapterVersion':h3.ANIMATE,'video':c.model_dump()});url=f"/api/v1/projects/{project}/canvases/{b['documentId']}/generate"
 payload={'revision':1,'boardRevision':b['revision'],'boardId':b['id'],'profileId':h3.ANIMATE,'idempotencyKey':'h3-immutable-test','seed':str(2**64-1),'approved':True}
 r=client.post(url,json=payload);assert r.status_code==200,r.text
 first=r.json();assert first['seed']==str(2**64-1)
 settings=deepcopy(b['settings']);settings['video']['activeMode']='camera-direction';settings['adapterVersion']='minimax-h3-camera-direction-v1'
 assert client.post(root(project)+'/boards/'+b['id'],json={'revision':b['revision'],'settings':settings}).status_code==200
 repeated=client.post(url,json=payload);assert repeated.status_code==200 and repeated.json()['id']==first['id']
 assert len(launches)==1
 with app.state.session_factory() as session:
  generation=session.get(Generation,first['id']);assert generation.provenance_json['mode']=='animate-image'
  job=session.get(Job,first['jobId']);assert job.input_payload['canvas_board_id']==b['id']
  assert len(list(session.scalars(select(Generation))))==1


@pytest.mark.parametrize('change', ['unchanged', 'edited-draft', 'manual-selection', 'newer-request'])
def test_completed_video_displays_without_replacing_a_draft_or_explicit_choice(canvas_client, change):
 from datetime import timedelta
 from darius_api.canvas_api import completed
 from darius_api.database import CanvasDocumentRecord as Document, CanvasRevisionRecord as Revision, MossBoardRecord as Board, utcnow
 client, app, project, _ = canvas_client
 cfg = config('reference-video', 0)
 board = add(client, project, settings={'adapterVersion':'minimax-h3-reference-video-v1','video':cfg.model_dump()})
 with app.state.session_factory.begin() as session:
  doc = session.get(Document, board['documentId'])
  def run(key, offset=0, status='completed'):
   ids = [key+'-final', key+'-intermediate'] if status == 'completed' else []
   job = Job(id=key+'-job', project_id=project, job_type='generation', provider='local-comfyui', status=status,
             input_payload={'canvas_generation_id':key}, output_asset_ids=ids)
   session.add(job);session.flush()
   for aid in ids:
    session.add(Asset(id=aid,project_id=project,kind='video',role='generation',path=f'/mock/{aid}.mp4',content_hash='a'*64,
       duration=5,mime_type='video/mp4',provider='local-comfyui',workflow_run_id=job.id,
       metadata_json={'ffprobe':{'streams':[{'codec_type':'video'},{'codec_type':'audio'}]}}))
   generation = Generation(id=key,document_id=doc.id,project_id=project,revision=1,selection_version=0,
       seed=42,job_id=job.id,idempotency_key=key,created_at=utcnow()+timedelta(seconds=offset),
       provenance_json={'profileId':'minimax-h3-reference-video-v1','mode':'reference-video','outputs':{'214':'final','264':'intermediate'},
                        'board':{'boardId':board['id'],'boardRevision':1}})
   session.add(generation);session.flush()
   return job, generation
  job, generation = run('video-result')
  if change == 'edited-draft':
   original = session.get(Revision,(doc.id,1)).content_json
   session.add(Revision(document_id=doc.id,revision=2,content_json={**original,'globalPrompt':'A newer draft kept for later'}))
   doc.revision = 2
   row = session.get(Board,board['id']);row.revision = 2
   settings = deepcopy(row.settings_json);settings['video']['activeMode']='camera-direction'
   settings['adapterVersion']='minimax-h3-camera-direction-v1';row.settings_json=settings
  elif change == 'manual-selection':
   _, chosen = run('chosen-result',-60)
   doc.active_generation_id=chosen.id;doc.selection_version=1
  elif change == 'newer-request':
   run('later-request',60,'queued')
  completed(session,job,{})
  expected = 'chosen-result' if change == 'manual-selection' else None if change == 'newer-request' else generation.id
  assert doc.active_generation_id == expected
  assert doc.revision == (2 if change == 'edited-draft' else 1)
  if change == 'edited-draft':
   assert session.get(Board,board['id']).settings_json['video']['activeMode'] == 'camera-direction'
   assert session.get(Revision,(doc.id,2)).content_json['globalPrompt']=='A newer draft kept for later'
 workspace=client.get(root(project)).json()
 displayed=next(b for b in workspace['boards'] if b['id']==board['id'])['activeResult']
 if change in {'unchanged','edited-draft'}:
  assert displayed['assetIds']==['video-result-final','video-result-intermediate']


def test_cpu_final_upscaler_changes_only_device_and_keeps_original_recipe(tmp_path):
 original=config('reference-video',1)
 source=deepcopy(original)
 before, _=h3.compile_graph(settings_for(tmp_path),original,42,{'ref0':'pinned.png'})
 original.modeDrafts['reference-video'].upscaleDevice='cpu'
 after, provenance=h3.compile_graph(settings_for(tmp_path),original,42,{'ref0':'pinned.png'})
 assert before['140']['inputs']['device']=='cuda'
 assert after['140']['inputs']['device']=='cpu'
 after['140']['inputs']['device']='cuda'
 assert after==before
 assert provenance['videoConfig']['modeDrafts']['reference-video']['upscaleDevice']=='cpu'
 assert source.modeDrafts['reference-video'].upscaleDevice=='cuda'
 assert h3.failure_recovery('MinimaxH3LatentUpscaler3D: Allocation on device', True)['message']=='Preview saved; final upscale ran out of GPU memory.'
 assert not h3.failure_recovery('upscale failed', True)['canResumeFinalOnly']
 with pytest.raises(ValidationError): h3.VideoDraft(upscaleDevice='auto')


def test_failed_upscale_retains_playable_intermediate_without_replacing_final(canvas_client, tmp_path, monkeypatch):
 from types import SimpleNamespace
 from datetime import timedelta
 from darius_api.database import CanvasDocumentRecord as Document, utcnow
 from darius_api.providers import PartialVideoError
 client, app, project, _=canvas_client
 board=add(client,project,'Video',settings={'adapterVersion':'minimax-h3-reference-video-v1','video':config('reference-video',0).model_dump()})
 media=tmp_path/'preview.mp4';media.write_bytes(b'fixture video')
 monkeypatch.setattr('darius_api.media.ingest_generated',lambda *args: SimpleNamespace(kind='video',duration=5,path=media,content_hash='a'*64,mime_type='video/mp4',width=640,height=360,fps=24,sample_rate=48000,metadata={}))
 with app.state.session_factory.begin() as session:
  session.add(Asset(id='previous-final',project_id=project,kind='video',role='generation',path=str(tmp_path/'final.mp4'),content_hash='b'*64,mime_type='video/mp4',provider='fixture'))
  previous=Job(id='previous-video-job',project_id=project,provider='local-comfyui',status='completed',input_payload={},output_asset_ids=['previous-final'])
  failed=Job(id='failed-video-job',project_id=project,provider='local-comfyui',status='failed',error_detail='MinimaxH3LatentUpscaler3D: Allocation on device',input_payload={'canvas_generation_id':'failed-generation'})
  session.add_all([previous,failed]);session.flush()
  older=Generation(id='previous-generation',document_id=board['documentId'],project_id=project,revision=1,job_id=previous.id,idempotency_key='previous-key',seed='42',selection_version=0,provenance_json={'profileId':'minimax-h3-reference-video-v1'},created_at=utcnow()-timedelta(minutes=1))
  generation=Generation(id='failed-generation',document_id=board['documentId'],project_id=project,revision=1,job_id=failed.id,idempotency_key='failed-key',seed='42',selection_version=0,provenance_json={'profileId':'minimax-h3-reference-video-v1','mediaReceipts':[],'videoConfig':config('reference-video',0).model_dump()})
  session.add_all([older,generation]);session.flush()
  session.get(Document,board['documentId']).active_generation_id=older.id
  h3.retain_intermediate(session,app.state.settings,failed,PartialVideoError(failed.error_detail,[media],'comfy-fixture'))
 document=client.get(f"/api/v1/projects/{project}/canvases/{board['documentId']}").json()
 assert document['activeGenerationId']=='previous-generation'
 assert document['generations'][0]['provenance']['recovery']['outOfMemory']
 assert document['generations'][0]['assetIds']
 latest=client.get(root(project)).json()['boards'][0]
 assert latest['activeResult']['assetIds']==['previous-final']
 assert latest['latest']['intermediateAssetIds'] and latest['latest']['recovery']['stage']=='upscale'
