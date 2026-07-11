from __future__ import annotations

from array import array
import logging
import queue
import subprocess
import sys
import threading
import time
from typing import Dict, Iterator, Optional

import psutil

from app.config import Settings
from app.database import Database
from app.models import validate_twitch_name
from app.twitch import TwitchStatusClient


class StreamManager:
    def __init__(self, settings: Settings, database: Database, twitch_client: TwitchStatusClient, logger: logging.Logger) -> None:
        self.settings = settings
        self.database = database
        self.twitch_client = twitch_client
        self.logger = logger

        self._lock = threading.RLock()
        self._subscribers: Dict[int, queue.Queue[Optional[bytes]]] = {}
        self._next_subscriber_id = 1
        self._listeners = 0
        self._idle_deadline: Optional[float] = None

        self._encoder_proc: Optional[subprocess.Popen] = None
        self._streamlink_proc: Optional[subprocess.Popen] = None
        self._decoder_proc: Optional[subprocess.Popen] = None

        self._broadcast_thread: Optional[threading.Thread] = None
        self._pcm_thread: Optional[threading.Thread] = None
        self._stderr_threads: list[threading.Thread] = []
        self._pipeline_stop_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._pipeline_started_at = 0.0
        self._source_state = "stopped"
        self._last_error: Optional[str] = None
        self._reconnect_attempt = 0
        self._current_volume = self._load_volume_setting()
        self._idle_thread = threading.Thread(target=self._idle_loop, name="tuxplayer-idle", daemon=True)
        self._idle_thread.start()

        chunk_frames = max(1, int(self.settings.stream_sample_rate * (self.settings.stream_chunk_ms / 1000.0)))
        self._pcm_chunk_size = chunk_frames * 2 * 2
        self._chunk_sleep = chunk_frames / float(self.settings.stream_sample_rate)
        self._mp3_chunk_size = 1024

    def subscribe(self) -> Iterator[bytes]:
        subscriber_id: Optional[int] = None
        subscriber_queue: Optional[queue.Queue[Optional[bytes]]] = None
        with self._lock:
            self._ensure_pipeline_locked()
            subscriber_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            subscriber_queue = queue.Queue(maxsize=self.settings.subscriber_queue_size)
            self._subscribers[subscriber_id] = subscriber_queue
            self._listeners = len(self._subscribers)
            self._idle_deadline = None
            self.logger.info("Lytter forbundet. Antal lyttere: %s", self._listeners)

        assert subscriber_queue is not None

        def generator() -> Iterator[bytes]:
            try:
                while True:
                    chunk = subscriber_queue.get()
                    if chunk is None:
                        break
                    yield chunk
            finally:
                if subscriber_id is not None:
                    self.unsubscribe(subscriber_id)

        return generator()

    def unsubscribe(self, subscriber_id: int) -> None:
        with self._lock:
            queue_ref = self._subscribers.pop(subscriber_id, None)
            if queue_ref is None:
                return
            self._listeners = len(self._subscribers)
            self.logger.info("Lytter afbrudt. Antal lyttere: %s", self._listeners)
            if self._listeners == 0:
                self._idle_deadline = time.monotonic() + self.idle_timeout()

    def select_channel(self, channel_id: Optional[int]) -> None:
        self.database.set_active_channel(channel_id)
        with self._lock:
            self._reconnect_attempt = 0
            self._last_error = None
            self._source_state = "unknown" if channel_id else "stopped"
            self._stop_source_locked()

    def restart_source(self) -> None:
        with self._lock:
            self._reconnect_attempt = 0
            self._last_error = None
            self._stop_source_locked()
            self._source_state = "unknown"

    def stop_source_only(self) -> None:
        with self._lock:
            self._stop_source_locked()
            self._source_state = "stopped"

    def test_channel(self, twitch_name: str) -> Dict[str, object]:
        validated = validate_twitch_name(twitch_name)
        status = self.twitch_client.get_channel_status(validated)
        if status.state != "unknown":
            return {
                "ok": status.state == "live",
                "state": status.state,
                "title": status.title,
                "viewer_count": status.viewer_count,
            }
        command = self._streamlink_probe_command(validated)
        result = subprocess.run(command, capture_output=True, text=True, shell=False, timeout=20)
        ok = result.returncode == 0
        return {
            "ok": ok,
            "state": "live" if ok else "offline",
            "message": (result.stdout or result.stderr).strip()[:300],
        }

    def get_status(self) -> Dict[str, object]:
        active_channel = self.database.get_active_channel()
        api_status = None
        if active_channel:
            api_status = self.twitch_client.get_channel_status(active_channel["twitch_name"])
        with self._lock:
            stream_running = bool(self._encoder_proc and self._encoder_proc.poll() is None)
            uptime_seconds = int(time.monotonic() - self._pipeline_started_at) if stream_running else 0
            status = {
                "status": "ok",
                "active_channel": active_channel["twitch_name"] if active_channel else None,
                "source_state": self._resolve_source_state(api_status.state if api_status else "unknown"),
                "stream_running": stream_running,
                "listeners": self._listeners,
                "stream_url": self.settings.stream_url,
                "uptime_seconds": uptime_seconds,
                "last_error": self._last_error,
                "streamlink_pid": self._streamlink_proc.pid if self._streamlink_proc and self._streamlink_proc.poll() is None else None,
                "ffmpeg_pid": self._encoder_proc.pid if self._encoder_proc and self._encoder_proc.poll() is None else None,
                "stream_volume": self._current_volume,
            }
            usage = self._process_usage()
            status.update(usage)
        if api_status:
            status["title"] = api_status.title
            status["viewer_count"] = api_status.viewer_count
            status["profile_image_url"] = api_status.profile_image_url
        return status

    def idle_timeout(self) -> int:
        value = self.database.get_setting("idle_timeout")
        if value:
            try:
                return max(1, int(value))
            except ValueError:
                return self.settings.stream_idle_timeout
        return self.settings.stream_idle_timeout

    @property
    def listeners(self) -> int:
        with self._lock:
            return self._listeners

    def get_volume(self) -> float:
        with self._lock:
            return self._current_volume

    def set_volume(self, value: float) -> float:
        normalized = self._normalize_volume(value)
        with self._lock:
            self._current_volume = normalized
            self.database.set_setting("stream_volume", str(normalized))
        self.logger.info("Stream-volumen opdateret til %.1f", normalized)
        return normalized

    def shutdown(self) -> None:
        self._shutdown_event.set()
        with self._lock:
            self._stop_pipeline_locked(notify_subscribers=True)

    def _ensure_pipeline_locked(self) -> None:
        if self._encoder_proc and self._encoder_proc.poll() is None:
            return
        self._pipeline_stop_event = threading.Event()
        self._start_encoder_locked()
        self._pipeline_started_at = time.monotonic()
        self._source_state = "silence"
        self._broadcast_thread = threading.Thread(target=self._broadcast_loop, name="tuxplayer-broadcast", daemon=True)
        self._broadcast_thread.start()
        self._pcm_thread = threading.Thread(target=self._pcm_loop, name="tuxplayer-pcm", daemon=True)
        self._pcm_thread.start()
        self.logger.info("MP3-pipeline startet.")

    def _start_encoder_locked(self) -> None:
        self._encoder_proc = subprocess.Popen(
            self._encoder_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
        )
        self._start_stderr_reader(self._encoder_proc, "encoder")

    def _encoder_command(self) -> list[str]:
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "s16le",
            "-ar",
            str(self.settings.stream_sample_rate),
            "-ac",
            "2",
            "-i",
            "pipe:0",
            "-flush_packets",
            "1",
            "-write_xing",
            "0",
            "-f",
            "mp3",
            "-c:a",
            "libmp3lame",
            "-b:a",
            self.settings.stream_bitrate,
            "-content_type",
            "audio/mpeg",
            "pipe:1",
        ]

    def _pcm_loop(self) -> None:
        silence_chunk = b"\x00" * self._pcm_chunk_size
        backoff_schedule = [5, 15, 30, 60]
        next_retry_at = 0.0
        while not self._pipeline_stop_event.is_set() and not self._shutdown_event.is_set():
            active_channel = self.database.get_active_channel()
            if active_channel and active_channel["enabled"]:
                with self._lock:
                    source_ready = self._source_processes_alive_locked()
                    if not source_ready and time.monotonic() >= next_retry_at:
                        self._stop_source_locked()
                        if self._start_source_locked(active_channel["twitch_name"]):
                            self._source_state = "live"
                            self._reconnect_attempt = 0
                        else:
                            wait_seconds = backoff_schedule[min(self._reconnect_attempt, len(backoff_schedule) - 1)]
                            next_retry_at = time.monotonic() + wait_seconds
                            self._reconnect_attempt += 1
                    decoder_stdout = self._decoder_proc.stdout if self._decoder_proc and self._decoder_proc.stdout else None
                if decoder_stdout is not None:
                    try:
                        payload = decoder_stdout.read(self._pcm_chunk_size)
                    except Exception as exc:
                        payload = b""
                        self._set_error(f"PCM læsning fejlede: {exc}")
                    if payload:
                        self._write_encoder(self._apply_volume(payload))
                        continue
                    self._set_error("Twitch-kilden leverede ikke lyddata.")
                    with self._lock:
                        self._stop_source_locked()
                        self._source_state = "offline"
                    wait_seconds = backoff_schedule[min(self._reconnect_attempt, len(backoff_schedule) - 1)]
                    next_retry_at = time.monotonic() + wait_seconds
                    self._reconnect_attempt += 1
            else:
                with self._lock:
                    self._stop_source_locked()
                    self._source_state = "silence" if active_channel is None else "stopped"
            self._write_encoder(silence_chunk)
            time.sleep(self._chunk_sleep)
        self.logger.info("PCM-loop stoppet.")

    def _broadcast_loop(self) -> None:
        encoder_stdout = self._encoder_proc.stdout if self._encoder_proc and self._encoder_proc.stdout else None
        if encoder_stdout is None:
            return
        try:
            while not self._pipeline_stop_event.is_set() and not self._shutdown_event.is_set():
                chunk = encoder_stdout.read(self._mp3_chunk_size)
                if not chunk:
                    if not self._pipeline_stop_event.is_set():
                        self._set_error("MP3-encoderen stoppede uventet.")
                    break
                with self._lock:
                    subscribers = list(self._subscribers.values())
                for subscriber_queue in subscribers:
                    self._enqueue_for_subscriber(subscriber_queue, chunk)
        finally:
            with self._lock:
                for subscriber_queue in self._subscribers.values():
                    self._enqueue_for_subscriber(subscriber_queue, None, allow_drop=False)
            self.logger.info("Broadcast-loop stoppet.")

    def _idle_loop(self) -> None:
        while not self._shutdown_event.is_set():
            should_stop = False
            with self._lock:
                if (
                    self._listeners == 0
                    and self._idle_deadline is not None
                    and time.monotonic() >= self._idle_deadline
                    and self._encoder_proc is not None
                ):
                    should_stop = True
            if should_stop:
                with self._lock:
                    self.logger.info("Idle-timeout nået. Twitch-kilde og pipeline stoppes.")
                    self._stop_pipeline_locked(notify_subscribers=False)
                    self._idle_deadline = None
            time.sleep(0.5)

    def _stop_pipeline_locked(self, notify_subscribers: bool) -> None:
        self._pipeline_stop_event.set()
        self._stop_source_locked()
        self._terminate_process(self._encoder_proc, "encoder")
        self._encoder_proc = None
        self._pipeline_started_at = 0.0
        self._idle_deadline = None
        self._source_state = "stopped"
        if notify_subscribers:
            for subscriber_queue in self._subscribers.values():
                self._enqueue_for_subscriber(subscriber_queue, None, allow_drop=False)

    def _start_source_locked(self, twitch_name: str) -> bool:
        validated = validate_twitch_name(twitch_name)
        try:
            streamlink_proc = subprocess.Popen(
                self._streamlink_command(validated),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                bufsize=0,
            )
            assert streamlink_proc.stdout is not None
            decoder_proc = subprocess.Popen(
                self._decoder_command(),
                stdin=streamlink_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                bufsize=0,
            )
            streamlink_proc.stdout.close()
            self._streamlink_proc = streamlink_proc
            self._decoder_proc = decoder_proc
            self._start_stderr_reader(streamlink_proc, "streamlink")
            self._start_stderr_reader(decoder_proc, "decoder")
            self.logger.info("Twitch-kilde startet for %s.", validated)
            return True
        except Exception as exc:
            self._set_error(f"Kunne ikke starte Twitch-kilde for {validated}: {exc}")
            self._stop_source_locked()
            return False

    def _stop_source_locked(self) -> None:
        self._terminate_process(self._decoder_proc, "decoder")
        self._terminate_process(self._streamlink_proc, "streamlink")
        self._decoder_proc = None
        self._streamlink_proc = None

    def _source_processes_alive_locked(self) -> bool:
        return bool(
            self._streamlink_proc
            and self._decoder_proc
            and self._streamlink_proc.poll() is None
            and self._decoder_proc.poll() is None
        )

    def _terminate_process(self, proc: Optional[subprocess.Popen], label: str) -> None:
        if proc is None:
            return
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.logger.warning("%s reagerede ikke på SIGTERM. Tvinger stop.", label)
            proc.kill()
            proc.wait(timeout=3)
        except Exception as exc:
            self.logger.warning("Kunne ikke stoppe %s korrekt: %s", label, exc)
        finally:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                if proc.stderr:
                    proc.stderr.close()
            except Exception:
                pass

    def _start_stderr_reader(self, proc: subprocess.Popen, label: str) -> None:
        thread = threading.Thread(target=self._drain_stderr, args=(proc, label), name=f"tuxplayer-{label}-stderr", daemon=True)
        thread.start()
        self._stderr_threads.append(thread)

    def _drain_stderr(self, proc: subprocess.Popen, label: str) -> None:
        if proc.stderr is None:
            return
        try:
            while True:
                line = proc.stderr.readline()
                if not line:
                    break
                message = line.decode("utf-8", errors="replace").strip()
                if message:
                    self.logger.warning("%s: %s", label, message)
                    if label in {"streamlink", "decoder", "encoder"}:
                        self._last_error = message[:500]
                        if "No playable streams found" in message:
                            self._source_state = "offline"
        except Exception as exc:
            self.logger.debug("stderr-reader stoppet for %s: %s", label, exc)

    def _write_encoder(self, pcm_bytes: bytes) -> None:
        with self._lock:
            encoder_stdin = self._encoder_proc.stdin if self._encoder_proc and self._encoder_proc.stdin else None
        if encoder_stdin is None:
            return
        try:
            encoder_stdin.write(pcm_bytes)
            encoder_stdin.flush()
        except BrokenPipeError:
            self._set_error("MP3-encoderen lukkede sin input-pipe.")
        except Exception as exc:
            self._set_error(f"Kunne ikke skrive PCM til encoder: {exc}")

    def _apply_volume(self, pcm_bytes: bytes) -> bytes:
        with self._lock:
            volume = self._current_volume
        if not pcm_bytes or volume == 1.0:
            return pcm_bytes
        try:
            samples = array("h")
            samples.frombytes(pcm_bytes)
            if sys.byteorder != "little":
                samples.byteswap()
            for index in range(len(samples)):
                scaled = int(samples[index] * volume)
                if scaled > 32767:
                    scaled = 32767
                elif scaled < -32768:
                    scaled = -32768
                samples[index] = scaled
            if sys.byteorder != "little":
                samples.byteswap()
            return samples.tobytes()
        except Exception as exc:
            self._set_error(f"Kunne ikke justere volumen: {exc}")
            return pcm_bytes

    def _enqueue_for_subscriber(
        self, subscriber_queue: queue.Queue[Optional[bytes]], chunk: Optional[bytes], allow_drop: bool = True
    ) -> None:
        try:
            subscriber_queue.put_nowait(chunk)
        except queue.Full:
            if not allow_drop:
                return
            try:
                subscriber_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber_queue.put_nowait(chunk)
            except queue.Full:
                pass

    def _resolve_source_state(self, twitch_state: str) -> str:
        if self._source_state == "live":
            return "live"
        if self._source_state in {"offline", "error", "stopped", "silence"}:
            return self._source_state
        return twitch_state if twitch_state != "unknown" else self._source_state

    def _process_usage(self) -> Dict[str, Optional[float]]:
        pids = []
        if self._encoder_proc and self._encoder_proc.poll() is None:
            pids.append(self._encoder_proc.pid)
        if self._streamlink_proc and self._streamlink_proc.poll() is None:
            pids.append(self._streamlink_proc.pid)
        cpu_total = 0.0
        memory_total = 0.0
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                cpu_total += proc.cpu_percent(interval=0.0)
                memory_total += proc.memory_info().rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {
            "cpu_percent": round(cpu_total, 1) if pids else None,
            "memory_mb": round(memory_total, 1) if pids else None,
        }

    def _set_error(self, message: str) -> None:
        self._last_error = message[:500]
        self._source_state = "error"
        self.logger.warning(message)

    def _load_volume_setting(self) -> float:
        value = self.database.get_setting("stream_volume")
        if value is None:
            return self._normalize_volume(self.settings.stream_volume)
        try:
            return self._normalize_volume(float(value))
        except ValueError:
            return self._normalize_volume(self.settings.stream_volume)

    @staticmethod
    def _normalize_volume(value: float) -> float:
        return round(min(3.0, max(0.5, float(value))), 1)

    @staticmethod
    def _streamlink_quality(value: str) -> str:
        candidate = (value or "").strip()
        if not candidate:
            return "best"
        for char in candidate:
            if not (char.isalnum() or char in {"_", ",", "-", "+"}):
                raise ValueError("Ugyldig Streamlink-kvalitet.")
        return candidate

    def _streamlink_command(self, twitch_name: str) -> list[str]:
        validate_twitch_name(twitch_name)
        return [
            "streamlink",
            "--stdout",
            "--loglevel",
            "warning",
            "--retry-open",
            "3",
            "--hls-live-edge",
            str(self.settings.streamlink_live_edge),
            "--ringbuffer-size",
            "8M",
            f"https://www.twitch.tv/{twitch_name}",
            self._streamlink_quality(self.settings.streamlink_quality),
        ]

    def _streamlink_probe_command(self, twitch_name: str) -> list[str]:
        validate_twitch_name(twitch_name)
        return [
            "streamlink",
            "--stream-url",
            "--hls-live-edge",
            str(self.settings.streamlink_live_edge),
            f"https://www.twitch.tv/{twitch_name}",
            self._streamlink_quality(self.settings.streamlink_quality),
        ]

    def _decoder_command(self) -> list[str]:
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            "pipe:0",
            "-vn",
            "-f",
            "s16le",
            "-ac",
            "2",
            "-ar",
            str(self.settings.stream_sample_rate),
            "pipe:1",
        ]
