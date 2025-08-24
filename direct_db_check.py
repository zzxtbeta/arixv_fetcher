#!/usr/bin/env python3
"""直接检查数据库中的论文数据"""

import os
from dotenv import load_dotenv
import requests
import json

# 加载环境变量
load_dotenv()

from src.db.supabase_client import supabase_client

def check_papers_table():
    """直接查询papers表"""
    print("=== 直接查询papers表 ===")
    try:
        # 查询所有论文
        papers = supabase_client.select(
            table="papers",
            columns="id, paper_title, published, arxiv_entry",
            limit=10
        )
        print(f"Papers表中的记录数: {len(papers) if papers else 0}")
        if papers:
            for paper in papers:
                print(f"  - ID: {paper.get('id')}, Title: {paper.get('paper_title')[:50]}..., ArXiv: {paper.get('arxiv_entry')}")
        else:
            print("  没有找到任何论文记录")
    except Exception as e:
        print(f"查询papers表失败: {e}")

def check_authors_table():
    """直接查询authors表"""
    print("\n=== 直接查询authors表 ===")
    try:
        authors = supabase_client.select(
            table="authors",
            columns="id, author_name_en",
            limit=10
        )
        print(f"Authors表中的记录数: {len(authors) if authors else 0}")
        if authors:
            for author in authors:
                print(f"  - ID: {author.get('id')}, Name: {author.get('author_name_en')}")
    except Exception as e:
        print(f"查询authors表失败: {e}")

def check_categories_table():
    """直接查询categories表"""
    print("\n=== 直接查询categories表 ===")
    try:
        categories = supabase_client.select(
            table="categories",
            columns="id, category",
            limit=10
        )
        print(f"Categories表中的记录数: {len(categories) if categories else 0}")
        if categories:
            for cat in categories:
                print(f"  - ID: {cat.get('id')}, Category: {cat.get('category')}")
    except Exception as e:
        print(f"查询categories表失败: {e}")

def check_institutions_table():
    """直接查询institutions表"""
    print("\n=== 直接查询institutions表 ===")
    try:
        institutions = supabase_client.select(
            table="institutions",
            columns="id, institution_name",
            limit=10
        )
        print(f"Institutions表中的记录数: {len(institutions) if institutions else 0}")
        if institutions:
            for inst in institutions:
                print(f"  - ID: {inst.get('id')}, Name: {inst.get('institution_name')}")
    except Exception as e:
        print(f"查询institutions表失败: {e}")

def check_api_overview():
    """通过API检查总览数据"""
    print("\n=== 通过API检查总览数据 ===")
    try:
        response = requests.get("http://localhost:8000/dashboard/overview")
        if response.status_code == 200:
            data = response.json()
            print(f"API返回的总览数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
        else:
            print(f"API调用失败，状态码: {response.status_code}")
    except Exception as e:
        print(f"API调用失败: {e}")

if __name__ == "__main__":
    print("开始直接检查数据库...")
    check_papers_table()
    check_authors_table()
    check_categories_table()
    check_institutions_table()
    check_api_overview()
    print("\n检查完成。")