# Graphy Demo 数据库表设计文档

## 概述

本文档描述了Graphy Demo项目的PostgreSQL数据库表结构设计。该系统主要用于存储和处理文档数据，包括文档解析、向量化、实体识别和图数据库功能。

## 数据库扩展

系统使用以下PostgreSQL扩展：
- `vector`: 用于向量存储和相似性搜索
- `age`: Apache AGE图数据库扩展

## 表结构总览

| 表名 | 描述 | 主要功能 |
|------|------|----------|
| `docs` | 文档主表 | 存储文档基本信息和元数据 |
| `sections` | 章节表 | 存储文档的章节结构 |
| `pages` | 页面表 | 存储文档页面信息 |
| `chunks` | 文本块表 | 存储文档分块内容和向量嵌入 |
| `doc_references` | 文档引用表 | 存储图片、表格、公式等引用 |
| `page_chunks` | 页面-文本块关联表 | 关联页面和文本块 |
| `chunk_references` | 文本块-引用关联表 | 关联文本块和引用 |
| `benchmark_qa` | 基准测试问答对表 | 存储生成的问答对数据 |
| `evaluation_results` | 评估结果表 | 存储模型评估结果 |

## 详细表结构

### 1. docs (文档主表)

**功能**: 存储文档的基本信息和元数据

**字段说明**:
- `doc_id` (TEXT, PK): 文档唯一标识符
- `metadata` (JSONB): 文档元数据，包含标题、作者、摘要等
- `thread_id` (TEXT): 会话线程ID
- `type` (TEXT): 文档类型，默认为'as'
- `created_at` (TIMESTAMPTZ): 创建时间
- `updated_at` (TIMESTAMPTZ): 更新时间

**索引**:
- `idx_docs_metadata_title`: 文档标题索引 (GIN)

**创建SQL**:
```sql
CREATE TABLE docs (
    doc_id TEXT PRIMARY KEY,
    metadata JSONB NOT NULL,
    thread_id TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'as',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_docs_metadata_title ON docs ((metadata->>'title'));
```

### 2. sections (章节表)

**功能**: 存储文档的章节层次结构

**字段说明**:
- `sec_id` (TEXT, PK): 章节唯一标识符
- `doc_id` (TEXT, FK): 关联的文档ID
- `name` (TEXT): 章节名称
- `level` (SMALLINT): 章节层级
- `parent_id` (TEXT): 父章节ID
- `full_path` (TEXT[]): 章节完整路径数组
- `thread_id` (TEXT): 会话线程ID
- `created_at` (TIMESTAMPTZ): 创建时间
- `updated_at` (TIMESTAMPTZ): 更新时间

**索引**:
- `idx_sections_doc`: 文档ID索引
- `idx_sections_parent`: 父章节ID索引

**创建SQL**:
```sql
CREATE TABLE sections (
    sec_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(doc_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    level SMALLINT NOT NULL,
    parent_id TEXT,
    full_path TEXT[] NOT NULL,
    thread_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sections_doc ON sections(doc_id);
CREATE INDEX idx_sections_parent ON sections(parent_id);
```

### 3. pages (页面表)

**功能**: 存储文档页面信息

**字段说明**:
- `doc_id` (TEXT, FK): 关联的文档ID
- `page_number` (INTEGER): 页面编号
- `thread_id` (TEXT): 会话线程ID
- `created_at` (TIMESTAMPTZ): 创建时间
- `updated_at` (TIMESTAMPTZ): 更新时间

**主键**: (doc_id, page_number)

**索引**:
- `idx_pages_doc`: 文档ID索引

**创建SQL**:
```sql
CREATE TABLE pages (
    doc_id TEXT NOT NULL REFERENCES docs(doc_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    thread_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (doc_id, page_number)
);

CREATE INDEX idx_pages_doc ON pages(doc_id);
```

### 4. chunks (文本块表)

**功能**: 存储文档分块内容和向量嵌入

**字段说明**:
- `chunk_id` (TEXT, PK): 文本块唯一标识符
- `sec_id` (TEXT, FK): 关联的章节ID
- `text` (TEXT): 文本内容
- `tokens` (INTEGER): 标记数量
- `page_idx` (INTEGER[]): 页面索引数组
- `embedding` (VECTOR(1024)): 向量嵌入
- `sparse_embedding` (JSONB): 稀疏向量嵌入
- `embedding_metadata` (JSONB): 嵌入模型元数据
- `thread_id` (TEXT): 会话线程ID
- `position_in_section` (INTEGER): 在章节中的位置
- `created_at` (TIMESTAMPTZ): 创建时间
- `updated_at` (TIMESTAMPTZ): 更新时间

**索引**:
- `idx_chunks_sec`: 章节ID索引
- `idx_chunks_sparse_embedding`: 稀疏向量索引 (GIN)
- `idx_chunks_page`: 页面索引数组索引 (GIN)
- `idx_chunks_hnsw`: 向量相似性搜索索引 (HNSW)
- `idx_chunks_embedding`: 向量索引 (IVFFlat，HNSW的备选)

**创建SQL**:
```sql
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    sec_id TEXT NOT NULL REFERENCES sections(sec_id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    tokens INTEGER NOT NULL,
    page_idx INTEGER[],
    embedding VECTOR(1024),
    sparse_embedding JSONB,
    embedding_metadata JSONB DEFAULT '{"model": "BAAI/bge-m3"}',
    thread_id TEXT NOT NULL,
    position_in_section INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_chunks_sec ON chunks(sec_id);
CREATE INDEX idx_chunks_sparse_embedding ON chunks USING GIN (sparse_embedding);
CREATE INDEX idx_chunks_page ON chunks USING GIN (page_idx);

-- HNSW索引
CREATE INDEX idx_chunks_hnsw ON chunks
USING hnsw (embedding vector_l2_ops)
WITH (m = 16, ef_construction = 200);
```

### 5. doc_references (文档引用表)

**功能**: 存储文档中的图片、表格、公式等引用

**字段说明**:
- `ref_id` (TEXT, PK): 引用唯一标识符
- `doc_id` (TEXT, FK): 关联的文档ID
- `type` (TEXT): 引用类型 (image/table/equation)
- `content` (TEXT): 引用内容
- `path` (TEXT): 文件路径
- `caption` (TEXT): 引用标题
- `page_idx` (INTEGER): 页面索引
- `thread_id` (TEXT): 会话线程ID
- `created_at` (TIMESTAMPTZ): 创建时间
- `updated_at` (TIMESTAMPTZ): 更新时间

**索引**:
- `idx_doc_references`: 文档ID索引
- `idx_doc_refs_page`: 文档和页面索引

**创建SQL**:
```sql
CREATE TABLE doc_references (
    ref_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(doc_id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    content TEXT,
    path TEXT,
    caption TEXT,
    page_idx INTEGER,
    thread_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_doc_references ON doc_references(doc_id);
CREATE INDEX idx_doc_refs_page ON doc_references(doc_id, page_idx);
```

### 6. page_chunks (页面-文本块关联表)

**功能**: 关联页面和文本块

**字段说明**:
- `doc_id` (TEXT): 文档ID
- `page_number` (INTEGER): 页面编号
- `chunk_id` (TEXT, FK): 文本块ID

**主键**: (doc_id, page_number, chunk_id)

**索引**:
- `idx_page_chunks_chunk`: 文本块ID索引

**创建SQL**:
```sql
CREATE TABLE page_chunks (
    doc_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    PRIMARY KEY (doc_id, page_number, chunk_id),
    FOREIGN KEY (doc_id, page_number) REFERENCES pages(doc_id, page_number) ON DELETE CASCADE
);

CREATE INDEX idx_page_chunks_chunk ON page_chunks(chunk_id);
```

### 7. chunk_references (文本块-引用关联表)

**功能**: 关联文本块和引用

**字段说明**:
- `chunk_id` (TEXT, FK): 文本块ID
- `ref_id` (TEXT, FK): 引用ID

**主键**: (chunk_id, ref_id)

**索引**:
- `idx_chunk_refs_chunk`: 文本块ID索引
- `idx_chunk_refs_ref`: 引用ID索引

**创建SQL**:
```sql
CREATE TABLE chunk_references (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    ref_id TEXT NOT NULL REFERENCES doc_references(ref_id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, ref_id)
);

CREATE INDEX idx_chunk_refs_chunk ON chunk_references(chunk_id);
CREATE INDEX idx_chunk_refs_ref ON chunk_references(ref_id);
```

### 8. benchmark_qa (基准测试问答对表)

**功能**: 存储生成的基准测试问答对数据

**字段说明**:
- `id` (TEXT, PK): 问答对唯一标识符
- `question` (TEXT): 问题内容
- `reference_answer` (TEXT): 标准答案
- `question_type` (TEXT): 问题类型 (definition/application/requirement/boundary)
- `difficulty` (INTEGER): 难度等级 (1-5)
- `chunk_ids` (TEXT[]): 关联的文本块ID数组
- `negative_samples` (TEXT[]): 负样本答案数组
- `required_citations` (TEXT[]): 必需引用数组
- `thread_id` (TEXT): 会话线程ID
- `metadata` (JSONB): 元数据信息
- `created_at` (TIMESTAMPTZ): 创建时间
- `updated_at` (TIMESTAMPTZ): 更新时间

**索引**:
- `idx_benchmark_qa_type`: 问题类型索引
- `idx_benchmark_qa_difficulty`: 难度等级索引
- `idx_benchmark_qa_chunks`: 文本块ID数组索引 (GIN)
- `idx_benchmark_qa_thread`: 线程ID索引
- `idx_benchmark_qa_citations`: 引用数组索引 (GIN)
- `idx_benchmark_qa_created`: 创建时间索引

**创建SQL**:
```sql
CREATE TABLE benchmark_qa (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    question_type TEXT DEFAULT 'unknown',
    difficulty INTEGER CHECK (difficulty >= 1 AND difficulty <= 5),
    chunk_ids TEXT[] NOT NULL,
    negative_samples TEXT[],
    required_citations TEXT[],
    thread_id TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_benchmark_qa_type ON benchmark_qa(question_type);
CREATE INDEX idx_benchmark_qa_difficulty ON benchmark_qa(difficulty);
CREATE INDEX idx_benchmark_qa_chunks ON benchmark_qa USING GIN (chunk_ids);
CREATE INDEX idx_benchmark_qa_thread ON benchmark_qa(thread_id);
CREATE INDEX idx_benchmark_qa_citations ON benchmark_qa USING GIN (required_citations);
CREATE INDEX idx_benchmark_qa_created ON benchmark_qa(created_at);
```

### 9. evaluation_results (评估结果表)

**功能**: 存储模型评估结果

**字段说明**:
- `id` (SERIAL, PK): 评估结果唯一标识符
- `question_id` (TEXT): 关联的问题ID
- `model_answer` (TEXT): 模型生成的答案
- `citations` (TEXT[]): 引用数组
- `scores` (JSONB): 评分详情 (accuracy, completeness, relevance, traceability, clarity)
- `weighted_score` (FLOAT): 加权总分
- `justification` (TEXT): 评分理由
- `failure_type` (TEXT): 失败类型
- `thread_id` (TEXT): 会话线程ID
- `created_at` (TIMESTAMPTZ): 创建时间
- `updated_at` (TIMESTAMPTZ): 更新时间

**索引**:
- `idx_evaluation_results_question_id`: 问题ID索引
- `idx_evaluation_results_thread_id`: 线程ID索引
- `idx_evaluation_results_created`: 创建时间索引
- `idx_evaluation_results_weighted_score`: 加权分数索引

**创建SQL**:
```sql
CREATE TABLE evaluation_results (
    id SERIAL PRIMARY KEY,
    question_id TEXT NOT NULL,
    model_answer TEXT NOT NULL,
    citations TEXT[],
    scores JSONB NOT NULL,
    weighted_score FLOAT,
    justification TEXT,
    failure_type TEXT,
    thread_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_evaluation_results_question_id ON evaluation_results(question_id);
CREATE INDEX idx_evaluation_results_thread_id ON evaluation_results(thread_id);
CREATE INDEX idx_evaluation_results_created ON evaluation_results(created_at);
CREATE INDEX idx_evaluation_results_weighted_score ON evaluation_results(weighted_score);
```

## 触发器

系统为所有主要表创建了自动更新时间戳的触发器：

```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为每个表创建触发器
CREATE TRIGGER update_docs_updated_at
    BEFORE UPDATE ON docs
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sections_updated_at
    BEFORE UPDATE ON sections
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_pages_updated_at
    BEFORE UPDATE ON pages
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_chunks_updated_at
    BEFORE UPDATE ON chunks
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_doc_references_updated_at
    BEFORE UPDATE ON doc_references
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_benchmark_qa_updated_at
    BEFORE UPDATE ON benchmark_qa
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_evaluation_results_updated_at
    BEFORE UPDATE ON evaluation_results
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
```