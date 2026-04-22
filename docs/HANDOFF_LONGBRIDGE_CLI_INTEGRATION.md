# Handoff: Longbridge CLI 资讯层集成

## 任务概览

将 Longbridge CLI 作为优先情报源接入主分析管线，CLI 获取 `news`/`filing`/`consensus`/`institution-rating` 后，搜索服务回填缺失维度（`risk_check`/`industry`）。

## 改了什么

### 新增文件

| 文件 | 说明 |
|------|------|
| `src/services/longbridge_content_service.py` | Longbridge CLI 适配服务，封装 CLI 调用、JSON 解析、数据归一化 |
| `tests/test_longbridge_content_service.py` | 单元测试：初始化、可用性检查、fetch_intel 流程 |
| `tests/test_pipeline_longbridge_intel.py` | 集成测试：Longbridge 优先 + 搜索 fallback 的完整链路 |
| `docs/LONGBRIDGE_CLI_CONTENT_GUIDE.md` | 使用指南：CLI 安装、认证、配置、故障排查 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/core/pipeline.py` | 新增 `_collect_intel_results()`，CLI 优先，搜索补缺失维度 |
| `src/search_service.py` | `search_comprehensive_intel()` 增加 `dimensions` 过滤参数 |
| `src/config.py` | 新增 4 个配置项：`longbridge_cli_enabled/binary/timeout/cache_ttl` |
| `src/analyzer.py` | 空响应同模型重试（最多 2 次 + 1s 延迟） |
| `.env.example` | 新增 Longbridge CLI 配置块 + `LITELLM_FALLBACK_MODELS` 示例 |
| `.gitignore` | 添加 `.omc/` |
| `tests/test_search_news_freshness.py` | dimensions 过滤参数测试 |
| `tests/test_pipeline_optional_service_resilience.py` | Longbridge 服务初始化失败容错测试 |
| `README.md` | 更新架构图和情报源说明 |
| `docs/CHANGELOG.md` | `[Unreleased]` 新增条目 |

### 配置项

```bash
# Longbridge CLI 资讯层
LONGBRIDGE_CLI_ENABLED=true
LONGBRIDGE_CLI_BINARY=longbridge
LONGBRIDGE_CLI_TIMEOUT=4
LONGBRIDGE_CLI_CACHE_TTL=300

# LLM fallback
LITELLM_FALLBACK_MODELS=anthropic/kimi-for-coding,anthropic/claude-sonnet-4-6
```

## 为什么这么改

1. **CLI 数据质量更高**：Longbridge CLI 返回结构化 SEC 公告、一致预期、机构评级，比搜索抓取更可靠
2. **减少搜索 API 调用**：4 个核心维度由 CLI 覆盖，搜索只补 `risk_check`/`industry`
3. **空响应重试**：cliproxy 偶发返回空 content，同模型重试避免不必要的模型切换

## 验证情况

### 单元测试

```bash
python -m pytest tests/test_longbridge_content_service.py -v
python -m pytest tests/test_pipeline_longbridge_intel.py -v
python -m pytest tests/test_search_news_freshness.py -v
python -m pytest tests/test_pipeline_optional_service_resilience.py -v
```

全部通过。

### 端到端测试（ARKK, ASTS, RDW）

```bash
python main.py --stocks ARKK,ASTS,RDW --debug
```

- LongbridgeCLI 成功获取 news/filing/consensus/institution-rating
- 数据存入 `news_intel` 表，provider='LongbridgeCLI'
- 搜索 fallback 补充 risk_check/industry
- LLM 分析生成完整报告

### LLM 模型测试

| 模型 | 耗时 | 响应长度 | 状态 |
|------|------|----------|------|
| openai/gpt-5.4 | ~40s | ~4000 字符 | 正常 |
| anthropic/kimi-for-coding | 64.2s | 5141 字符 | 正常 |
| anthropic/claude-sonnet-4-6 | 62.1s | 5947 字符 | 正常 |

## 未验证项

- CI 流水线未跑（本地 worktree 环境）
- Docker 构建未验证
- 大盘复盘在 LLM 空响应时仍可能 fallback 到模板（已加重试，但代理层偶发问题无法完全消除）

## 风险点

1. **CLI 认证独立**：Longbridge CLI 使用 `longbridge auth login`（存储在 `~/.longbridge/`），与 OpenAPI SDK 的 `LONGBRIDGE_APP_KEY` 完全独立。CLI 未登录时服务静默降级为搜索 fallback
2. **CLI 超时边界**：单个维度 4 秒超时，4 个维度串行执行最长 16 秒。网络波动时可能部分维度缺失
3. **缓存 TTL**：300 秒线程安全缓存，避免重复 CLI 调用。同一股票在 5 分钟内多次分析会复用缓存
4. **LLM fallback 依赖 anthropic 接口**：kimi 和 claude 均走 `anthropic/` 前缀，需要 `ANTHROPIC_API_KEY` 配置

## 回滚方式

```bash
# 禁用 CLI 资讯层（无需改代码）
export LONGBRIDGE_CLI_ENABLED=false

# 或回滚代码到集成前
git revert 31a6b69
```

## 后续建议

1. 监控 `news_intel` 表中 provider='LongbridgeCLI' 的数据占比，评估 CLI 覆盖效果
2. 若 CLI 调用频繁超时，考虑将 `LONGBRIDGE_CLI_TIMEOUT` 调大或并行化维度调用
3. 考虑将机构评级数据接入评分算法（当前只做展示，未参与评分计算）
