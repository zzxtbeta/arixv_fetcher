# 项目中ORCID匹配逻辑详细说明

## 概述

项目通过 `orcid_search_and_pick` 函数实现根据作者姓名和机构名称寻找对应ORCID的功能。该函数位于 `src/agent/utils.py` 文件中，采用多层次的匹配策略来确保准确性。

## 核心函数

### 主函数：`orcid_search_and_pick(name, institution, max_results=10)`

**参数：**
- `name`: 作者姓名（字符串）
- `institution`: 机构名称（字符串，可为空）
- `max_results`: 最大搜索结果数（默认10）

**返回值：**
- 成功：包含ORCID信息的字典
- 失败：None

## 详细匹配流程

### 1. 缓存检查阶段

```python
# 构建缓存键：标准化姓名 + 标准化机构名
key = f"{normalize_name_for_strict(name)}|{norm_string(institution)}"
if key in _ORCID_CACHE:
    return _ORCID_CACHE[key]
```

- 使用姓名和机构的标准化组合作为缓存键
- 避免重复的API调用，提高性能

### 2. 查询构建阶段

#### 2.1 姓名查询构建

```python
name = (name or "").strip()
parts = name.split()
if len(parts) >= 2:
    given = " ".join(parts[:-1])  # 名
    family = parts[-1]           # 姓
    name_query = f'(given-names:"{given}" AND family-name:"{family}") OR (given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
else:
    name_query = f'(given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
```

**查询策略：**
- 如果姓名包含多个部分：优先精确匹配（名+姓），备选模糊匹配
- 如果姓名只有一个部分：在所有姓名字段中搜索
- 搜索字段包括：given-names（名）、family-name（姓）、other-names（其他名称）

#### 2.2 机构过滤

```python
if institution:
    query = f'({name_query}) AND affiliation-org-name:"{institution}"'
else:
    query = name_query
```

- 如果指定机构：在查询中添加机构过滤条件
- 如果未指定机构：仅使用姓名查询

### 3. ORCID API调用阶段

```python
sess = get_orcid_session()
r = sess.get(urls["search"], params={"q": query, "rows": max_results}, headers=headers, timeout=15)
r.raise_for_status()
data = r.json()
results = data.get("result") or []
```

- 使用ORCID公共API进行搜索
- 设置15秒超时
- 获取指定数量的候选结果

### 4. 候选人详细信息获取阶段

对每个候选人，系统会获取三类详细信息：

#### 4.1 个人信息 (`/person`)
```python
p = sess.get(f"{base}/{orcid_id}/person", headers=headers, timeout=10)
```
- 获取姓名、显示名称、其他名称等

#### 4.2 就业信息 (`/employments`)
```python
e = sess.get(f"{base}/{orcid_id}/employments", headers=headers, timeout=10)
```
- 获取工作经历、机构、部门、职位、时间等

#### 4.3 教育信息 (`/educations`)
```python
d = sess.get(f"{base}/{orcid_id}/educations", headers=headers, timeout=10)
```
- 获取教育经历、学校、院系、学位、时间等

### 5. 数据解析和标准化阶段

#### 5.1 个人信息解析
```python
def parse_person(pd: Dict[str, Any]) -> Dict[str, Any]:
    out = {"display_name": "", "given_names": "", "family_name": "", "other_names": []}
    name_obj = (pd or {}).get("name") or {}
    if name_obj:
        gn = (name_obj.get("given-names") or {}).get("value") if name_obj.get("given-names") else ""
        fn = (name_obj.get("family-name") or {}).get("value") if name_obj.get("family-name") else ""
        out["given_names"] = gn or ""
        out["family_name"] = fn or ""
        out["display_name"] = f"{gn} {fn}".strip()
```

#### 5.2 机构信息解析
```python
def parse_affs(ad: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    # 解析就业或教育信息
    # 提取：organization, department, role, start_date, end_date
```

#### 5.3 日期格式化
```python
def orcid_format_date(obj: Any) -> str:
    # 将ORCID日期对象转换为标准格式
    # 支持：YYYY, YYYY-MM, YYYY-MM-DD
```

### 6. 严格匹配验证阶段

#### 6.1 姓名匹配验证
```python
name_norm = normalize_name_for_strict(name)  # 输入姓名标准化
disp = normalize_name_for_strict(info.get("display_name", ""))  # 显示名标准化
gn = normalize_name_for_strict(info.get("given_names", ""))     # 名标准化
fn = normalize_name_for_strict(info.get("family_name", ""))     # 姓标准化

# 严格相等检查
strict_ok = name_norm == disp or name_norm == f"{gn} {fn}".strip()
if not strict_ok:
    continue  # 跳过不匹配的候选人
```

**姓名标准化规则：**
- 转换为小写
- 合并多个空格为单个空格
- 去除首尾空格

#### 6.2 机构匹配验证
```python
if institution:
    best = best_aff_match_for_institution(institution, info)
    if not best:
        continue  # 跳过机构不匹配的候选人
```

### 7. 机构匹配算法详解

#### 7.1 机构名称标准化 (`normalize_aff_variants`)

```python
def normalize_aff_variants(name: str) -> List[str]:
    # 生成多种机构名称变体
    candidates = [
        name,                                    # 原始名称
        strip_parentheses(name),                # 去除括号内容
        first_segment_before_comma(name),       # 逗号前第一段
        strip_dept_prefix(name),                # 去除部门前缀
        # ... 更多变体
    ]
    
    # 包含去冠词形式（如 "The University" -> "University"）
    candidates += [strip_articles(c) for c in candidates]
    
    # 标准化并去重
    norms = []
    for c in candidates:
        normalized = norm_string(c)  # 转为小写字母数字
        if normalized and normalized not in norms:
            norms.append(normalized)
```

**机构名称变体生成策略：**
1. **原始形式**：保持原始输入
2. **去括号**：移除括号及其内容
3. **逗号分割**：提取逗号前后的关键部分
4. **去部门前缀**：移除"Department of"、"School of"等前缀
5. **去冠词**：移除"The"、"A"、"An"等冠词
6. **组合变体**：上述规则的组合应用

#### 7.2 相似度计算 (`best_aff_match_for_institution`)

```python
def score_one(org: str, dept: str) -> float:
    best = 0.0
    # 机构名称匹配
    for k in normalize_aff_variants(org):
        for t in target_norms:
            best = max(best, SequenceMatcher(None, t, k).ratio())
    
    # 部门名称辅助匹配
    if dept:
        for k in normalize_aff_variants(dept):
            for t in target_norms:
                best = max(best, SequenceMatcher(None, t, k).ratio())
    return best
```

**匹配策略：**
1. **就业信息优先**：优先匹配就业记录中的机构
2. **教育信息备选**：如就业信息无匹配，则匹配教育记录
3. **相似度阈值**：要求相似度 ≥ 0.86 才认为匹配成功
4. **双重匹配**：同时考虑机构名称和部门名称

#### 7.3 匹配结果返回
```python
# 返回最佳匹配（就业信息优先）
if best_emp and best_emp_s >= 0.86:
    return {"kind": "employment", **best_emp}
if best_edu and best_edu_s >= 0.86:
    return {"kind": "education", **best_edu}
return None
```

### 8. 结果选择和缓存阶段

```python
# 选择第一个通过所有验证的候选人
picked = cand[0] if cand else None

# 缓存结果（包括None结果）
_ORCID_CACHE[key] = picked
return picked
```

## 辅助函数说明

### 字符串标准化函数

1. **`normalize_name_for_strict(s)`**：姓名严格标准化
   - 转小写，合并空格
   - 用于精确姓名匹配

2. **`norm_string(s)`**：通用字符串标准化
   - 只保留小写字母和数字
   - 用于机构名称匹配

3. **`strip_parentheses(s)`**：去除括号内容
   - 移除 "(...)" 及其内容

4. **`strip_dept_prefix(s)`**：去除部门前缀
   - 移除 "Department of"、"School of" 等

5. **`strip_articles(s)`**：去除冠词
   - 移除 "The"、"A"、"An" 等

### 机构匹配相关函数

1. **`normalize_aff_variants(name)`**：生成机构名称变体
2. **`best_aff_match_for_institution(aff_name, scholar)`**：寻找最佳机构匹配

## 匹配成功的条件

一个ORCID记录要被成功匹配，必须同时满足：

1. **姓名匹配**：
   - 标准化后的输入姓名 = 标准化后的显示姓名，或
   - 标准化后的输入姓名 = 标准化后的"名 姓"组合

2. **机构匹配**（如果指定了机构）：
   - 在就业或教育记录中找到相似度 ≥ 0.86 的机构匹配

3. **API响应正常**：
   - ORCID API调用成功
   - 能够获取到完整的个人和机构信息

## 缓存机制

- **缓存键**：`标准化姓名|标准化机构名`
- **缓存内容**：完整的匹配结果（包括None）
- **缓存作用**：避免重复API调用，提高性能
- **缓存位置**：内存中的全局字典 `_ORCID_CACHE`

## 错误处理

- **网络超时**：设置15秒搜索超时，10秒详情获取超时
- **API错误**：捕获异常，返回None
- **数据解析错误**：容错处理，跳过有问题的候选人
- **空结果处理**：缓存None结果，避免重复查询

## 性能优化

1. **缓存机制**：避免重复API调用
2. **批量获取**：一次获取多个候选人，然后筛选
3. **早期退出**：姓名不匹配时立即跳过
4. **超时控制**：防止长时间等待
5. **结果限制**：限制最大搜索结果数

## 使用示例

```python
# 基本用法
result = orcid_search_and_pick("Song Han", "MIT")

# 不指定机构
result = orcid_search_and_pick("Song Han", "")

# 指定更多结果
result = orcid_search_and_pick("Song Han", "MIT", max_results=20)
```

## 返回结果格式

```python
{
    "orcid_id": "0000-0002-4904-2696",
    "display_name": "Song Han",
    "given_names": "Song",
    "family_name": "Han",
    "other_names": [],
    "employments": [
        {
            "organization": "Stanford University",
            "department": "Computer Science",
            "role": "Assistant Professor",
            "start_date": "2020-01",
            "end_date": ""
        }
    ],
    "educations": [
        {
            "organization": "MIT",
            "department": "EECS",
            "role": "Ph.D.",
            "start_date": "2015-09",
            "end_date": "2020-05"
        }
    ]
}
```

这个匹配系统通过多层次的验证和智能的相似度计算，确保了ORCID匹配的高准确性，同时通过缓存和优化策略保证了良好的性能。