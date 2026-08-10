"""Child-process transfer presenter.

Runs V7 optical transfer in a dedicated process so Tk callbacks and repaint
work cannot disturb optical frame timing. Only one process owns the SDL
display at a time: this worker OR the Phase 1 campaign worker.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from dataclasses import asdict, dataclass

from superqr_desktop.v7.profiles import OpticalProfile, get_profile
from superqr_desktop.v7.renderer import V7TransferRenderer
from superqr_desktop.v7.sender import V7SenderSession


@dataclass(frozen=True)
class TransferLaunchConfig:
    file_path: str
    profile_key: str
    interval_ms: int
    display_index: int
    fullscreen: bool
    marker_size: int


@dataclass(frozen=True)
class TransferSnapshot:
    state: str  # SENDING, STOPPED, DONE, ERROR
    current_frame_idx: int
    total_frames: int
    interval_ms: int
    profile_key: str
    present_count: int
    last_render_ms: float
    last_flip_ms: float
    error: str | None


def _transfer_process_main(config: TransferLaunchConfig, stop_event, updates) -> None:
    """Child entry point. All SDL ownership stays in this process."""
    import pygame

    profile = get_profile(config.profile_key)
    sender = V7SenderSession()
    sender.set_profile(profile)
    sender.set_interval(config.interval_ms)

    try:
        sender.prepare_transfer(config.file_path)
    except Exception as exc:
        updates.put(asdict(TransferSnapshot(
            state="ERROR", current_frame_idx=0, total_frames=0,
            interval_ms=config.interval_ms, profile_key=config.profile_key,
            present_count=0, last_render_ms=0.0, last_flip_ms=0.0,
            error=f"{type(exc).__name__}: {exc}",
        )))
        return

    # -- set up SDL --
    pygame.init()
    if config.fullscreen:
        flags = pygame.FULLSCREEN | pygame.NOFRAME
    else:
        flags = pygame.RESIZABLE
    try:
        screen = pygame.display.set_mode(
            (config.marker_size, config.marker_size), flags, display=config.display_index,
        )
    except pygame.error:
        screen = pygame.display.set_mode(
            (config.marker_size, config.marker_size), flags,
        )
    pygame.display.set_caption("SuperQR V7 Transfer")

    renderer = V7TransferRenderer(config.marker_size, profile)

    present_count = 0
    last_advance = time.monotonic()
    last_publish = 0.0
    error: str | None = None

    try:
        while not stop_event.is_set():
            now = time.monotonic()
            if now - last_advance >= config.interval_ms / 1000.0:
                last_advance = now
                sender.advance_frame()

                started_ns = time.perf_counter_ns()
                try:
                    symbols = sender.get_frame_symbols()
                    renderer.prepare_symbols(symbols)
                    surface = renderer.cached_frame_display
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    break

                flip_started_ns = time.perf_counter_ns()
                if surface is not None and screen is not None:
                    cw, ch = screen.get_size()
                    m = config.marker_size
                    screen.fill((8, 10, 14))
                    screen.blit(surface, ((cw - m) // 2, (ch - m) // 2))
                    pygame.display.flip()

                completed_ns = time.perf_counter_ns()
                present_count += 1

                if now - last_publish >= 0.05:
                    try:
                        updates.put_nowait(asdict(TransferSnapshot(
                            state=sender.transfer_state,
                            current_frame_idx=sender.current_frame_idx,
                            total_frames=sender.total_frames,
                            interval_ms=config.interval_ms,
                            profile_key=config.profile_key,
                            present_count=present_count,
                            last_render_ms=(flip_started_ns - started_ns) / 1_000_000.0,
                            last_flip_ms=(completed_ns - flip_started_ns) / 1_000_000.0,
                            error=None,
                        )))
                    except queue.Full:
                        pass
                    last_publish = now

            # process quit events
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
                    stop_event.set()
                    break

            time.sleep(0.001)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        pygame.display.quit()
        pygame.quit()
        try:
            updates.put_nowait(asdict(TransferSnapshot(
                state="DONE" if error is None else "ERROR",
                current_frame_idx=sender.current_frame_idx,
                total_frames=sender.total_frames,
                interval_ms=config.interval_ms,
                profile_key=config.profile_key,
                present_count=present_count,
                last_render_ms=0.0,
                last_flip_ms=0.0,
                error=error,
            )))
        except queue.Full:
            pass


class TransferPresentationWorker:
    """Runs transfer SDL presentation outside Tk's process."""

    def __init__(self):
        self._context = multiprocessing.get_context("spawn")
        self._stop = self._context.Event()
        self._updates = self._context.Queue(maxsize=8)
        self._process: multiprocessing.Process | None = None
        self._launch_thread: threading.Thread | None = None
        self._launch_error: str | None = None
        self._snapshot: TransferSnapshot | None = None

    def start(self, config: TransferLaunchConfig) -> None:
        if self._process is not None:
            raise RuntimeError("transfer worker already started")
        self._stop.clear()
        self._snapshot = None
        self._launch_error = None

        self._process = self._context.Process(
            target=_transfer_process_main,
            args=(config, self._stop, self._updates),
            name="superqr-transfer-present",
            daemon=False,
        )
        self._launch_thread = threading.Thread(
            target=self._launch_process,
            name="superqr-transfer-launch",
            daemon=True,
        )
        self._launch_thread.start()

    def _launch_process(self) -> None:
        try:
            assert self._process is not None
            self._process.start()
        except Exception as exc:
            self._launch_error = f"{type(exc).__name__}: {exc}"

    def _drain_updates(self) -> None:
        while True:
            try:
                message = self._updates.get_nowait()
            except queue.Empty:
                break
            self._snapshot = TransferSnapshot(**message)

    def snapshot(self) -> TransferSnapshot | None:
        self._drain_updates()
        if self._snapshot is None and self._launch_error is not None:
            self._snapshot = TransferSnapshot(
                state="ERROR", current_frame_idx=0, total_frames=0,
                interval_ms=0, profile_key="",
                present_count=0, last_render_ms=0.0, last_flip_ms=0.0,
                error=self._launch_error,
            )
        return self._snapshot

    def is_alive(self) -> bool:
        if self._launch_thread is not None and self._launch_thread.is_alive():
            return True
        return self._process is not None and self._process.is_alive()

    def request_stop(self) -> None:
        self._stop.set()

    def stop(self, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        self._stop.set()
        launch_thread = self._launch_thread
        if launch_thread is not None and launch_thread.is_alive():
            launch_thread.join(max(0.0, deadline - time.monotonic()))
        process = self._process
        if process is not None and process.is_alive():
            process.join(max(0.0, deadline - time.monotonic()))
        if process is not None and process.is_alive():
            process.terminate()
            process.join(1.0)
        self._process = None
        self._drain_updates()
