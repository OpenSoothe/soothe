"""PostgreSQL availability check."""

import socket


def check_postgres_available() -> bool:
    """Check if PostgreSQL is running on localhost:5432."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", 5432))
        sock.close()
    except Exception:
        return False
    else:
        return result == 0
