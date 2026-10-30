from copy import deepcopy
import pytest
from darius_api import canvas_h3 as h3
from darius_api.database import Asset
from test_canvas_body_swap import config as short_config
from test_media_backend import settings_for
from test_canvas import canvas_client
from test_moss_workspace import add


def config():
    current=h3.VideoConfig(activeMode='body-swap-sequential')
    current.modeDrafts['body-swap-sequential'].inputs=short_config().modeDrafts['body-swap'].inputs
    return current


@pytest.mark.parametrize('duration',[0,60.5,3600])
def test_sequential_graph_binds_long_interval_and_uint64_seed_without_changing_recipe(tmp_path,duration):
    current=config();draft=current.modeDrafts[current.activeMode]
    draft.totalDuration=duration;draft.clipStart=2.5;draft.chunkSeconds=1.7;draft.swapLongEdge=1920
    settings=settings_for(tmp_path)
    original=deepcopy(h3.artifacts(settings,h3.BODY_SWAP_SEQUENTIAL)[0])
    graph,receipt=h3.compile_graph(settings,current,2**64-1,{'character':'pinned/image.png','source':'pinned/video.mp4'})
    assert graph['1']['inputs']['file']=='pinned/video.mp4'
    assert graph['3']['inputs']['image']=='pinned/image.png'
    assert graph['31']['inputs']=={'preset':'H3 (1920)','custom_long_edge':1920,'video':['1',0]}
    assert graph['32']['inputs']['total_duration_seconds']==duration
    assert graph['32']['inputs']['start_seconds']==2.5 and graph['32']['inputs']['chunk_seconds']==1.7
    assert graph['32']['inputs']['seed']==2**64-1
    assert graph['28']['inputs']['seed']==(2**64-1)%2**31
    for key in ('overlap_frames','carry_previous_frames','seed_mode','steps','sampler_name','scheduler','seam_method','seam_blend_frames','refresh_chunks','video','reference','model','clip','vae','prompt'):
        assert graph['32']['inputs'][key]==original['32']['inputs'][key]
    assert {k:v for k,v in graph.items() if k not in {'1','3','27','28','31','32','33'}}=={k:v for k,v in original.items() if k not in {'1','3','27','28','31','32','33'}}
    assert receipt['outputs']=={'33':'final'} and receipt['seedSlot']=='32.seed'
    assert receipt['timing']['allRemaining'] is (duration==0)
    assert receipt['timing']['frames'] is None
    assert h3.artifacts(settings,h3.BODY_SWAP_SEQUENTIAL)[0]==original


def test_existing_drafts_gain_independent_sequential_defaults():
    old=short_config().model_dump();old['modeDrafts'].pop('body-swap-sequential')
    current=h3.VideoConfig.model_validate(old)
    draft=current.modeDrafts['body-swap-sequential']
    assert draft.totalDuration==0 and draft.chunkSeconds==3.1 and draft.swapLongEdge==640
    assert draft.inputs==[]
    assert current.modeDrafts['body-swap'].model_dump()==old['modeDrafts']['body-swap']
    assert h3.timing('body-swap',5)['frames']==107


@pytest.mark.parametrize('field,value',[('totalDuration',-1),('totalDuration',float('inf')),('chunkSeconds',.9),('chunkSeconds',5.1)])
def test_invalid_sequential_controls_rejected(field,value):
    payload=config().model_dump();payload['modeDrafts']['body-swap-sequential'][field]=value
    with pytest.raises(ValueError):h3.VideoConfig.model_validate(payload)


def test_sequential_requires_exact_project_video_and_valid_interval(tmp_path):
    current=config()
    assets={'image':Asset(id='image',project_id='p',kind='image',content_hash='a'*64),
            'video':Asset(id='video',project_id='p',kind='video',content_hash='b'*64,duration=180)}
    class Session:
        def get(self,cls,key):return assets.get(key)
    h3.validate_inputs(Session(),'p',current)
    assets['video'].project_id='other'
    with pytest.raises(ValueError):h3.validate_inputs(Session(),'p',current)
    assets['video'].project_id='p';current.modeDrafts[current.activeMode].clipStart=180
    with pytest.raises(ValueError):h3.validate_inputs(Session(),'p',current)
    current.modeDrafts[current.activeMode].clipStart=0;current.modeDrafts[current.activeMode].totalDuration=.1
    with pytest.raises(ValueError,match='five frames'):
        h3.compile_graph(settings_for(tmp_path),current,1,{'character':'image.png','source':'video.mp4'})


def test_sequential_board_engine_and_duplicate_preserve_long_duration(canvas_client):
    client,app,project,_=canvas_client
    current=config();current.modeDrafts[current.activeMode].inputs=[]
    current.modeDrafts[current.activeMode].totalDuration=180.5
    board=add(client,project,settings={'adapterVersion':h3.BODY_SWAP_SEQUENTIAL,'video':current.model_dump()})
    duplicate=add(client,project,duplicateBoardId=board['id'])
    assert duplicate['settings']==board['settings']
    mode=next(m for m in client.get('/api/v1/canvas/video/engine').json()['modes'] if m['id']=='body-swap-sequential')
    assert mode['sequential'] and mode['allRemainingSource'] and mode['referenceVideo']
    assert mode['durations']==[] and mode['timings']==[]
