"""Optional CPU Pipecat audio sidecar. Darius remains the only model/tool executor.

The browser relays its verified Darius reply over the same session. This service
never receives model credentials, project assets, or authority to launch a job.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import io
import wave
from uuid import uuid4

os.environ.setdefault('LOGURU_LEVEL', 'INFO')
os.environ.setdefault('PIPECAT_SMART_TURN_LOG_DATA', '0')
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState
from pipecat.frames.frames import DataFrame, Frame, InterruptionFrame, TTSAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker, PipelineParams
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.workers.runner import WorkerRunner

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / 'data' / 'models'
from apps.voice.origins import voice_origins
ORIGINS = voice_origins(ROOT)
VOICES = {'af_heart', 'af_bella', 'af_nicole', 'am_adam', 'am_michael', 'bf_emma', 'bm_george'}
log = logging.getLogger('darius.pipecat')


class Runtime:
    def __init__(self):
        self.kokoro = self.vosk = self.whisper = None
        self.error = ''
        self.loaded = False
        self.asr_lock = threading.Lock()
        self.tts_lock = asyncio.Lock()
        self.last_metrics = {}

    def load(self):
        try:
            import onnxruntime as ort
            from kokoro_onnx import Kokoro
            from vosk import Model, SetLogLevel
            from faster_whisper import WhisperModel
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(MODELS / 'pipecat' / 'kokoro-v1.0.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
            self.kokoro = Kokoro.from_session(session, str(MODELS / 'pipecat' / 'voices-v1.0.bin'))
            SetLogLevel(-1)
            self.vosk = Model(str(MODELS / 'vosk-model-small-en-us-0.15'))
            self.whisper = WhisperModel(str(MODELS / 'whisper-base-en'), device='cpu', compute_type='int8', cpu_threads=2, local_files_only=True)
            self.kokoro.create('Ready.', voice='af_heart', lang='en-us')
            self.transcribe(bytes(32000))  # Warm CPU decoder before accepting speech.
            self.loaded = True
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'[:500]
            log.exception('Pipecat CPU warmup failed')

    @property
    def ready(self):
        return self.loaded and not self.error

    def transcribe(self, pcm):
        with self.asr_lock:
            audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
            segments, _ = self.whisper.transcribe(audio, language='en', beam_size=1, best_of=1, temperature=0.0, condition_on_previous_text=False, vad_filter=False, without_timestamps=True)
            return ' '.join(segment.text.strip() for segment in segments).strip()


runtime = Runtime()


@dataclass
class SpeakFrame(DataFrame):
    turn_id: str
    text: str = ''
    final: bool = False


class Session:
    def __init__(self, socket, resources=runtime):
        self.socket, self.runtime = socket, resources
        self.worker = None
        self.send_lock = asyncio.Lock()
        self.input_lock = asyncio.Lock()
        self.mode, self.voice = 'conversation', 'af_heart'
        self.turn_id, self.spoken, self.received = '', '', 0
        self.input = bytearray()
        self.speaking = False
        self.quiet = 0.0
        self.silence_limit = 1.2
        self.last_analysis = 0.0
        self.last_partial = ''
        self.asr_task = None
        self.closed = False
        self.analysis_failed = False
        self.after_asr = bytearray()
        self.capture_epoch = 0
        self.draft_segments = []
        self.ended_turn = ''

    def initialize_input(self):
        from vosk import KaldiRecognizer
        self.recognizer = KaldiRecognizer(self.runtime.vosk, 16000)
        self.vad = SileroVADAnalyzer(sample_rate=16000, params=VADParams(confidence=0.75, start_secs=0.18, stop_secs=0.2))
        self.vad.set_sample_rate(16000)
        self.turn = LocalSmartTurnAnalyzerV3(sample_rate=16000, cpu_count=1, params=SmartTurnParams(stop_secs=3))
        self.turn.set_sample_rate(16000)

    async def send(self, kind, **values):
        if not self.closed:
            async with self.send_lock:
                await self.socket.send_json({'type': kind, **values})

    async def interrupt(self):
        old = self.turn_id
        self.turn_id = ''
        if self.worker:
            await self.worker.queue_frame(InterruptionFrame())
        await self.send('interruption', turn_id=old)

    def reset_input(self):
        self.input.clear(); self.speaking = False; self.quiet = 0
        self.last_partial = ''; self.last_analysis = 0
        self.draft_segments.clear()
        self.recognizer.Reset(); self.turn.clear()

    async def feed(self, pcm):
        async with self.input_lock:
            await self._feed(pcm)

    async def _feed(self, pcm):
        if self.closed or self.mode == 'paused':
            return
        if self.asr_task and not self.asr_task.done():
            if len(self.after_asr) + len(pcm) <= 960000:
                self.after_asr.extend(pcm)
            else:
                self.after_asr.clear()
                await self.send('error', message='Speech arrived faster than CPU transcription could finish. Please repeat the next message; no extra task was submitted.')
            return
        for offset in range(0, len(pcm), 1024):
            if self.closed: break
            chunk = pcm[offset:offset + 1024]
            state = await self.vad.analyze_audio(chunk)
            speech = state in {VADState.SPEAKING, VADState.STOPPING}
            endpoint = self.turn.append_audio(chunk, speech)
            self.input.extend(chunk)
            if not self.speaking and not speech:
                del self.input[:-16000]  # Half a second of pre-roll.
                continue
            if speech:
                if not self.speaking:
                    self.speaking = True
                    self.recognizer.AcceptWaveform(bytes(self.input[:-len(chunk)]))
                    await self.interrupt()
                    await self.send('speech_started')
                self.quiet = 0
            else:
                self.quiet += len(chunk) / 32000
            final_segment = self.recognizer.AcceptWaveform(chunk)
            result = json.loads(self.recognizer.Result() if final_segment else self.recognizer.PartialResult())
            segment = result.get('text' if final_segment else 'partial', '').strip()
            if final_segment and segment:
                self.draft_segments.append(segment)
            partial = ' '.join([*self.draft_segments, *([segment] if segment and not final_segment else [])])
            if partial and partial != self.last_partial:
                self.last_partial = partial
                await self.send('partial', text=partial)
            complete = endpoint == EndOfTurnState.COMPLETE or self.quiet >= self.silence_limit or len(self.input) >= 960000
            if not complete and self.quiet >= 0.25 and self.quiet - self.last_analysis >= 0.3:
                self.last_analysis = self.quiet
                try:
                    endpoint, _ = await self.turn.analyze_end_of_turn()
                    complete = endpoint == EndOfTurnState.COMPLETE
                except Exception:
                    if not self.analysis_failed:
                        log.exception('Smart Turn failed; using bounded VAD endpointing')
                    self.analysis_failed = True
            if complete:
                audio = bytes(self.input)
                self.reset_input()
                await self.send('transcribing')
                self.asr_task = asyncio.create_task(self.finalize(audio, self.capture_epoch))
                break

    async def finalize(self, audio, capture_epoch=None):
        started = time.monotonic()
        try:
            text = await asyncio.to_thread(self.runtime.transcribe, audio)
            if self.closed or self.mode == 'paused' or capture_epoch is not None and capture_epoch != self.capture_epoch:
                return
            tokens = re.findall(r'\w+', text.lower())
            echo = re.findall(r'\w+', self.spoken.lower())
            if not text or len(tokens) >= 4 and ' '.join(tokens) in ' '.join(echo):
                await self.send('listening')
                return
            self.turn_id = uuid4().hex
            self.ended_turn = ''
            self.spoken, self.received = '', 0
            elapsed = round((time.monotonic() - started) * 1000)
            self.runtime.last_metrics['transcription_ms'] = elapsed
            await self.send('final', text=text, turn_id=self.turn_id, transcription_ms=elapsed)
        except Exception:
            log.exception('Pipecat transcription failed')
            await self.send('error', message='CPU transcription failed. Your existing chat and render jobs are unchanged; try again or choose Classic voice.')
        finally:
            self.asr_task = None
            if self.after_asr and not self.closed and self.mode != 'paused':
                pending = bytes(self.after_asr); self.after_asr.clear()
                await self.feed(pending)

    async def command(self, message):
        kind = message.get('type')
        if kind == 'configure':
            if message.get('mode', 'conversation') not in {'conversation', 'paused'}:
                raise ValueError('Unsupported capture mode')
            self.mode = message.get('mode', 'conversation')
            self.silence_limit = max(0.5, min(3, float(message.get('silence_seconds', 1.2))))
            self.voice = message.get('voice') if message.get('voice') in VOICES else 'af_heart'
            if self.mode == 'paused':
                self.capture_epoch += 1
                self.after_asr.clear()
                await self.interrupt(); self.reset_input()
        elif kind == 'interrupt':
            await self.interrupt()
        elif kind in {'reply_chunk', 'reply_end'}:
            if message.get('turn_id') != self.turn_id or not self.turn_id or self.ended_turn == self.turn_id:
                return  # Late model/tool replies are saved in chat, never replayed.
            text = message.get('text', '')
            if not isinstance(text, str) or len(text) > 4000:
                raise ValueError('Invalid speech text')
            text = text[:max(0, 1200 - self.received)]
            self.received += len(text)
            self.spoken += text
            if text or kind == 'reply_end':
                if kind == 'reply_end': self.ended_turn = self.turn_id
                await self.worker.queue_frame(SpeakFrame(self.turn_id, text, kind == 'reply_end'))
        else:
            raise ValueError('Unknown Pipecat message')


class CpuSpeech(FrameProcessor):
    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if not isinstance(frame, SpeakFrame):
            await self.push_frame(frame, direction)
            return
        session = self.session
        if frame.turn_id != session.turn_id:
            return
        if frame.text.strip():
            started, first = time.monotonic(), True
            try:
                async with session.runtime.tts_lock:
                    stream = session.runtime.kokoro.create_stream(frame.text, voice=session.voice, lang='en-gb' if session.voice.startswith('b') else 'en-us')
                    async for samples, rate in stream:
                        if frame.turn_id != session.turn_id:
                            break
                        if first:
                            elapsed = round((time.monotonic() - started) * 1000)
                            session.runtime.last_metrics['tts_first_audio_ms'] = elapsed
                            await session.send('speech_metrics', turn_id=frame.turn_id, ttfb_ms=elapsed)
                            first = False
                        pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
                        for offset in range(0, len(pcm), rate // 5):  # 100 ms PCM packets.
                            audio = TTSAudioRawFrame(audio=pcm[offset:offset + rate // 5], sample_rate=rate, num_channels=1)
                            audio.metadata['turn_id'] = frame.turn_id
                            await self.push_frame(audio)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Pipecat CPU speech failed')
                await session.send('error', message='Pipecat speech failed. Your reply is saved in chat; you can keep speaking or switch to Classic voice.')
        if frame.final and frame.turn_id == session.turn_id:
            await self.push_frame(frame)


class SocketAudio(FrameProcessor):
    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            if frame.metadata.get('turn_id') == self.session.turn_id:
                await self.session.send('audio', turn_id=self.session.turn_id, sample_rate=frame.sample_rate, pcm=base64.b64encode(frame.audio).decode())
        elif isinstance(frame, SpeakFrame) and frame.final:
            await self.session.send('audio_done', turn_id=frame.turn_id)
        else:
            await self.push_frame(frame, direction)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(asyncio.to_thread(runtime.load))
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title='Darius Pipecat CPU voice', lifespan=lifespan)
active_sessions = 0
app.add_middleware(CORSMiddleware, allow_origins=sorted(ORIGINS), allow_methods=['GET'], allow_headers=['Content-Type'])


@app.get('/health')
def health():
    return {'service': 'darius-pipecat', 'version': 1, 'ready': runtime.ready, 'device': 'cpu',
            'pipeline': 'pipecat-ai 1.12.0', 'turn_detection': 'Silero + Smart Turn v3.2',
            'transcription': 'faster-whisper CPU int8', 'speech': 'Kokoro ONNX CPU',
            'voices': sorted(VOICES), 'last_metrics': runtime.last_metrics, 'error': runtime.error}


@app.get('/speaker-test')
async def speaker_test(request: Request, voice: str = 'af_heart'):
    if request.headers.get('origin') and request.headers['origin'] not in ORIGINS:
        raise HTTPException(403, 'This origin cannot use local speech.')
    if not runtime.ready: raise HTTPException(503, 'Pipecat is warming up.')
    if voice not in VOICES: raise HTTPException(422, 'Choose an installed Pipecat voice.')
    async with runtime.tts_lock:
        samples, rate = await asyncio.to_thread(runtime.kokoro.create, 'Darius speaker test. You should hear this clearly.', voice=voice, lang='en-gb' if voice.startswith('b') else 'en-us')
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
        wav.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
    return Response(output.getvalue(), media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@app.websocket('/listen')
async def listen(socket: WebSocket):
    global active_sessions
    if socket.headers.get('origin') not in ORIGINS:
        await socket.close(code=1008); return
    await socket.accept()
    if not runtime.ready:
        await socket.send_json({'type': 'error', 'message': 'Pipecat CPU voice is warming up or unavailable. Check Settings or use Classic voice.'})
        await socket.close(code=1013); return
    if active_sessions >= 2:
        await socket.send_json({'type': 'error', 'message': 'Two Pipecat sessions are already open. Close another voice session or use Classic voice.'})
        await socket.close(code=1013); return
    active_sessions += 1
    session = Session(socket)
    runner = WorkerRunner(handle_sigint=False, check_dangling_tasks=False)
    job = None
    try:
        await asyncio.to_thread(session.initialize_input)
        worker = PipelineWorker(Pipeline([CpuSpeech(session), SocketAudio(session)]), params=PipelineParams(audio_out_sample_rate=24000), enable_rtvi=False, enable_turn_tracking=False, idle_timeout_secs=None)
        session.worker = worker
        started = asyncio.Event()
        @worker.event_handler('on_pipeline_started')
        async def pipeline_started(_worker, _frame):
            started.set()
        @worker.event_handler('on_pipeline_error')
        async def pipeline_error(_worker, _frame):
            await session.send('error', message='The Pipecat audio pipeline failed. Your chat and render jobs are saved; reconnect or choose Classic voice.')
        await runner.add_workers(worker)
        job = asyncio.create_task(runner.run())
        await asyncio.wait_for(started.wait(), 10)
        await session.send('ready', backend='pipecat', sample_rate=16000)
        while True:
            incoming = await socket.receive()
            if incoming['type'] == 'websocket.disconnect':
                break
            if incoming.get('bytes') is not None:
                pcm = incoming['bytes']
                if len(pcm) > 32768 or len(pcm) % 2:
                    await socket.close(code=1009); break
                await session.feed(pcm)
            elif incoming.get('text') is not None:
                if len(incoming['text']) > 8192:
                    await socket.close(code=1009); break
                value = json.loads(incoming['text'])
                if not isinstance(value, dict):
                    raise ValueError('An object is required')
                await session.command(value)
    except WebSocketDisconnect:
        pass
    except (ValueError, TypeError):
        await session.send('error', message='Invalid Pipecat session message.')
    except Exception:
        log.exception('Pipecat session failed')
        with suppress(Exception):
            await session.send('error', message='Pipecat disconnected. Your chat and render jobs are retained. Choose Classic voice or reconnect.')
    finally:
        active_sessions -= 1
        session.closed = True
        if session.asr_task:
            session.asr_task.cancel()
            with suppress(asyncio.CancelledError):
                await session.asr_task
        if session.worker:
            with suppress(Exception):
                await asyncio.wait_for(session.worker.cancel(), 5)
        if job:
            with suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(job, 5)
        if hasattr(session, 'turn'):
            await session.turn.cleanup()
        if hasattr(session, 'vad'):
            await session.vad.cleanup()
        with suppress(Exception):
            await socket.close()
