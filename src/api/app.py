"""Main FastAPI application for ArXiv Scraper backend."""

import os
import sys
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Fix for Windows event loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.db.checkpoints import CheckpointerManager
from src.agent.graph import build_graph
from src.agent.data_graph import build_data_processing_graph
from src.api.graph import router as graph_router
from src.api.data_processing import router as data_processing_router
from src.api.dashboard import router as dashboard_router
from src.api.models import ErrorResponse

import logging
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage the application's lifespan. This is the recommended way to manage
    resources that need to be initialized on startup and cleaned up on shutdown.
    """
    # Get the database URL from environment variables
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set")

    try:
        # Initialize the async checkpointer
        await CheckpointerManager.initialize(DATABASE_URL)
        logger.info("Async checkpointer initialized successfully")
        
        # Get the checkpointer instance
        checkpointer = await CheckpointerManager.get_checkpointer()
        
        # Build the benchmark graph with async checkpointer
        benchmark_graph = await build_graph(checkpointer)
        app.state.graph = benchmark_graph
        
        # Build the data processing graph with async checkpointer
        data_processing_graph = await build_data_processing_graph(checkpointer)
        app.state.data_processing_graph = data_processing_graph
        logger.info("Successfully compiled graphs and attached to app state.")
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to initialize application: {str(e)}")
        raise
    finally:
        # Clean up resources on shutdown
        await CheckpointerManager.close()
    logger.info("Application shutdown: graph resources released.")


# Create FastAPI app
app = FastAPI(
    title="ArXiv Scraper API",
    description="Backend API for ArXiv scraping and minimal chat",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(graph_router)
app.include_router(data_processing_router)
app.include_router(dashboard_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled exceptions."""
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            code=500,
            message="Internal Server Error",
            detail=str(exc),
        ).model_dump(),
    )


@app.get("/")
async def root():
    """Root endpoint to check if API is running."""
    return {"message": "ArXiv Scraper API is running"} 