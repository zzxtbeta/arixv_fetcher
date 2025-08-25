"""断点续传管理器

提供JSON文件批量处理的断点续传功能，当所有Tavily API key额度耗尽时
能够保存进度并支持后续恢复处理。
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

class ProcessingStatus(Enum):
    """处理状态枚举"""
    PENDING = "pending"          # 等待处理
    IN_PROGRESS = "in_progress"  # 正在处理
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 处理失败
    API_EXHAUSTED = "api_exhausted"  # API额度耗尽
    PAUSED = "paused"            # 暂停

@dataclass
class PaperProcessingRecord:
    """单篇论文处理记录"""
    paper_id: str
    status: ProcessingStatus
    attempts: int = 0
    last_attempt_time: Optional[str] = None
    error_message: Optional[str] = None
    processing_time: Optional[float] = None  # 处理耗时（秒）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "status": self.status.value,
            "attempts": self.attempts,
            "last_attempt_time": self.last_attempt_time,
            "error_message": self.error_message,
            "processing_time": self.processing_time
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PaperProcessingRecord':
        return cls(
            paper_id=data["paper_id"],
            status=ProcessingStatus(data["status"]),
            attempts=data.get("attempts", 0),
            last_attempt_time=data.get("last_attempt_time"),
            error_message=data.get("error_message"),
            processing_time=data.get("processing_time")
        )

@dataclass
class BatchProcessingSession:
    """批量处理会话"""
    session_id: str
    source_file: str  # 原始JSON文件路径
    total_papers: int
    processed_papers: int = 0
    failed_papers: int = 0
    skipped_papers: int = 0
    start_time: Optional[str] = None
    last_update_time: Optional[str] = None
    status: ProcessingStatus = ProcessingStatus.PENDING
    api_exhausted_time: Optional[str] = None  # API额度耗尽时间
    current_api_key_index: int = 0  # 当前使用的API key索引
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "source_file": self.source_file,
            "total_papers": self.total_papers,
            "processed_papers": self.processed_papers,
            "failed_papers": self.failed_papers,
            "skipped_papers": self.skipped_papers,
            "start_time": self.start_time,
            "last_update_time": self.last_update_time,
            "status": self.status.value,
            "api_exhausted_time": self.api_exhausted_time,
            "current_api_key_index": self.current_api_key_index,
            "error_message": self.error_message
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BatchProcessingSession':
        return cls(
            session_id=data["session_id"],
            source_file=data["source_file"],
            total_papers=data["total_papers"],
            processed_papers=data.get("processed_papers", 0),
            failed_papers=data.get("failed_papers", 0),
            skipped_papers=data.get("skipped_papers", 0),
            start_time=data.get("start_time"),
            last_update_time=data.get("last_update_time"),
            status=ProcessingStatus(data.get("status", ProcessingStatus.PENDING.value)),
            api_exhausted_time=data.get("api_exhausted_time"),
            current_api_key_index=data.get("current_api_key_index", 0),
            error_message=data.get("error_message")
        )

class ResumeManager:
    """断点续传管理器"""
    
    def __init__(self, storage_dir: str = "./resume_data"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        
        # 会话存储文件
        self.sessions_file = self.storage_dir / "sessions.json"
        # 论文处理记录存储目录
        self.records_dir = self.storage_dir / "records"
        self.records_dir.mkdir(exist_ok=True)
        
        self._sessions: Dict[str, BatchProcessingSession] = {}
        self._load_sessions()
    
    def _load_sessions(self):
        """加载所有会话"""
        if self.sessions_file.exists():
            try:
                with open(self.sessions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for session_id, session_data in data.items():
                        self._sessions[session_id] = BatchProcessingSession.from_dict(session_data)
                logger.info(f"Loaded {len(self._sessions)} processing sessions")
            except Exception as e:
                logger.error(f"Failed to load sessions: {e}")
    
    def _save_sessions(self):
        """保存所有会话"""
        try:
            data = {sid: session.to_dict() for sid, session in self._sessions.items()}
            with open(self.sessions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")
    
    def _get_records_file(self, session_id: str) -> Path:
        """获取指定会话的记录文件路径"""
        return self.records_dir / f"{session_id}_records.json"
    
    def _load_records(self, session_id: str) -> Dict[str, PaperProcessingRecord]:
        """加载指定会话的论文处理记录"""
        records_file = self._get_records_file(session_id)
        if not records_file.exists():
            return {}
        
        try:
            with open(records_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {pid: PaperProcessingRecord.from_dict(record_data) 
                       for pid, record_data in data.items()}
        except Exception as e:
            logger.error(f"Failed to load records for session {session_id}: {e}")
            return {}
    
    def _save_records(self, session_id: str, records: Dict[str, PaperProcessingRecord]):
        """保存指定会话的论文处理记录"""
        records_file = self._get_records_file(session_id)
        try:
            data = {pid: record.to_dict() for pid, record in records.items()}
            with open(records_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save records for session {session_id}: {e}")
    
    def create_session(self, source_file: str, paper_ids: List[str]) -> str:
        """创建新的处理会话"""
        session_id = f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        session = BatchProcessingSession(
            session_id=session_id,
            source_file=source_file,
            total_papers=len(paper_ids),
            start_time=datetime.now(timezone.utc).isoformat(),
            last_update_time=datetime.now(timezone.utc).isoformat(),
            status=ProcessingStatus.PENDING
        )
        
        # 初始化论文处理记录
        records = {}
        for paper_id in paper_ids:
            records[paper_id] = PaperProcessingRecord(
                paper_id=paper_id,
                status=ProcessingStatus.PENDING
            )
        
        self._sessions[session_id] = session
        self._save_sessions()
        self._save_records(session_id, records)
        
        logger.info(f"Created processing session {session_id} with {len(paper_ids)} papers")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[BatchProcessingSession]:
        """获取会话信息"""
        return self._sessions.get(session_id)
    
    def list_sessions(self, status_filter: Optional[ProcessingStatus] = None) -> List[BatchProcessingSession]:
        """列出所有会话"""
        sessions = list(self._sessions.values())
        if status_filter:
            sessions = [s for s in sessions if s.status == status_filter]
        return sorted(sessions, key=lambda x: x.start_time or "", reverse=True)
    
    def get_pending_papers(self, session_id: str) -> List[str]:
        """获取待处理的论文ID列表"""
        records = self._load_records(session_id)
        return [pid for pid, record in records.items() 
                if record.status in [ProcessingStatus.PENDING, ProcessingStatus.FAILED]]
    
    def get_pending_paper_ids(self, session_id: str) -> Optional[List[str]]:
        """获取待处理的论文ID列表（API兼容方法）"""
        if session_id not in self._sessions:
            return None
        return self.get_pending_papers(session_id)
    
    def update_session_progress(self, session_id: str, inserted_count: int = 0, 
                              skipped_count: int = 0, error_message: Optional[str] = None,
                              processed_count: int = 0, failed_count: int = 0, 
                              status: Optional[str] = None):
        """更新会话进度（支持流式处理）"""
        if session_id not in self._sessions:
            logger.warning(f"Session {session_id} not found for progress update")
            return
        
        session = self._sessions[session_id]
        session.total_inserted = getattr(session, 'total_inserted', 0) + inserted_count
        session.total_skipped = getattr(session, 'total_skipped', 0) + skipped_count
        session.processed_papers = getattr(session, 'processed_papers', 0) + processed_count
        session.failed_papers = getattr(session, 'failed_papers', 0) + failed_count
        session.last_update_time = datetime.now(timezone.utc).isoformat()
        
        if error_message:
            session.error_message = error_message
            if not status:
                session.status = ProcessingStatus.FAILED
        
        # 更新会话状态
        if status:
            if status == "completed":
                session.status = ProcessingStatus.COMPLETED
            elif status == "failed":
                session.status = ProcessingStatus.FAILED
            elif status == "api_quota_exhausted":
                session.status = ProcessingStatus.API_EXHAUSTED
        
        self._save_sessions()
        logger.info(f"Updated session {session_id} progress: +{inserted_count} inserted, +{skipped_count} skipped, +{processed_count} processed, +{failed_count} failed")
    
    def get_processed_papers(self, session_id: str) -> List[str]:
        """获取已处理的论文ID列表"""
        records = self._load_records(session_id)
        return [pid for pid, record in records.items() 
                if record.status == ProcessingStatus.COMPLETED]
    
    def update_paper_status(self, session_id: str, paper_id: str, 
                          status: ProcessingStatus, error_message: Optional[str] = None,
                          processing_time: Optional[float] = None):
        """更新论文处理状态"""
        records = self._load_records(session_id)
        
        if paper_id not in records:
            records[paper_id] = PaperProcessingRecord(paper_id=paper_id, status=status)
        
        record = records[paper_id]
        record.status = status
        record.last_attempt_time = datetime.now(timezone.utc).isoformat()
        record.attempts += 1
        
        if error_message:
            record.error_message = error_message
        if processing_time:
            record.processing_time = processing_time
        
        self._save_records(session_id, records)
        
        # 更新会话统计
        self._update_session_stats(session_id)
    
    def _update_session_stats(self, session_id: str):
        """更新会话统计信息"""
        if session_id not in self._sessions:
            return
        
        session = self._sessions[session_id]
        records = self._load_records(session_id)
        
        session.processed_papers = sum(1 for r in records.values() 
                                     if r.status == ProcessingStatus.COMPLETED)
        session.failed_papers = sum(1 for r in records.values() 
                                  if r.status == ProcessingStatus.FAILED)
        session.skipped_papers = sum(1 for r in records.values() 
                                   if r.status in [ProcessingStatus.PAUSED])
        session.last_update_time = datetime.now(timezone.utc).isoformat()
        
        # 检查是否全部完成
        if session.processed_papers + session.failed_papers + session.skipped_papers >= session.total_papers:
            session.status = ProcessingStatus.COMPLETED
        
        self._save_sessions()
    
    def mark_api_exhausted(self, session_id: str, current_api_key_index: int):
        """标记API额度耗尽"""
        if session_id not in self._sessions:
            return
        
        session = self._sessions[session_id]
        session.status = ProcessingStatus.API_EXHAUSTED
        session.api_exhausted_time = datetime.now(timezone.utc).isoformat()
        session.current_api_key_index = current_api_key_index
        
        self._save_sessions()
        logger.warning(f"Session {session_id} marked as API exhausted at key index {current_api_key_index}")
    
    def resume_session(self, session_id: str) -> bool:
        """恢复会话处理"""
        if session_id not in self._sessions:
            logger.error(f"Session {session_id} not found")
            return False
        
        session = self._sessions[session_id]
        if session.status not in [ProcessingStatus.API_EXHAUSTED, ProcessingStatus.PAUSED, ProcessingStatus.FAILED]:
            logger.warning(f"Session {session_id} is not in a resumable state: {session.status}")
            return False
        
        session.status = ProcessingStatus.IN_PROGRESS
        session.last_update_time = datetime.now(timezone.utc).isoformat()
        self._save_sessions()
        
        logger.info(f"Resumed session {session_id}")
        return True
    
    def get_session_progress(self, session_id: str) -> Dict[str, Any]:
        """获取会话进度信息"""
        if session_id not in self._sessions:
            return {}
        
        session = self._sessions[session_id]
        records = self._load_records(session_id)
        
        progress = {
            "session_id": session_id,
            "status": session.status.value,
            "total_papers": session.total_papers,
            "processed_papers": session.processed_papers,
            "failed_papers": session.failed_papers,
            "skipped_papers": session.skipped_papers,
            "pending_papers": session.total_papers - session.processed_papers - session.failed_papers - session.skipped_papers,
            "progress_percentage": round((session.processed_papers / session.total_papers) * 100, 2) if session.total_papers > 0 else 0,
            "start_time": session.start_time,
            "last_update_time": session.last_update_time,
            "api_exhausted_time": session.api_exhausted_time,
            "current_api_key_index": session.current_api_key_index,
            "error_message": session.error_message
        }
        
        return progress
    
    def delete_session(self, session_id: str) -> bool:
        """删除指定的会话"""
        if session_id not in self._sessions:
            return False
        
        # 删除会话记录
        del self._sessions[session_id]
        
        # 删除论文处理记录文件
        records_file = self._get_records_file(session_id)
        if records_file.exists():
            records_file.unlink()
        
        # 保存更新后的会话列表
        self._save_sessions()
        
        logger.info(f"Deleted session {session_id}")
        return True
    
    def cleanup_completed_sessions(self, keep_days: int = 7):
        """清理已完成的旧会话"""
        cutoff_time = datetime.now(timezone.utc).timestamp() - (keep_days * 24 * 3600)
        
        to_remove = []
        for session_id, session in self._sessions.items():
            if session.status == ProcessingStatus.COMPLETED and session.last_update_time:
                try:
                    session_time = datetime.fromisoformat(session.last_update_time.replace('Z', '+00:00')).timestamp()
                    if session_time < cutoff_time:
                        to_remove.append(session_id)
                except Exception:
                    continue
        
        for session_id in to_remove:
            del self._sessions[session_id]
            records_file = self._get_records_file(session_id)
            if records_file.exists():
                records_file.unlink()
            logger.info(f"Cleaned up completed session {session_id}")
        
        if to_remove:
            self._save_sessions()
            logger.info(f"Cleaned up {len(to_remove)} completed sessions")

# 全局实例
resume_manager = ResumeManager()