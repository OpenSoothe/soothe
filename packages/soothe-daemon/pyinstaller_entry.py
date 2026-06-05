"""PyInstaller entry point for soothe-daemon.

Calls multiprocessing.freeze_support() before any daemon imports
so that the spawn-context worker pool works in frozen executables.
"""

import multiprocessing

multiprocessing.freeze_support()

from soothe_daemon.bootstrap.entrypoint import main  # noqa: E402

if __name__ == "__main__":
    main()
