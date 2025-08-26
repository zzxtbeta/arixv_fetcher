#!/usr/bin/env python3
"""
测试脚本：验证数据库表结构是否正确创建
"""

import asyncio
import os
from src.db.database import DatabaseManager

async def test_schema():
    """测试数据库表结构"""
    try:
        # 检查环境变量
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            print("错误：DATABASE_URL 环境变量未设置")
            return
            
        # 尝试初始化数据库连接（如果尚未初始化）
        try:
            await DatabaseManager.initialize(DATABASE_URL)
            print("数据库连接初始化成功")
        except Exception as init_error:
            print(f"数据库初始化警告（可能已初始化）：{init_error}")
        
        # 查询所有表
        async with DatabaseManager.get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    ORDER BY table_name;
                """)
                tables = await cur.fetchall()
                
                print("\n数据库中的表：")
                for table in tables:
                    print(f"  - {table[0]}")
                
                # 检查特定表是否存在
                expected_tables = [
                    'papers', 'authors', 'affiliations', 'ranking_systems',
                    'keywords', 'categories', 'people_verified', 'author_paper',
                    'author_affiliation', 'paper_category', 'paper_keyword',
                    'affiliation_rankings', 'author_people_verified'
                ]
                
                existing_table_names = [table[0] for table in tables]
                
                print("\n表创建状态检查：")
                for table_name in expected_tables:
                    if table_name in existing_table_names:
                        print(f"  ✓ {table_name} - 已创建")
                    else:
                        print(f"  ✗ {table_name} - 未找到")
                        
        await DatabaseManager.close()
        print("\n数据库连接已关闭")
        
    except Exception as e:
        print(f"测试失败：{e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_schema())