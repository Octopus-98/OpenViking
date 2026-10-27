"""Compile conflict counts isolate invalid files and propagate cancellation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openviking.service.compile_targets import CompileLifecycle


async def test_counts_only_unfixed_annotations():
    body = (
        b'body: {"state":"unfixed"}\n<!-- ordinary {"state":"unfixed"} -->\n'
        b'<!-- CONFLICTS_CONTENT {"state":"unfixed"}, {"state":"fixed"} -->'
        b'<!-- CONFLICTS_CONTENT {"state":"unfixed"} -->'
    )
    fs = SimpleNamespace(
        tree=AsyncMock(return_value=[{"uri": "to/page.md", "rel_path": "page.md", "isDir": False}]),
        read_file_bytes=AsyncMock(return_value=body),
    )
    assert await CompileLifecycle(None, fs)._count_conflicts("to", None) == 2


@pytest.mark.parametrize(
    "bad_content",
    [
        b'<!-- CONFLICTS_CONTENT {"state":broken} -->',
        OSError("unreadable output"),
    ],
)
async def test_invalid_file_does_not_hide_valid_conflicts(bad_content):
    fs = SimpleNamespace(
        tree=AsyncMock(
            return_value=[
                {"uri": "to/a-good.md", "rel_path": "a-good.md", "isDir": False},
                {"uri": "to/b-bad.md", "rel_path": "b-bad.md", "isDir": False},
            ]
        ),
        read_file_bytes=AsyncMock(
            side_effect=[b'<!-- CONFLICTS_CONTENT {"state":"unfixed"} -->', bad_content]
        ),
    )
    assert await CompileLifecycle(None, fs)._count_conflicts("to", None) == 1


async def test_cancellation_is_not_treated_as_a_file_error():
    fs = SimpleNamespace(
        tree=AsyncMock(return_value=[{"uri": "to/page.md", "rel_path": "page.md", "isDir": False}]),
        read_file_bytes=AsyncMock(side_effect=asyncio.CancelledError),
    )
    with pytest.raises(asyncio.CancelledError):
        await CompileLifecycle(None, fs)._count_conflicts("to", None)
