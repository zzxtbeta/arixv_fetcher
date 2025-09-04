"""Request and response models for the API."""

from typing import Optional
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Error response model."""

    code: int = Field(400, description="Error code")
    message: str = Field("Error", description="Error message")
    detail: Optional[str] = Field(None, description="Error details")


class SupplementRolesRequest(BaseModel):
    """Request model for supplement roles API."""
    
    batch_size: Optional[int] = Field(50, description="Number of records to process in each batch")
    max_records: Optional[int] = Field(5000, description="Maximum number of records to process")
    start_id: Optional[int] = Field(None, description="Start ID for processing range (inclusive)")
    end_id: Optional[int] = Field(None, description="End ID for processing range (inclusive)")


class DataEnrichmentRequest(BaseModel):
    """Request model for data enrichment API."""
    
    batch_size: Optional[int] = Field(50, description="Number of records to process in each batch")
    max_records: Optional[int] = Field(5000, description="Maximum number of records to process")
    start_id: Optional[int] = Field(None, description="Start ID for processing range (inclusive)")
    end_id: Optional[int] = Field(None, description="End ID for processing range (inclusive)")


class ProcessRoleRequest(BaseModel):
    """Request model for process role API."""
    
    batch_size: Optional[int] = Field(50, description="Number of records to process in each batch")
    max_records: Optional[int] = Field(5000, description="Maximum number of records to process")
    start_id: Optional[int] = Field(None, description="Start ID for processing range (inclusive)")
    end_id: Optional[int] = Field(None, description="End ID for processing range (inclusive)")


class EmailSupplementRequest(BaseModel):
    """Request model for email supplement API."""
    
    batch_size: Optional[int] = Field(10, description="Number of records to process in each batch")
    start_id: Optional[int] = Field(None, description="Start ID for processing range (inclusive)")
    end_id: Optional[int] = Field(None, description="End ID for processing range (inclusive)")
