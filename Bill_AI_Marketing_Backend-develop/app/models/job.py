from app.extensions import db
from datetime import datetime
import uuid
import json

class Job(db.Model):
    __tablename__ = 'jobs'
    
    """
    Job Model - Tracks async scraping jobs (Celery tasks).
    
    Supports both legacy structure (task_name, result, error) and new structure
    (job_type, progress tracking, etc.) for backward compatibility.
    
    Attributes:
        job_id (str): Unique identifier (UUID) - matches Celery task.id
        tenant_id (str): Which tenant owns this job
        job_type (str): Type of job ('profile_scrape', 'company_scrape', etc.) - nullable for legacy
        task_name (str): Legacy field for task name - nullable for new jobs
        status (str): Job status ('pending', 'processing', 'completed', 'failed')
        total_items (int): Total number of items to process (new structure)
        completed_items (int): Number of items completed (new structure)
        success_count (int): Number of successful items (new structure)
        failed_count (int): Number of failed items (new structure)
        result_data (json): Additional result data (new structure)
        result (json): Legacy result field - nullable for new jobs
        error_message (str): Error message if job failed (new structure)
        error (text): Legacy error field - nullable for new jobs
        created_at (datetime): When job was created
        updated_at (datetime): When job was last updated
        completed_at (datetime): When job completed (new structure)
    """
    
    job_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    
    # Legacy fields (for backward compatibility)
    task_name = db.Column(db.String(255), nullable=True)
    result = db.Column(db.JSON, nullable=True)
    error = db.Column(db.Text, nullable=True)
    
    # New fields (for profile scraping and enhanced tracking)
    job_type = db.Column(db.String(50), nullable=True)  # 'profile_scrape', 'company_scrape', etc.
    status = db.Column(db.String(50), nullable=False, default='pending')  # 'pending', 'processing', 'completed', 'failed'
    total_items = db.Column(db.Integer, default=0)
    completed_items = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    result_data = db.Column(db.Text, nullable=True)  # JSON string for additional data
    error_message = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert job to dictionary for API response."""
        # Check if this is a new-style job (has job_type) or legacy job
        if self.job_type:
            # New structure with progress tracking
            result_data = None
            if self.result_data:
                try:
                    result_data = json.loads(self.result_data)
                except (json.JSONDecodeError, TypeError):
                    result_data = {}
            
            return {
                "job_id": self.job_id,
                "tenant_id": self.tenant_id,
                "job_type": self.job_type,
                "status": self.status,
                "total_items": self.total_items,
                "completed_items": self.completed_items,
                "success_count": self.success_count,
                "failed_count": self.failed_count,
                "result_data": result_data,
                "error_message": self.error_message,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "progress": {
                    "completed": self.completed_items,
                    "total": self.total_items,
                    "percentage": round((self.completed_items / self.total_items * 100) if self.total_items > 0 else 0, 2)
                },
                "results": {
                    "success": self.success_count,
                    "failed": self.failed_count
                }
            }
        else:
            # Legacy structure
            return {
                "job_id": self.job_id,
                "task_name": self.task_name,
                "status": self.status,
                "result": self.result,
                "error": self.error,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }
