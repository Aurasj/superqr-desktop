"""SuperQR V7 Desktop — bootstrap entry point."""

from __future__ import annotations

import multiprocessing

from superqr_desktop.ui.main_window import MainWindow


def main():
    multiprocessing.freeze_support()
    MainWindow().run()


if __name__ == "__main__":
    main()
