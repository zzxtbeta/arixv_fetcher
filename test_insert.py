#!/usr/bin/env python3

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

# Fix for Windows event loop compatibility
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_data_insertion():
    """Test the complete arXiv data processing graph with focus on data insertion."""
    
    from src.agent.data_graph import data_processing_graph
    from src.agent.state import DataProcessingState
    
    # Create initial state
    initial_state = DataProcessingState(
        processing_status="pending",
        error_message=None,
        raw_papers=[],
        papers=[],
        fetched=0,
        inserted=0,
        skipped=0,
        categories=["cs.AI", "cs.CV"]
    )
    
    # Create config with date range (last 7 days to get more papers)
    config = {
        "categories": ["cs.AI", "cs.CV"],
        "start_date": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"),
        "end_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "max_results": 5  # Small number for testing
    }
    
    logger.info(f"Testing data insertion with categories: {config['categories']}")
    logger.info(f"Date range: {config['start_date']} to {config['end_date']}")
    logger.info("Starting data processing graph...")
    
    try:
        # Run the graph
        result = await data_processing_graph.ainvoke(initial_state, config=config)
        
        # Check results
        status = result.get("processing_status", "unknown")
        fetched_count = result.get("fetched", 0)
        inserted_count = result.get("inserted", 0)
        skipped_count = result.get("skipped", 0)
        error_msg = result.get("error_message")
        
        logger.info(f"Graph completed with status: {status}")
        logger.info(f"Fetched: {fetched_count}, Inserted: {inserted_count}, Skipped: {skipped_count}")
        
        if error_msg:
            logger.error(f"Error occurred: {error_msg}")
            print("❌ Data insertion test failed")
            return False
        elif status == "completed" and inserted_count > 0:
            print("✅ Data insertion test passed")
            return True
        elif status == "completed" and inserted_count == 0:
            logger.warning("Graph completed but no data was inserted")
            print("⚠️ Data insertion test completed but no new data inserted (possibly duplicates)")
            return True
        else:
            print("❌ Data insertion test failed")
            return False
            
    except Exception as e:
        logger.error(f"Exception during graph execution: {str(e)}")
        print("❌ Data insertion test failed with exception")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_data_insertion())
    exit(0 if success else 1)