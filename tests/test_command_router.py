from types import SimpleNamespace
import tomllib

import pytest

from darius_api import command_router as router


@pytest.fixture(autouse=True)
def clear_decision_cache():
    router._recognize.cache_clear()
    yield
    router._recognize.cache_clear()


@pytest.mark.parametrize('text, expected', [
    ('Hey Darius, could you please bring up my video gallery?', {'action': 'gallery', 'kind': 'video'}),
    ('Browse our photo gallery', {'action': 'gallery', 'kind': 'image'}),
    ('Show me the gallery of clips', {'action': 'gallery', 'kind': 'video'}),
    ('Display the gallery', {'action': 'gallery', 'kind': None}),
    ('Could you show the next picture please?', {'action': 'next'}),
    ('Go to the preceding video', {'action': 'previous'}),
    ('Choose the 21st picture', {'action': 'select', 'index': 20, 'autoplay': False}),
    ('Open item forty-two', {'action': 'select', 'index': 41, 'autoplay': False}),
    ('Open the ninety ninth image', {'action': 'select', 'index': 98}),
    ('Open video number three fullscreen and play it', {'action': 'select', 'index': 2, 'autoplay': True}),
    ('Resume the current video', {'action': 'play', 'bare': False}),
    ('Continue playing the video', {'action': 'play', 'bare': False}),
    ('Start playing it', {'action': 'play', 'bare': False}),
    ('Stop playing the video', {'action': 'stop', 'bare': False}),
    ('Start over', {'action': 'restart', 'bare': True}),
    ('Jump ahead by fifteen seconds', {'action': 'seek', 'seconds': 15}),
    ('Go back thirty seconds', {'action': 'seek', 'seconds': -30}),
    ('Rewind the video by twenty seconds', {'action': 'seek', 'seconds': -20}),
    ('Fast forward the video five seconds', {'action': 'seek', 'seconds': 5}),
    ('Select the photo named Forest opening', {'action': 'select_name', 'name': 'Forest opening'}),
    ('Enlarge the latest image', {'action': 'open', 'target': 'the latest image'}),
    ('Zoom in on this image', {'action': 'open', 'target': 'this image'}),
])
def test_hassil_maps_variations_to_typed_existing_commands(text, expected):
    result = router.route_command(text)
    assert result and result['engine'] == 'hassil'
    assert all(result[key] == value for key, value in expected.items()), result


@pytest.mark.parametrize('text', [
    "Don't open the gallery", 'Do not pause the video', 'Never open image three',
    'Open image three but not fullscreen', 'Show me how to open the gallery',
    'Why did the video stop?', 'Generate a video and play it',
    'Open the gallery then delete all images', 'Open the video and edit the image',
    'Select the image and generate a new one', 'Open an image instead of that video',
    'Open the settings', 'Close the session', 'Delete video three',
    'Create an image of a forest', 'Tell me a story about a gallery',
    'Please explain image generation', 'Open https://example.com',
    'Open C:/test-files/movie.mp4', 'Select the image named Generate a video',
    'Can you not open it full size?',
])
def test_non_commands_negation_generation_and_compounds_never_become_actions(text):
    assert router.route_command(text) is None


def test_routes_are_bounded_and_callers_cannot_poison_cached_commands():
    assert router.route_command(None) is None
    assert router.route_command('') is None
    assert router.route_command('Open the gallery ' + 'x' * 350) is None
    first = router.route_command('Open the gallery')
    first['action'] = 'delete'
    assert router.route_command('Open the gallery')['action'] == 'gallery'
    assert router._recognize.cache_info().maxsize == 512


def fake_match(action):
    return SimpleNamespace(intent=SimpleNamespace(name='Playback'), entities={'playback': SimpleNamespace(value=action)})


def test_conflicting_matches_ask_for_clarification(monkeypatch):
    monkeypatch.setattr(router, 'recognize_all', lambda *a, **kw: iter([fake_match('play'), fake_match('pause')]))
    assert router.route_command('Play the video')['action'] == 'clarify'


def test_excessive_match_count_does_not_silently_pick_the_first_action(monkeypatch):
    monkeypatch.setattr(router, 'recognize_all', lambda *a, **kw: iter([fake_match('play')] * 65))
    assert router.route_command('Play the video')['action'] == 'clarify'


def test_catalogue_is_packaged_and_dependency_is_pinned():
    settings = tomllib.loads((router.CATALOG_PATH.parents[4] / 'pyproject.toml').read_text(encoding='utf-8'))
    assert f'hassil=={router.ENGINE_VERSION}' in settings['project']['dependencies']
    assert 'command_intents/*.yaml' in settings['tool']['setuptools']['package-data']['darius_api']
    assert router.catalog().language == 'en'
    assert len(router.catalog().intents) >= 10
