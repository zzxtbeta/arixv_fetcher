#!/usr/bin/env python3
"""
测试论文数据获取和处理功能
"""

import requests
import json
import time

def test_paper_processing():
    """测试论文数据获取是否正常工作"""
    
    # 用户上传的论文ID
    paper_ids = ["2504.12526v1", "2504.14775v2"]
    
    print("=== 测试论文数据获取功能 ===")
    print(f"测试论文ID: {paper_ids}")
    
    try:
        # 准备请求数据
        ids_str = ",".join(paper_ids)
        
        # 发送请求
        print("\n发送请求到 /data/fetch-arxiv-by-id...")
        response = requests.post(
            "http://localhost:8000/data/fetch-arxiv-by-id",
            params={"ids": ids_str},
            timeout=60  # 增加超时时间以允许完整处理
        )
        
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 请求成功!")
            print(f"响应数据: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            # 检查处理结果
            status = result.get('status')
            session_id = result.get('session_id')
            inserted = result.get('inserted', 0)
            fetched = result.get('fetched', 0)
            
            print(f"\n处理状态: {status}")
            print(f"会话ID: {session_id}")
            print(f"获取论文数: {fetched}")
            print(f"插入数据库: {inserted}")
            
            if status == 'success' and inserted > 0:
                print("\n🎉 论文数据获取成功！数据已保存到数据库。")
            elif status == 'api_quota_exhausted':
                print("\n⚠️  API配额耗尽，可以稍后使用session_id恢复处理。")
            else:
                print(f"\n⚠️  处理状态: {status}，可能需要检查具体原因。")
                
        else:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except requests.exceptions.Timeout:
        print("⏰ 请求超时 - 论文处理可能需要更长时间")
        print("💡 建议：检查会话记录文件查看处理进度")
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求错误: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析错误: {e}")
    except Exception as e:
        print(f"❌ 其他错误: {e}")

def check_database_data():
    """检查数据库中是否有论文数据"""
    print("\n=== 检查数据库中的论文数据 ===")
    
    try:
        # 检查最新论文
        response = requests.get(
            "http://localhost:8000/dashboard/latest-papers",
            params={"page": 1, "limit": 10},
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            papers = result.get('papers', [])
            total = result.get('total', 0)
            
            print(f"数据库中总论文数: {total}")
            print(f"最新论文数: {len(papers)}")
            
            if papers:
                print("\n最新论文列表:")
                for i, paper in enumerate(papers[:5], 1):
                    print(f"{i}. {paper.get('title', 'N/A')} (ID: {paper.get('arxiv_id', 'N/A')})")
            else:
                print("\n⚠️  数据库中暂无论文数据")
        else:
            print(f"❌ 获取数据库数据失败: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 检查数据库数据时出错: {e}")

if __name__ == "__main__":
    test_paper_processing()
    time.sleep(2)
    check_database_data()