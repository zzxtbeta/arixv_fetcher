#!/usr/bin/env python3

import sys
import os
sys.path.append('.')

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

from src.db.postgres_client import postgres_client
import asyncio

async def check_null_dates():
    try:
        # 查询有null日期的记录 (前10条)
        records = await postgres_client.select(
            table='author_affiliation',
            columns='id, author_id, affiliation_id, start_date, end_date',
            filters={'start_date__isnull': True, 'end_date__isnull': True},
            limit=10
        )
        
        print(f'Found {len(records)} records with null dates:')
        for r in records:
            print(f'ID: {r["id"]}, Author: {r["author_id"]}, Affiliation: {r["affiliation_id"]}, Start: {r["start_date"]}, End: {r["end_date"]}')
            
        # 统计总数
        total_count = await postgres_client.count(
            table='author_affiliation',
            filters={'start_date__isnull': True, 'end_date__isnull': True}
        )
        
        print(f'\nTotal records with null dates: {total_count}')
        
    except Exception as e:
        print(f'Error: {e}')

if __name__ == '__main__':
    asyncio.run(check_null_dates())