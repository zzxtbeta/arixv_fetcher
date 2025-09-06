#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：按照项目逻辑查找Song Han + MIT的ORCID
完全使用项目中的默认参数和逻辑
"""

import sys
import os
import json
from pathlib import Path

# 添加src目录到Python路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

try:
    from agent.utils import orcid_search_and_pick, best_aff_match_for_institution
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    print("请确保在项目根目录运行此脚本")
    sys.exit(1)

def main():
    """
    主测试函数：按照项目逻辑查找Song Han + MIT的ORCID
    """
    print("=" * 80)
    print("Song Han + MIT ORCID匹配测试")
    print("使用项目默认参数和逻辑")
    print("=" * 80)
    
    # 测试参数
    author_name = "Song Han"
    institution = "NVIDIA"
    
    print(f"作者姓名: {author_name}")
    print(f"机构名称: {institution}")
    print(f"候选人个数: 10 (项目默认值)")
    print(f"相似度阈值: 0.86 (项目默认值)")
    print()
    
    print("开始ORCID匹配...")
    print("-" * 40)
    
    try:
        # 使用项目默认参数调用orcid_search_and_pick
        # max_results=10 是默认值
        result = orcid_search_and_pick(author_name, institution)
        
        if result:
            print("✅ 找到ORCID匹配结果!")
            print()
            print("匹配结果详情:")
            print("-" * 20)
            print(f"ORCID ID: {result.get('orcid_id', 'N/A')}")
            print(f"显示名称: {result.get('display_name', 'N/A')}")
            print(f"名: {result.get('given_names', 'N/A')}")
            print(f"姓: {result.get('family_name', 'N/A')}")
            
            # 显示就业信息
            employments = result.get('employments', [])
            print(f"\n就业信息 ({len(employments)} 条):")
            for i, emp in enumerate(employments, 1):
                print(f"  {i}. 机构: {emp.get('organization', 'N/A')}")
                print(f"     部门: {emp.get('department', 'N/A')}")
                print(f"     职位: {emp.get('role', 'N/A')}")
                print(f"     时间: {emp.get('start_date', 'N/A')} - {emp.get('end_date', 'N/A') or '至今'}")
                print()
            
            # 显示教育信息
            educations = result.get('educations', [])
            print(f"教育信息 ({len(educations)} 条):")
            for i, edu in enumerate(educations, 1):
                print(f"  {i}. 学校: {edu.get('organization', 'N/A')}")
                print(f"     院系: {edu.get('department', 'N/A')}")
                print(f"     学位: {edu.get('role', 'N/A')}")
                print(f"     时间: {edu.get('start_date', 'N/A')} - {edu.get('end_date', 'N/A') or '至今'}")
                print()
            
            # 测试机构匹配逻辑
            print("机构匹配分析:")
            print("-" * 20)
            best_match = best_aff_match_for_institution(institution, result)
            if best_match:
                print(f"✅ 找到机构匹配: {best_match.get('kind', 'N/A')}")
                print(f"   机构: {best_match.get('organization', 'N/A')}")
                print(f"   部门: {best_match.get('department', 'N/A')}")
                print(f"   职位: {best_match.get('role', 'N/A')}")
            else:
                print("❌ 未找到机构匹配")
                print("   这解释了为什么指定MIT时匹配失败")
            
            print("\n完整结果JSON:")
            print("-" * 20)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
        else:
            print("❌ 未找到ORCID匹配结果")
            print()
            print("可能的原因:")
            print("1. 姓名匹配失败 - ORCID记录中的姓名与输入不完全匹配")
            print("2. 机构匹配失败 - ORCID记录中没有MIT相关的就业或教育信息")
            print("3. 相似度不足 - 机构名称相似度低于0.86阈值")
            print("4. API问题 - ORCID API调用失败或返回空结果")
            
            print("\n建议尝试:")
            print("- 不指定机构进行搜索")
            print("- 使用机构全名 'Massachusetts Institute of Technology'")
            print("- 检查网络连接和ORCID API状态")
    
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {str(e)}")
        import traceback
        print("\n错误详情:")
        print(traceback.format_exc())
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)

def test_without_institution():
    """
    对比测试：不指定机构的情况
    """
    print("\n" + "=" * 80)
    print("对比测试：不指定机构")
    print("=" * 80)
    
    author_name = "Song Han"
    
    print(f"作者姓名: {author_name}")
    print(f"机构名称: (未指定)")
    print()
    
    try:
        result = orcid_search_and_pick(author_name, "")
        
        if result:
            print("✅ 不指定机构时找到匹配结果!")
            print(f"ORCID ID: {result.get('orcid_id', 'N/A')}")
            print(f"显示名称: {result.get('display_name', 'N/A')}")
            
            # 简要显示机构信息
            employments = result.get('employments', [])
            if employments:
                print(f"\n就业机构:")
                for emp in employments[:3]:  # 只显示前3个
                    print(f"  - {emp.get('organization', 'N/A')}")
            
            educations = result.get('educations', [])
            if educations:
                print(f"\n教育机构:")
                for edu in educations[:3]:  # 只显示前3个
                    print(f"  - {edu.get('organization', 'N/A')}")
        else:
            print("❌ 即使不指定机构也未找到匹配结果")
    
    except Exception as e:
        print(f"❌ 对比测试错误: {str(e)}")

if __name__ == "__main__":
    main()
    test_without_institution()