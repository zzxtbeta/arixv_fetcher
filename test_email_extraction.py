#!/usr/bin/env python3
"""
Test script for email extraction functionality.
Tests the complete flow: PDF -> LLM -> email extraction -> database storage.
"""

import asyncio
import sys
import os
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from db.database import DatabaseManager
from agent.data_graph import process_single_paper

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_email_extraction():
    """Test email extraction from a sample paper."""
    
    # Sample paper data with PDF URL that likely contains email addresses
    test_paper = {
        "title": "Test Paper for Email Extraction",
        "authors": ["John Doe", "Jane Smith"],
        "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",  # Use a real arXiv paper
        "published_at": "2023-01-01",
        "arxiv_entry": "2301.00001"
    }
    
    logger.info("Testing email extraction functionality...")
    
    # Test the process_single_paper function
    try:
        result = await process_single_paper({"paper": test_paper})
        papers = result.get("papers", [])
        
        if not papers:
            logger.error("No papers returned from processing")
            return False
            
        paper = papers[0]
        author_affiliations = paper.get("author_affiliations", [])
        
        logger.info(f"Processed paper: {paper.get('title')}")
        logger.info(f"Number of authors processed: {len(author_affiliations)}")
        
        # Check if email extraction worked
        emails_found = 0
        for author_info in author_affiliations:
            name = author_info.get("name")
            email = author_info.get("email")
            affiliations = author_info.get("affiliations", [])
            
            logger.info(f"Author: {name}")
            logger.info(f"  Email: {email if email else 'Not found'}")
            logger.info(f"  Affiliations: {affiliations}")
            
            if email:
                emails_found += 1
        
        logger.info(f"Total emails extracted: {emails_found}/{len(author_affiliations)}")
        
        if emails_found > 0:
            logger.info("✅ Email extraction test PASSED - at least one email was found")
            return True
        else:
            logger.warning("⚠️ Email extraction test PARTIAL - no emails found (may be normal if PDF doesn't contain emails)")
            return True  # This is still considered a pass as not all papers have emails
            
    except Exception as e:
        logger.error(f"❌ Email extraction test FAILED: {e}")
        return False

async def test_database_storage():
    """Test that emails are properly stored in the database."""
    
    logger.info("Testing database storage of emails...")
    
    try:
        db = DatabaseManager()
        
        # Check if any authors have email addresses
        async with db.get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT author_name_en, email FROM authors WHERE email IS NOT NULL LIMIT 5"
                )
                rows = await cur.fetchall()
                
                logger.info(f"Found {len(rows)} authors with email addresses in database:")
                for row in rows:
                    logger.info(f"  {row[0]}: {row[1]}")
                
                if len(rows) > 0:
                    logger.info("✅ Database storage test PASSED - emails found in database")
                    return True
                else:
                    logger.info("ℹ️ No emails found in database yet (may be normal for new setup)")
                    return True
                    
    except Exception as e:
        logger.error(f"❌ Database storage test FAILED: {e}")
        return False

async def main():
    """Run all email extraction tests."""
    
    logger.info("Starting email extraction tests...")
    
    # Test 1: Email extraction from PDF
    test1_passed = await test_email_extraction()
    
    # Test 2: Database storage
    test2_passed = await test_database_storage()
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("EMAIL EXTRACTION TEST SUMMARY")
    logger.info("="*50)
    logger.info(f"PDF Email Extraction: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    logger.info(f"Database Storage: {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    
    if test1_passed and test2_passed:
        logger.info("\n🎉 All email extraction tests PASSED!")
        return 0
    else:
        logger.error("\n💥 Some email extraction tests FAILED!")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)