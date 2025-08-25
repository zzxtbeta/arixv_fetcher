import React, { useState, useEffect } from 'react';
import { listSessions, getSessionDetails, resumeSession, deleteSession } from '../api';
import './SessionManager.css';

interface Session {
  session_id: string;
  status: string;
  total_papers: number;
  completed_papers: number;
  failed_papers: number;
  pending_papers: number;
  total_inserted: number;
  total_skipped: number;
  created_at: string;
  updated_at: string | null;
  error_message: string | null;
}

interface SessionDetails {
  session_id: string;
  status: string;
  total_papers: number;
  total_inserted: number;
  total_skipped: number;
  created_at: string;
  updated_at: string | null;
  error_message: string | null;
  papers: Record<string, {
    status: string;
    error_message: string | null;
    processing_time: number | null;
    created_at: string;
    updated_at: string | null;
  }>;
}

const SessionManager: React.FC = () => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<SessionDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [resumeLoading, setResumeLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);

  // 获取会话列表
  const fetchSessions = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listSessions();
      if (response.status === 'success') {
        setSessions(response.sessions);
      } else {
        setError('获取会话列表失败');
      }
    } catch (err: any) {
      setError(`获取会话列表失败: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 获取会话详情
  const fetchSessionDetails = async (sessionId: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await getSessionDetails(sessionId);
      if (response.status === 'success') {
        setSelectedSession(response.session);
        setShowDetails(true);
      } else {
        setError('获取会话详情失败');
      }
    } catch (err: any) {
      setError(`获取会话详情失败: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 恢复会话处理
  const resumeSessionHandler = async (sessionId: string) => {
    setResumeLoading(sessionId);
    setError(null);
    try {
      const response = await resumeSession(sessionId);
      
      if (response.status === 'success') {
        alert(`会话 ${sessionId} 恢复成功！\n处理完成: ${response.inserted} 篇\n跳过: ${response.skipped} 篇`);
        fetchSessions(); // 刷新会话列表
      } else if (response.status === 'already_completed') {
        alert(`会话 ${sessionId} 已经完成处理`);
      } else if (response.status === 'no_pending_papers') {
        alert(`会话 ${sessionId} 没有待处理的论文`);
      } else if (response.status === 'api_quota_exhausted') {
        alert(`API配额已用完，会话 ${sessionId} 已保存进度，稍后可继续恢复`);
      } else {
        setError(`恢复会话失败: ${response.message || '未知错误'}`);
      }
    } catch (err: any) {
      setError(`恢复会话失败: ${err.response?.data?.detail || err.message}`);
    } finally {
      setResumeLoading(null);
    }
  };

  // 删除会话
  const deleteSessionHandler = async (sessionId: string) => {
    if (!window.confirm(`确定要删除会话 ${sessionId} 吗？此操作不可撤销。`)) {
      return;
    }
    
    setLoading(true);
    setError(null);
    try {
      const response = await deleteSession(sessionId);
      if (response.status === 'success') {
        alert(`会话 ${sessionId} 删除成功`);
        fetchSessions(); // 刷新会话列表
        if (selectedSession?.session_id === sessionId) {
          setSelectedSession(null);
          setShowDetails(false);
        }
      } else {
        setError('删除会话失败');
      }
    } catch (err: any) {
      setError(`删除会话失败: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 格式化日期
  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('zh-CN');
  };

  // 获取状态颜色
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return '#28a745';
      case 'failed': return '#dc3545';
      case 'pending': return '#ffc107';
      case 'processing': return '#007bff';
      default: return '#6c757d';
    }
  };

  // 获取状态文本
  const getStatusText = (status: string) => {
    switch (status) {
      case 'completed': return '已完成';
      case 'failed': return '失败';
      case 'pending': return '待处理';
      case 'processing': return '处理中';
      default: return status;
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  return (
    <div className="session-manager">
      <div className="session-header">
        <h2>会话管理 - 断点续传</h2>
        <button 
          onClick={fetchSessions} 
          disabled={loading}
          className="refresh-btn"
        >
          {loading ? '刷新中...' : '刷新列表'}
        </button>
      </div>

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      <div className="session-content">
        <div className="session-list">
          <h3>会话列表</h3>
          {sessions.length === 0 ? (
            <p>暂无会话记录</p>
          ) : (
            <div className="sessions">
              {sessions.map((session) => (
                <div key={session.session_id} className="session-item">
                  <div className="session-info">
                    <div className="session-id">
                      <strong>会话ID:</strong> {session.session_id}
                    </div>
                    <div className="session-status">
                      <span 
                        className="status-badge"
                        style={{ backgroundColor: getStatusColor(session.status) }}
                      >
                        {getStatusText(session.status)}
                      </span>
                    </div>
                    <div className="session-stats">
                      <span>总计: {session.total_papers}</span>
                      <span>已完成: {session.completed_papers}</span>
                      <span>失败: {session.failed_papers}</span>
                      <span>待处理: {session.pending_papers}</span>
                    </div>
                    <div className="session-time">
                      创建时间: {formatDate(session.created_at)}
                    </div>
                    {session.error_message && (
                      <div className="session-error">
                        错误: {session.error_message}
                      </div>
                    )}
                  </div>
                  <div className="session-actions">
                    <button 
                      onClick={() => fetchSessionDetails(session.session_id)}
                      disabled={loading}
                      className="details-btn"
                    >
                      查看详情
                    </button>
                    {(session.status === 'failed' || session.pending_papers > 0) && (
                      <button 
                        onClick={() => resumeSessionHandler(session.session_id)}
                        disabled={resumeLoading === session.session_id}
                        className="resume-btn"
                      >
                        {resumeLoading === session.session_id ? '恢复中...' : '恢复处理'}
                      </button>
                    )}
                    <button 
                      onClick={() => deleteSessionHandler(session.session_id)}
                      disabled={loading}
                      className="delete-btn"
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {showDetails && selectedSession && (
          <div className="session-details">
            <div className="details-header">
              <h3>会话详情</h3>
              <button 
                onClick={() => setShowDetails(false)}
                className="close-btn"
              >
                关闭
              </button>
            </div>
            <div className="details-content">
              <div className="details-summary">
                <p><strong>会话ID:</strong> {selectedSession.session_id}</p>
                <p><strong>状态:</strong> 
                  <span 
                    className="status-badge"
                    style={{ backgroundColor: getStatusColor(selectedSession.status) }}
                  >
                    {getStatusText(selectedSession.status)}
                  </span>
                </p>
                <p><strong>总论文数:</strong> {selectedSession.total_papers}</p>
                <p><strong>已插入:</strong> {selectedSession.total_inserted}</p>
                <p><strong>已跳过:</strong> {selectedSession.total_skipped}</p>
                <p><strong>创建时间:</strong> {formatDate(selectedSession.created_at)}</p>
                {selectedSession.updated_at && (
                  <p><strong>更新时间:</strong> {formatDate(selectedSession.updated_at)}</p>
                )}
                {selectedSession.error_message && (
                  <p><strong>错误信息:</strong> <span className="error-text">{selectedSession.error_message}</span></p>
                )}
              </div>
              <div className="papers-list">
                <h4>论文处理详情</h4>
                <div className="papers-grid">
                  {Object.entries(selectedSession.papers).map(([paperId, paper]) => (
                    <div key={paperId} className="paper-item">
                      <div className="paper-id">{paperId}</div>
                      <div className="paper-status">
                        <span 
                          className="status-badge small"
                          style={{ backgroundColor: getStatusColor(paper.status) }}
                        >
                          {getStatusText(paper.status)}
                        </span>
                      </div>
                      {paper.error_message && (
                        <div className="paper-error">{paper.error_message}</div>
                      )}
                      <div className="paper-time">
                        {formatDate(paper.created_at)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default SessionManager;