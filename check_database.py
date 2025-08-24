#!/usr/bin/env python3
"""
直接检查数据库中的论文数据
"""

import requests
import json

def check_specific_papers():
    """检查特定论文是否在数据库中"""
    print("=== 检查特定论文数据 ===")
    
    target_ids = ["2504.12526v1", "2504.14775v2"]
    
    try:
        # 获取所有论文数据
        response = requests.get(
            "http://localhost:8000/dashboard/latest-papers",
            params={"page": 1, "limit": 50},  # 增加限制数量
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            papers = result.get('papers', [])
            total = result.get('total', 0)
            
            print(f"数据库中总论文数: {total}")
            print(f"返回的论文数: {len(papers)}")
            
            if papers:
                print("\n所有论文列表:")
                found_papers = []
                for i, paper in enumerate(papers, 1):
                    arxiv_id = paper.get('arxiv_id', 'N/A')
                    title = paper.get('title', 'N/A')[:60] + '...' if len(paper.get('title', '')) > 60 else paper.get('title', 'N/A')
                    created_at = paper.get('created_at', 'N/A')
                    print(f"{i}. {arxiv_id}: {title} (创建时间: {created_at})")
                    
                    # 检查是否是我们要找的论文
                    if arxiv_id in target_ids:
                        found_papers.append(arxiv_id)
                
                print(f"\n目标论文查找结果:")
                for target_id in target_ids:
                    if target_id in found_papers:
                        print(f"✅ {target_id}: 已找到")
                    else:
                        print(f"❌ {target_id}: 未找到")
                        
                if found_papers:
                    print(f"\n🎉 成功找到 {len(found_papers)}/{len(target_ids)} 篇目标论文！")
                else:
                    print("\n⚠️  未找到任何目标论文")
            else:
                print("\n⚠️  数据库中暂无论文数据")
                
        else:
            print(f"❌ 获取数据库数据失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except Exception as e:
        print(f"❌ 检查数据库时出错: {e}")

def check_paper_by_search():
    """通过搜索API检查论文"""
    print("\n=== 通过搜索检查论文 ===")
    
    try:
        # 搜索特定论文
        response = requests.get(
            "http://localhost:8000/dashboard/search-papers",
            params={"query": "MOM Memory-Efficient", "page": 1, "limit": 10},
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            papers = result.get('papers', [])
            total = result.get('total', 0)
            
            print(f"搜索结果总数: {total}")
            
            if papers:
                print("\n搜索到的论文:")
                for paper in papers:
                    arxiv_id = paper.get('arxiv_id', 'N/A')
                    title = paper.get('title', 'N/A')
                    print(f"- {arxiv_id}: {title}")
            else:
                print("\n未搜索到相关论文")
                
        else:
            print(f"❌ 搜索失败: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 搜索时出错: {e}")

def check_overview():
    """检查总览数据"""
    print("\n=== 检查总览数据 ===")
    
    try:
        response = requests.get(
            "http://localhost:8000/dashboard/overview",
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"总论文数: {result.get('papers', 0)}")
            print(f"总作者数: {result.get('authors', 0)}")
            print(f"总机构数: {result.get('affiliations', 0)}")
            print(f"总分类数: {result.get('categories', 0)}")
        else:
            print(f"❌ 获取总览失败: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 获取总览时出错: {e}")

if __name__ == "__main__":
    check_overview()
    check_specific_papers()
    check_paper_by_search()