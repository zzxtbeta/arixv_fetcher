"""Main entry point for ArXiv scraper and chat service."""

import uvicorn
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file before any other imports
load_dotenv()

# Add project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if __name__ == "__main__":
    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    ) 