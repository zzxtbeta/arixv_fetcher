"""
OpenAlex 相关 API 接口
提供全面的学术数据查询服务
"""

from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime

from ..agent.openalex_utils import (
    openalex_client,
    search_authors_by_criteria,
    find_phd_candidates,
    search_papers_by_criteria,
    get_institution_profile
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/openalex", tags=["OpenAlex"])


@router.get("/authors/search")
async def search_authors(
    name: Optional[str] = Query(None, description="作者姓名"),
    institutions: Optional[str] = Query(None, description="机构名称，多个用逗号分隔"),
    country: Optional[str] = Query(None, description="国家代码（如 CN, US）"),
    per_page: int = Query(25, description="每页结果数量", le=100)
) -> Dict[str, Any]:
    """
    搜索作者
    支持按姓名、机构、国家等条件筛选
    """
    try:
        institution_list = []
        if institutions:
            institution_list = [inst.strip() for inst in institutions.split(",")]
        
        results = search_authors_by_criteria(
            name=name,
            institutions=institution_list if institution_list else None,
            country=country,
            per_page=per_page
        )
        
        return {
            "success": True,
            "count": len(results),
            "authors": results,
            "message": f"Found {len(results)} authors"
        }
        
    except Exception as e:
        logger.error(f"Error searching authors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/authors/phd-candidates")
async def find_phd_candidates_api(
    institutions: str = Query(..., description="机构名称，多个用逗号分隔（如：北京大学,清华大学,浙江大学）"),
    research_areas: Optional[str] = Query(
        "artificial intelligence,machine learning,computer science", 
        description="研究领域，多个用逗号分隔"
    ),
    country: str = Query("CN", description="国家代码"),
    min_works: int = Query(3, description="最少论文数量"),
    max_works: int = Query(20, description="最多论文数量"),
    recent_years: int = Query(5, description="考虑的年份范围")
) -> Dict[str, Any]:
    """
    查找疑似博士生
    基于发文量、时间窗口、研究领域等启发式规则
    """
    try:
        institution_list = [inst.strip() for inst in institutions.split(",")]
        research_list = [area.strip() for area in research_areas.split(",")]
        
        results = openalex_client.find_phd_candidates_by_institutions(
            institution_names=institution_list,
            research_areas=research_list,
            country=country,
            min_works_count=min_works,
            max_works_count=max_works,
            recent_years=recent_years
        )
        
        return {
            "success": True,
            "count": len(results),
            "candidates": results,
            "query_parameters": {
                "institutions": institution_list,
                "research_areas": research_list,
                "country": country,
                "works_range": f"{min_works}-{max_works}",
                "recent_years": recent_years
            },
            "message": f"Found {len(results)} potential PhD candidates"
        }
        
    except Exception as e:
        logger.error(f"Error finding PhD candidates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/authors/{author_id:path}/collaboration")
async def get_author_collaboration(
    author_id: str,
    limit: int = Query(50, description="返回的合作者数量上限")
) -> Dict[str, Any]:
    """
    获取作者的合作网络
    """
    try:
        # URL解码并确保 author_id 格式正确
        import urllib.parse
        author_id = urllib.parse.unquote(author_id)
        
        if not author_id.startswith("https://openalex.org/"):
            author_id = f"https://openalex.org/{author_id}"
        
        collaboration_data = openalex_client.get_author_collaboration_network(
            author_id=author_id,
            limit=limit
        )
        
        return {
            "success": True,
            "author_id": author_id,
            "collaboration_network": collaboration_data,
            "message": f"Retrieved collaboration network with {collaboration_data.get('total_collaborators', 0)} collaborators"
        }
        
    except Exception as e:
        logger.error(f"Error getting collaboration network: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/papers/search")
async def search_papers_advanced_api(
    title: Optional[str] = Query(None, description="论文标题关键词"),
    author_name: Optional[str] = Query(None, description="作者姓名"),
    institutions: Optional[str] = Query(None, description="机构名称，多个用逗号分隔"),
    concepts: Optional[str] = Query(None, description="研究概念/领域，多个用逗号分隔"),
    publication_year_start: Optional[int] = Query(None, description="发表年份起始"),
    publication_year_end: Optional[int] = Query(None, description="发表年份结束"),
    is_oa: Optional[bool] = Query(None, description="是否开放获取"),
    min_citations: Optional[int] = Query(None, description="最小引用数"),
    sort_by: str = Query("cited_by_count", description="排序方式：cited_by_count, publication_date, relevance_score"),
    per_page: int = Query(25, description="每页结果数量", le=100)
) -> Dict[str, Any]:
    """
    高级论文搜索
    支持多维度筛选和排序
    """
    try:
        # 处理机构列表
        institution_list = None
        if institutions:
            institution_list = [inst.strip() for inst in institutions.split(",")]
        
        # 处理概念列表
        concept_list = None
        if concepts:
            concept_list = [concept.strip() for concept in concepts.split(",")]
        
        # 处理年份范围
        publication_year_range = None
        if publication_year_start or publication_year_end:
            start = publication_year_start or 2000
            end = publication_year_end or datetime.now().year
            publication_year_range = (start, end)
        
        results = search_papers_by_criteria(
            title=title,
            author_name=author_name,
            institution_names=institution_list,
            concepts=concept_list,
            publication_year_range=publication_year_range,
            is_oa=is_oa,
            min_citations=min_citations,
            sort_by=sort_by,
            per_page=per_page
        )
        
        return {
            "success": True,
            "count": len(results),
            "papers": results,
            "query_parameters": {
                "title": title,
                "author_name": author_name,
                "institutions": institution_list,
                "concepts": concept_list,
                "year_range": publication_year_range,
                "is_oa": is_oa,
                "min_citations": min_citations,
                "sort_by": sort_by
            },
            "message": f"Found {len(results)} papers"
        }
        
    except Exception as e:
        logger.error(f"Error searching papers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/papers/trending")
async def get_trending_papers_api(
    research_areas: str = Query(
        "artificial intelligence,machine learning,computer science",
        description="研究领域，多个用逗号分隔"
    ),
    time_period: int = Query(365, description="时间窗口（天数）"),
    min_citations: int = Query(5, description="最小引用数"),
    per_page: int = Query(25, description="每页结果数量", le=100)
) -> Dict[str, Any]:
    """
    获取趋势论文
    基于时间、引用数等因子计算趋势得分
    """
    try:
        research_list = [area.strip() for area in research_areas.split(",")]
        
        results = openalex_client.get_trending_papers(
            research_areas=research_list,
            time_period=time_period,
            min_citations=min_citations,
            per_page=per_page
        )
        
        return {
            "success": True,
            "count": len(results),
            "trending_papers": results,
            "query_parameters": {
                "research_areas": research_list,
                "time_period_days": time_period,
                "min_citations": min_citations
            },
            "message": f"Found {len(results)} trending papers"
        }
        
    except Exception as e:
        logger.error(f"Error getting trending papers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/institutions/profile")
async def get_institution_profile_api(
    name: str = Query(..., description="机构名称"),
    years_back: int = Query(5, description="分析年限")
) -> Dict[str, Any]:
    """
    获取机构研究概况
    包括论文统计、研究领域分布等
    """
    try:
        profile = get_institution_profile(name)
        
        if not profile:
            raise HTTPException(status_code=404, detail=f"Institution '{name}' not found")
        
        return {
            "success": True,
            "institution_profile": profile,
            "message": f"Retrieved profile for {profile.get('institution', {}).get('name', name)}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting institution profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/institutions/search")
async def search_institutions(
    query: str = Query(..., description="机构名称或关键词"),
    country: Optional[str] = Query(None, description="国家代码"),
    institution_type: Optional[str] = Query(None, description="机构类型"),
    per_page: int = Query(25, description="每页结果数量", le=100)
) -> Dict[str, Any]:
    """
    搜索机构
    """
    try:
        from pyalex import Institutions
        
        institutions_query = Institutions().search(query)
        
        if country:
            institutions_query = institutions_query.filter(country_code=country.upper())
        
        if institution_type:
            institutions_query = institutions_query.filter(type=institution_type)
        
        results = institutions_query.select([
            "id", "display_name", "country_code", "type", "works_count", 
            "cited_by_count", "homepage_url", "ror"
        ]).get(per_page=per_page)
        
        # 增强机构信息
        enhanced_results = []
        for inst in results:
            enhanced_inst = inst.copy()
            enhanced_inst['openalex_id'] = inst['id']
            enhanced_results.append(enhanced_inst)
        
        return {
            "success": True,
            "count": len(enhanced_results),
            "institutions": enhanced_results,
            "message": f"Found {len(enhanced_results)} institutions"
        }
        
    except Exception as e:
        logger.error(f"Error searching institutions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/concepts/search")
async def search_concepts(
    query: str = Query(..., description="概念关键词"),
    level: Optional[int] = Query(None, description="概念层级 (0-5)"),
    per_page: int = Query(25, description="每页结果数量", le=100)
) -> Dict[str, Any]:
    """
    搜索研究概念/领域
    """
    try:
        from pyalex import Topics
        
        topics_query = Topics().search(query)
        
        if level is not None:
            topics_query = topics_query.filter(level=level)
        
        results = topics_query.select([
            "id", "display_name", "description", "level", "works_count",
            "cited_by_count", "subfield", "field", "domain"
        ]).get(per_page=per_page)
        
        return {
            "success": True,
            "count": len(results),
            "concepts": results,
            "message": f"Found {len(results)} research concepts"
        }
        
    except Exception as e:
        logger.error(f"Error searching concepts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """健康检查"""
    try:
        # 简单测试 OpenAlex 连接
        from pyalex import Works
        test_result = Works().get(per_page=1)
        
        return {
            "status": "healthy",
            "openalex_connection": "ok" if test_result else "failed",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
