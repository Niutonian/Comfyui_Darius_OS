from copy import deepcopy
import pytest
from darius_api import canvas_h3 as h3
from darius_api.database import Asset
from darius_api.moss_workspace import BoardSettings
from test_media_backend import settings_for
from test_canvas import canvas_client
from test_moss_workspace import add


def config():
    c=h3.VideoConfig(activeMode='body-swap')
    c.modeDrafts['body-swap'].inputs=[
        h3.MediaBinding(id='character',assetId='image',assetVersionId='a'*64,mediaKind='image',role='replacement-character',token=1),
        h3.MediaBinding(id='source',assetId='video',assetVersionId='b'*64,mediaKind='video',role='source-video',token=2)]
    return c


def test_body_swap_preserves_tested_wiring_and_pins_inputs(tmp_path):
    c=config();d=c.modeDrafts['body-swap'];d.clipStart=7.5;d.swapLongEdge=640;d.visionModel='installed/vision:9b'
    settings=settings_for(tmp_path)
    baseline=deepcopy(h3.artifacts(settings,h3.BODY_SWAP)[0])
    g,p=h3.compile_graph(settings,c,2**64-1,{'character':'pinned/char.png','source':'pinned/source.mp4'})
    assert g['1']['inputs']['file']=='pinned/source.mp4'
    assert g['3']['inputs']['image']=='pinned/char.png'
    assert g['32']['inputs']['start_seconds']==7.5 and g['32']['inputs']['duration_seconds']==5
    assert g['31']['inputs']['preset']=='Balanced (640)'
    assert g['8']['inputs']['length']==['32',1]
    assert g['24']['inputs']['audio']==['2',1]
    assert g['20']['inputs']['noise_seed']==2**64-1
    assert g['28']['inputs']['seed']==(2**64-1) % 2**31
    assert g['27']['inputs']['model']=='installed/vision:9b'
    assert g['27']['inputs']['base_url']==settings.ollama_base_url
    assert p['outputs']=={'25':'final','26':'source'}
    assert p['timing']['frames']==107 and p['capability']=='video-to-video'
    assert h3.artifacts(settings,h3.BODY_SWAP)[0]==baseline


@pytest.mark.parametrize('change',['no-video','two-images','long'])
def test_body_swap_rejects_invalid_inputs_before_queue(tmp_path,change):
    c=config();d=c.modeDrafts['body-swap']
    if change=='no-video':d.inputs.pop()
    elif change=='two-images':d.inputs[1].mediaKind='image'
    else:d.seconds=10
    with pytest.raises(ValueError):h3.compile_graph(settings_for(tmp_path),c,1,{'character':'a','source':'b'})


def test_body_swap_enforces_project_and_exact_video_version():
    c=config();assets={'image':Asset(id='image',project_id='p',kind='image',content_hash='a'*64),
                        'video':Asset(id='video',project_id='other',kind='video',content_hash='b'*64,duration=4.5)}
    class Session:
        def get(self,cls,key):return assets.get(key)
    with pytest.raises(ValueError):h3.validate_inputs(Session(),'p',c)
    assets['video'].project_id='p';h3.validate_inputs(Session(),'p',c)
    c.modeDrafts['body-swap'].clipStart=4.4
    with pytest.raises(ValueError,match='five frames'):h3.validate_inputs(Session(),'p',c)


def test_existing_drafts_gain_body_swap_without_changing_other_modes():
    old=h3.VideoConfig().model_dump();old['modeDrafts'].pop('body-swap')
    current=h3.VideoConfig.model_validate(old)
    assert current.modeDrafts['body-swap'].seconds==5
    assert current.modeDrafts['animate-image'].model_dump()==old['modeDrafts']['animate-image']


def test_body_swap_board_round_trip_and_engine_limit(canvas_client):
    client,app,project,_=canvas_client
    b=add(client,project,settings={'adapterVersion':h3.BODY_SWAP})
    assert b['settings']['video']['activeMode']=='body-swap'
    assert b['settings']['video']['modeDrafts']['body-swap']['seconds']==5
    engine=client.get('/api/v1/canvas/video/engine').json()
    mode=next(m for m in engine['modes'] if m['id']=='body-swap')
    assert mode['durations']==[5] and mode['referenceVideo'] is True
    assert mode['timings'][0]['frames']==107 and mode['followsSource'] is True
