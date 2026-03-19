"""Allow running the daemon as a module: python -m soothe.cli.daemon."""

from soothe.cli.daemon.entrypoint import main

if __name__ == "__main__":
    main()
