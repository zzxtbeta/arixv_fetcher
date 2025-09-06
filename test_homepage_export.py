#!/usr/bin/env python3
"""
测试导出作者数据API是否包含homepage字段
"""

import requests
import json

def test_export_authors_homepage():
    """测试导出作者数据是否包含homepage字段"""
    try:
        # 测试JSON格式导出，设置超时
        print("Testing JSON export...")
        response = requests.get("http://localhost:8000/dashboard/export-authors?format=json", timeout=10)
        
        if response.status_code == 200:
            # 只读取响应的前1000个字符来检查结构
            response_text = response.text[:1000]
            print(f"Response preview (first 1000 chars): {response_text}")
            
            # 检查是否包含homepage字段
            if '"homepage"' in response_text:
                print("✅ Homepage field found in response!")
                return True
            else:
                print("❌ Homepage field not found in response")
                return False
        else:
            print(f"❌ API request failed with status code: {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ Request timed out - API is taking too long to respond")
        return False
    except Exception as e:
        print(f"❌ Error testing export API: {e}")
        return False

if __name__ == "__main__":
    print("Testing homepage field in export authors API...")
    success = test_export_authors_homepage()
    
    if success:
        print("\n🎉 Test passed! Homepage field is successfully added to export data.")
    else:
        print("\n💥 Test failed! Homepage field is not properly added.")