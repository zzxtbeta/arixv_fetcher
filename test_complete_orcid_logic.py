#!/usr/bin/env python3
"""
完整测试项目中的ORCID匹配逻辑

这个脚本完全按照项目中的orcid_search_and_pick函数逻辑来执行，
包括严格的姓名匹配和机构匹配，以确定为什么会有不同的结果。
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from agent.utils import (
    orcid_search_and_pick, normalize_name_for_strict,
    get_orcid_session, get_orcid_headers, get_orcid_base_urls,
    best_aff_match_for_institution
)

def detailed_orcid_search_simulation(name: str, institution: str = "", max_results: int = 10):
    """详细模拟orcid_search_and_pick函数的执行过程"""
    print(f"=== 详细ORCID搜索模拟 ===")
    print(f"姓名: {name}")
    print(f"机构: {institution}")
    print(f"最大结果数: {max_results}")
    
    urls = get_orcid_base_urls()
    headers = get_orcid_headers()
    sess = get_orcid_session()
    
    # 1. 构建查询
    name = (name or "").strip()
    parts = name.split()
    if len(parts) >= 2:
        given = " ".join(parts[:-1])
        family = parts[-1]
        name_query = f'(given-names:"{given}" AND family-name:"{family}") OR (given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    else:
        name_query = f'(given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    
    if institution:
        query = f'({name_query}) AND affiliation-org-name:"{institution}"'
    else:
        query = name_query
    
    print(f"\n=== 步骤1: 查询构建 ===")
    print(f"查询语句: {query}")
    
    # 2. 执行搜索
    try:
        r = sess.get(urls["search"], params={"q": query, "rows": max_results}, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        results = data.get("result") or []
        print(f"\n=== 步骤2: API搜索结果 ===")
        print(f"找到 {len(results)} 个候选人")
        
        if not results:
            print("没有找到任何候选人，返回None")
            return None
            
    except Exception as e:
        print(f"搜索失败: {e}")
        return None
    
    # 3. 获取详细信息并进行匹配
    print(f"\n=== 步骤3: 候选人详细信息获取和匹配 ===")
    
    def fetch_details(orcid_id: str):
        """获取ORCID详细信息"""
        try:
            base = urls["base"]
            # person
            p = sess.get(f"{base}/{orcid_id}/person", headers=headers, timeout=10)
            person = p.json() if p.status_code == 200 else {}
            # employments
            e = sess.get(f"{base}/{orcid_id}/employments", headers=headers, timeout=10)
            emp = e.json() if e.status_code == 200 else {}
            # educations
            d = sess.get(f"{base}/{orcid_id}/educations", headers=headers, timeout=10)
            edu = d.json() if d.status_code == 200 else {}
            
            # 解析信息
            def parse_person(pd):
                out = {"display_name": "", "given_names": "", "family_name": "", "other_names": []}
                name_obj = (pd or {}).get("name") or {}
                if name_obj:
                    gn = (name_obj.get("given-names") or {}).get("value") if name_obj.get("given-names") else ""
                    fn = (name_obj.get("family-name") or {}).get("value") if name_obj.get("family-name") else ""
                    out["given_names"] = gn or ""
                    out["family_name"] = fn or ""
                    out["display_name"] = f"{gn} {fn}".strip()
                ons = []
                other = (pd or {}).get("other-names") or {}
                if other.get("other-name"):
                    for item in other.get("other-name"):
                        if item and item.get("content"):
                            ons.append(item.get("content"))
                out["other_names"] = ons
                return out
            
            def parse_affs(ad, key):
                out = []
                for group in (ad or {}).get("affiliation-group", []) or []:
                    for s in (group or {}).get("summaries", []) or []:
                        if not s or key not in s:
                            continue
                        sd = s[key]
                        org = (sd or {}).get("organization", {}) or {}
                        out.append({
                            "organization": org.get("name", "") or "",
                            "department": (sd or {}).get("department-name", "") or "",
                            "role": (sd or {}).get("role-title", "") or "",
                            "start_date": (sd or {}).get("start-date"),
                            "end_date": (sd or {}).get("end-date"),
                        })
                # 格式化日期
                for item in out:
                    def orcid_format_date(obj):
                        if not obj:
                            return ""
                        try:
                            y = (obj.get("year") or {}).get("value")
                            m = (obj.get("month") or {}).get("value")
                            d = (obj.get("day") or {}).get("value")
                            if y and m and d:
                                return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
                            if y and m:
                                return f"{int(y):04d}-{int(m):02d}"
                            if y:
                                return f"{int(y):04d}"
                        except Exception:
                            return ""
                        return ""
                    item["start_date"] = orcid_format_date(item["start_date"])
                    item["end_date"] = orcid_format_date(item["end_date"])
                return out
            
            info = {"orcid_id": orcid_id}
            info.update(parse_person(person))
            info["employments"] = parse_affs(emp, "employment-summary")
            info["educations"] = parse_affs(edu, "education-summary")
            return info
            
        except Exception as e:
            print(f"    获取 {orcid_id} 详细信息失败: {e}")
            return None
    
    # 4. 评估候选人
    candidates = []
    name_norm = normalize_name_for_strict(name)
    print(f"目标姓名标准化: '{name_norm}'")
    
    for i, r in enumerate(results):
        orcid_id = ((r or {}).get("orcid-identifier") or {}).get("path")
        if not orcid_id:
            continue
            
        print(f"\n--- 候选人 {i+1}: {orcid_id} ---")
        
        info = fetch_details(orcid_id)
        if not info:
            print("  获取详细信息失败，跳过")
            continue
        
        # 严格姓名匹配检查
        disp = normalize_name_for_strict(info.get("display_name", ""))
        gn = normalize_name_for_strict(info.get("given_names", ""))
        fn = normalize_name_for_strict(info.get("family_name", ""))
        full_name = f"{gn} {fn}".strip()
        
        print(f"  显示名称: '{info.get('display_name', '')}' -> 标准化: '{disp}'")
        print(f"  完整姓名: '{gn} {fn}' -> 标准化: '{full_name}'")
        
        strict_ok = name_norm == disp or name_norm == full_name
        print(f"  姓名匹配: {strict_ok}")
        
        if not strict_ok:
            print(f"  姓名不匹配，跳过")
            continue
        
        # 机构匹配检查
        if institution:
            print(f"  检查机构匹配: {institution}")
            best = best_aff_match_for_institution(institution, info)
            if best:
                print(f"  机构匹配成功: {best}")
            else:
                print(f"  机构匹配失败，跳过")
                continue
        else:
            print(f"  无需机构匹配")
        
        print(f"  ✓ 候选人通过所有检查")
        candidates.append(info)
    
    # 5. 返回结果
    print(f"\n=== 步骤4: 最终结果 ===")
    if candidates:
        picked = candidates[0]
        print(f"选择第一个匹配的候选人: {picked['orcid_id']} ({picked.get('display_name', '')})")
        return picked
    else:
        print("没有找到匹配的候选人")
        return None

def test_both_scenarios():
    """测试两种场景"""
    name = "Song Han"
    
    print("\n" + "="*80)
    print("场景1: 指定MIT机构")
    print("="*80)
    result1 = detailed_orcid_search_simulation(name, "MIT", 10)
    
    print("\n" + "="*80)
    print("场景2: 不指定机构")
    print("="*80)
    result2 = detailed_orcid_search_simulation(name, "", 10)
    
    print("\n" + "="*80)
    print("对比项目中的实际函数结果")
    print("="*80)
    
    # 使用项目中的实际函数
    actual1 = orcid_search_and_pick(name, "MIT", 10)
    actual2 = orcid_search_and_pick(name, "", 10)
    
    print(f"项目函数 - 指定MIT: {actual1['orcid_id'] if actual1 else None}")
    print(f"项目函数 - 不指定机构: {actual2['orcid_id'] if actual2 else None}")
    print(f"模拟函数 - 指定MIT: {result1['orcid_id'] if result1 else None}")
    print(f"模拟函数 - 不指定机构: {result2['orcid_id'] if result2 else None}")

if __name__ == "__main__":
    test_both_scenarios()