#!/usr/bin/env python3
"""
手动触发处理pending状态的论文
"""

import requests
import json
import time

def trigger_resume_processing():
    """触发恢复处理pending的会话"""
    
    print("=== 触发恢复处理功能 ===")
    
    # 最新的会话ID
    session_id = "batch_20250824_163002"
    
    try:
        print(f"尝试恢复会话: {session_id}")
        
        # 使用正确的恢复处理API
        response = requests.post(
            "http://localhost:8000/data/fetch-arxiv-by-id",
            params={
                "ids": "",  # 空的，因为我们使用resume_session_id
                "resume_session_id": session_id
            },
            timeout=120  # 2分钟超时
        )
        
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 恢复处理请求成功!")
            print(f"响应数据: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            # 检查处理结果
            status = result.get('status')
            processed = result.get('processed', 0)
            failed = result.get('failed', 0)
            
            print(f"\n处理状态: {status}")
            print(f"处理成功: {processed}")
            print(f"处理失败: {failed}")
            
            if status == 'completed' and processed > 0:
                print("\n🎉 论文处理完成！")
                return True
            elif status == 'api_quota_exhausted':
                print("\n⚠️  API配额耗尽")
            else:
                print(f"\n⚠️  处理状态: {status}")
                
        else:
            print(f"❌ 恢复处理失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except requests.exceptions.Timeout:
        print("⏰ 请求超时 - 处理可能仍在进行中")
        return None
    except Exception as e:
        print(f"❌ 错误: {e}")
        
    return False

def check_processing_status():
    """检查处理状态"""
    print("\n=== 检查处理状态 ===")
    
    try:
        # 读取会话文件
        with open('resume_data/sessions.json', 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            
        session_id = "batch_20250824_163002"
        if session_id in sessions:
            session = sessions[session_id]
            print(f"会话状态: {session['status']}")
            print(f"已处理: {session['processed_papers']}")
            print(f"失败: {session['failed_papers']}")
            print(f"总数: {session['total_papers']}")
            
        # 读取记录文件
        try:
            with open(f'resume_data/records/{session_id}_records.json', 'r', encoding='utf-8') as f:
                records = json.load(f)
                
            print("\n论文处理详情:")
            for paper_id, record in records.items():
                print(f"- {paper_id}: {record['status']} (尝试次数: {record['attempts']})")
                if record['error_message']:
                    print(f"  错误: {record['error_message']}")
                    
        except FileNotFoundError:
            print("记录文件不存在")
            
    except Exception as e:
        print(f"❌ 检查状态时出错: {e}")

def check_database_papers():
    """检查数据库中的论文"""
    print("\n=== 检查数据库中的论文 ===")
    
    try:
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
            
            if papers:
                print("\n最新论文:")
                for paper in papers:
                    arxiv_id = paper.get('arxiv_id', 'N/A')
                    title = paper.get('title', 'N/A')[:80] + '...' if len(paper.get('title', '')) > 80 else paper.get('title', 'N/A')
                    print(f"- {arxiv_id}: {title}")
            else:
                print("\n⚠️  数据库中暂无论文数据")
                
        else:
            print(f"❌ 获取数据库数据失败: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 检查数据库时出错: {e}")

if __name__ == "__main__":
    # 先检查当前状态
    check_processing_status()
    
    # 触发恢复处理
    result = trigger_resume_processing()
    
    # 等待一下再检查状态
    if result is not False:
        time.sleep(3)
        check_processing_status()
        
    # 检查数据库
    check_database_papers()