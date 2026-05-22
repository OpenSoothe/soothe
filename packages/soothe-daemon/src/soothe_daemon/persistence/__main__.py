"""Run stale worker cleanup: ``python -m soothe_daemon.persistence``."""

from soothe_daemon.persistence.process_cleanup import reap_from_cli

if __name__ == "__main__":
    reap_from_cli()
