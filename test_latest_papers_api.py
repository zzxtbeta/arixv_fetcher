#!/usr/bin/env python3
"""测试latest-papers API"""

import requests
import json

def test_latest_papers_api():
    """测试latest-papers API"""
    print("=== 测试latest-papers API ===")
    
    # 测试基本调用
    try:
        response = requests.get("http://localhost:8000/dashboard/latest-papers")
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"返回数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
        else:
            print(f"错误响应: {response.text}")
    except Exception as e:
        print(f"API调用失败: {e}")
    
    # 测试带参数的调用
    print("\n=== 测试带参数的latest-papers API ===")
    try:
        response = requests.get("http://localhost:8000/dashboard/latest-papers?page=1&limit=10")
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"返回数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
        else:
            print(f"错误响应: {response.text}")
    except Exception as e:
        print(f"API调用失败: {e}")

if __name__ == "__main__":
    test_latest_papers_api()