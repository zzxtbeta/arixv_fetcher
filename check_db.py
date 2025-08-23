import asyncio
from src.db.database import DatabaseManager
import os
from dotenv import load_dotenv

load_dotenv()

async def check_database():
    await DatabaseManager.initialize(os.getenv('DATABASE_URL'))
    pool = await DatabaseManager.get_pool()
    
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # Check all recent papers and their author counts
            await cur.execute("""
                SELECT p.arxiv_entry, p.paper_title, COUNT(ap.author_id) as author_count 
                FROM papers p 
                LEFT JOIN author_paper ap ON p.id = ap.paper_id 
                GROUP BY p.id, p.arxiv_entry, p.paper_title 
                ORDER BY p.id DESC LIMIT 10
            """)
            rows = await cur.fetchall()
            print('Recent papers and their author counts:')
            for row in rows:
                print(f'{row[0]}: {row[1][:50]}... - {row[2]} authors')
            
            # Check recent author-paper relationships
            await cur.execute("""
                SELECT p.arxiv_entry, a.author_name_en, ap.author_order 
                FROM papers p 
                JOIN author_paper ap ON p.id = ap.paper_id 
                JOIN authors a ON ap.author_id = a.id 
                ORDER BY p.id DESC, ap.author_order LIMIT 20
            """)
            rows2 = await cur.fetchall()
            print('\nRecent author-paper relationships:')
            for row in rows2:
                print(f'{row[0]}: {row[1]} (order: {row[2]})')
            
            # Check for potential duplicates in author_paper table
            await cur.execute("""
                SELECT ap.author_id, ap.paper_id, COUNT(*) as count
                FROM author_paper ap
                JOIN papers p ON ap.paper_id = p.id
                GROUP BY ap.author_id, ap.paper_id
                HAVING COUNT(*) > 1
                LIMIT 10
            """)
            duplicates = await cur.fetchall()
            print('\nDuplicate author-paper relationships:')
            if duplicates:
                for dup in duplicates:
                    print(f'Author ID {dup[0]}, Paper ID {dup[1]}: {dup[2]} entries')
            else:
                print('No duplicates found in author_paper table')

if __name__ == '__main__':
    asyncio.run(check_database())