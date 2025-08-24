#!/usr/bin/env python3
"""
测试前端到后端的 API 连接
"""

import requests
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

def test_api_endpoint(url, description):
    """测试单个 API 端点"""
    try:
        start_time = time.time()
        response = requests.get(url, timeout=10)
        duration = time.time() - start_time
        
        print(f"✅ {description}")
        print(f"   状态码: {response.status_code}")
        print(f"   响应时间: {duration:.3f}秒")
        print(f"   响应大小: {len(response.content)} bytes")
        
        if response.headers.get('content-type', '').startswith('application/json'):
            try:
                data = response.json()
                print(f"   JSON 数据: {json.dumps(data, ensure_ascii=False)[:100]}...")
            except:
                print(f"   响应内容: {response.text[:100]}...")
        else:
            print(f"   响应内容: {response.text[:100]}...")
        
        return True, duration
        
    except requests.exceptions.Timeout:
        print(f"❌ {description} - 请求超时")
        return False, 10.0
    except requests.exceptions.ConnectionError:
        print(f"❌ {description} - 连接失败")
        return False, 0.0
    except Exception as e:
        print(f"❌ {description} - 错误: {str(e)}")
        return False, 0.0

def test_cors_headers():
    """测试 CORS 配置"""
    print("\n🔍 测试 CORS 配置...")
    
    try:
        # 模拟前端的 OPTIONS 请求
        response = requests.options(
            'http://localhost:8000/dashboard/overview',
            headers={
                'Origin': 'http://localhost:5174',
                'Access-Control-Request-Method': 'GET',
                'Access-Control-Request-Headers': 'accept,content-type'
            },
            timeout=5
        )
        
        print(f"OPTIONS 请求状态码: {response.status_code}")
        
        cors_headers = {
            'Access-Control-Allow-Origin': response.headers.get('Access-Control-Allow-Origin'),
            'Access-Control-Allow-Methods': response.headers.get('Access-Control-Allow-Methods'),
            'Access-Control-Allow-Headers': response.headers.get('Access-Control-Allow-Headers'),
        }
        
        print("CORS 头信息:")
        for header, value in cors_headers.items():
            status = "✅" if value else "❌"
            print(f"  {status} {header}: {value or '未设置'}")
        
        return all(cors_headers.values())
        
    except Exception as e:
        print(f"❌ CORS 测试失败: {str(e)}")
        return False

def test_concurrent_requests():
    """测试并发请求性能"""
    print("\n🚀 测试并发请求性能...")
    
    urls = [
        ('http://localhost:8000/dashboard/overview', 'Overview API'),
        ('http://localhost:8000/dashboard/latest-papers?limit=5', 'Latest Papers API'),
        ('http://localhost:8000/docs', 'API 文档'),
    ]
    
    results = []
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_url = {
            executor.submit(test_api_endpoint, url, desc): (url, desc)
            for url, desc in urls
        }
        
        for future in as_completed(future_to_url):
            url, desc = future_to_url[future]
            try:
                success, duration = future.result()
                results.append((desc, success, duration))
            except Exception as e:
                print(f"❌ {desc} 并发测试失败: {str(e)}")
                results.append((desc, False, 0.0))
    
    # 统计结果
    successful = sum(1 for _, success, _ in results if success)
    total_time = sum(duration for _, _, duration in results)
    avg_time = total_time / len(results) if results else 0
    
    print(f"\n📊 并发测试结果:")
    print(f"成功率: {successful}/{len(results)} ({successful/len(results)*100:.1f}%)")
    print(f"平均响应时间: {avg_time:.3f}秒")
    
    return successful == len(results)

def test_data_loading_simulation():
    """模拟前端数据加载过程"""
    print("\n🎭 模拟前端数据加载过程...")
    
    # 模拟前端组件加载顺序
    loading_steps = [
        ('http://localhost:8000/dashboard/overview', 'Overview Cards 数据'),
        ('http://localhost:8000/dashboard/latest-papers?limit=10', 'Latest Papers 数据'),
        ('http://localhost:8000/dashboard/author?q=test', 'Author Search 测试'),
    ]
    
    total_loading_time = 0
    all_success = True
    
    for i, (url, description) in enumerate(loading_steps, 1):
        print(f"\n步骤 {i}: 加载 {description}")
        success, duration = test_api_endpoint(url, description)
        total_loading_time += duration
        
        if not success:
            all_success = False
            print(f"⚠️ 步骤 {i} 失败，可能导致前端一直加载")
    
    print(f"\n📈 总加载时间: {total_loading_time:.3f}秒")
    
    if total_loading_time > 10:
        print("⚠️ 总加载时间过长，可能导致用户体验问题")
    elif total_loading_time > 5:
        print("⚠️ 加载时间偏长")
    else:
        print("✅ 加载时间正常")
    
    return all_success

def main():
    """主测试函数"""
    print("🔍 前端 API 连接诊断开始")
    print("=" * 60)
    
    # 基础连接测试
    print("\n1️⃣ 基础 API 连接测试")
    basic_success, _ = test_api_endpoint(
        'http://localhost:8000/dashboard/overview',
        'Dashboard Overview API'
    )
    
    # CORS 测试
    print("\n2️⃣ CORS 配置测试")
    cors_success = test_cors_headers()
    
    # 并发请求测试
    print("\n3️⃣ 并发请求测试")
    concurrent_success = test_concurrent_requests()
    
    # 数据加载模拟
    print("\n4️⃣ 数据加载模拟")
    loading_success = test_data_loading_simulation()
    
    # 总结
    print("\n" + "=" * 60)
    print("🏁 诊断结果总结")
    
    tests = [
        ('基础 API 连接', basic_success),
        ('CORS 配置', cors_success),
        ('并发请求', concurrent_success),
        ('数据加载', loading_success),
    ]
    
    passed = sum(1 for _, success in tests if success)
    total = len(tests)
    
    for test_name, success in tests:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status} {test_name}")
    
    print(f"\n总体结果: {passed}/{total} 测试通过")
    
    if not basic_success:
        print("\n💡 建议检查:")
        print("1. 后端服务是否正常运行 (python -m src.main)")
        print("2. 后端端口是否为 8000")
        print("3. 防火墙是否阻止了连接")
    
    if not cors_success:
        print("\n💡 CORS 问题建议:")
        print("1. 检查后端 CORS 中间件配置")
        print("2. 确认允许的源包含 http://localhost:5174")
    
    if not loading_success:
        print("\n💡 数据加载问题建议:")
        print("1. 检查数据库连接")
        print("2. 确认 Supabase 配置正确")
        print("3. 检查 API 响应时间")

if __name__ == "__main__":
    main()