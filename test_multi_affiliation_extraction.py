#!/usr/bin/env python3
"""
测试多机构时间段提取功能

这个脚本用于测试增强后的LLM提取能力，验证其是否能够正确识别和区分不同机构的时间段信息。
"""

import asyncio
import sys
import os
import logging
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.agent.utils import extract_email_and_dates_with_llm

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 测试用的网页内容样本
TEST_WEBPAGE_CONTENT = """
<html>
<head><title>Dr. John Smith - Academic Profile</title></head>
<body>
    <h1>Dr. John Smith</h1>
    <p>Email: john.smith@university.edu</p>
    
    <h2>Academic Positions</h2>
    <ul>
        <li><strong>Professor</strong> - Stanford University (2018-present)</li>
        <li><strong>Associate Professor</strong> - MIT (2012-2018)</li>
        <li><strong>Assistant Professor</strong> - Harvard University (2008-2012)</li>
        <li><strong>Postdoc</strong> - UC Berkeley (2006-2008)</li>
    </ul>
    
    <h2>Education</h2>
    <p>PhD in Computer Science, Carnegie Mellon University (2006)</p>
    
    <h2>Research Interests</h2>
    <p>Machine Learning, Natural Language Processing, Computer Vision</p>
    
    <h2>Contact Information</h2>
    <p>Office: Gates Building, Room 123</p>
    <p>Phone: +1-650-123-4567</p>
</body>
</html>
"""

TEST_WEBPAGE_CONTENT_2 = """
<html>
<head><title>Prof. Maria Garcia - Faculty Page</title></head>
<body>
    <h1>Professor Maria Garcia</h1>
    <p>Contact: m.garcia@tech.edu</p>
    
    <div class="career-history">
        <h3>Career Timeline</h3>
        <div class="position">
            <h4>Full Professor</h4>
            <p>California Institute of Technology</p>
            <p>2020 - Current</p>
        </div>
        <div class="position">
            <h4>Associate Professor</h4>
            <p>University of California, Los Angeles</p>
            <p>2015 - 2020</p>
        </div>
        <div class="position">
            <h4>Assistant Professor</h4>
            <p>University of Southern California</p>
            <p>2010 - 2015</p>
        </div>
    </div>
    
    <p>Research focus: Artificial Intelligence, Robotics, and Human-Computer Interaction</p>
</body>
</html>
"""

async def test_single_extraction(content: str, author_name: str, test_name: str):
    """测试单个网页内容的提取"""
    logger.info(f"\n=== {test_name} ===")
    logger.info(f"测试作者: {author_name}")
    
    try:
        result = await extract_email_and_dates_with_llm(content, author_name)
        
        if result:
            logger.info("提取结果:")
            logger.info(f"  邮箱: {result.get('email', 'N/A')}")
            logger.info(f"  置信度: {result.get('confidence', 'N/A')}")
            
            affiliations = result.get('affiliations', [])
            if affiliations:
                logger.info(f"  机构关联数量: {len(affiliations)}")
                for i, aff in enumerate(affiliations, 1):
                    logger.info(f"    机构 {i}:")
                    logger.info(f"      名称: {aff.get('institution', 'N/A')}")
                    logger.info(f"      职位: {aff.get('position', 'N/A')}")
                    logger.info(f"      开始时间: {aff.get('start_date', 'N/A')}")
                    logger.info(f"      结束时间: {aff.get('end_date', 'N/A')}")
            else:
                logger.warning("  未提取到机构关联信息")
        else:
            logger.warning("提取失败或无结果")
            
        return result
        
    except Exception as e:
        logger.error(f"提取过程中发生错误: {str(e)}")
        return None

async def validate_extraction_results(result: dict, expected_affiliations_count: int):
    """验证提取结果的准确性"""
    validation_errors = []
    
    if not result:
        validation_errors.append("提取结果为空")
        return validation_errors
    
    # 验证邮箱
    email = result.get('email')
    if not email or '@' not in email:
        validation_errors.append(f"邮箱格式无效: {email}")
    
    # 验证置信度
    confidence = result.get('confidence')
    if confidence not in ['high', 'medium', 'low']:
        validation_errors.append(f"置信度值无效: {confidence}")
    
    # 验证机构关联
    affiliations = result.get('affiliations', [])
    if len(affiliations) != expected_affiliations_count:
        validation_errors.append(f"机构关联数量不符合预期: 期望 {expected_affiliations_count}, 实际 {len(affiliations)}")
    
    # 验证每个机构关联的数据完整性
    for i, aff in enumerate(affiliations):
        if not aff.get('institution'):
            validation_errors.append(f"机构 {i+1}: 缺少机构名称")
        
        start_date = aff.get('start_date')
        end_date = aff.get('end_date')
        
        # 验证日期格式
        import re
        for date_field, date_value in [('start_date', start_date), ('end_date', end_date)]:
            if date_value and date_value != 'present':
                if not re.match(r'^\d{4}(-\d{2}(-\d{2})?)?$', str(date_value)):
                    validation_errors.append(f"机构 {i+1}: {date_field} 格式无效: {date_value}")
    
    return validation_errors

async def run_comprehensive_test():
    """运行综合测试"""
    logger.info("开始多机构时间段提取功能测试")
    logger.info(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    test_cases = [
        {
            'content': TEST_WEBPAGE_CONTENT,
            'author_name': 'John Smith',
            'test_name': '测试案例1: 标准学术履历页面',
            'expected_affiliations': 4  # Stanford, MIT, Harvard, UC Berkeley
        },
        {
            'content': TEST_WEBPAGE_CONTENT_2,
            'author_name': 'Maria Garcia',
            'test_name': '测试案例2: 结构化职业时间线',
            'expected_affiliations': 3  # Caltech, UCLA, USC
        }
    ]
    
    total_tests = len(test_cases)
    passed_tests = 0
    
    for test_case in test_cases:
        result = await test_single_extraction(
            test_case['content'],
            test_case['author_name'],
            test_case['test_name']
        )
        
        # 验证结果
        validation_errors = await validate_extraction_results(
            result,
            test_case['expected_affiliations']
        )
        
        if validation_errors:
            logger.error(f"验证失败: {'; '.join(validation_errors)}")
        else:
            logger.info("✅ 测试通过")
            passed_tests += 1
        
        logger.info("-" * 50)
    
    # 测试总结
    logger.info(f"\n=== 测试总结 ===")
    logger.info(f"总测试数: {total_tests}")
    logger.info(f"通过测试: {passed_tests}")
    logger.info(f"失败测试: {total_tests - passed_tests}")
    logger.info(f"成功率: {(passed_tests / total_tests * 100):.1f}%")
    
    if passed_tests == total_tests:
        logger.info("🎉 所有测试通过！多机构时间段提取功能正常工作。")
    else:
        logger.warning("⚠️ 部分测试失败，需要进一步调试和优化。")

if __name__ == "__main__":
    asyncio.run(run_comprehensive_test())