# arXiv 论文获取与机构抽取工作流（技术说明）

本文档详细说明本项目中 arXiv 论文抓取接口与工作流的设计与实现要点，包含：
- 如何获取“最近 N 天”的论文
- 如何额外获取作者的机构信息
- arXiv API 的可扩展能力（尚未启用但可支持的用法）

> 参考：日常类目列表页（示例，`show=2000` 展示大容量列表）可用于人工校验抓取效果：
> [`https://arxiv.org/list/cs.LG/2025-04?skip=1075&show=2000`](https://arxiv.org/list/cs.LG/2025-04?skip=1075&show=2000)

---

## 1. 最新 N 天论文获取（后端实现概览）

代码位置：`src/agent/data_graph.py`

- 入口节点：`fetch_arxiv_today`
  - 从 LangGraph `config.configurable` 读取参数：
    - `days`：近 N 天（UTC），默认 1
    - `categories`：分类列表（如 `cs.AI,cs.CV`），`all|*` 表示不过滤分类
    - `max_results`：抓取上限，分页拉取
  - 调用 `_search_papers_by_window(categories, days, max_results)` 获取论文元数据列表

- 关键查询逻辑：`_build_search_query` + arXiv 官方 API `query`
  - 组装 `search_query`：
    - 时间窗：`submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM] OR lastUpdatedDate:[...]`
    - 分类：`cat:cs.AI OR cat:cs.CV ...`（若传入分类）
  - 分页参数：
    - `start`：偏移
    - `max_results`：每页大小（建议控制在数百，避免过大）
  - 排序：`sortBy=submittedDate`，`sortOrder=descending`
  - 解析 Atom Feed，提取：`id/title/summary/authors/categories/pdf_url/published/updated`

- 幂等与去重：
  - 入库时以 `arxiv_entry`（即 `id` 的主编号部分）做唯一约束，`ON CONFLICT DO NOTHING`
  - 兜底唯一对照：`(paper_title, published)`

- 典型抓取调用（底层 arXiv 原始请求示例）：
```bash
curl "https://export.arxiv.org/api/query?search_query=(submittedDate:[202508090000 TO 202508120000] OR lastUpdatedDate:[202508090000 TO 202508120000])%20AND%20(cat:cs.AI%20OR%20cat:cs.CV)&start=0&max_results=100&sortBy=submittedDate&sortOrder=descending" -H "User-Agent: arxiv-scraper/0.1"
```

- 对外 API（本项目）：
```bash
curl -X POST "http://localhost:8000/data/fetch-arxiv-today?thread_id=dashboard&days=3&categories=cs.AI,cs.CV&max_results=200"
```

> 备注：为礼貌使用 API，务必带 `User-Agent`，控制请求频率，分页分批获取并在失败时重试。

---

## 2. 作者机构信息的获取（PDF + LLM）

- 节点：`process_single_paper`
  - 并行策略：使用 LangGraph `Send` 对每篇论文并发执行，且通过全局信号量 `AFFILIATION_MAX_CONCURRENCY`（默认 4）限流
  - 步骤：
    1. 下载 `pdf_url`，用 `pdfplumber` 只解析首页文本（降低开销）
    2. 组装提示词（系统/用户），要求 LLM 严格输出 JSON：作者 → 机构数组
    3. JSON 解析失败或文本缺失时，返回空机构列表，不阻断主流程

- 汇合与写库：
  - 并行完成后，统一在 `upsert_papers` 单节点内串行入库，避免并发写导致的锁冲突
  - 写库内容：
    - `papers`、`authors`、`affiliations` 基础信息
    - 关系表：`author_paper`、`author_affiliation`、`paper_category`

---

## 3. arXiv API 的更多可用能力（可扩展）
> 本节为“可支持”的扩展能力，当前代码未启用；如有需要，可在不大改架构的情况下扩展参数与节点分支。

### 3.1 通过 `arXiv ID` 精确获取
- API 支持使用 `id_list` 精确拉取 1 篇或多篇论文：
```bash
# 单个或多个以逗号分隔
curl "https://export.arxiv.org/api/query?id_list=2504.14636,2504.14645" -H "User-Agent: arxiv-scraper/0.1"
```
- 集成策略：
  - 在抓取入口新增可选参数 `id_list`，若提供则跳过 `search_query`，直接以 `id_list` 拉取
  - 其余流程（PDF/LLM 并行、入库去重）保持不变

### 3.2 指定“某一天”的论文
- 通过时间窗精确到日：将 `start_dt`/`end_dt` 设置为目标日的 `[00:00, 23:59]`（UTC），仍用 `submittedDate` 与 `lastUpdatedDate` 组合：
```text
submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359] OR lastUpdatedDate:[YYYYMMDD0000 TO YYYYMMDD2359]
```
- 集成策略：增加 `date=YYYY-MM-DD` 参数时，内部构造对应的时间窗；`days` 参数忽略

### 3.3 更细的检索维度
- 标题/摘要/作者等字段检索：可组合 `title/author/abstract` 等关键词（API 支持布尔逻辑）
- 类别多选：`cat:cs.AI OR cat:cs.LG ...`
- 去重与排序：
  - `sortBy=submittedDate | lastUpdatedDate | relevance`
  - `sortOrder=ascending | descending`
- 分页：`start` 偏移 + `max_results` 每页大小（建议几百以内）

### 3.4 性能与配额友好
- 请求头务必包含明确的 `User-Agent`
- 控制频率（指数退避/固定间隔），失败重试
- 结果缓存与断点续扫（可结合 LangGraph 的 checkpoint 与自定义游标）

---

## 4. 工作流（LangGraph）概览

```
START
  └─ fetch_arxiv_today  (搜索 N 天 + 分类 + 分页) 
       ├─ Send(process_single_paper) × M  (PDF 首页文本 + LLM 机构映射，并行、限流)
       └─ join
  └─ upsert_papers  (幂等入库、关系表补全)
END
```

- `Send` 并行：对每篇论文独立处理，结果通过状态聚合（列表追加）返回
- 写库集中在单节点，避免并发写导致的死锁与“prepared statement already exists”等问题

### 4.1 Send 并行与并发限制（简述）
- **作用分工**：
  - **Send**：把同一种处理节点对多条数据“扇出并行”执行；每个任务拿到独立输入。
  - **Semaphore**：限制真正“重活”（PDF 下载/LLM 请求）的并发度，防止过载。
- **聚合机制**：状态字段（如 `papers`）使用“累加”聚合（例如 `operator.add`），每个子任务返回 `{"papers": [单条]}`，最终汇合成总列表。
- **接线要点**：
  - 从 `fetch_arxiv_today` 通过 `dispatch_affiliations` 返回若干 `Send("process_single_paper", {...})`。
  - 同时连接 `process_single_paper -> upsert_papers` 和 `fetch_arxiv_today -> upsert_papers`，确保“有任务”和“无任务”两种情形都能汇合并继续。
- **限流示例**：
```python
_AFF_SEM = asyncio.Semaphore(int(os.getenv("AFFILIATION_MAX_CONCURRENCY", 4)))
async with _AFF_SEM:
    # PDF 下载 + LLM 调用（重活）
    ...
```
- **为什么单节点写库**：避免并发写导致的锁竞争/死锁/连接池冲突；吞吐主要受 PDF/LLM 限制而非写库。
- **常见坑**：未聚合 `papers`、漏接 `process_single_paper -> upsert_papers`、不设限流、在并行节点直接写库。

---

## 5. 与当前代码的关系
- 本文档仅描述现有实现与潜在扩展，未修改 `src/agent/data_graph.py`
- 若需要支持 `id_list` 或“某一天”精确拉取，可在 API 层增加参数并复用现有节点

---

## 6. 常见问答
- 为什么有时 `inserted=0, skipped>0`？
  - 表示此前已经入库或满足唯一性约束；这是正常的幂等行为
- 为什么有的论文没有机构？
  - PDF 首页无法抽取、版面结构复杂、LLM JSON 不合规等情况都会导致为空；主流程不因此失败 