#!/usr/bin/env python3
"""
测试 API 缓存性能
"""

import requests
import time
import json

def test_cache_performance():
    """测试缓存性能"""
    print("🔍 测试 API 缓存性能")
    print("=" * 50)
    
    url = "http://localhost:8000/dashboard/overview"
    
    # 测试多次请求，观察缓存效果
    for i in range(5):
        print(f"\n请求 {i+1}:")
        
        start_time = time.time()
        try:
            response = requests.get(url, timeout=10)
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ 成功 - 响应时间: {duration:.3f}秒")
                print(f"   数据: {json.dumps(data, ensure_ascii=False)}")
                
                # 分析响应时间
                if duration < 0.1:
                    print(f"   🚀 极快响应 (可能来自缓存)")
                elif duration < 0.5:
                    print(f"   ⚡ 快速响应")
                elif duration < 2.0:
                    print(f"   🐌 响应较慢")
                else:
                    print(f"   🐢 响应很慢 (可能是数据库查询)")
            else:
                print(f"❌ 失败 - 状态码: {response.status_code}")
                
        except Exception as e:
            print(f"❌ 错误: {str(e)}")
        
        # 短暂等待
        if i < 4:
            time.sleep(1)
    
    print("\n" + "=" * 50)
    print("📝 缓存测试说明:")
    print("- 第一次请求通常较慢 (需要查询数据库)")
    print("- 后续请求应该很快 (来自缓存，TTL=5分钟)")
    print("- 如果所有请求都很慢，说明缓存未生效")

def test_concurrent_cache():
    """测试并发请求的缓存效果"""
    print("\n🚀 测试并发请求缓存效果")
    print("=" * 50)
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    url = "http://localhost:8000/dashboard/overview"
    
    def make_request(request_id):
        start_time = time.time()
        try:
            response = requests.get(url, timeout=10)
            duration = time.time() - start_time
            return request_id, True, duration, response.status_code
        except Exception as e:
            duration = time.time() - start_time
            return request_id, False, duration, str(e)
    
    # 发起10个并发请求
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request, i+1) for i in range(10)]
        
        results = []
        for future in as_completed(futures):
            results.append(future.result())
    
    # 按请求ID排序
    results.sort(key=lambda x: x[0])
    
    print("\n并发请求结果:")
    total_time = 0
    success_count = 0
    
    for request_id, success, duration, status in results:
        if success:
            print(f"请求 {request_id:2d}: ✅ {duration:.3f}秒 (状态码: {status})")
            total_time += duration
            success_count += 1
        else:
            print(f"请求 {request_id:2d}: ❌ {duration:.3f}秒 (错误: {status})")
    
    if success_count > 0:
        avg_time = total_time / success_count
        print(f"\n📊 统计结果:")
        print(f"成功率: {success_count}/10 ({success_count*10}%)")
        print(f"平均响应时间: {avg_time:.3f}秒")
        
        if avg_time < 0.5:
            print("✅ 并发性能优秀")
        elif avg_time < 2.0:
            print("⚠️ 并发性能一般")
        else:
            print("❌ 并发性能较差")

def test_cache_expiry():
    """测试缓存过期机制"""
    print("\n⏰ 测试缓存过期机制")
    print("=" * 50)
    print("注意: 此测试需要等待缓存过期 (5分钟)")
    print("建议手动测试或修改缓存TTL为较短时间")
    
    url = "http://localhost:8000/dashboard/overview"
    
    # 第一次请求
    print("\n第一次请求 (建立缓存):")
    start_time = time.time()
    try:
        response = requests.get(url, timeout=10)
        duration = time.time() - start_time
        print(f"响应时间: {duration:.3f}秒")
    except Exception as e:
        print(f"错误: {str(e)}")
    
    # 立即第二次请求
    print("\n第二次请求 (应该来自缓存):")
    start_time = time.time()
    try:
        response = requests.get(url, timeout=10)
        duration = time.time() - start_time
        print(f"响应时间: {duration:.3f}秒")
        
        if duration < 0.1:
            print("✅ 缓存生效")
        else:
            print("⚠️ 缓存可能未生效")
    except Exception as e:
        print(f"错误: {str(e)}")

def main():
    """主测试函数"""
    print("🧪 API 缓存性能测试")
    
    # 基础缓存测试
    test_cache_performance()
    
    # 并发缓存测试
    test_concurrent_cache()
    
    # 缓存过期测试
    test_cache_expiry()
    
    print("\n🏁 缓存测试完成")
    print("\n💡 优化建议:")
    print("1. 如果缓存未生效，检查服务器重启是否清空了内存缓存")
    print("2. 考虑使用 Redis 等外部缓存存储")
    print("3. 根据数据更新频率调整缓存TTL")
    print("4. 为不同类型的数据设置不同的缓存策略")

if __name__ == "__main__":
    main()