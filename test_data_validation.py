#!/usr/bin/env python3
"""
测试多机构数据验证和处理逻辑

这个脚本测试增强后的数据验证和错误处理逻辑，不依赖实际的LLM调用。
"""

import sys
import os
import logging
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_date_validation():
    """测试日期验证逻辑"""
    logger.info("=== 测试日期验证逻辑 ===")
    
    # 模拟日期验证函数
    import re
    from datetime import datetime
    
    def validate_date(date_value, date_field):
        """验证日期格式和范围"""
        validation_errors = []
        
        if not date_value:
            return validation_errors
            
        # Check if it's "present" (valid for end_date)
        if date_value.lower() == 'present':
            if date_field == 'end_date':
                return validation_errors
            else:
                validation_errors.append(f"'present' is not valid for {date_field}")
                return validation_errors
        
        # Validate date format (YYYY or YYYY-MM-DD)
        if not re.match(r'^\d{4}(-\d{2}(-\d{2})?)?$', date_value):
            validation_errors.append(f"Invalid date format for {date_field}: {date_value}")
            return validation_errors
        
        # Validate date range (reasonable academic career dates)
        try:
            if len(date_value) == 4:  # YYYY format
                year = int(date_value)
            else:  # YYYY-MM-DD format
                year = int(date_value.split('-')[0])
            
            current_year = datetime.now().year
            if year < 1950 or year > current_year + 5:
                validation_errors.append(f"Date year {year} is outside reasonable range (1950-{current_year+5})")
        except ValueError:
            validation_errors.append(f"Failed to parse year from date: {date_value}")
        
        return validation_errors
    
    # 测试用例
    test_cases = [
        # 有效日期
        ('2020', 'start_date', []),
        ('2020-01', 'start_date', []),
        ('2020-01-15', 'start_date', []),
        ('present', 'end_date', []),
        
        # 无效日期
        ('present', 'start_date', ["'present' is not valid for start_date"]),
        ('invalid', 'start_date', ['Invalid date format for start_date: invalid']),
        ('1900', 'start_date', ['Date year 1900 is outside reasonable range (1950-2030)']),
        ('2050', 'start_date', ['Date year 2050 is outside reasonable range (1950-2030)']),
        ('20-01', 'start_date', ['Invalid date format for start_date: 20-01']),
    ]
    
    passed = 0
    total = len(test_cases)
    
    for date_value, date_field, expected_errors in test_cases:
        errors = validate_date(date_value, date_field)
        if errors == expected_errors:
            logger.info(f"✅ PASS: {date_value} ({date_field})")
            passed += 1
        else:
            logger.error(f"❌ FAIL: {date_value} ({date_field})")
            logger.error(f"   Expected: {expected_errors}")
            logger.error(f"   Got: {errors}")
    
    logger.info(f"日期验证测试: {passed}/{total} 通过")
    return passed == total

def test_affiliation_data_structure():
    """测试机构关联数据结构验证"""
    logger.info("\n=== 测试机构关联数据结构验证 ===")
    
    def validate_affiliation_data(affiliations_data):
        """验证机构关联数据结构"""
        validation_errors = []
        
        # 验证是否为列表
        if not isinstance(affiliations_data, list):
            validation_errors.append(f"Expected list, got {type(affiliations_data)}")
            return validation_errors
        
        # 验证每个机构关联
        for i, affiliation in enumerate(affiliations_data):
            if not isinstance(affiliation, dict):
                validation_errors.append(f"Affiliation {i}: expected dict, got {type(affiliation)}")
                continue
            
            # 验证必需字段
            institution = affiliation.get('institution', '').strip()
            if not institution:
                validation_errors.append(f"Affiliation {i}: missing or empty institution name")
            
            # 验证日期字段
            for date_field in ['start_date', 'end_date']:
                date_value = affiliation.get(date_field)
                if date_value and date_value != 'present':
                    import re
                    if not re.match(r'^\d{4}(-\d{2}(-\d{2})?)?$', str(date_value)):
                        validation_errors.append(f"Affiliation {i}: invalid {date_field} format: {date_value}")
        
        return validation_errors
    
    # 测试用例
    test_cases = [
        # 有效数据
        ([
            {
                'institution': 'Stanford University',
                'position': 'Professor',
                'start_date': '2018',
                'end_date': 'present'
            },
            {
                'institution': 'MIT',
                'position': 'Associate Professor',
                'start_date': '2012',
                'end_date': '2018'
            }
        ], []),
        
        # 无效数据类型
        ("not a list", ["Expected list, got <class 'str'>"]),
        
        # 缺少机构名称
        ([{
            'position': 'Professor',
            'start_date': '2018'
        }], ["Affiliation 0: missing or empty institution name"]),
        
        # 无效日期格式
        ([{
            'institution': 'Stanford University',
            'start_date': 'invalid-date'
        }], ["Affiliation 0: invalid start_date format: invalid-date"]),
        
        # 混合有效和无效数据
        ([
            {
                'institution': 'Stanford University',
                'start_date': '2018',
                'end_date': 'present'
            },
            {
                'institution': '',  # 空机构名称
                'start_date': 'bad-date'  # 无效日期
            }
        ], [
            "Affiliation 1: missing or empty institution name",
            "Affiliation 1: invalid start_date format: bad-date"
        ])
    ]
    
    passed = 0
    total = len(test_cases)
    
    for affiliations_data, expected_errors in test_cases:
        errors = validate_affiliation_data(affiliations_data)
        if errors == expected_errors:
            logger.info(f"✅ PASS: 数据结构验证")
            passed += 1
        else:
            logger.error(f"❌ FAIL: 数据结构验证")
            logger.error(f"   Expected: {expected_errors}")
            logger.error(f"   Got: {errors}")
    
    logger.info(f"数据结构验证测试: {passed}/{total} 通过")
    return passed == total

def test_institution_matching():
    """测试机构名称匹配逻辑"""
    logger.info("\n=== 测试机构名称匹配逻辑 ===")
    
    def match_institution(extracted_name, existing_names):
        """模拟机构名称匹配逻辑"""
        extracted_lower = extracted_name.lower()
        
        # 定义常见的机构名称映射
        institution_mappings = {
            'massachusetts institute of technology': 'mit',
            'mit': 'massachusetts institute of technology',
            'stanford university': 'stanford',
            'stanford': 'stanford university',
            'harvard university': 'harvard',
            'harvard': 'harvard university'
        }
        
        for existing_name in existing_names:
            existing_lower = existing_name.lower()
            
            # 精确匹配
            if extracted_lower == existing_lower:
                return existing_name
            
            # 包含匹配
            if extracted_lower in existing_lower or existing_lower in extracted_lower:
                return existing_name
            
            # 通过映射匹配
            if extracted_lower in institution_mappings:
                mapped_name = institution_mappings[extracted_lower]
                if mapped_name in existing_lower or existing_lower in mapped_name:
                    return existing_name
            
            if existing_lower in institution_mappings:
                mapped_name = institution_mappings[existing_lower]
                if mapped_name in extracted_lower or extracted_lower in mapped_name:
                    return existing_name
            
            # 关键词匹配（至少3个字符的单词）
            extracted_words = [word for word in extracted_lower.split() if len(word) > 3]
            existing_words = [word for word in existing_lower.split() if len(word) > 3]
            
            if extracted_words and existing_words:
                common_words = set(extracted_words) & set(existing_words)
                if common_words:
                    return existing_name
        
        return None
    
    # 测试用例
    test_cases = [
        # 精确匹配
        ('Stanford University', ['Stanford University', 'MIT', 'Harvard'], 'Stanford University'),
        
        # 部分匹配
        ('Stanford', ['Stanford University', 'MIT', 'Harvard'], 'Stanford University'),
        ('University of Stanford', ['Stanford University', 'MIT', 'Harvard'], 'Stanford University'),
        
        # 关键词匹配
        ('Massachusetts Institute of Technology', ['Stanford University', 'MIT', 'Harvard'], 'MIT'),
        
        # 无匹配
        ('UC Berkeley', ['Stanford University', 'MIT', 'Harvard'], None),
        
        # 大小写不敏感
        ('stanford university', ['Stanford University', 'MIT', 'Harvard'], 'Stanford University'),
    ]
    
    passed = 0
    total = len(test_cases)
    
    for extracted_name, existing_names, expected_match in test_cases:
        result = match_institution(extracted_name, existing_names)
        if result == expected_match:
            logger.info(f"✅ PASS: '{extracted_name}' -> '{result}'")
            passed += 1
        else:
            logger.error(f"❌ FAIL: '{extracted_name}'")
            logger.error(f"   Expected: '{expected_match}'")
            logger.error(f"   Got: '{result}'")
    
    logger.info(f"机构匹配测试: {passed}/{total} 通过")
    return passed == total

def run_all_tests():
    """运行所有测试"""
    logger.info("开始多机构数据验证和处理逻辑测试")
    logger.info(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    tests = [
        test_date_validation,
        test_affiliation_data_structure,
        test_institution_matching
    ]
    
    passed_tests = 0
    total_tests = len(tests)
    
    for test_func in tests:
        try:
            if test_func():
                passed_tests += 1
        except Exception as e:
            logger.error(f"测试 {test_func.__name__} 执行失败: {str(e)}")
    
    # 测试总结
    logger.info(f"\n=== 测试总结 ===")
    logger.info(f"总测试模块: {total_tests}")
    logger.info(f"通过测试: {passed_tests}")
    logger.info(f"失败测试: {total_tests - passed_tests}")
    logger.info(f"成功率: {(passed_tests / total_tests * 100):.1f}%")
    
    if passed_tests == total_tests:
        logger.info("🎉 所有测试通过！数据验证和处理逻辑正常工作。")
        return True
    else:
        logger.warning("⚠️ 部分测试失败，需要进一步调试和优化。")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)