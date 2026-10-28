# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Regression tests for reindexing single-file URIs under tree locks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from openviking.server.identity import RequestContext, Role
from openviking.service import reindex_executor as reindex_module
from openviking.service.reindex_executor import ReindexExecutor
from openviking_cli.session.user_id import UserIdentifier


class _FakeVikingFS:
    def __init__(self, uri: str, path: str, agfs):
        self._uri = uri
        self._path = path
        self._async_agfs = agfs

    def _uri_to_path(self, uri: str, ctx=None):
        assert uri == self._uri
        return self._path

    async def stat(self, uri: str, ctx=None, skip_count=False):
        assert uri == self._uri
        assert skip_count is True
        return {"isDir": False}


async def test_reindex_single_file_uri_acquires_exact_lock(monkeypatch):
    uri = "viking://resources/profile.md"
    path = "/local/default/resources/profile.md"
    lease = {"lease_id": "file"}
    agfs = SimpleNamespace(
        pathlock_acquire_exact=AsyncMock(return_value=lease),
        pathlock_acquire_tree=AsyncMock(side_effect=AssertionError("file used tree lock")),
        pathlock_as_borrowed=AsyncMock(return_value={"lease_ref": "borrowed"}),
        pathlock_release=AsyncMock(),
    )

    viking_fs = _FakeVikingFS(uri, path, agfs)
    service = SimpleNamespace(
        viking_fs=viking_fs,
        vikingdb_manager=SimpleNamespace(has_queue_manager=True),
    )
    monkeypatch.setattr(reindex_module, "get_service", lambda: service)
    monkeypatch.setattr(reindex_module, "get_viking_fs", lambda: viking_fs)

    executor = ReindexExecutor()

    async def rebuild(*, uri, mode, run):
        run.counters.scanned_records = 1
        run.counters.rebuilt_records = 1

    executor._reindex_resource = AsyncMock(side_effect=rebuild)
    ctx = RequestContext(
        user=UserIdentifier("acc1", "test_user"),
        role=Role.ROOT,
    )

    result = await executor._run(
        uri=uri,
        object_type="resource",
        mode="vectors_only",
        ctx=ctx,
    )

    assert result["status"] == "completed"
    assert result["uri"] == uri
    assert result["scanned_records"] == 1
    assert result["rebuilt_records"] == 1
    agfs.pathlock_acquire_exact.assert_awaited_once_with(path)
    agfs.pathlock_acquire_tree.assert_not_awaited()
    agfs.pathlock_release.assert_awaited_once_with(lease)
