"""Run with .venv-pipecat/Scripts/python.exe -m pytest tests/test_pipecat_voice.py."""
import asyncio
import json
from types import SimpleNamespace

import pytest
pytest.importorskip('pipecat')
import numpy as np
from apps.voice.pipecat_server import Session, CpuSpeech, SocketAudio, SpeakFrame, app
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker, PipelineParams
from pipecat.workers.runner import WorkerRunner
from pipecat.frames.frames import InterruptionFrame


class Socket:
    def __init__(self):
        self.events = []; self.done = asyncio.Event()
    async def send_json(self, event):
        self.events.append(event)
        if event['type'] == 'audio_done': self.done.set()


class Worker:
    def __init__(self): self.frames = []
    async def queue_frame(self, frame): self.frames.append(frame)


def test_reply_text_is_bound_to_the_current_utterance_and_never_replays():
    async def run():
        session = Session(Socket(), SimpleNamespace())
        session.worker = Worker(); session.turn_id = 'current'
        await session.command({'type': 'reply_chunk', 'turn_id': 'old', 'text': 'Old result'})
        assert not session.worker.frames
        await session.command({'type': 'reply_chunk', 'turn_id': 'current', 'text': 'A current result.'})
        assert session.worker.frames[-1].text == 'A current result.'
        await session.interrupt()
        assert isinstance(session.worker.frames[-1], InterruptionFrame)
        await session.command({'type': 'reply_chunk', 'turn_id': 'current', 'text': 'Late result'})
        assert len(session.worker.frames) == 2
    asyncio.run(run())


def test_reply_completion_cannot_be_queued_repeatedly():
    async def run():
        session = Session(Socket(), SimpleNamespace()); session.worker = Worker(); session.turn_id = 'current'
        await session.command({'type': 'reply_end', 'turn_id': 'current'})
        await session.command({'type': 'reply_end', 'turn_id': 'current'})
        await session.command({'type': 'reply_chunk', 'turn_id': 'current', 'text': 'Too late'})
        assert len(session.worker.frames) == 1
    asyncio.run(run())


def test_invalid_commands_and_voice_text_are_bounded():
    async def run():
        session = Session(Socket(), SimpleNamespace()); session.worker = Worker(); session.turn_id = 'current'
        for value in ({'type': 'execute_workflow'}, {'type': 'reply_chunk', 'turn_id': 'current', 'text': 'x' * 4001}, {'type': 'configure', 'mode': 'anything'}):
            with pytest.raises(ValueError): await session.command(value)
        await session.command({'type': 'reply_chunk', 'turn_id': 'current', 'text': 'x' * 4000})
        assert len(session.worker.frames[-1].text) == 1200
        await session.command({'type': 'configure', 'voice': 'not-an-installed-voice'})
        assert session.voice == 'af_heart'
    asyncio.run(run())


def test_pipecat_pipeline_streams_pcm_then_completion_and_cleans_up():
    class Kokoro:
        async def create_stream(self, *_args, **_kwargs):
            for _ in range(3):
                yield np.zeros(2400, dtype=np.float32), 24000
                await asyncio.sleep(0)
    async def run():
        socket = Socket()
        resources = SimpleNamespace(kokoro=Kokoro(), tts_lock=asyncio.Lock(), last_metrics={})
        session = Session(socket, resources); session.turn_id = 'current'
        worker = PipelineWorker(Pipeline([CpuSpeech(session), SocketAudio(session)]), params=PipelineParams(), enable_rtvi=False, enable_turn_tracking=False, idle_timeout_secs=None)
        runner = WorkerRunner(handle_sigint=False, check_dangling_tasks=False)
        await runner.add_workers(worker)
        job = asyncio.create_task(runner.run())
        try:
            await worker.queue_frame(SpeakFrame('current', 'A verified reply.'))
            await worker.queue_frame(SpeakFrame('current', final=True))
            await asyncio.wait_for(socket.done.wait(), 8)
            assert [event['type'] for event in socket.events].count('audio') == 3
            assert socket.events[-1] == {'type': 'audio_done', 'turn_id': 'current'}
            assert all(event['turn_id'] == 'current' for event in socket.events)
        finally:
            await worker.cancel()
            await asyncio.wait_for(job, 5)
    asyncio.run(run())


def test_untrusted_web_origin_cannot_connect():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/listen', headers={'origin': 'https://untrusted.example'}): pass


def test_echo_is_not_sent_to_darius_again():
    async def run():
        socket = Socket()
        session = Session(socket, SimpleNamespace(transcribe=lambda _: 'Your harbour image is ready'))
        session.spoken = 'Your harbour image is ready.'
        await session.finalize(b'fake pcm')
        assert not any(event['type'] == 'final' for event in socket.events)
        assert socket.events[-1]['type'] == 'listening'
    asyncio.run(run())


def test_speech_during_final_transcription_is_buffered_not_dropped():
    async def run():
        session = Session(Socket(), SimpleNamespace())
        session.asr_task = asyncio.create_task(asyncio.sleep(30))
        try:
            await session.feed(b'\0\0' * 1024)
            assert session.after_asr == b'\0\0' * 1024
        finally:
            session.asr_task.cancel()
            with pytest.raises(asyncio.CancelledError): await session.asr_task
    asyncio.run(run())
