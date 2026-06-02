"""Allow running the daemon as a module: python -m soothe_daemon."""

from soothe_daemon.bootstrap.entrypoint import main

if __name__ == "__main__":
    main()
