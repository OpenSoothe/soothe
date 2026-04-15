"""Allow running the daemon as a module: python -m soothe.daemon."""

from soothe_daemon.daemon.entrypoint import main

if __name__ == "__main__":
    main()
