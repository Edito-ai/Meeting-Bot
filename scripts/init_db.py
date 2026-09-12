"""One-time (but safe to re-run) MongoDB index setup. Run via scripts/setup_server.sh.
(main.py also calls ensure_indexes() on every backend startup as a defensive no-op.)
"""
from common.db import ensure_indexes

if __name__ == "__main__":
    ensure_indexes()
    print("Mongo indexes ensured.")
