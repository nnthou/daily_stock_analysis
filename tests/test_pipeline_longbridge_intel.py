# -*- coding: utf-8 -*-
"""
Tests for Longbridge-first + search fallback intel collection in pipeline.
"""

from unittest.mock import MagicMock

from src.core.pipeline import StockAnalysisPipeline
from src.search_service import SearchResponse, SearchResult


def _resp(query: str, title: str) -> SearchResponse:
    return SearchResponse(
        query=query,
        results=[SearchResult(title=title, snippet="snippet", url="", source="test")],
        provider="test",
        success=True,
    )


def test_collect_intel_results_prefers_longbridge_then_searches_missing_dimensions():
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.longbridge_content_service = MagicMock()
    pipeline.search_service = MagicMock()

    pipeline.longbridge_content_service.is_available = True
    pipeline.longbridge_content_service.fetch_intel.return_value = {
        "latest_news": _resp("lb news", "lb-news"),
        "earnings": _resp("lb consensus", "lb-earnings"),
    }
    pipeline.search_service.is_available = True
    pipeline.search_service.search_comprehensive_intel.return_value = {
        "announcements": _resp("search announcements", "search-announcement"),
        "market_analysis": _resp("search analysis", "search-analysis"),
        "risk_check": _resp("search risk", "search-risk"),
        "industry": _resp("search industry", "search-industry"),
    }
    pipeline.search_service.format_intel_report.return_value = "formatted-context"

    intel, context = pipeline._collect_intel_results("AAPL", "Apple")

    pipeline.search_service.search_comprehensive_intel.assert_called_once_with(
        stock_code="AAPL",
        stock_name="Apple",
        max_searches=4,
        dimensions=["announcements", "market_analysis", "risk_check", "industry"],
    )
    assert list(intel.keys()) == [
        "latest_news",
        "earnings",
        "announcements",
        "market_analysis",
        "risk_check",
        "industry",
    ]
    assert context == "formatted-context"


def test_collect_intel_results_uses_full_search_when_longbridge_unavailable():
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.longbridge_content_service = None
    pipeline.search_service = MagicMock()
    pipeline.search_service.is_available = True
    pipeline.search_service.search_comprehensive_intel.return_value = {
        "latest_news": _resp("search news", "search-news"),
    }
    pipeline.search_service.format_intel_report.return_value = "search-only"

    intel, context = pipeline._collect_intel_results("600519", "贵州茅台")

    pipeline.search_service.search_comprehensive_intel.assert_called_once_with(
        stock_code="600519",
        stock_name="贵州茅台",
        max_searches=6,
        dimensions=["latest_news", "announcements", "market_analysis", "risk_check", "earnings", "industry"],
    )
    assert list(intel.keys()) == ["latest_news"]
    assert context == "search-only"
