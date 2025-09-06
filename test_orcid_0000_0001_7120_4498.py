#!/usr/bin/env python3
"""
测试用户提到的ORCID 0000-0001-7120-4498 的详细信息

检查这个ORCID是否:
1. 姓名匹配 "Song Han"
2. 是否有MIT相关的机构信息
3. 为什么它会在不带机构过滤的查询中排在前面
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from agent.utils import (
    get_orcid_session, get_orcid_headers, get_orcid_base_urls,
    normalize_name_for_strict, best_aff_match_for_institution
)

def fetch_orcid_details(orcid_id: str):
    """获取指定ORCID的详细信息"""
    urls = get_orcid_base_urls()
    headers = get_orcid_headers()
    sess = get_orcid_session()
    
    try:
        base = urls["base"]
        
        # 获取个人信息
        p = sess.get(f"{base}/{orcid_id}/person", headers=headers, timeout=10)
        person = p.json() if p.status_code == 200 else {}
        
        # 获取就业信息
        e = sess.get(f"{base}/{orcid_id}/employments", headers=headers, timeout=10)
        emp = e.json() if e.status_code == 200 else {}
        
        # 获取教育信息
        d = sess.get(f"{base}/{orcid_id}/educations", headers=headers, timeout=10)
        edu = d.json() if d.status_code == 200 else {}
        
        return person, emp, edu
    except Exception as e:
        print(f"获取ORCID详细信息失败: {e}")
        return {}, {}, {}

def parse_person_info(person_data):
    """解析个人信息"""
    name_obj = (person_data or {}).get("name") or {}
    if name_obj:
        given_names = (name_obj.get("given-names") or {}).get("value") if name_obj.get("given-names") else ""
        family_name = (name_obj.get("family-name") or {}).get("value") if name_obj.get("family-name") else ""
        display_name = f"{given_names} {family_name}".strip()
    else:
        given_names = ""
        family_name = ""
        display_name = ""
    
    # 其他名称
    other_names = []
    other = (person_data or {}).get("other-names") or {}
    if other.get("other-name"):
        for item in other.get("other-name"):
            if item and item.get("content"):
                other_names.append(item.get("content"))
    
    return {
        "display_name": display_name,
        "given_names": given_names,
        "family_name": family_name,
        "other_names": other_names
    }

def parse_affiliations(aff_data, key):
    """解析机构信息"""
    affiliations = []
    for group in (aff_data or {}).get("affiliation-group", []) or []:
        for s in (group or {}).get("summaries", []) or []:
            if not s or key not in s:
                continue
            sd = s[key]
            org = (sd or {}).get("organization", {}) or {}
            
            # 格式化日期
            def format_date(date_obj):
                if not date_obj:
                    return ""
                try:
                    y = (date_obj.get("year") or {}).get("value")
                    m = (date_obj.get("month") or {}).get("value")
                    d = (date_obj.get("day") or {}).get("value")
                    if y and m and d:
                        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
                    if y and m:
                        return f"{int(y):04d}-{int(m):02d}"
                    if y:
                        return f"{int(y):04d}"
                except Exception:
                    return ""
                return ""
            
            affiliations.append({
                "organization": org.get("name", "") or "",
                "department": (sd or {}).get("department-name", "") or "",
                "role": (sd or {}).get("role-title", "") or "",
                "start_date": format_date((sd or {}).get("start-date")),
                "end_date": format_date((sd or {}).get("end-date")),
            })
    
    return affiliations

def test_specific_orcid():
    """测试用户提到的特定ORCID"""
    orcid_id = "0000-0001-7120-4498"
    target_name = "Song Han"
    target_institution = "MIT"
    
    print(f"=== 测试ORCID: {orcid_id} ===")
    
    # 获取详细信息
    person, emp, edu = fetch_orcid_details(orcid_id)
    
    if not person:
        print("无法获取个人信息")
        return
    
    # 解析个人信息
    person_info = parse_person_info(person)
    print(f"\n=== 个人信息 ===")
    print(f"显示名称: {person_info['display_name']}")
    print(f"名: {person_info['given_names']}")
    print(f"姓: {person_info['family_name']}")
    print(f"其他名称: {person_info['other_names']}")
    
    # 姓名匹配检查
    print(f"\n=== 姓名匹配检查 ===")
    target_norm = normalize_name_for_strict(target_name)
    display_norm = normalize_name_for_strict(person_info['display_name'])
    given_norm = normalize_name_for_strict(person_info['given_names'])
    family_norm = normalize_name_for_strict(person_info['family_name'])
    full_name_norm = f"{given_norm} {family_norm}".strip()
    
    print(f"目标姓名标准化: '{target_norm}'")
    print(f"显示名称标准化: '{display_norm}'")
    print(f"完整姓名标准化: '{full_name_norm}'")
    print(f"姓名匹配结果: {target_norm == display_norm or target_norm == full_name_norm}")
    
    # 解析就业信息
    employments = parse_affiliations(emp, "employment-summary")
    print(f"\n=== 就业信息 ({len(employments)}条) ===")
    for i, employment in enumerate(employments, 1):
        print(f"  {i}. 机构: {employment['organization']}")
        print(f"     部门: {employment['department']}")
        print(f"     职位: {employment['role']}")
        print(f"     开始: {employment['start_date']}")
        print(f"     结束: {employment['end_date']}")
        print()
    
    # 解析教育信息
    educations = parse_affiliations(edu, "education-summary")
    print(f"=== 教育信息 ({len(educations)}条) ===")
    for i, education in enumerate(educations, 1):
        print(f"  {i}. 机构: {education['organization']}")
        print(f"     部门: {education['department']}")
        print(f"     学位: {education['role']}")
        print(f"     开始: {education['start_date']}")
        print(f"     结束: {education['end_date']}")
        print()
    
    # MIT机构匹配检查
    print(f"=== MIT机构匹配检查 ===")
    all_affiliations = employments + educations
    
    # 构建完整的学者信息用于机构匹配
    scholar_info = {
        "orcid_id": orcid_id,
        "display_name": person_info['display_name'],
        "given_names": person_info['given_names'],
        "family_name": person_info['family_name'],
        "other_names": person_info['other_names'],
        "employments": employments,
        "educations": educations
    }
    
    # 使用项目中的机构匹配逻辑
    best_match = best_aff_match_for_institution(target_institution, scholar_info)
    
    if best_match:
        print(f"找到MIT匹配: {best_match}")
    else:
        print("未找到MIT匹配")
        
        # 手动检查是否有MIT相关的机构
        mit_related = []
        for aff in all_affiliations:
            org_name = aff['organization'].lower()
            dept_name = aff['department'].lower()
            if 'mit' in org_name or 'massachusetts institute' in org_name or 'mit' in dept_name:
                mit_related.append(aff)
        
        if mit_related:
            print(f"手动发现MIT相关机构 ({len(mit_related)}条):")
            for aff in mit_related:
                print(f"  - {aff['organization']} / {aff['department']}")
        else:
            print("手动检查也未发现MIT相关机构")

if __name__ == "__main__":
    test_specific_orcid()