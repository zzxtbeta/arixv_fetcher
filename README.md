# ArXiv 爬取 + 机构抽取 + 最小聊天 + 前端看板

## 项目简介

- 从 arXiv 抓取近 N 天论文，写入规范化数据库表（papers/authors/affiliations 等），并为作者抽取机构（PDF 首页 + LLM- **ORCID 富化**：
  - 新数据：抓取流程内并行尝试 ORCID（受限并发），仅在"作者姓名严格一致 + 机构相似匹配通过"时，补全 `authors.orcid` 与 `author_affiliation.role/start_date/end_date`（保守更新）。
  - 老数据：提供批量和单个作者接口进行补齐；支持只更新空值或完全覆盖两种模式。
  - 角色信息：自动组合 ORCID 的 `role-title` 和 `department-name` 为完整角色，如 `"Senior Staff Engineer (Tongyi Lab)"`；仅在有实际角色时存储，避免将部门名误当作角色。）。
- 提供最小聊天接口（DashScope 兼容 OpenAI）。
- 提供前端 React 看板（Vite + Ant Design），展示总览与作者模糊检索（机构、最近论文、合作作者）。
- 新增 ORCID 富化：基于作者姓名 + 机构相似匹配补全作者 ORCID 与作者-机构的 role/start_date/end_date，支持角色信息完整组合。

技术栈：FastAPI、LangGraph（Send 并行）、psycopg3、requests、pdfplumber、Supabase Python SDK（通用查询）、React + Ant Design、ORCID Public API。

## 目录结构
- `src/agent/graph.py`：最小聊天图（start → chat → end）
- `src/agent/data_graph.py`：arXiv 抓取 → 并行机构抽取（Send）→ 规范化入库
- `src/api/graph.py`：聊天 API
- `src/api/data_processing.py`：抓取 API
- `src/api/dashboard.py`：看板 API（总览、作者检索）
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

# Supabase Python SDK（通用查询，供看板 API 使用）
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=你的Supabase匿名键
```

说明：
- `DATABASE_URL` 可使用 Supabase 提供的 Postgres 连接串或本地 Postgres。
- 机构抽取依赖 `pdfplumber` 抽取 PDF 首页文本 + LLM 严格 JSON 映射作者 → 机构名，顺序与 arXiv 作者序一致；失败时不阻断流程。

## 安装与运行（后端）

安装依赖：

```bash
pip install .
```

启动 API 服务：

```bash
python -m src.main
```

- 服务默认 `http://localhost:8000`
- Swagger：`http://localhost:8000/docs`

## API 一览（后端）

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

- 看板总览：`GET /dashboard/overview`
- 作者检索：`GET /dashboard/author?q=模糊人名`
- 聊天：`POST /agent/chat`

## 数据处理（简述）

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
  - 总览卡片（论文/作者/机构/类别计数）
  - 作者模糊检索（大小写与空格不敏感）：展示 ORCID、机构（含 role/起止/latest）、最近论文、常合作作者，QS 标签含 2025/2024 且显示名次变化箭头
  - 最新论文流（分页）；支持在顶部直接发起抓取（日期范围/类别/上限、或按 ID）

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

## 备注
- 若抓取响应 `inserted=0, skipped=0` 且 `fetched>0`：通常是并行聚合/版本不一致或 RLS/权限问题；已将 Send 并行按官方推荐接线并在写库前汇合。Supabase RLS 下请确保 INSERT 策略放行。
- 若机构为空：可能 PDF 不可抽取或 LLM 返回不规范；已加入短退避重试与严格 JSON 解析，仍失败则为空。
- ORCID 富化支持灵活更新策略：批量接口用 `only_missing` 参数，单个作者接口用 `overwrite` 参数，可根据需要选择只更新空值或完全覆盖。

---
如需扩展：
- 后端：新增最新论文 API、增加 OCR 兜底、机构名规范化、缓存/重试策略等
- 前端：最新论文 feed、类别分布图、更多筛选与导出

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

