"""Synchronous in-process V7 transfer frame rendering."""

from __future__ import annotations

import io
import time

import pygame
import segno
from PIL import Image

from superqr_desktop.presentation.display import DisplayController
from superqr_desktop.v7.profiles import OpticalProfile
from superqr_desktop.v7.renderer import V7TransferRenderer


class TransferPresenter:
    """Render V7 transfer frames on the main-process SDL display."""

    def __init__(self, display: DisplayController):
        self._display = display
        self._renderer: V7TransferRenderer | None = None
        self._qr_surface: pygame.Surface | None = None
        self._last_qr_bytes: bytes | None = None
        self._last_profile: OpticalProfile | None = None

    def ensure_renderer(self, marker_size: int, profile: OpticalProfile) -> None:
        if profile.is_qr:
            self._renderer = None
            return
        if (self._renderer is None or self._renderer.marker_size != marker_size
                or self._renderer.profile != profile):
            self._renderer = V7TransferRenderer(marker_size, profile)

    def render_frame(self, symbols: list[int], marker_size: int, profile: OpticalProfile) -> dict:
        """Render one frame. Returns timing dict with render_ms and flip_ms."""
        started_ns = time.perf_counter_ns()
        if profile.is_qr:
            return self._render_qr(profile, marker_size, started_ns)
        self.ensure_renderer(marker_size, profile)
        assert self._renderer is not None
        self._renderer.prepare_symbols(symbols)
        surface = self._renderer.cached_frame_display
        screen = self._display.screen
        if surface is None or screen is None:
            return {"render_ms": 0.0, "flip_ms": 0.0}
        cw, ch = screen.get_size()
        screen.fill((8, 10, 14))
        screen.blit(surface, ((cw - marker) // 2, (ch - marker) // 2))
        flip_started_ns = time.perf_counter_ns()
        pygame.display.flip()
        completed_ns = time.perf_counter_ns()
        return {
            "render_ms": (flip_started_ns - started_ns) / 1_000_000.0,
            "flip_ms": (completed_ns - flip_started_ns) / 1_000_000.0,
        }

    def render_qr_bytes(self, frame_bytes: bytes, marker_size: int, profile: OpticalProfile) -> dict:
        started_ns = time.perf_counter_ns()
        return self._render_qr(profile, marker_size, started_ns, frame_bytes)

    def _render_qr(self, profile: OpticalProfile, marker_size: int, started_ns: int,
                   frame_bytes: bytes | None = None) -> dict:
        if frame_bytes is not None and frame_bytes != self._last_qr_bytes:
            qr = segno.make_qr(frame_bytes, version=profile.qr_version,
                               error=profile.qr_ecc, mask=profile.qr_mask,
                               mode="byte", boost_error=False)
            modules = qr.version * 4 + 17
            scale = max(1, marker_size // (modules + 8))
            out = io.BytesIO()
            qr.save(out, scale=scale, border=4, kind="png", dark="#000", light="#fff")
            out.seek(0)
            img = Image.open(out).convert("RGB")
            size = img.size[0]
            self._qr_surface = pygame.image.frombytes(img.tobytes("raw", "RGB"), (size, size), "RGB")
            self._last_qr_bytes = frame_bytes
            self._last_profile = profile
        screen = self._display.screen
        if self._qr_surface is None or screen is None:
            return {"render_ms": 0.0, "flip_ms": 0.0}
        cw, ch = screen.get_size()
        screen.fill((8, 10, 14))
        sw, sh = self._qr_surface.get_size()
        screen.blit(self._qr_surface, ((cw - sw) // 2, (ch - sh) // 2))
        flip_started_ns = time.perf_counter_ns()
        pygame.display.flip()
        completed_ns = time.perf_counter_ns()
        return {
            "render_ms": (flip_started_ns - started_ns) / 1_000_000.0,
            "flip_ms": (completed_ns - flip_started_ns) / 1_000_000.0,
        }

    def invalidate_renderer(self) -> None:
        self._renderer = None
        self._qr_surface = None
        self._last_qr_bytes = None
