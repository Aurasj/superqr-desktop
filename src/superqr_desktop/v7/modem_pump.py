"""Bounded lookahead for keeping modem encoding off the presentation thread."""
from __future__ import annotations
from dataclasses import dataclass
import queue
import threading
from .modem_sender import V7ModemSender

@dataclass(frozen=True)
class PumpedChannelFrame:
    generation_id: int
    symbol_id: int
    channel_bytes: bytes

@dataclass(frozen=True)
class ModemPumpSnapshot:
    queued_frames: int
    queue_capacity: int
    generated_frames: int
    stopped: bool
    error: str | None

class V7ModemFramePump:
    """Single-producer bounded prefetch queue for display/presentation adapters.

    The worker owns calls to ``next_physical_frame`` so RS/fountain work is done
    ahead of the display deadline. The queue is deliberately tiny and bounded;
    it never grows with file size. The presentation thread only dequeues already
    encoded fixed-size channel frames.
    """
    def __init__(self, sender: V7ModemSender, *, lookahead_frames: int = 4):
        if not 2 <= lookahead_frames <= 32:
            raise ValueError("lookahead_frames must be 2..32")
        self.sender = sender
        self.lookahead_frames = lookahead_frames
        self._queue: queue.Queue[PumpedChannelFrame] = queue.Queue(maxsize=lookahead_frames)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._generated = 0
        self._error: BaseException | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self._stop.is_set():
            raise RuntimeError("frame pump cannot be restarted after stop")
        self._thread = threading.Thread(target=self._run, name="superqr-v7-modem-prefetch", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                before = self.sender.snapshot()
                frame = self.sender.next_physical_frame()
                after = self.sender.snapshot()
                generation_id = after.last_generation_id
                symbol_id = after.last_symbol_id
                if generation_id is None or symbol_id is None:
                    raise RuntimeError("sender did not expose generated frame identity")
                pumped = PumpedChannelFrame(generation_id, symbol_id, frame)
                while not self._stop.is_set():
                    try:
                        self._queue.put(pumped, timeout=0.05)
                        with self._lock:
                            self._generated += 1
                        break
                    except queue.Full:
                        continue
        except BaseException as exc:
            with self._lock:
                self._error = exc
            self._stop.set()

    def take(self, timeout: float = 1.0) -> PumpedChannelFrame:
        if self._thread is None:
            raise RuntimeError("frame pump has not been started")
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty as exc:
            with self._lock:
                error = self._error
            if error is not None:
                raise RuntimeError("modem prefetch worker failed") from error
            raise TimeoutError("no prefetched modem frame available") from exc

    def stop(self, *, close_sender: bool = False, timeout: float = 1.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
        if close_sender:
            self.sender.close()

    def snapshot(self) -> ModemPumpSnapshot:
        with self._lock:
            error = self._error
            generated = self._generated
        return ModemPumpSnapshot(
            queued_frames=self._queue.qsize(),
            queue_capacity=self.lookahead_frames,
            generated_frames=generated,
            stopped=self._stop.is_set(),
            error=None if error is None else f"{type(error).__name__}: {error}",
        )
