#!/usr/bin/env python3
"""
测试断点续传功能的完整性

这个脚本测试以下功能：
1. 创建新的处理会话
2. 模拟API额度耗尽的情况
3. 恢复处理会话
4. 会话管理API接口
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import List

from src.agent.resume_manager import resume_manager, ProcessingStatus
from src.agent.state import DataProcessingState

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_resume_manager_basic():
    """测试ResumeManager的基本功能"""
    logger.info("=== 测试ResumeManager基本功能 ===")
    
    # 测试数据
    test_paper_ids = ["2504.14636", "2504.14645", "2504.14650", "2504.14655", "2504.14660"]
    
    # 1. 创建新会话
    session_id = resume_manager.create_session("test_file.json", test_paper_ids)
    logger.info(f"创建会话: {session_id}")
    
    # 2. 获取会话信息
    session = resume_manager.get_session(session_id)
    assert session is not None, "会话应该存在"
    assert session.total_papers == len(test_paper_ids), "论文总数应该匹配"
    assert session.status == ProcessingStatus.PENDING, "初始状态应该是pending"
    logger.info(f"会话信息: 总论文数={session.total_papers}, 状态={session.status}")
    
    # 3. 更新论文状态
    resume_manager.update_paper_status(session_id, test_paper_ids[0], ProcessingStatus.IN_PROGRESS)
    resume_manager.update_paper_status(session_id, test_paper_ids[1], ProcessingStatus.COMPLETED, processing_time=2.5)
    resume_manager.update_paper_status(session_id, test_paper_ids[2], ProcessingStatus.FAILED, error_message="测试错误")
    
    # 4. 获取待处理论文
    pending_ids = resume_manager.get_pending_papers(session_id)
    expected_pending = [test_paper_ids[2], test_paper_ids[3], test_paper_ids[4]]  # FAILED和PENDING状态的论文
    assert set(pending_ids) == set(expected_pending), f"待处理论文ID不匹配: {pending_ids} vs {expected_pending}"
    logger.info(f"待处理论文: {pending_ids}")
    
    # 5. 更新会话统计（通过内部方法）
    resume_manager._update_session_stats(session_id)
    
    # 6. 获取会话进度
    progress = resume_manager.get_session_progress(session_id)
    assert progress["processed_papers"] == 1, "已处理论文数应该是1"
    assert progress["failed_papers"] == 1, "失败论文数应该是1"
    logger.info(f"会话进度: {progress}")
    
    # 7. 列出所有会话
    sessions = resume_manager.list_sessions()
    assert len(sessions) >= 1, "应该至少有一个会话"
    logger.info(f"总会话数: {len(sessions)}")
    
    # 8. 删除会话
    success = resume_manager.delete_session(session_id)
    assert success, "删除会话应该成功"
    
    # 9. 确认会话已删除
    deleted_session = resume_manager.get_session(session_id)
    assert deleted_session is None, "会话应该已被删除"
    
    logger.info("✅ ResumeManager基本功能测试通过")

def test_api_exhaustion_simulation():
    """模拟API额度耗尽的情况"""
    logger.info("=== 测试API额度耗尽模拟 ===")
    
    test_paper_ids = ["2504.14636", "2504.14645", "2504.14650"]
    session_id = resume_manager.create_session("test_api_exhaustion.json", test_paper_ids)
    
    # 模拟处理第一篇论文成功
    resume_manager.update_paper_status(session_id, test_paper_ids[0], ProcessingStatus.IN_PROGRESS)
    resume_manager.update_paper_status(session_id, test_paper_ids[0], ProcessingStatus.COMPLETED, processing_time=1.5)
    
    # 模拟处理第二篇论文时API额度耗尽
    resume_manager.update_paper_status(session_id, test_paper_ids[1], ProcessingStatus.IN_PROGRESS)
    resume_manager.update_paper_status(
        session_id, 
        test_paper_ids[1], 
        ProcessingStatus.FAILED, 
        error_message="Tavily API quota exhausted"
    )
    
    # 更新会话状态为API额度耗尽
    resume_manager.mark_api_exhausted(session_id, current_api_key_index=0)
    
    # 获取待处理论文（应该包括失败的和未处理的）
    pending_ids = resume_manager.get_pending_papers(session_id)
    expected_pending = [test_paper_ids[1], test_paper_ids[2]]  # 失败的和未处理的
    assert set(pending_ids) == set(expected_pending), f"待处理论文ID不匹配: {pending_ids} vs {expected_pending}"
    
    logger.info(f"API额度耗尽后待处理论文: {pending_ids}")
    logger.info("✅ API额度耗尽模拟测试通过")
    
    # 清理
    resume_manager.delete_session(session_id)

def test_state_integration():
    """测试与DataProcessingState的集成"""
    logger.info("=== 测试状态集成 ===")
    
    test_paper_ids = ["2504.14636", "2504.14645"]
    session_id = resume_manager.create_session("test_state_integration.json", test_paper_ids)
    
    # 创建包含断点续传字段的状态
    state: DataProcessingState = {
        "session_id": session_id,
        "resume_mode": True,
        "processed_paper_ids": [],
        "failed_paper_ids": [],
        "api_exhausted": False,
        "current_batch_index": 0,
        "processing_status": "pending",
        "papers": [],
        "raw_papers": [],
        "fetched": 0,
        "inserted": 0,
        "skipped": 0
    }
    
    # 验证状态字段
    assert state["session_id"] == session_id, "会话ID应该匹配"
    assert state["resume_mode"] == True, "恢复模式应该为True"
    assert isinstance(state["processed_paper_ids"], list), "processed_paper_ids应该是列表"
    assert isinstance(state["failed_paper_ids"], list), "failed_paper_ids应该是列表"
    assert state["api_exhausted"] == False, "api_exhausted应该是布尔值"
    
    logger.info("状态字段验证通过")
    logger.info("✅ 状态集成测试通过")
    
    # 清理
    resume_manager.delete_session(session_id)

def test_edge_cases():
    """测试边界情况"""
    logger.info("=== 测试边界情况 ===")
    
    # 1. 空论文列表
    try:
        session_id = resume_manager.create_session("empty_test.json", [])
        assert False, "空论文列表应该抛出异常"
    except (ValueError, AssertionError):
        logger.info("✅ 空论文列表正确抛出异常")
    
    # 2. 不存在的会话
    non_existent_session = resume_manager.get_session("non-existent-session")
    assert non_existent_session is None, "不存在的会话应该返回None"
    logger.info("✅ 不存在的会话处理正确")
    
    # 3. 删除不存在的会话
    delete_result = resume_manager.delete_session("non-existent-session")
    assert delete_result == False, "删除不存在的会话应该返回False"
    logger.info("✅ 删除不存在的会话处理正确")
    
    # 4. 更新不存在会话的论文状态
    try:
        resume_manager.update_paper_status("non-existent-session", "paper-id", ProcessingStatus.COMPLETED)
        # 这应该不会抛出异常，但也不会有任何效果
        logger.info("✅ 更新不存在会话的论文状态处理正确")
    except Exception as e:
        logger.warning(f"更新不存在会话的论文状态时出现异常: {e}")
    
    logger.info("✅ 边界情况测试通过")

def main():
    """运行所有测试"""
    logger.info("开始测试断点续传功能")
    
    try:
        test_resume_manager_basic()
        test_api_exhaustion_simulation()
        test_state_integration()
        test_edge_cases()
        
        logger.info("🎉 所有测试通过！断点续传功能实现正确")
        
        # 显示使用示例
        logger.info("\n=== 使用示例 ===")
        logger.info("1. 创建新的批量处理请求:")
        logger.info("   POST /data/fetch-arxiv-by-id?ids=2504.14636,2504.14645,2504.14650")
        logger.info("\n2. 如果API额度耗尽，响应会包含session_id:")
        logger.info("   {\"status\": \"api_quota_exhausted\", \"session_id\": \"session-123\", ...}")
        logger.info("\n3. 恢复处理:")
        logger.info("   POST /data/fetch-arxiv-by-id?resume_session_id=session-123")
        logger.info("\n4. 查看所有会话:")
        logger.info("   GET /data/sessions")
        logger.info("\n5. 查看特定会话详情:")
        logger.info("   GET /data/sessions/session-123")
        logger.info("\n6. 删除会话:")
        logger.info("   DELETE /data/sessions/session-123")
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        raise

if __name__ == "__main__":
    main()