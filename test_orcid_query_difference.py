#!/usr/bin/env python3
"""
测试ORCID查询差异 - 验证不同查询方式的结果差异

这个脚本用于测试:
1. 带机构过滤的查询: (name_query) AND affiliation-org-name:"MIT"
2. 不带机构过滤的查询: name_query
3. 分析为什么会得到不同的ORCID结果
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from agent.utils import (
    get_orcid_session, get_orcid_headers, get_orcid_base_urls,
    normalize_name_for_strict, best_aff_match_for_institution
)

def test_orcid_query_difference():
    """测试不同ORCID查询方式的结果差异"""
    name = "Song Han"
    institution = "MIT"
    max_results = 10
    
    urls = get_orcid_base_urls()
    headers = get_orcid_headers()
    sess = get_orcid_session()
    
    # 构建查询
    name = (name or "").strip()
    parts = name.split()
    if len(parts) >= 2:
        given = " ".join(parts[:-1])
        family = parts[-1]
        name_query = f'(given-names:"{given}" AND family-name:"{family}") OR (given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    else:
        name_query = f'(given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    
    # 测试1: 带机构过滤的查询
    print("=== 测试1: 带机构过滤的查询 ===")
    query_with_institution = f'({name_query}) AND affiliation-org-name:"{institution}"'
    print(f"查询语句: {query_with_institution}")
    
    try:
        r1 = sess.get(urls["search"], params={"q": query_with_institution, "rows": max_results}, headers=headers, timeout=15)
        r1.raise_for_status()
        data1 = r1.json()
        results1 = data1.get("result") or []
        print(f"结果数量: {len(results1)}")
        
        for i, result in enumerate(results1):
            orcid_id = ((result or {}).get("orcid-identifier") or {}).get("path")
            print(f"  {i+1}. ORCID ID: {orcid_id}")
            
    except Exception as e:
        print(f"查询失败: {e}")
        results1 = []
    
    # 测试2: 不带机构过滤的查询
    print("\n=== 测试2: 不带机构过滤的查询 ===")
    query_without_institution = name_query
    print(f"查询语句: {query_without_institution}")
    
    try:
        r2 = sess.get(urls["search"], params={"q": query_without_institution, "rows": max_results}, headers=headers, timeout=15)
        r2.raise_for_status()
        data2 = r2.json()
        results2 = data2.get("result") or []
        print(f"结果数量: {len(results2)}")
        
        for i, result in enumerate(results2):
            orcid_id = ((result or {}).get("orcid-identifier") or {}).get("path")
            print(f"  {i+1}. ORCID ID: {orcid_id}")
            
    except Exception as e:
        print(f"查询失败: {e}")
        results2 = []
    
    # 分析差异
    print("\n=== 结果分析 ===")
    orcids1 = set()
    orcids2 = set()
    
    for result in results1:
        orcid_id = ((result or {}).get("orcid-identifier") or {}).get("path")
        if orcid_id:
            orcids1.add(orcid_id)
    
    for result in results2:
        orcid_id = ((result or {}).get("orcid-identifier") or {}).get("path")
        if orcid_id:
            orcids2.add(orcid_id)
    
    print(f"带机构过滤的ORCID集合: {orcids1}")
    print(f"不带机构过滤的ORCID集合: {orcids2}")
    print(f"只在带机构过滤中出现: {orcids1 - orcids2}")
    print(f"只在不带机构过滤中出现: {orcids2 - orcids1}")
    print(f"两者共同的ORCID: {orcids1 & orcids2}")
    
    # 测试3: 检查用户提到的ORCID是否在结果中
    user_mentioned_orcid = "0000-0001-7120-4498"
    our_previous_orcid = "0000-0002-4904-2696"
    
    print(f"\n=== 特定ORCID检查 ===")
    print(f"用户提到的ORCID {user_mentioned_orcid} 是否在带机构过滤结果中: {user_mentioned_orcid in orcids1}")
    print(f"用户提到的ORCID {user_mentioned_orcid} 是否在不带机构过滤结果中: {user_mentioned_orcid in orcids2}")
    print(f"我们之前得到的ORCID {our_previous_orcid} 是否在带机构过滤结果中: {our_previous_orcid in orcids1}")
    print(f"我们之前得到的ORCID {our_previous_orcid} 是否在不带机构过滤结果中: {our_previous_orcid in orcids2}")

if __name__ == "__main__":
    test_orcid_query_difference()