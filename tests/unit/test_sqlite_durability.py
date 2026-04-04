"""Unit tests for SQLiteDurability backend."""

import os
import tempfile


class TestSQLiteDurabilityUnit:
    """Unit tests for SQLiteDurability focusing on interface compliance."""

    def test_class_can_be_imported(self) -> None:
        """Test that SQLiteDurability class can be imported."""
        from soothe.backends.durability.sqlite import SQLiteDurability

        assert SQLiteDurability is not None

    def test_exported_from_package(self) -> None:
        """Test SQLiteDurability is exported from durability package."""
        from soothe.backends.durability import SQLiteDurability

        assert SQLiteDurability is not None

    def test_initialization_with_db_path(self) -> None:
        """Test initialization with custom db_path."""
        from soothe.backends.durability.sqlite import SQLiteDurability

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            durability = SQLiteDurability(db_path=tmp.name)
            assert durability is not None
            # Should have base class methods
            assert hasattr(durability, "create_thread")
            assert hasattr(durability, "resume_thread")
            assert hasattr(durability, "suspend_thread")
            assert hasattr(durability, "archive_thread")
            assert hasattr(durability, "list_threads")
        finally:
            os.unlink(tmp.name)

    def test_initialization_with_persist_store(self) -> None:
        """Test initialization with explicit PersistStore."""
        from soothe.backends.durability.sqlite import SQLiteDurability
        from soothe.backends.persistence.sqlite_store import SQLitePersistStore

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            store = SQLitePersistStore(db_path=tmp.name, namespace="durability")
            durability = SQLiteDurability(persist_store=store)
            assert durability._store is store
        finally:
            os.unlink(tmp.name)

    def test_protocol_compliance(self) -> None:
        """Test implements required protocol methods."""
        from soothe.backends.durability.sqlite import SQLiteDurability
        from soothe.protocols.durability import DurabilityProtocol

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            durability = SQLiteDurability(db_path=tmp.name)
            assert isinstance(durability, DurabilityProtocol)
        finally:
            os.unlink(tmp.name)
