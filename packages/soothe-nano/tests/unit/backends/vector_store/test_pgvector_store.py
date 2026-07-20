"""Unit tests for PGVectorStore row handling."""

from __future__ import annotations

import asyncio

from soothe_nano.backends.vector_store.pgvector import PGVectorStore, _row_get


class TestRowGet:
    def test_dict_row_uses_column_name(self) -> None:
        assert _row_get({"atttypmod": 768}, name="atttypmod", index=0) == 768

    def test_tuple_row_uses_index(self) -> None:
        assert _row_get(("skill-1", {"name": "x"}), name="id", index=0) == "skill-1"


class TestPGVectorStoreDictRows:
    def test_table_vector_dimension_uses_dict_row_column_names(self) -> None:
        async def _async_return(value: object) -> object:
            return value

        async def _async_test() -> None:
            store = PGVectorStore(collection="soothe_skillify")

            class _FakeCursor:
                async def fetchone(self) -> dict[str, int]:
                    return {"atttypmod": 768}

            class _FakeConnection:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args: object) -> None:
                    return None

                async def execute(self, *_args: object, **_kwargs: object) -> _FakeCursor:
                    return _FakeCursor()

            class _FakePool:
                def connection(self) -> _FakeConnection:
                    return _FakeConnection()

            store._ensure_pool = lambda: _async_return(_FakePool())  # type: ignore[method-assign,return-value]
            assert await store._table_vector_dimension() == 768

        asyncio.run(_async_test())

    def test_list_records_uses_dict_row_column_names(self) -> None:
        async def _async_return(value: object) -> object:
            return value

        async def _async_test() -> None:
            store = PGVectorStore(collection="soothe_skillify")

            class _FakeCursor:
                async def fetchall(self) -> list[dict[str, object]]:
                    return [
                        {"id": "skill-a", "payload": {"name": "alpha"}},
                        {"id": "skill-b", "payload": {"name": "beta"}},
                    ]

            class _FakeConnection:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args: object) -> None:
                    return None

                async def execute(self, *_args: object, **_kwargs: object) -> _FakeCursor:
                    return _FakeCursor()

            class _FakePool:
                def connection(self) -> _FakeConnection:
                    return _FakeConnection()

            store._ensure_pool = lambda: _async_return(_FakePool())  # type: ignore[method-assign,return-value]
            records = await store.list_records()
            assert [record.id for record in records] == ["skill-a", "skill-b"]
            assert records[0].payload == {"name": "alpha"}

        asyncio.run(_async_test())
