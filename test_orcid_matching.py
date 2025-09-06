#!/usr/bin/env python3
"""
测试ORCID匹配功能
测试作者：Song Han
测试机构：MIT
"""

import sys
import os
import json
from typing import Dict, Any, Optional

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入项目中的ORCID匹配函数
from src.agent.utils import (
    orcid_search_and_pick,
    best_aff_match_for_institution,
    normalize_name_for_strict,
    norm_string
)

def test_orcid_matching():
    """
    测试Song Han和MIT的ORCID匹配
    """
    print("=" * 60)
    print("ORCID匹配测试")
    print("=" * 60)
    
    # 测试参数
    author_name = "Song Han"
    institution = "MIT"
    
    print(f"测试作者: {author_name}")
    print(f"测试机构: {institution}")
    print()
    
    # 标准化处理
    normalized_name = normalize_name_for_strict(author_name)
    normalized_institution = norm_string(institution)
    
    print(f"标准化作者名: {normalized_name}")
    print(f"标准化机构名: {normalized_institution}")
    print()
    
    try:
        print("开始ORCID搜索...")
        result = orcid_search_and_pick(author_name, institution, max_results=10)
        
        if result:
            print("✅ 找到ORCID匹配结果:")
            print("-" * 40)
            
            # 基本信息
            print(f"ORCID ID: {result.get('orcid_id', 'N/A')}")
            print(f"显示名称: {result.get('display_name', 'N/A')}")
            print(f"名: {result.get('given_names', 'N/A')}")
            print(f"姓: {result.get('family_name', 'N/A')}")
            
            # 其他名称
            other_names = result.get('other_names', [])
            if other_names:
                print(f"其他名称: {', '.join(other_names)}")
            
            print()
            
            # 就业信息
            employments = result.get('employments', [])
            if employments:
                print("就业信息:")
                for i, emp in enumerate(employments, 1):
                    print(f"  {i}. 机构: {emp.get('organization', 'N/A')}")
                    print(f"     部门: {emp.get('department', 'N/A')}")
                    print(f"     职位: {emp.get('role', 'N/A')}")
                    print(f"     开始时间: {emp.get('start_date', 'N/A')}")
                    print(f"     结束时间: {emp.get('end_date', 'N/A')}")
                    print()
            
            # 教育信息
            educations = result.get('educations', [])
            if educations:
                print("教育信息:")
                for i, edu in enumerate(educations, 1):
                    print(f"  {i}. 机构: {edu.get('organization', 'N/A')}")
                    print(f"     部门: {edu.get('department', 'N/A')}")
                    print(f"     学位/角色: {edu.get('role', 'N/A')}")
                    print(f"     开始时间: {edu.get('start_date', 'N/A')}")
                    print(f"     结束时间: {edu.get('end_date', 'N/A')}")
                    print()
            
            # 测试机构匹配
            print("测试机构匹配:")
            best_match = best_aff_match_for_institution(institution, result)
            if best_match:
                print("✅ 找到最佳机构匹配:")
                print(f"  机构: {best_match.get('organization', 'N/A')}")
                print(f"  部门: {best_match.get('department', 'N/A')}")
                print(f"  职位: {best_match.get('role', 'N/A')}")
                print(f"  开始时间: {best_match.get('start_date', 'N/A')}")
                print(f"  结束时间: {best_match.get('end_date', 'N/A')}")
            else:
                print("❌ 未找到机构匹配")
            
            print()
            print("完整结果JSON:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
        else:
            print("❌ 未找到ORCID匹配结果")
            print("可能的原因:")
            print("1. 作者名称不匹配")
            print("2. 机构信息不匹配")
            print("3. ORCID数据库中没有该作者")
            print("4. 网络连接问题")
    
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {str(e)}")
        import traceback
        print("错误详情:")
        print(traceback.format_exc())

def test_different_variations():
    """
    测试不同的名称和机构变体
    """
    print("\n" + "=" * 60)
    print("测试不同变体")
    print("=" * 60)
    
    variations = [
        ("Song Han", "MIT"),
        ("Song Han", "Massachusetts Institute of Technology"),
        ("Han Song", "MIT"),  # 名字顺序颠倒
        ("Song Han", "EECS MIT"),  # 包含部门
        ("Song Han", ""),  # 不指定机构
    ]
    
    for i, (name, inst) in enumerate(variations, 1):
        print(f"\n测试变体 {i}: 作者='{name}', 机构='{inst}'")
        try:
            result = orcid_search_and_pick(name, inst, max_results=5)
            if result:
                print(f"✅ 找到匹配: ORCID={result.get('orcid_id')}, 名称={result.get('display_name')}")
            else:
                print("❌ 未找到匹配")
        except Exception as e:
            print(f"❌ 错误: {str(e)}")

if __name__ == "__main__":
    print("开始ORCID匹配测试...")
    print(f"当前工作目录: {os.getcwd()}")
    print(f"Python路径: {sys.path[0]}")
    print()
    
    # 主要测试
    test_orcid_matching()
    
    # 变体测试
    test_different_variations()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)