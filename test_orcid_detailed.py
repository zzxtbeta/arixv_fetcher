#!/usr/bin/env python3
"""
详细测试ORCID匹配功能
重点分析Song Han的ORCID信息
"""

import sys
import os
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入项目中的ORCID匹配函数
from src.agent.utils import (
    orcid_search_and_pick,
    orcid_candidates_by_name,
    best_aff_match_for_institution,
    normalize_name_for_strict
)

def analyze_song_han_orcid():
    """
    详细分析Song Han的ORCID信息
    """
    print("=" * 80)
    print("Song Han ORCID详细分析")
    print("=" * 80)
    
    author_name = "Song Han"
    
    print(f"分析作者: {author_name}")
    print()
    
    # 1. 不指定机构的搜索（已知能找到结果）
    print("1. 不指定机构的搜索:")
    print("-" * 40)
    
    try:
        result_no_inst = orcid_search_and_pick(author_name, "", max_results=10)
        
        if result_no_inst:
            print(f"✅ 找到ORCID: {result_no_inst.get('orcid_id')}")
            print(f"显示名称: {result_no_inst.get('display_name')}")
            print(f"名: {result_no_inst.get('given_names')}")
            print(f"姓: {result_no_inst.get('family_name')}")
            
            # 详细分析就业信息
            employments = result_no_inst.get('employments', [])
            print(f"\n就业信息 ({len(employments)} 条):")
            for i, emp in enumerate(employments, 1):
                org = emp.get('organization', 'N/A')
                dept = emp.get('department', 'N/A')
                role = emp.get('role', 'N/A')
                start = emp.get('start_date', 'N/A')
                end = emp.get('end_date', 'N/A')
                
                print(f"  {i}. 机构: {org}")
                print(f"     部门: {dept}")
                print(f"     职位: {role}")
                print(f"     时间: {start} - {end}")
                
                # 检查是否包含MIT相关信息
                org_lower = org.lower() if org != 'N/A' else ''
                dept_lower = dept.lower() if dept != 'N/A' else ''
                role_lower = role.lower() if role != 'N/A' else ''
                
                mit_keywords = ['mit', 'massachusetts institute of technology']
                has_mit = any(keyword in org_lower or keyword in dept_lower or keyword in role_lower 
                             for keyword in mit_keywords)
                
                if has_mit:
                    print(f"     *** 包含MIT相关信息 ***")
                print()
            
            # 详细分析教育信息
            educations = result_no_inst.get('educations', [])
            print(f"教育信息 ({len(educations)} 条):")
            for i, edu in enumerate(educations, 1):
                org = edu.get('organization', 'N/A')
                dept = edu.get('department', 'N/A')
                role = edu.get('role', 'N/A')
                start = edu.get('start_date', 'N/A')
                end = edu.get('end_date', 'N/A')
                
                print(f"  {i}. 机构: {org}")
                print(f"     部门: {dept}")
                print(f"     学位/角色: {role}")
                print(f"     时间: {start} - {end}")
                
                # 检查是否包含MIT相关信息
                org_lower = org.lower() if org != 'N/A' else ''
                dept_lower = dept.lower() if dept != 'N/A' else ''
                role_lower = role.lower() if role != 'N/A' else ''
                
                mit_keywords = ['mit', 'massachusetts institute of technology']
                has_mit = any(keyword in org_lower or keyword in dept_lower or keyword in role_lower 
                             for keyword in mit_keywords)
                
                if has_mit:
                    print(f"     *** 包含MIT相关信息 ***")
                print()
        
        else:
            print("❌ 未找到结果")
    
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        import traceback
        print(traceback.format_exc())
    
    print("\n" + "=" * 80)
    
    # 2. 测试MIT机构匹配
    print("2. 测试MIT机构匹配逻辑:")
    print("-" * 40)
    
    if result_no_inst:
        institutions_to_test = [
            "MIT",
            "Massachusetts Institute of Technology",
            "mit",
            "MASSACHUSETTS INSTITUTE OF TECHNOLOGY"
        ]
        
        for inst in institutions_to_test:
            print(f"\n测试机构: '{inst}'")
            best_match = best_aff_match_for_institution(inst, result_no_inst)
            
            if best_match:
                print(f"✅ 找到匹配:")
                print(f"  机构: {best_match.get('organization')}")
                print(f"  部门: {best_match.get('department')}")
                print(f"  职位: {best_match.get('role')}")
            else:
                print(f"❌ 未找到匹配")
    
    print("\n" + "=" * 80)
    
    # 3. 直接搜索ORCID候选人
    print("3. 直接搜索ORCID候选人:")
    print("-" * 40)
    
    try:
        candidates = orcid_candidates_by_name(author_name, max_candidates=5)
        print(f"找到 {len(candidates)} 个候选人:")
        
        for i, candidate in enumerate(candidates, 1):
            orcid_id = candidate.get('orcid-identifier', {}).get('path', 'N/A')
            given_names = candidate.get('person', {}).get('name', {}).get('given-names', {}).get('value', 'N/A')
            family_name = candidate.get('person', {}).get('name', {}).get('family-name', {}).get('value', 'N/A')
            
            print(f"  {i}. ORCID: {orcid_id}")
            print(f"     姓名: {given_names} {family_name}")
            
            # 检查就业信息
            employments = candidate.get('activities-summary', {}).get('employments', {}).get('employment-summary', [])
            if employments:
                print(f"     就业: {len(employments)} 条记录")
                for emp in employments[:2]:  # 只显示前2条
                    org_name = emp.get('organization', {}).get('name', 'N/A')
                    print(f"       - {org_name}")
            
            print()
    
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        import traceback
        print(traceback.format_exc())

def test_mit_specific_search():
    """
    测试指定MIT时的搜索逻辑
    """
    print("\n" + "=" * 80)
    print("MIT特定搜索测试")
    print("=" * 80)
    
    author_name = "Song Han"
    institution = "MIT"
    
    print(f"作者: {author_name}")
    print(f"机构: {institution}")
    print()
    
    try:
        # 使用更大的max_results来看是否能找到更多候选人
        result = orcid_search_and_pick(author_name, institution, max_results=20)
        
        if result:
            print("✅ 找到匹配结果")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("❌ 未找到匹配结果")
            print("\n尝试分析原因...")
            
            # 获取所有候选人
            candidates = orcid_candidates_by_name(author_name, max_candidates=10)
            print(f"总共找到 {len(candidates)} 个候选人")
            
            # 对每个候选人测试MIT匹配
            for i, candidate in enumerate(candidates, 1):
                orcid_id = candidate.get('orcid-identifier', {}).get('path', 'N/A')
                print(f"\n候选人 {i}: {orcid_id}")
                
                # 这里需要获取详细信息来测试机构匹配
                # 但为了简化，我们只显示基本信息
                given_names = candidate.get('person', {}).get('name', {}).get('given-names', {}).get('value', 'N/A')
                family_name = candidate.get('person', {}).get('name', {}).get('family-name', {}).get('value', 'N/A')
                print(f"姓名: {given_names} {family_name}")
    
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    print("开始详细ORCID分析...")
    print(f"当前工作目录: {os.getcwd()}")
    print()
    
    # 详细分析Song Han的ORCID
    analyze_song_han_orcid()
    
    # 测试MIT特定搜索
    test_mit_specific_search()
    
    print("\n" + "=" * 80)
    print("详细分析完成")
    print("=" * 80)