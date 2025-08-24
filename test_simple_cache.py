#!/usr/bin/env python3
"""
简单的缓存测试
"""

import requests
import time
import json

def test_simple_cache():
    """测试简单缓存"""
    print("🔍 简单缓存测试")
    print("=" * 40)
    
    url = "http://localhost:8000/dashboard/overview"
    
    print("\n第一次请求 (应该慢 - 查询数据库):")
    start_time = time.time()
    try:
        response = requests.get(url, timeout=15)
        duration1 = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 成功 - 响应时间: {duration1:.3f}秒")
            print(f"   数据: {json.dumps(data, ensure_ascii=False)}")
        else:
            print(f"❌ 失败 - 状态码: {response.status_code}")
            return
            
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        return
    
    print("\n等待 1 秒...")
    time.sleep(1)
    
    print("\n第二次请求 (应该快 - 来自缓存):")
    start_time = time.time()
    try:
        response = requests.get(url, timeout=15)
        duration2 = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 成功 - 响应时间: {duration2:.3f}秒")
            print(f"   数据: {json.dumps(data, ensure_ascii=False)}")
            
            # 分析缓存效果
            improvement = duration1 - duration2
            improvement_percent = (improvement / duration1) * 100
            
            print(f"\n📊 缓存效果分析:")
            print(f"第一次请求: {duration1:.3f}秒")
            print(f"第二次请求: {duration2:.3f}秒")
            print(f"时间改善: {improvement:.3f}秒 ({improvement_percent:.1f}%)")
            
            if improvement > 0.5:  # 改善超过 0.5 秒
                print("✅ 缓存效果明显")
            elif improvement > 0.1:  # 改善超过 0.1 秒
                print("⚡ 缓存有一定效果")
            elif improvement > 0:
                print("⚠️ 缓存效果微弱")
            else:
                print("❌ 缓存可能未生效")
                
        else:
            print(f"❌ 失败 - 状态码: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 错误: {str(e)}")

def test_multiple_quick_requests():
    """测试多个快速请求"""
    print("\n🚀 测试多个快速请求")
    print("=" * 40)
    
    url = "http://localhost:8000/dashboard/overview"
    
    times = []
    for i in range(3):
        print(f"\n请求 {i+1}:")
        start_time = time.time()
        try:
            response = requests.get(url, timeout=10)
            duration = time.time() - start_time
            times.append(duration)
            
            if response.status_code == 200:
                print(f"✅ 成功 - 响应时间: {duration:.3f}秒")
            else:
                print(f"❌ 失败 - 状态码: {response.status_code}")
                
        except Exception as e:
            print(f"❌ 错误: {str(e)}")
        
        # 短暂等待
        if i < 2:
            time.sleep(0.5)
    
    if times:
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        
        print(f"\n📊 请求时间统计:")
        print(f"平均时间: {avg_time:.3f}秒")
        print(f"最快时间: {min_time:.3f}秒")
        print(f"最慢时间: {max_time:.3f}秒")
        
        # 检查时间一致性
        time_variance = max_time - min_time
        if time_variance < 0.1:
            print("✅ 响应时间一致 (可能来自缓存)")
        elif time_variance < 0.5:
            print("⚡ 响应时间较一致")
        else:
            print("⚠️ 响应时间差异较大")

def main():
    """主测试函数"""
    print("🧪 简单缓存测试")
    
    # 简单缓存测试
    test_simple_cache()
    
    # 多个快速请求测试
    test_multiple_quick_requests()
    
    print("\n🏁 测试完成")
    print("\n💡 说明:")
    print("- 如果缓存生效，第二次请求应该明显更快")
    print("- 多个连续请求的时间应该比较一致")
    print("- 如果所有请求都很慢且时间相近，可能是网络延迟导致")

if __name__ == "__main__":
    main()