"""Static/dwelled ColorGrid frames must repaint after surface changes."""
import pygame
import pytest

from superqr_desktop.lab.lab_display import LabDisplayController


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.setattr(pygame.display, "get_init", lambda: True)
    monkeypatch.setattr(pygame.display, "flip", lambda: None)
    display = LabDisplayController(requested_fps=30)
    monkeypatch.setattr(display, "_pace_fallback", lambda: None)
    display.screen = pygame.Surface((100, 100))
    return display


def test_mutated_frame_surface_is_presented(controller):
    frame = pygame.Surface((80, 80))
    frame.fill("red")
    controller.present(frame)
    frame.fill("blue")
    controller.present(frame)
    assert controller.screen.get_at((50, 50)) == pygame.Color("blue")


def test_same_frame_repaints_after_window_surface_recreation(controller):
    frame = pygame.Surface((80, 80))
    frame.fill("red")
    controller.present(frame)
    controller.screen = pygame.Surface((120, 120))
    controller.present(frame)
    assert controller.screen.get_at((60, 60)) == pygame.Color("red")
    assert controller.screen.get_at((0, 0)) == pygame.Color("white")


def test_window_lifecycle_events_are_not_filtered(monkeypatch):
    allowed, blocked = [], []
    monkeypatch.setattr(pygame.event, "set_allowed", allowed.append)
    monkeypatch.setattr(pygame.event, "set_blocked", blocked.append)
    LabDisplayController._apply_event_filter()
    assert allowed == [None]
    assert blocked == [pygame.MOUSEMOTION]
