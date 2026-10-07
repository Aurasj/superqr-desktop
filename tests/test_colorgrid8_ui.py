"""ColorGrid tab selection must reach the actual sender subprocess."""
import io
from unittest.mock import Mock

import pytest

from superqr_desktop.ui.main_window import MainWindow


@pytest.mark.parametrize("method", ["_select_colorgrid_default_1mb", "_select_colorgrid_default_10mb"])
def test_missing_local_fixture_explains_how_to_select_a_file(monkeypatch, method):
    window = MainWindow.__new__(MainWindow)
    window._colorgrid_progress = Mock()
    window._colorgrid_file = None
    monkeypatch.setattr("superqr_desktop.ui.main_window.Path.is_file", lambda _: False)
    getattr(window, method)()
    assert window._colorgrid_file is None
    assert "CHOOSE ANY FILE" in window._colorgrid_progress.set.call_args.args[0]


@pytest.mark.parametrize("grid", ["240x216", "336x288"])
@pytest.mark.parametrize("fullscreen", [False, True])
def test_colorgrid_launch_uses_selected_grid_at_30fps(tmp_path, monkeypatch, grid, fullscreen):
    window = MainWindow.__new__(MainWindow)
    source = tmp_path / "small.txt"
    source.write_text("ColorGrid UI regression", encoding="utf-8")
    window._colorgrid_file = source
    window._colorgrid_grid = Mock(get=Mock(return_value=grid))
    window._colorgrid_progress = Mock()
    window._status = Mock()
    window._grid8_process = None
    window._fullscreen = Mock(get=Mock(return_value=fullscreen))
    window._selected_display_index = lambda: 0
    window.display = Mock()
    process = Mock(stdout=io.StringIO())
    popen = Mock(return_value=process)
    monkeypatch.setattr("superqr_desktop.ui.main_window.subprocess.Popen", popen)
    monkeypatch.setattr("superqr_desktop.ui.main_window.threading.Thread", Mock())

    window._start_colorgrid()

    command = popen.call_args.args[0]
    assert command[command.index("--grid") + 1] == grid
    assert command[command.index("--fps") + 1] == "30"
    assert command[command.index("--file") + 1] == str(source)
    assert ("--windowed" in command) is not fullscreen
    assert f"{grid} @ 30 FPS" in window._colorgrid_progress.set.call_args.args[0]
    # Selecting another grid must not launch a second sender during a transfer.
    window._start_colorgrid()
    assert popen.call_count == 1


def test_colorgrid_panel_exposes_readonly_240_grid_option():
    import tkinter as tk
    from tkinter import ttk
    from superqr_desktop.ui import styles

    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    root.withdraw()
    try:
        styles.setup_styles(root)
        window = MainWindow.__new__(MainWindow)
        window._colorgrid_panel = ttk.Frame(root)
        window._colorgrid_grid = tk.StringVar(root, value="240x216")
        window._colorgrid_file_label = tk.StringVar(root, value="small.txt")
        window._colorgrid_file_meta = tk.StringVar(root, value="text file")
        window._colorgrid_progress = tk.StringVar(root, value="Ready")
        window._build_colorgrid_panel()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        combo, = [child for child in descendants(window._colorgrid_panel) if isinstance(child, ttk.Combobox)]
        assert tuple(combo.cget("values")) == ("240x216", "336x288")
        assert str(combo.cget("state")) == "readonly"
        assert combo.get() == "240x216"
        combo.current(1)
        assert window._colorgrid_grid.get() == "336x288"
        combo.current(0)
        assert window._colorgrid_grid.get() == "240x216"
    finally:
        root.destroy()
