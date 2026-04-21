# -*- coding: utf-8 -*-
"""
Longbridge CLI 资讯服务

职责：
1. 调用本机 longbridge CLI 拉取结构化资讯（news / filing / consensus / institution-rating）
2. symbol 规范化（复用 data_provider.longbridge_fetcher._to_longbridge_symbol）
3. JSON 输出归一化为统一的 SearchResponse / SearchResult
4. 短 TTL 线程安全缓存，避免重复 CLI 调用

边界：
- CLI 不存在或未登录时静默降级，返回空字典
- 单个维度超时或返回非零退出码时跳过该维度，不影响其它维度
- 解析异常直接抛出，不包第二层静默 fallback
"""

import json
import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from data_provider.longbridge_fetcher import _to_longbridge_symbol
from src.search_service import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class LongbridgeContentService:
    _DIMENSIONS = [
        ("latest_news", ["news", "{symbol}", "--count", "5", "--format", "json"]),
        ("announcements", ["filing", "{symbol}", "--format", "json"]),
        ("earnings", ["consensus", "{symbol}", "--format", "json"]),
        ("market_analysis", ["institution-rating", "{symbol}", "--format", "json"]),
    ]

    def __init__(
        self,
        binary: str = "longbridge",
        timeout_seconds: float = 4.0,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, tuple[float, Dict[str, SearchResponse]]] = {}
        self._cache_lock = threading.Lock()

    @property
    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def fetch_intel(self, stock_code: str, stock_name: str) -> Dict[str, SearchResponse]:
        symbol = _to_longbridge_symbol(stock_code)
        if symbol is None or not self.is_available:
            return {}

        cache_key = f"{symbol}:{stock_name}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        results: Dict[str, SearchResponse] = {}
        for dimension, template in self._DIMENSIONS:
            payload = self._run_json_command([part.format(symbol=symbol) for part in template])
            if payload is None:
                continue

            response = self._normalize_dimension(
                dimension=dimension,
                payload=payload,
                stock_name=stock_name,
                symbol=symbol,
            )
            if response.results:
                results[dimension] = response

        self._put_cache(cache_key, results)
        return results

    def _run_json_command(self, args: List[str]) -> Optional[Any]:
        try:
            completed = subprocess.run(
                [self.binary, *args],
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout_seconds,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.warning("Longbridge CLI command skipped at boundary: %s", exc)
            return None

        return json.loads(completed.stdout or "null")

    def _normalize_dimension(
        self,
        *,
        dimension: str,
        payload: Any,
        stock_name: str,
        symbol: str,
    ) -> SearchResponse:
        if dimension in {"latest_news", "announcements"}:
            results = self._normalize_news_like(payload, dimension)
        elif dimension == "earnings":
            results = self._normalize_consensus(payload)
        else:
            results = self._normalize_institution_rating(payload)

        return SearchResponse(
            query=f"longbridge {dimension} {symbol}",
            results=results,
            provider="LongbridgeCLI",
            success=True,
        )

    def _normalize_news_like(self, payload: Any, dimension: str) -> List[SearchResult]:
        rows = payload if isinstance(payload, list) else []
        results: List[SearchResult] = []
        for row in rows[:5]:
            title = str(row.get("title") or row.get("headline") or "").strip()
            if not title:
                continue
            url = (
                row.get("url")
                or row.get("link")
                or (row.get("file_urls") or [""])[0]
            )
            results.append(
                SearchResult(
                    title=title,
                    snippet=str(row.get("content") or row.get("summary") or row.get("file_name") or "").strip(),
                    url=str(url or ""),
                    source="LongbridgeCLI",
                    published_date=self._normalize_date(row.get("published_at") or row.get("publish_at")),
                )
            )
        return results

    def _normalize_consensus(self, payload: Any) -> List[SearchResult]:
        rows = payload.get("list", []) if isinstance(payload, dict) else []
        results: List[SearchResult] = []
        for row in rows[:3]:
            metrics = []
            for detail in row.get("details", [])[:5]:
                key = detail.get("key")
                estimate = detail.get("estimate")
                if key is not None and estimate is not None:
                    metrics.append(f"{key}={estimate}")
            if not metrics:
                continue
            period = row.get("period") or payload.get("current_period") or "current"
            results.append(
                SearchResult(
                    title=f"{period} 一致预期",
                    snippet=", ".join(metrics),
                    url="",
                    source="LongbridgeCLI",
                    published_date=None,
                )
            )
        return results

    def _normalize_institution_rating(self, payload: Any) -> List[SearchResult]:
        if not isinstance(payload, dict):
            return []
        distribution = payload.get("distribution", {})
        target = payload.get("target_price", {})
        snippet = ", ".join(
            [
                f"buy={distribution.get('buy', 0)}",
                f"hold={distribution.get('hold', 0)}",
                f"sell={distribution.get('sell', 0)}",
                f"avg_target={target.get('average', '-')}",
                f"high_target={target.get('high', '-')}",
                f"low_target={target.get('low', '-')}",
            ]
        )
        return [
            SearchResult(
                title="机构评级与目标价",
                snippet=snippet,
                url="",
                source="LongbridgeCLI",
                published_date=None,
            )
        ]

    def _normalize_date(self, value: Any) -> Optional[str]:
        if not value:
            return None
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.date().isoformat()

    def _get_cache(self, key: str) -> Optional[Dict[str, SearchResponse]]:
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is None:
                return None
            ts, value = hit
            if time.time() - ts > self.cache_ttl_seconds:
                self._cache.pop(key, None)
                return None
            return value

    def _put_cache(self, key: str, value: Dict[str, SearchResponse]) -> None:
        with self._cache_lock:
            self._cache[key] = (time.time(), value)
