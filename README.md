# ArXiv 爬取 + 机构抽取 + 网络搜索 + OpenAlex 全球学术查询 + 最小聊天 + 前端看板

## 项目简介

- 从 arXiv 抓取近 N 天论文，写入规范化数据库表（papers/authors/affiliations 等），并为作者抽取机构（PDF 首页 + LLM 映射）。
- 集成 OpenAlex（全球最大的开放学术数据库）提供全面学术查询能力，支持作者消歧、博士生筛选、跨期刊论文搜索等高级功能。
- 提供 Tavily 网络搜索功能，可搜索研究人员的详细信息、职位角色等。
- 支持论文标题和 arXiv ID 的模糊搜索，快速定位相关文献。
- 提供最小聊天接口（DashScope 兼容 OpenAI）。
- 提供前端 React 看板（Vite + Ant Design），展示总览、作者检索、网络搜索与最新论文流。
- 新增 ORCID 富化：基于作者姓名 + 机构相似匹配补全作者 ORCID 与作者-机构的 role/start_date/end_date，支持角色信息完整组合。

技术栈：FastAPI、LangGraph（Send 并行）、psycopg3、requests、pdfplumber、Tavily API、Supabase Python SDK（通用查询）、**pyalex（OpenAlex Python SDK）**、React + Ant Design、ORCID Public API。

## 目录结构
- `src/agent/graph.py`：最小聊天图（start → chat → end）
- `src/agent/data_graph.py`：arXiv 抓取 → 并行机构抽取（Send）→ 规范化入库
- `src/agent/utils.py`：工具函数（arXiv API、PDF 解析、ORCID、QS 排名、Tavily 网络搜索）
- `src/agent/openalex_utils.py`：OpenAlex 集成工具（全球学术数据查询、作者消歧、博士生筛选）
- `src/api/openalex_api.py`：OpenAlex API 接口（作者/论文/机构高级搜索）
- `src/api/graph.py`：聊天 API
- `src/api/data_processing.py`：抓取 API
- `src/api/dashboard.py`：看板 API（总览、作者检索、网络搜索、论文搜索）
- `src/db/`：数据库连接、LangGraph checkpoint、Supabase 通用客户端
- `frontend/`：React 看板（Vite + TS + AntD）

## 环境依赖
- Python >= 3.11
- PostgreSQL / Supabase Postgres
- Node >= 18（仅前端）

## 环境变量
在项目根目录创建 `.env`，示例：

```
# 数据库（后端必需）
DATABASE_URL=postgresql://用户名:密码@主机:端口/数据库名

# DashScope 兼容 OpenAI（机构抽取与聊天）
DASHSCOPE_API_KEY=你的阿里云百炼API密钥
AFFILIATION_MODEL=qwen-max   # 可选，默认 qwen-max；也可用 QWEN_MODEL

# Tavily API（网络搜索功能）
TAVILY_API_KEY=你的Tavily API密钥

# ORCID API（作者信息富化）
ORCID_CLIENT_ID=你的ORCID客户端ID
ORCID_CLIENT_SECRET=你的ORCID客户端密钥

# OpenAlex API（全球学术数据查询，可选）
OPENALEX_EMAIL=你的邮箱地址  # 进入 polite pool，获得更快响应速度
OPENALEX_API_KEY=你的OpenAlex API密钥  # 可选，但有助于提升请求限额

# Supabase Python SDK（通用查询，供看板 API 使用）
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=你的Supabase匿名键
```

说明：
- `DATABASE_URL` 可使用 Supabase 提供的 Postgres 连接串或本地 Postgres。
- `TAVILY_API_KEY` 用于网络搜索功能，可在 [Tavily](https://tavily.com) 获取。
- `OPENALEX_EMAIL` 用于进入 OpenAlex 的 polite pool，获得更快更稳定的响应速度。
- `OPENALEX_API_KEY` 可选，但有助于提升 OpenAlex API 的请求限额。
- 机构抽取依赖 `pdfplumber` 抽取 PDF 首页文本 + LLM 严格 JSON 映射作者 → 机构名，顺序与 arXiv 作者序一致；失败时不阻断流程。

## 安装与运行（后端）

安装依赖：

```bash
pip install .
# 或手动安装核心依赖
pip install fastapi uvicorn psycopg3 requests pdfplumber langchain-openai langgraph tavily-python supabase pyalex
```

启动 API 服务：

```bash
python -m src.main
```

- 服务默认 `http://localhost:8000`
- Swagger：`http://localhost:8000/docs`

## API 一览（后端）

### 数据抓取与处理

- 抓取与入库：`POST /data/fetch-arxiv-today`
  - 查询参数：
    - `thread_id`：LangGraph checkpoint 线程 ID
    - `categories`：逗号分隔，如 `cs.AI,cs.CV`；传 `all|*` 表示不过滤分类
    - `max_results`：抓取上限（分页累积），默认 200
    - `start_date`：起始日期（YYYY-MM-DD）。若未提供，将默认 `today-1`（UTC）。
    - `end_date`：结束日期（YYYY-MM-DD，含当日）。若未提供，将默认 `today`（UTC）；最大不可超过当天。
  - 示例：
```bash
curl -X POST \
  "http://localhost:8000/data/fetch-arxiv-today?thread_id=1&categories=all&max_results=200&start_date=2025-08-11&end_date=2025-08-12"
```
  - 成功响应：
  ```json
  { "status": "success", "inserted": 123, "skipped": 45, "fetched": 168 }
  ```

- 按 ID 抓取与入库：`POST /data/fetch-arxiv-by-id?ids=2504.14636,2504.14645&thread_id=...`

### 数据富化接口

- 现有机构对齐（QS 富化）：`POST /data/enrich-affiliations-qsrank`
  - 功能：基于 `docs/qs-world-rankings-2025.csv` 将 `affiliations.country` 与 `affiliation_rankings`（QS 2024/2025）补全。
  - 匹配：忽略大小写/空格；自动去括号、去部门前缀、截取逗号前主体；支持相似度匹配（阈值设定，避免误配）。
  - 可选参数：`force_country`、`force_rank`（布尔），用于覆盖已有国家/排名。

- 批量 ORCID 富化：`POST /data/enrich-orcid`
  - 功能：批量为既有作者-机构关系补齐 `authors.orcid` 与 `author_affiliation.role/start_date/end_date`。
  - 匹配：作者姓名严格相等，机构采用相似度匹配（阈值≈0.86）。
  - 参数：
    - `only_missing`：布尔，默认 `true`。为 `true` 时只更新 NULL 值；为 `false` 时覆盖所有匹配数据。
    - `batch_size`：批次大小，默认 200
    - `max_rows`：处理上限，默认 2000
  - 角色信息：自动组合 `role-title + (department-name)`，如 `"Senior Staff Engineer (Tongyi Lab)"`

- 单个作者 ORCID 富化：`POST /data/enrich-orcid-author`
  - 功能：为指定作者补齐 ORCID 与机构关系信息。
  - 参数：
    - `author_id`：作者 ID（必需）
    - `overwrite`：布尔，默认 `false`。为 `true` 时覆盖现有数据；为 `false` 时只更新空值。
  - 示例：`POST /data/enrich-orcid-author?author_id=796&overwrite=true`

- 单个作者 OpenAlex 富化： `POST /data/enrich-openalex-author`
  - 功能：为指定作者补齐 OpenAlex 学术指标与研究领域信息。
  - 参数：
    - `author_id` ：作者 ID（必需）
    - `overwrite` ：布尔，默认 `false` 。为 `true` 时覆盖现有数据；为 `false` 时只更新空值。
  - 示例： `POST /data/enrich-openalex-author?author_id=796&overwrite=true`

### 看板与搜索接口

- 看板总览：`GET /dashboard/overview` - 返回论文/作者/机构/类别总数统计
- 作者检索：`GET /dashboard/author?q=模糊人名` - 支持大小写与空格不敏感的作者搜索
- 最新论文：`GET /dashboard/latest-papers?page=1&limit=20&title_search=关键词&arxiv_search=ID` 
  - 支持论文标题模糊搜索（`title_search`）
  - 支持 arXiv ID 模糊搜索（`arxiv_search`）
  - 分页展示，包含作者和类别信息

### 网络搜索接口

- 通用网络搜索：`POST /dashboard/web-search?name=人名&affiliation=机构名&search_prompt=搜索问题`
  - 功能：使用 Tavily API 进行网络搜索，支持自定义搜索问题
  - 返回：AI 摘要、相关网页结果、搜索源链接
  - 示例：`search_prompt="What research does"` 或 `"Tell me about the publications of"`

- 角色搜索：`POST /dashboard/search-role?name=人名&affiliation=机构名`
  - 功能：专门搜索某人在某机构的职位角色
  - 返回：提取的角色信息、AI 摘要、搜索结果

### 其他接口

- 聊天：`POST /agent/chat` - DashScope 兼容的聊天接口
- 数据图表：
  - `GET /dashboard/charts/affiliation-paper-count?days=7` - 机构论文数量统计
  - `GET /dashboard/charts/affiliation-author-count?days=7` - 机构作者数量统计

## OpenAlex 全球学术查询 API

基于 OpenAlex（全球最大开放学术数据库）提供的高级学术查询接口，支持跨期刊、跨学科的全面学术数据分析。

### 作者相关接口

- 作者搜索：`GET /openalex/authors/search?name=姓名&institutions=机构&country=国家代码`
  - 支持按姓名、机构、国家等多维度搜索
  - 提供作者消歧和机构匹配
  - 返回学术指标、研究领域、ORCID 等详细信息

- 博士生筛选：`GET /openalex/authors/phd-candidates?institutions=北京大学,清华大学&research_areas=artificial intelligence`
  - 基于启发式规则筛选疑似博士生
  - 支持按机构、研究领域、发文量等条件筛选
  - 提供可能性评分和学术概况分析
  - 示例实际场景：找到北大、浙大、清华的人工智能方向在读博士

- 合作网络：`GET /openalex/authors/{author_id}/collaboration?limit=50`
  - 分析作者的合作网络和频繁合作者
  - 提供合作统计和近期合作论文信息

### 论文相关接口

- 高级论文搜索：`GET /openalex/papers/search`
  - 参数：`title`, `author_name`, `institutions`, `concepts`, `publication_year_start/end`, `is_oa`, `min_citations`, `sort_by`
  - 支持多维度筛选：标题、作者、机构、研究领域、年份、开放获取状态、引用数等
  - 返回完整论文信息、作者列表、机构信息、摘要等

- 趋势论文：`GET /openalex/papers/trending?research_areas=machine learning&time_period=365`
  - 基于时间窗口和引用增长计算趋势得分
  - 发现特定领域的热门和新兴论文

### 机构相关接口

- 机构搜索：`GET /openalex/institutions/search?query=机构名&country=CN&institution_type=education`
  - 支持按名称、国家、机构类型搜索
  - 返回机构基本信息、学术指标、官网链接等

- 机构研究概况：`GET /openalex/institutions/profile?name=清华大学&years_back=5`
  - 分析机构的研究概况和学术统计
  - 包括论文数量、引用统计、开放获取比例、主要研究领域分布
  - 提供时间序列分析和年度趋势

### 研究概念接口

- 概念搜索：`GET /openalex/concepts/search?query=machine learning&level=2`
  - 搜索研究概念和学科领域
  - 支持按层级筛选（0-5级概念体系）
  - 返回概念描述、论文数量、学科归属等

## 数据处理流程

### 整体执行流程
```
1. fetch_arxiv_today     → 获取论文列表
2. dispatch_affiliations → 分发并行处理任务（使用 LangGraph Send）
   ├─ process_single_paper     (并行) → PDF解析 + LLM机构抽取
   └─ process_orcid_for_paper  (并行) → ORCID查询 + 角色信息抽取
3. upsert_papers         → 汇总并写入数据库
```

### 详细说明

- **arXiv 获取**（`fetch_arxiv_today`）：
  - 使用官方 API `search_query` 构造时间窗查询（`submittedDate`/`lastUpdatedDate`），结合分类（`cat:xxx`）与分页（`start/max_results`）。
  - 查询参数支持 `start_date/end_date`（优先）或默认 `[today-1, today]`，`categories=all|*` 时不做分类过滤。
  - 解析 Atom Feed 获取 `id/title/summary/authors/categories/pdf 链接/published/updated` 等字段。
  - 幂等：以 `arxiv_entry` 去重（`ON CONFLICT DO NOTHING`），已存在则跳过；也兜底按 `(paper_title, published)` 唯一对照。

- **并行处理**（`dispatch_affiliations` + `Send`）：
  - 使用 LangGraph 的 `Send` 机制为每篇论文创建两个并行任务：
    - `process_single_paper`：PDF首页抽取 + LLM机构映射
    - `process_orcid_for_paper`：ORCID查询 + 作者-机构关系富化
  - 并发数量受限（环境变量控制），避免API限流
  - 所有并行任务完成后自动汇聚到下一步

- **机构抽取**（`process_single_paper`）：
  - 使用 `pdfplumber` 抽取 PDF 首页文本（短退避重试，不阻断流程）。
  - 使用 Qwen 将作者列表映射到机构名列表（英文标准化空格/大小写）。

- **ORCID 富化**（`process_orcid_for_paper`）：
  - 并行尝试 ORCID（受限并发），仅在"作者姓名严格一致 + 机构相似匹配通过"时，补全 `authors.orcid` 与 `author_affiliation.role/start_date/end_date`（保守更新）。
  - 角色信息自动组合 `role-title + (department-name)`，如 `"Senior Staff Engineer (Tongyi Lab)"`

- **数据库写入**（`upsert_papers`）：
  - 等待所有并行任务完成后，统一写库避免锁冲突
  - QS 富化：按 QS CSV 对机构做补全，命中则写 `affiliations.country` 与 `affiliation_rankings`

- **网络搜索增强**：
  - Tavily API 集成：提供研究人员信息的实时网络搜索
  - 支持自定义搜索提示词，灵活查询各类信息
  - LLM 自动提取关键信息（如职位、角色等）

- **可靠性保证**：
  - 错误与空结果被安全吞吐，保证主流程可完成；缺失字段入库为 NULL
  - LangGraph 可视化中的"断开"节点是正常现象（`Send` 动态并行的可视化限制）

### 详细说明

- **arXiv 获取**：
  - 使用官方 API `search_query` 构造时间窗查询（`submittedDate`/`lastUpdatedDate`），结合分类（`cat:xxx`）与分页（`start/max_results`）。
  - 查询参数支持 `start_date/end_date`（优先）或默认 `[today-1, today]`，`categories=all|*` 时不做分类过滤。
  - 解析 Atom Feed 获取 `id/title/summary/authors/categories/pdf 链接/published/updated` 等字段。
  - 幂等：以 `arxiv_entry` 去重（`ON CONFLICT DO NOTHING`），已存在则跳过；也兜底按 `(paper_title, published)` 唯一对照。

- **机构抽取**：
  - 使用 `pdfplumber` 抽取 PDF 首页文本（短退避重试，不阻断流程）。
  - 使用 Qwen 将作者列表映射到机构名列表（英文标准化空格/大小写）。
  - LangGraph `Send` 并行抽取，统一写库避免锁冲突。

- **QS 富化**：
  - 抓取流程与历史对齐接口均会按 QS CSV 对机构做补全：命中则写 `affiliations.country`，并为 2024/2025 写入 `affiliation_rankings`；未命中不影响主流程。

- **ORCID 富化**：
  - 新数据：抓取流程内并行尝试 ORCID（受限并发），仅在“作者姓名严格一致 + 机构相似匹配通过”时，补全 `authors.orcid` 与 `author_affiliation.role/start_date/end_date`（保守更新）。
  - 老数据：可用临时接口一键回填；失败或未命中均不影响主流程。

- **并发与可靠性**：
  - PDF/LLM 与 ORCID 查询并发受控；数据库写入集中在单节点串行执行，避免死锁。
  - 错误与空结果被安全吞吐，保证主流程可完成；缺失字段入库为 NULL。

## 前端看板（frontend/）

- 技术栈：Vite + React + TypeScript + Ant Design
- 功能：
  - **总览卡片**：论文/作者/机构/类别计数统计
  - **OpenAlex 全球学术查询**（🆕 核心功能）：
    - **作者搜索**：按姓名、机构、国家等条件搜索全球作者，提供详细学术指标和研究领域
    - **博士生筛选**：智能筛选指定机构的疑似博士生候选人，支持按研究领域、发文量等条件过滤
    - **论文高级搜索**：多维度论文检索，支持标题、作者、机构、概念、年份、引用数等复合筛选
    - **机构分析**：搜索全球学术机构，查看机构研究概况、学术统计和主要研究领域
    - **合作网络分析**：可视化作者的合作网络和频繁合作者信息
  - **作者搜索**：模糊检索（大小写与空格不敏感），展示 ORCID、机构（含 role/起止/latest）、最近论文、常合作作者，QS 标签含 2025/2024 且显示名次变化箭头
  - **网络搜索工具**：
    - 支持输入人名、机构名和自定义搜索提示词
    - 提供专门的角色搜索功能
    - 展示 AI 摘要和相关网页源链接
    - 结果可折叠展示，支持外链跳转
  - **最新论文流**：
    - 分页展示，支持论文标题和 arXiv ID 模糊搜索
    - 集成论文搜索功能，实时筛选匹配结果
    - 支持在顶部直接发起抓取（日期范围/类别/上限、或按 ID）
    - 搜索状态下显示匹配数量和筛选提示

### OpenAlex 全球学术查询特色

- **多标签页设计**：作者搜索、博士生查询、论文搜索、机构分析、合作网络五大功能模块
- **智能博士生筛选**：基于发文量、学术年龄、引用数等启发式规则，自动评分排序
- **高级论文筛选**：支持开放获取过滤、引用数阈值、多研究领域交叉检索
- **机构研究画像**：可视化展示机构的论文统计、引用分析、研究领域分布
- **实时数据交互**：所有查询结果支持分页、排序、详情展开，响应式设计
### 网络搜索界面特点
- **双模式搜索**：通用搜索（自定义问题）+ 专门角色搜索
- **智能结果展示**：AI 摘要卡片 + 折叠式源链接列表
- **实时反馈**：搜索状态指示、错误处理、加载动画
- **用户友好**：表单验证、清空功能、响应式布局

### 论文搜索界面特点
- **灵活筛选**：支持论文标题或 arXiv ID 两种搜索模式
- **即时切换**：选择搜索类型后动态更新提示词
- **状态管理**：搜索与清空操作，重置分页状态
- **结果计数**：动态显示匹配结果数量

### 界面预览

![ArXiv Intelligence Dashboard](./webui.png)

- 启动：
  ```bash
  cd frontend
  npm install
  npm run dev
  ```
  打开 `http://localhost:5173`
  - 构建：
  ```bash
  npm run build
  # 产物在 frontend/dist，可用任意静态服务器部署
  ```

## 使用示例

### OpenAlex 全球学术查询示例

1. **智能博士生筛选**（解决实际需求：找到北大、浙大、清华的人工智能方向在读博士）：
   ```bash
   curl -X GET "http://localhost:8000/openalex/authors/phd-candidates" \
     -G -d "institutions=北京大学,浙江大学,清华大学" \
     -d "research_areas=artificial intelligence,machine learning,computer science" \
     -d "country=CN" \
     -d "min_works=3" \
     -d "max_works=20"
   ```

2. **作者消歧和详细信息查询**：
   ```bash
   curl -X GET "http://localhost:8000/openalex/authors/search" \
     -G -d "name=Geoffrey Hinton" \
     -d "institutions=University of Toronto" \
     -d "country=CA"
   ```

3. **跨期刊高级论文搜索**：
   ```bash
   curl -X GET "http://localhost:8000/openalex/papers/search" \
     -G -d "title=transformer attention" \
     -d "concepts=artificial intelligence,natural language processing" \
     -d "publication_year_start=2020" \
     -d "min_citations=50" \
     -d "is_oa=true" \
     -d "sort_by=cited_by_count"
   ```

4. **机构研究概况分析**：
   ```bash
   curl -X GET "http://localhost:8000/openalex/institutions/profile" \
     -G -d "name=清华大学" \
     -d "years_back=5"
   ```

5. **合作网络分析**：
   ```bash
   curl -X GET "http://localhost:8000/openalex/authors/A2887243803/collaboration" \
     -G -d "limit=20"
   ```

### 网络搜索功能示例

1. **通用搜索**：
   ```bash
   curl -X POST "http://localhost:8000/dashboard/web-search" \
     -G -d "name=Geoffrey Hinton" \
     -d "affiliation=University of Toronto" \
     -d "search_prompt=What research achievements and awards has"
   ```

2. **角色搜索**：
   ```bash
   curl -X POST "http://localhost:8000/dashboard/search-role" \
     -G -d "name=Yann LeCun" \
     -d "affiliation=New York University"
   ```

### 论文搜索功能示例

1. **按标题搜索**：
   ```bash
   curl "http://localhost:8000/dashboard/latest-papers?title_search=transformer&page=1&limit=10"
   ```

2. **按 arXiv ID 搜索**：
   ```bash
   curl "http://localhost:8000/dashboard/latest-papers?arxiv_search=2504.14&page=1&limit=10"
   ```

### 前端界面操作

1. **OpenAlex 全球学术查询**：
   - 在"OpenAlex 全球学术查询系统"卡片中选择相应标签页
   - **博士生查询**：输入目标机构（如"北京大学,清华大学,浙江大学"）和研究领域，系统会基于启发式规则智能筛选并评分
   - **作者搜索**：按姓名、机构、国家等条件搜索，查看详细学术指标和研究领域
   - **论文搜索**：多维度筛选，支持标题、作者、机构、概念、年份、引用数等复合条件
   - **机构分析**：搜索全球学术机构，查看研究概况和统计数据
   - **合作网络**：从作者搜索结果中点击"合作网络"按钮，查看作者的学术合作关系

2. **网络搜索工具**：
   2. **网络搜索工具**：
   - 输入自定义搜索问题，如"What research does"、"Tell me about recent work by"
   - 点击"General Search"获取综合信息，或"Find Role/Position"获取职位信息
   - 查看 AI 摘要和相关网页源链接

2. **论文搜索**：
   2. **论文搜索**：
   - 选择搜索类型：论文标题或 arXiv ID
   - 输入关键词后点击"Search"按钮
   - 查看筛选后的论文列表，标题显示匹配数量## 备注
- 若抓取响应 `inserted=0, skipped=0` 且 `fetched>0`：通常是并行聚合/版本不一致或 RLS/权限问题；已将 Send 并行按官方推荐接线并在写库前汇合。Supabase RLS 下请确保 INSERT 策略放行。
- 若机构为空：可能 PDF 不可抽取或 LLM 返回不规范；已加入短退避重试与严格 JSON 解析，仍失败则为空。
- ORCID 富化支持灵活更新策略：批量接口用 `only_missing` 参数，单个作者接口用 `overwrite` 参数，可根据需要选择只更新空值或完全覆盖。
- **网络搜索功能**：需要有效的 `TAVILY_API_KEY`，若未配置则相关功能会提示不可用。搜索结果基于实时网页内容，准确性依赖于网络资源质量。
- **论文搜索功能**：支持标题的模糊匹配和 arXiv ID 的部分匹配，搜索对大小写不敏感。
- **OpenAlex 集成功能**（🆕 重要补充）：
  - OpenAlex 是全球最大的开放学术数据库，覆盖 2.5 亿+论文、1 亿+作者、10 万+机构
  - 提供强大的作者消歧能力，有效解决同名作者区分问题
  - 支持跨期刊、跨学科的全面学术分析，弥补单一 arXiv 数据源的不足
  - 博士生筛选基于启发式规则（发文量、学术年龄、引用模式等），仅供参考，实际判断需结合多方信息
  - API 请求建议设置 `OPENALEX_EMAIL` 进入 polite pool，获得更稳定的服务
- **关于 LangGraph 可视化**：LangSmith 中显示的"断开"节点是正常现象，这是由于 `Send` 函数创建的动态并行边在静态图中无法预先显示。实际执行时所有并行任务会正确运行并汇聚。

---
如需扩展：
- 后端：增加 OCR 兜底、机构名规范化、缓存/重试策略、更多搜索数据源集成等
- 前端：类别分布图、更多筛选与导出功能、搜索历史记录、结果保存等
- **OpenAlex 深度集成**：引用网络分析、学术影响力评估、研究趋势预测、机构合作网络等高级功能

## Supabase RLS 策略（开发/看板用）

注意：以下策略仅用于本地开发或内部环境，放开了匿名与已认证角色的“读/写/改/删”。生产环境请按需收紧，切勿对公网直接暴露写权限。

在 Supabase SQL Editor 执行：

```sql
-- 为下列表启用 RLS，并放开 anon、authenticated 读/写/改/删
-- 安全提示：生产环境请改为更细粒度策略

-- helper: 为一个表创建四个策略
-- 用法：将 <table_name> 依次替换为每张表名
-- 也可直接执行下方逐表语句

-- affiliation_rankings
alter table public.affiliation_rankings enable row level security;
create policy "anon/auth can select affiliation_rankings" on public.affiliation_rankings for select to anon, authenticated using (true);
create policy "anon/auth can insert affiliation_rankings" on public.affiliation_rankings for insert to anon, authenticated with check (true);
create policy "anon/auth can update affiliation_rankings" on public.affiliation_rankings for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete affiliation_rankings" on public.affiliation_rankings for delete to anon, authenticated using (true);

-- affiliations
alter table public.affiliations enable row level security;
create policy "anon/auth can select affiliations" on public.affiliations for select to anon, authenticated using (true);
create policy "anon/auth can insert affiliations" on public.affiliations for insert to anon, authenticated with check (true);
create policy "anon/auth can update affiliations" on public.affiliations for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete affiliations" on public.affiliations for delete to anon, authenticated using (true);

-- author_affiliation
alter table public.author_affiliation enable row level security;
create policy "anon/auth can select author_affiliation" on public.author_affiliation for select to anon, authenticated using (true);
create policy "anon/auth can insert author_affiliation" on public.author_affiliation for insert to anon, authenticated with check (true);
create policy "anon/auth can update author_affiliation" on public.author_affiliation for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete author_affiliation" on public.author_affiliation for delete to anon, authenticated using (true);

-- author_paper
alter table public.author_paper enable row level security;
create policy "anon/auth can select author_paper" on public.author_paper for select to anon, authenticated using (true);
create policy "anon/auth can insert author_paper" on public.author_paper for insert to anon, authenticated with check (true);
create policy "anon/auth can update author_paper" on public.author_paper for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete author_paper" on public.author_paper for delete to anon, authenticated using (true);

-- author_people_verified
alter table public.author_people_verified enable row level security;
create policy "anon/auth can select author_people_verified" on public.author_people_verified for select to anon, authenticated using (true);
create policy "anon/auth can insert author_people_verified" on public.author_people_verified for insert to anon, authenticated with check (true);
create policy "anon/auth can update author_people_verified" on public.author_people_verified for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete author_people_verified" on public.author_people_verified for delete to anon, authenticated using (true);

-- authors
alter table public.authors enable row level security;
create policy "anon/auth can select authors" on public.authors for select to anon, authenticated using (true);
create policy "anon/auth can insert authors" on public.authors for insert to anon, authenticated with check (true);
create policy "anon/auth can update authors" on public.authors for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete authors" on public.authors for delete to anon, authenticated using (true);

-- categories
alter table public.categories enable row level security;
create policy "anon/auth can select categories" on public.categories for select to anon, authenticated using (true);
create policy "anon/auth can insert categories" on public.categories for insert to anon, authenticated with check (true);
create policy "anon/auth can update categories" on public.categories for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete categories" on public.categories for delete to anon, authenticated using (true);

-- checkpoint_blobs
alter table public.checkpoint_blobs enable row level security;
create policy "anon/auth can select checkpoint_blobs" on public.checkpoint_blobs for select to anon, authenticated using (true);
create policy "anon/auth can insert checkpoint_blobs" on public.checkpoint_blobs for insert to anon, authenticated with check (true);
create policy "anon/auth can update checkpoint_blobs" on public.checkpoint_blobs for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete checkpoint_blobs" on public.checkpoint_blobs for delete to anon, authenticated using (true);

-- checkpoint_migrations
alter table public.checkpoint_migrations enable row level security;
create policy "anon/auth can select checkpoint_migrations" on public.checkpoint_migrations for select to anon, authenticated using (true);
create policy "anon/auth can insert checkpoint_migrations" on public.checkpoint_migrations for insert to anon, authenticated with check (true);
create policy "anon/auth can update checkpoint_migrations" on public.checkpoint_migrations for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete checkpoint_migrations" on public.checkpoint_migrations for delete to anon, authenticated using (true);

-- checkpoint_writes
alter table public.checkpoint_writes enable row level security;
create policy "anon/auth can select checkpoint_writes" on public.checkpoint_writes for select to anon, authenticated using (true);
create policy "anon/auth can insert checkpoint_writes" on public.checkpoint_writes for insert to anon, authenticated with check (true);
create policy "anon/auth can update checkpoint_writes" on public.checkpoint_writes for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete checkpoint_writes" on public.checkpoint_writes for delete to anon, authenticated using (true);

-- checkpoints
alter table public.checkpoints enable row level security;
create policy "anon/auth can select checkpoints" on public.checkpoints for select to anon, authenticated using (true);
create policy "anon/auth can insert checkpoints" on public.checkpoints for insert to anon, authenticated with check (true);
create policy "anon/auth can update checkpoints" on public.checkpoints for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete checkpoints" on public.checkpoints for delete to anon, authenticated using (true);

-- keywords
alter table public.keywords enable row level security;
create policy "anon/auth can select keywords" on public.keywords for select to anon, authenticated using (true);
create policy "anon/auth can insert keywords" on public.keywords for insert to anon, authenticated with check (true);
create policy "anon/auth can update keywords" on public.keywords for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete keywords" on public.keywords for delete to anon, authenticated using (true);

-- paper_category
alter table public.paper_category enable row level security;
create policy "anon/auth can select paper_category" on public.paper_category for select to anon, authenticated using (true);
create policy "anon/auth can insert paper_category" on public.paper_category for insert to anon, authenticated with check (true);
create policy "anon/auth can update paper_category" on public.paper_category for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete paper_category" on public.paper_category for delete to anon, authenticated using (true);

-- paper_keyword
alter table public.paper_keyword enable row level security;
create policy "anon/auth can select paper_keyword" on public.paper_keyword for select to anon, authenticated using (true);
create policy "anon/auth can insert paper_keyword" on public.paper_keyword for insert to anon, authenticated with check (true);
create policy "anon/auth can update paper_keyword" on public.paper_keyword for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete paper_keyword" on public.paper_keyword for delete to anon, authenticated using (true);

-- papers
alter table public.papers enable row level security;
create policy "anon/auth can select papers" on public.papers for select to anon, authenticated using (true);
create policy "anon/auth can insert papers" on public.papers for insert to anon, authenticated with check (true);
create policy "anon/auth can update papers" on public.papers for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete papers" on public.papers for delete to anon, authenticated using (true);

-- people_verified
alter table public.people_verified enable row level security;
create policy "anon/auth can select people_verified" on public.people_verified for select to anon, authenticated using (true);
create policy "anon/auth can insert people_verified" on public.people_verified for insert to anon, authenticated with check (true);
create policy "anon/auth can update people_verified" on public.people_verified for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete people_verified" on public.people_verified for delete to anon, authenticated using (true);

-- ranking_systems
alter table public.ranking_systems enable row level security;
create policy "anon/auth can select ranking_systems" on public.ranking_systems for select to anon, authenticated using (true);
create policy "anon/auth can insert ranking_systems" on public.ranking_systems for insert to anon, authenticated with check (true);
create policy "anon/auth can update ranking_systems" on public.ranking_systems for update to anon, authenticated using (true) with check (true);
create policy "anon/auth can delete ranking_systems" on public.ranking_systems for delete to anon, authenticated using (true);
```

> 提示：若不希望 checkpoint_* 表开放写权限，可仅保留 `for select` 策略，并去掉 insert/update/delete。

