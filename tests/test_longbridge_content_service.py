# -*- coding: utf-8 -*-
"""
Unit tests for LongbridgeContentService.

Verifies:
1. Symbol normalization (A-share returns empty, US/HK returns intel)
2. Four priority dimensions are fetched and normalized
3. CLI boundary errors skip the failing dimension gracefully
4. Short TTL cache prevents redundant CLI calls
"""

import json
import os
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.longbridge_content_service import LongbridgeContentService


def _completed(payload):
    return subprocess.CompletedProcess(
        args=["longbridge"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


@patch("src.services.longbridge_content_service.shutil.which", return_value="/usr/local/bin/longbridge")
def test_fetch_intel_returns_empty_for_a_share(_mock_which):
    service = LongbridgeContentService()
    assert service.fetch_intel("600519", "贵州茅台") == {}


@patch("src.services.longbridge_content_service.shutil.which", return_value="/usr/local/bin/longbridge")
@patch("src.services.longbridge_content_service.subprocess.run")
def test_fetch_intel_normalizes_four_priority_dimensions(mock_run, _mock_which):
    mock_run.side_effect = [
        _completed([
            {
                "id": 101,
                "title": "Apple launches new AI features",
                "content": "New on-device AI suite expands to Mac.",
                "url": "https://example.com/news/apple-ai",
                "publisher": "Reuters",
                "published_at": "2026-04-20T12:30:00Z",
            }
        ]),
        _completed([
            {
                "id": 201,
                "title": "10-Q filed",
                "file_name": "aapl-10q.pdf",
                "publish_at": "2026-04-19T08:00:00Z",
                "file_urls": ["https://example.com/filing/aapl-10q.pdf"],
            }
        ]),
        _completed({
            "currency": "USD",
            "current_period": "2026Q2",
            "list": [
                {
                    "period": "2026Q2",
                    "details": [
                        {"key": "Revenue", "estimate": "91.2B", "is_released": False},
                        {"key": "EPS", "estimate": "1.62", "is_released": False},
                    ],
                }
            ],
        }),
        _completed({
            "distribution": {"buy": 28, "hold": 9, "sell": 2},
            "target_price": {"average": "233.5", "high": "260.0", "low": "185.0"},
        }),
    ]

    service = LongbridgeContentService()
    intel = service.fetch_intel("AAPL", "Apple")

    assert list(intel.keys()) == [
        "latest_news",
        "announcements",
        "earnings",
        "market_analysis",
    ]
    assert intel["latest_news"].provider == "LongbridgeCLI"
    assert intel["latest_news"].results[0].published_date == "2026-04-20"
    assert intel["announcements"].results[0].url == "https://example.com/filing/aapl-10q.pdf"
    assert "Revenue=91.2B" in intel["earnings"].results[0].snippet
    assert "buy=28" in intel["market_analysis"].results[0].snippet


@patch("src.services.longbridge_content_service.shutil.which", return_value="/usr/local/bin/longbridge")
@patch("src.services.longbridge_content_service.subprocess.run")
def test_fetch_intel_skips_dimension_when_cli_boundary_fails(mock_run, _mock_which):
    mock_run.side_effect = [
        subprocess.TimeoutExpired(cmd=["longbridge", "news"], timeout=4.0),
        _completed([]),
        _completed({"currency": "USD", "current_period": "2026Q2", "list": []}),
        _completed({"distribution": {"buy": 10, "hold": 3, "sell": 1}}),
    ]

    service = LongbridgeContentService()
    intel = service.fetch_intel("AAPL", "Apple")

    assert "latest_news" not in intel
    assert "market_analysis" in intel


@patch("src.services.longbridge_content_service.shutil.which", return_value="/usr/local/bin/longbridge")
@patch("src.services.longbridge_content_service.subprocess.run")
def test_fetch_intel_uses_short_ttl_cache(mock_run, _mock_which):
    mock_run.side_effect = [
        _completed([]),
        _completed([]),
        _completed({"currency": "USD", "current_period": "2026Q2", "list": []}),
        _completed({"distribution": {"buy": 10, "hold": 3, "sell": 1}}),
    ]

    service = LongbridgeContentService(cache_ttl_seconds=300.0)
    service.fetch_intel("AAPL", "Apple")
    service.fetch_intel("AAPL", "Apple")

    assert mock_run.call_count == 4
