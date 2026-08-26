"""Format auto-detection table tests."""

from __future__ import annotations

import pytest

from kiln.data.formats import DataFormat, detect_format, detect_row

ALPACA = {"instruction": "2+2?", "output": "4"}
CHATML = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]}
SHAREGPT = {
    "conversations": [
        {"from": "human", "value": "hi"},
        {"from": "gpt", "value": "yo"},
    ]
}


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (ALPACA, DataFormat.ALPACA),
        (CHATML, DataFormat.CHATML),
        (SHAREGPT, DataFormat.SHAREGPT),
        ({"text": "just words"}, None),
        ({}, None),
        ({"messages": "not a list"}, None),  # messages must be a list
        ({"conversations": {}}, None),
        ({"instruction": "x"}, None),  # instruction without output is not alpaca
    ],
)
def test_detect_row(row, expected):
    assert detect_row(row) == expected


def test_majority_vote_wins():
    rows = [CHATML, ALPACA, ALPACA]
    assert detect_format(rows) == DataFormat.ALPACA


def test_all_unrecognized_returns_none():
    assert detect_format([{"foo": 1}, {"bar": 2}]) is None
