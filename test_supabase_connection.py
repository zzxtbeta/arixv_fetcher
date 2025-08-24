#!/usr/bin/env python3
"""
测试 Supabase 数据库连接
"""

import os
import time
import logging
from dotenv import load_dotenv
from src.db.supabase_client import SupabaseClient

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_supabase_connection():
    """测试 Supabase 连接"""
    logger.info("开始测试 Supabase 连接...")
    
    # 检查环境变量
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    
    logger.info(f"SUPABASE_URL: {'已设置' if supabase_url else '未设置'}")
    logger.info(f"SUPABASE_ANON_KEY: {'已设置' if supabase_key else '未设置'}")
    
    if not supabase_url or not supabase_key:
        logger.error("❌ Supabase 环境变量未正确设置")
        return False
    
    # 测试连接
    try:
        client = SupabaseClient()
        
        if client.client is None:
            logger.error("❌ Supabase 客户端初始化失败")
            return False
        
        logger.info("✅ Supabase 客户端初始化成功")
        
        # 测试简单查询
        start_time = time.time()
        
        # 尝试查询 papers 表的前5条记录
        try:
            result = client.select(
                table="papers",
                columns="id,title,created_at",
                limit=5
            )
            
            query_time = time.time() - start_time
            logger.info(f"✅ 数据库查询成功，耗时: {query_time:.2f}秒")
            logger.info(f"查询到 {len(result)} 条记录")
            
            if result:
                logger.info(f"示例记录: {result[0].get('title', 'N/A')[:50]}...")
            
            return True
            
        except Exception as e:
            query_time = time.time() - start_time
            logger.error(f"❌ 数据库查询失败，耗时: {query_time:.2f}秒")
            logger.error(f"错误信息: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Supabase 连接测试失败: {str(e)}")
        return False

def test_table_access():
    """测试表访问权限"""
    logger.info("\n测试表访问权限...")
    
    try:
        client = SupabaseClient()
        
        if client.client is None:
            logger.error("❌ 客户端未初始化")
            return False
        
        # 测试各个表的访问权限
        tables_to_test = [
            "papers",
            "authors", 
            "affiliations",
            "paper_authors",
            "paper_affiliations"
        ]
        
        for table in tables_to_test:
            try:
                start_time = time.time()
                result = client.select(
                    table=table,
                    columns="*",
                    limit=1
                )
                query_time = time.time() - start_time
                logger.info(f"✅ 表 '{table}' 访问正常，耗时: {query_time:.2f}秒")
                
            except Exception as e:
                logger.error(f"❌ 表 '{table}' 访问失败: {str(e)}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 表访问测试失败: {str(e)}")
        return False

def test_network_latency():
    """测试网络延迟"""
    logger.info("\n测试网络延迟...")
    
    try:
        client = SupabaseClient()
        
        if client.client is None:
            logger.error("❌ 客户端未初始化")
            return False
        
        # 进行多次简单查询测试延迟
        latencies = []
        
        for i in range(5):
            start_time = time.time()
            try:
                client.select(
                    table="papers",
                    columns="id",
                    limit=1
                )
                latency = time.time() - start_time
                latencies.append(latency)
                logger.info(f"查询 {i+1}: {latency:.3f}秒")
                
            except Exception as e:
                logger.error(f"查询 {i+1} 失败: {str(e)}")
        
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            min_latency = min(latencies)
            max_latency = max(latencies)
            
            logger.info(f"\n📊 延迟统计:")
            logger.info(f"平均延迟: {avg_latency:.3f}秒")
            logger.info(f"最小延迟: {min_latency:.3f}秒")
            logger.info(f"最大延迟: {max_latency:.3f}秒")
            
            if avg_latency > 5.0:
                logger.warning("⚠️ 平均延迟较高，可能影响用户体验")
            elif avg_latency > 2.0:
                logger.warning("⚠️ 延迟偏高")
            else:
                logger.info("✅ 延迟正常")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 网络延迟测试失败: {str(e)}")
        return False

def main():
    """主测试函数"""
    logger.info("🔍 Supabase 连接诊断开始")
    logger.info("=" * 50)
    
    # 基础连接测试
    connection_ok = test_supabase_connection()
    
    if connection_ok:
        # 表访问测试
        test_table_access()
        
        # 网络延迟测试
        test_network_latency()
    
    logger.info("\n" + "=" * 50)
    logger.info("🏁 Supabase 连接诊断完成")
    
    if not connection_ok:
        logger.error("\n💡 建议检查:")
        logger.error("1. .env 文件中的 SUPABASE_URL 和 SUPABASE_ANON_KEY 是否正确")
        logger.error("2. 网络连接是否正常")
        logger.error("3. Supabase 项目是否正常运行")
        logger.error("4. API 密钥是否有效")

if __name__ == "__main__":
    main()