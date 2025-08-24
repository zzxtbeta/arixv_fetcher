import asyncio
import logging
from src.agent.data_graph import build_data_processing_graph
from src.api.data_processing import _gen_thread_id

# 设置日志级别
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_fetch_by_id():
    """测试通过ArXiv ID获取论文的完整流程"""
    try:
        # 构建图
        graph = await build_data_processing_graph()
        
        # 配置参数 - 使用一个真实的ArXiv ID
        config = {
            'configurable': {
                'thread_id': _gen_thread_id('test-fetch-by-id'),
                'id_list': ['2508.14997']  # 使用用户提到的ArXiv ID
            }
        }
        
        logger.info(f"开始测试Fetch by ID流程，ArXiv ID: {config['configurable']['id_list']}")
        
        # 执行图
        result = await graph.ainvoke({}, config=config)
        
        logger.info(f"处理结果: {result}")
        
        # 检查结果中的关键信息
        if 'papers' in result:
            papers = result['papers']
            logger.info(f"处理了 {len(papers)} 篇论文")
            
            for i, paper in enumerate(papers):
                logger.info(f"论文 {i+1}:")
                logger.info(f"  标题: {paper.get('title', 'N/A')}")
                logger.info(f"  作者数量: {len(paper.get('authors', []))}")
                
                # 检查作者的role信息
                authors = paper.get('authors', [])
                for j, author in enumerate(authors):
                    if isinstance(author, dict):
                        role = author.get('role', 'N/A')
                        name = author.get('name', 'N/A')
                        logger.info(f"  作者 {j+1}: {name}, role: {role}")
                    else:
                        logger.info(f"  作者 {j+1}: {author} (字符串格式，无role信息)")
                        
                # 检查是否有orcid_aff_meta信息
                orcid_aff_meta = paper.get('orcid_aff_meta', {})
                if orcid_aff_meta:
                    logger.info(f"  ORCID机构元数据: {orcid_aff_meta}")
                else:
                    logger.info(f"  未找到ORCID机构元数据")
                    
        return result
        
    except Exception as e:
        logger.error(f"测试失败: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(test_fetch_by_id())