下面是一份**基于 Supabase 官方文档**整理的 Python SDK（`supabase‑py`）的 CRUD 操作使用指南 Markdown，附带官方链接引用，仅包含你需要的内容：

---

````markdown
# Supabase Python SDK CRUD 操作指南

## 📌 初始化连接

```python
from supabase import create_client
import os

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)
````

---

## ➕ Insert（插入数据）

* 方法：`.insert(json, count=None, returning='representation', default_to_null=False)`
* 必选参数：

  * `json`: dict（单条）或 list of dicts（多条）
* 可选参数：

  * `count`: 行数统计方式
  * `returning`: `'minimal'` 或 `'representation'`
  * `default_to_null`: bulk 插入时将缺失字段设为 `NULL`（否则使用列默认值）
    ([Supabase][1])

**示例**：

```python
# 单条插入
response = supabase.table("planets").insert({"id":1, "name":"Pluto"}).execute()

# 批量插入
response = supabase.table("characters").insert([
  {"id":1, "name":"Frodo"},
  {"id":2, "name":"Sam"},
]).execute()
```

([Supabase][1])

---

## 🔍 Select（查询数据）

* 方法：`.select(columns)` + 链式 filter，如 `.eq()`, `.gt()`, `.lt()`, `.in_()`, `.ilike()`, `.like()`, `.is_()` 等
* 支持 `.order(column, desc=True/False)`、`.limit(n)`、`.range(from_, to_)`
* 可用：

  * `.maybe_single()`：返回单条或 `None`
  * `.single()`：确保一定返回一条且失败时抛错
    ([Analytics Vidhya][2])

---

## ✏️ Update（更新数据）

* 方法：`.update(json, count=None)`
* 参数：

  * `json`: 要更新的字段
  * 必须搭配过滤条件使用 `.eq()`, `.gt()`, `.lt()` 等
* 示例：

```python
response = supabase.table("instruments") \
  .update({"name": "piano"}) \
  .eq("id", 1) \
  .execute()
```

([Supabase][3], [Analytics Vidhya][2])

更新 JSON 字段时也支持嵌套结构查询和更新。
([apidog][4])

---

## ❌ Delete（删除数据）

* 方法：`.delete()`，必须与过滤条件链配合使用
* 示例：

```python
response = supabase.table("todos") \
  .delete() \
  .eq("id", some_id) \
  .execute()
```

([Supabase][1], [blog.theinfosecguy.xyz][5])

---

## 🔄 Upsert（插入或更新）

* 方法：`.upsert(json)`，可搭配 `.on_conflict(column_or_list)`
* 冲突时更新，无冲突则插入
  ([Supabase][1], [Supabase][3])

---

## 🧠 常用过滤与选项参数一览

* 过滤方法：

  * `.eq(…)`, `.neq(…)`, `.gt(…)`, `.gte()`, `.lt()`, `.lte()`
  * `.like()`, `.ilike()`, `.is_(None or True/False)`
  * `.in_(list)`, `.contains()`, `.contained_by()`, `.range_*` 等
    ([Supabase][1])
* 辅助查询：

  * `.order(column, desc=True/False)`
  * `.limit(n)`
  * `.range(from, to)`
  * `.maybe_single()`, `.single()`

---

## ✅ Execute 方法与响应结构

* `.execute()` 返回一个 `APIResponse`，其 `.data` 属性包含结果列表，`.count` 可用（当指定 `count` 参数）
* `returning='representation'` 可返回插入或更新后的完整对象
  ([Stack Overflow][6], [Analytics Vidhya][2], [Supabase][1])

---

## 📚 官方参考文档链接

* **Insert data**: Supabase Docs “Python: Insert data” ([Supabase][1])
* **Update data**: Supabase Docs “Python: Update data” ([Supabase][3])
* **Introduction & filters**: Supabase Docs “Python: Introduction” + filters 列表 ([Supabase][7])

---

## 🧾 快速 Markdown 汇总表

| 操作     | 示例                                                                     |
| ------ | ---------------------------------------------------------------------- |
| 插入     | `supabase.table("tbl").insert(obj).execute()`                          |
| 查询     | `supabase.table("tbl").select("*").eq("col", val).limit(10).execute()` |
| 更新     | `supabase.table("tbl").update({"col": new}).eq("id", id).execute()`    |
| 删除     | `supabase.table("tbl").delete().eq("id", id).execute()`                |
| Upsert | `supabase.table("tbl").upsert(obj).on_conflict("id").execute()`        |

---

希望这份基于官方文档的 Markdown CRUD 指南正符合你的需求，无需额外抽象代码或结构。

[1]: https://supabase.com/docs/reference/python/insert?utm_source=chatgpt.com "Python: Insert data | Supabase Docs"
[2]: https://www.analyticsvidhya.com/blog/2022/07/introduction-to-supabase-postgres-database-using-python/?utm_source=chatgpt.com "Introduction to Supabase: Postgres Database using Python"
[3]: https://supabase.com/docs/reference/python/update?utm_source=chatgpt.com "Python: Update data | Supabase Docs"
[4]: https://apidog.com/blog/supabase-api/?utm_source=chatgpt.com "How to Use Supabase API: A Complete Guide - Apidog"
[5]: https://blog.theinfosecguy.xyz/building-a-crud-api-with-fastapi-and-supabase-a-step-by-step-guide?utm_source=chatgpt.com "Building a CRUD API with FastAPI and Supabase - Keshav Malik"
[6]: https://stackoverflow.com/questions/78970312/supabase-python-client-returns-an-empty-list-when-making-a-query?utm_source=chatgpt.com "Supabase python client returns an empty list when making a query"
[7]: https://supabase.com/docs/reference/python/introduction?utm_source=chatgpt.com "Python: Introduction | Supabase Docs"
