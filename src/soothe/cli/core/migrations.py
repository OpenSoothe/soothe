"""One-time migration utilities."""

import logging
from pathlib import Path

from soothe.config import SOOTHE_HOME


def migrate_rocksdb_to_data_subfolder() -> None:
    """Migrate RocksDB data files to data/ subfolders.

    This is a one-time migration to reorganize RocksDB storage structure.
    Moves existing RocksDB files from component root directories to data/ subfolders:
    - durability/ -> durability/data/
    - context/ -> context/data/
    - memory/ -> memory/data/
    """
    logger = logging.getLogger(__name__)
    home = Path(SOOTHE_HOME).expanduser()

    for component in ["durability", "context", "memory"]:
        component_dir = home / component
        data_dir = component_dir / "data"

        # Skip if data/ already exists (already migrated or fresh install)
        if data_dir.exists():
            continue

        # Skip if component directory doesn't exist
        if not component_dir.exists():
            continue

        # Check for RocksDB files (*.db files, LOG, LOCK, OPTIONS*, etc.)
        rocksdb_files = []
        for pattern in ["*.db", "LOG", "LOCK", "OPTIONS*", "CURRENT", "IDENTITY", "MANIFEST-*"]:
            rocksdb_files.extend(component_dir.glob(pattern))

        # Skip if no RocksDB files found
        if not rocksdb_files:
            continue

        # Perform migration
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            for file_path in rocksdb_files:
                dest = data_dir / file_path.name
                file_path.rename(dest)
            logger.info("Migrated %d RocksDB files from %s/ to %s/data/", len(rocksdb_files), component, component)
        except Exception as e:
            logger.warning("Failed to migrate %s to data/ subfolder: %s", component, e)
