"""
OpenAlex 集成工具函数
基于 pyalex 库，提供全面的学术数据查询和分析功能
"""

import os
import logging
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, date
import pyalex
from pyalex import Works, Authors, Sources, Institutions, Topics, Publishers, Funders
from difflib import SequenceMatcher
import re

# 配置 pyalex
if email := os.getenv("OPENALEX_EMAIL"):
    pyalex.config.email = email

if api_key := os.getenv("OPENALEX_API_KEY"):
    pyalex.config.api_key = api_key

# 配置重试策略
pyalex.config.max_retries = 3
pyalex.config.retry_backoff_factor = 0.5
pyalex.config.retry_http_codes = [429, 500, 503]

logger = logging.getLogger(__name__)


class OpenAlexIntegration:
    """OpenAlex 数据集成类"""
    
    def __init__(self):
        self.works = Works()
        self.authors = Authors()
        self.institutions = Institutions()
        self.topics = Topics()
        
    # ==================== 作者相关功能 ====================
    
    def search_authors_by_name_and_institution(
        self, 
        author_name: str, 
        institution_names: List[str],
        country: Optional[str] = None,
        per_page: int = 25
    ) -> List[Dict]:
        """
        按作者姓名和机构搜索作者
        支持多机构匹配，提供更准确的作者消歧
        """
        try:
            # 首先搜索机构ID
            institution_ids = []
            for inst_name in institution_names:
                inst_results = self.institutions.search(inst_name).get()
                if inst_results:
                    # 如果指定了国家，优先选择匹配国家的机构
                    if country:
                        country_matches = [
                            inst for inst in inst_results 
                            if inst.get('country_code', '').lower() == country.lower()
                        ]
                        if country_matches:
                            institution_ids.append(country_matches[0]['id'])
                        else:
                            institution_ids.append(inst_results[0]['id'])
                    else:
                        institution_ids.append(inst_results[0]['id'])
            
            if not institution_ids:
                logger.warning(f"No institutions found for: {institution_names}")
                return []
            
            # 搜索作者
            query = self.authors.search(author_name)
            
            # 添加机构过滤
            for inst_id in institution_ids:
                inst_id_clean = inst_id.replace("https://openalex.org/", "")
                query = query.filter(affiliations={"institution": {"id": inst_id_clean}})
            
            results = query.select([
                "id", "display_name", "orcid", "works_count", "cited_by_count", 
                "summary_stats", "affiliations", "topics", "last_known_institutions"
            ]).get(per_page=per_page)
            
            # 增强作者信息
            enhanced_results = []
            for author in results:
                enhanced_author = self._enhance_author_info(author)
                enhanced_results.append(enhanced_author)
            
            return enhanced_results
            
        except Exception as e:
            logger.error(f"Error searching authors: {e}")
            return []
    
    def find_phd_candidates_by_institutions(
        self,
        institution_names: List[str],
        research_areas: List[str],
        country: Optional[str] = None,
        min_works_count: int = 2,  # 降低最小论文数
        max_works_count: int = 30,  # 提高最大论文数
        recent_years: int = 8  # 扩大时间窗口
    ) -> List[Dict]:
        """
        查找指定机构的疑似博士生
        基于发文量、时间窗口、研究领域等启发式规则
        """
        try:
            # 获取机构ID
            institution_ids = self._get_institution_ids(institution_names, country)
            if not institution_ids:
                return []
            
            # 获取研究领域概念ID
            concept_ids = self._get_concept_ids(research_areas)
            
            # 构建查询
            current_year = datetime.now().year
            start_year = current_year - recent_years
            
            authors_list = []
            
            for inst_id in institution_ids:
                inst_id_clean = inst_id.replace("https://openalex.org/", "")
                
                # 查询该机构的作者 - 使用数字而不是字符串格式
                actual_min = max(1, min_works_count - 1)  # 避免0或负数
                query = (self.authors
                        .filter(affiliations={"institution": {"id": inst_id_clean}})
                        .filter(works_count=actual_min)  # 直接使用数字
                        .filter(last_known_institutions={"id": inst_id_clean}))
                
                # 添加概念过滤（如果有研究领域）
                if concept_ids:
                    for concept_id in concept_ids:
                        concept_id_clean = concept_id.replace("https://openalex.org/", "")
                        query = query.filter(topics={"id": concept_id_clean})
                
                # 执行查询
                results = query.select([
                    "id", "display_name", "orcid", "works_count", "cited_by_count",
                    "summary_stats", "affiliations", "topics"
                ]).get(per_page=100)
                
                # 应用启发式规则筛选疑似博士生，包括最大论文数过滤
                for author in results:
                    works_count = author.get('works_count', 0)
                    if works_count > max_works_count:
                        continue  # 跳过论文数太多的作者
                        
                    if self._is_likely_phd_candidate(author, start_year, min_works_count, max_works_count):
                        enhanced_author = self._enhance_author_info(author)
                        enhanced_author['phd_likelihood_score'] = self._calculate_phd_likelihood(author)
                        authors_list.append(enhanced_author)
            
            # 按可能性得分排序
            authors_list.sort(key=lambda x: x.get('phd_likelihood_score', 0), reverse=True)
            
            return authors_list
            
        except Exception as e:
            logger.error(f"Error finding PhD candidates: {e}")
            return []
    
    def get_author_collaboration_network(
        self, 
        author_id: str, 
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        获取作者的合作网络
        """
        try:
            author_id_clean = author_id.replace("https://openalex.org/", "")
            
            # 获取作者的所有论文
            works = (Works()
                    .filter(author={"id": author_id_clean})
                    .select(["id", "title", "authorships", "publication_year", "cited_by_count"])
                    .get(per_page=200))
            
            # 分析合作者
            collaborators = {}
            for work in works:
                for authorship in work.get('authorships', []):
                    if authorship.get('author', {}).get('id') != author_id:
                        collab_id = authorship.get('author', {}).get('id')
                        collab_name = authorship.get('author', {}).get('display_name')
                        
                        if collab_id and collab_name:
                            if collab_id not in collaborators:
                                collaborators[collab_id] = {
                                    'id': collab_id,
                                    'name': collab_name,
                                    'collaboration_count': 0,
                                    'total_citations': 0,
                                    'recent_collaborations': []
                                }
                            
                            collaborators[collab_id]['collaboration_count'] += 1
                            collaborators[collab_id]['total_citations'] += work.get('cited_by_count', 0)
                            
                            if work.get('publication_year', 0) >= 2020:
                                collaborators[collab_id]['recent_collaborations'].append({
                                    'title': work.get('title'),
                                    'year': work.get('publication_year'),
                                    'citations': work.get('cited_by_count', 0)
                                })
            
            # 转换为列表并排序
            collab_list = list(collaborators.values())
            collab_list.sort(key=lambda x: x['collaboration_count'], reverse=True)
            
            return {
                'total_collaborators': len(collab_list),
                'frequent_collaborators': collab_list[:limit],
                'total_papers_analyzed': len(works)
            }
            
        except Exception as e:
            logger.error(f"Error getting collaboration network: {e}")
            return {}
    
    # ==================== 论文相关功能 ====================
    
    def search_papers_advanced(
        self,
        title: Optional[str] = None,
        author_name: Optional[str] = None,
        institution_names: Optional[List[str]] = None,
        concepts: Optional[List[str]] = None,
        publication_year_range: Optional[tuple] = None,
        is_oa: Optional[bool] = None,
        min_citations: Optional[int] = None,
        sort_by: str = "cited_by_count",
        per_page: int = 25
    ) -> List[Dict]:
        """
        高级论文搜索
        """
        try:
            query = Works()
            
            # 标题搜索
            if title:
                query = query.search(title)
            
            # 作者搜索
            if author_name:
                # 使用正确的作者搜索方式 - 先获取作者ID，然后过滤
                authors_query = Authors().search(author_name).get(per_page=1)
                if authors_query:
                    author_id = authors_query[0]['id'].replace("https://openalex.org/", "")
                    query = query.filter(authorships={"author": {"id": author_id}})
                else:
                    # 如果找不到作者，使用文本搜索
                    query = query.search(author_name)
            
            # 机构过滤
            if institution_names:
                inst_ids = self._get_institution_ids(institution_names)
                for inst_id in inst_ids:
                    inst_id_clean = inst_id.replace("https://openalex.org/", "")
                    query = query.filter(authorships={"institutions": {"id": inst_id_clean}})
            
            # 概念/研究领域过滤
            if concepts:
                concept_ids = self._get_concept_ids(concepts)
                for concept_id in concept_ids:
                    concept_id_clean = concept_id.replace("https://openalex.org/", "")
                    query = query.filter(topics={"id": concept_id_clean})
            
            # 年份范围
            if publication_year_range:
                start_year, end_year = publication_year_range
                query = query.filter(publication_year=f"{start_year}:{end_year}")
            
            # 开放获取
            if is_oa is not None:
                query = query.filter(open_access={"is_oa": is_oa})
            
            # 最小引用数
            if min_citations:
                query = query.filter(cited_by_count=f">={min_citations}")
            
            # 排序 - 修复pyalex的sort方法调用
            if sort_by in ["cited_by_count", "publication_date", "relevance_score"]:
                if sort_by == "publication_date":
                    sort_by = "publication_year"
                # pyalex的sort方法不需要参数，需要使用不同的方式
                # 我们会在结果获取后进行排序
            
            results = query.select([
                "id", "title", "publication_year", "cited_by_count", "open_access",
                "authorships", "topics", "abstract_inverted_index", "doi"
            ]).get(per_page=per_page)
            
            # 增强论文信息
            enhanced_results = []
            for work in results:
                enhanced_work = self._enhance_work_info(work)
                enhanced_results.append(enhanced_work)
            
            # 在获取结果后进行排序
            if sort_by == "cited_by_count":
                enhanced_results.sort(key=lambda x: x.get('cited_by_count', 0), reverse=True)
            elif sort_by == "publication_year":
                enhanced_results.sort(key=lambda x: x.get('publication_year', 0), reverse=True)
            
            return enhanced_results
            
        except Exception as e:
            logger.error(f"Error in advanced paper search: {e}")
            return []
    
    def get_trending_papers(
        self,
        research_areas: List[str],
        time_period: int = 365,  # 天数
        min_citations: int = 5,
        per_page: int = 25
    ) -> List[Dict]:
        """
        获取指定研究领域的趋势论文
        """
        try:
            # 计算时间范围
            from datetime import timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=time_period)
            
            concept_ids = self._get_concept_ids(research_areas)
            if not concept_ids:
                return []
            
            query = Works()
            
            # 添加概念过滤
            for concept_id in concept_ids:
                concept_id_clean = concept_id.replace("https://openalex.org/", "")
                query = query.filter(topics={"id": concept_id_clean})
            
            # 时间和引用过滤
            query = (query
                    .filter(from_publication_date=start_date.strftime('%Y-%m-%d'))
                    .filter(cited_by_count=f">={min_citations}")
                    .sort("cited_by_count:desc"))
            
            results = query.select([
                "id", "title", "publication_year", "cited_by_count", "open_access",
                "authorships", "topics", "abstract_inverted_index", "doi"
            ]).get(per_page=per_page)
            
            # 计算趋势得分
            enhanced_results = []
            for work in results:
                enhanced_work = self._enhance_work_info(work)
                enhanced_work['trending_score'] = self._calculate_trending_score(work, time_period)
                enhanced_results.append(enhanced_work)
            
            # 按趋势得分重新排序
            enhanced_results.sort(key=lambda x: x.get('trending_score', 0), reverse=True)
            
            return enhanced_results
            
        except Exception as e:
            logger.error(f"Error getting trending papers: {e}")
            return []
    
    # ==================== 机构相关功能 ====================
    
    def analyze_institution_research_profile(
        self,
        institution_name: str,
        years_back: int = 5
    ) -> Dict[str, Any]:
        """
        分析机构的研究概况
        """
        try:
            # 搜索机构
            inst_results = self.institutions.search(institution_name).get(per_page=1)
            if not inst_results:
                return {}
            
            institution = inst_results[0]
            inst_id = institution['id'].replace("https://openalex.org/", "")
            
            # 获取时间范围
            current_year = datetime.now().year
            start_year = current_year - years_back
            
            # 获取该机构的论文
            works = (Works()
                    .filter(authorships={"institutions": {"id": inst_id}})
                    .filter(publication_year=f">{start_year-1}")  # >2021 相当于 >=2022
                    .select([
                        "id", "title", "publication_year", "cited_by_count",
                        "authorships", "topics", "open_access"
                    ])
                    .get(per_page=200))
            
            # 分析研究领域
            concept_counts = {}
            total_citations = 0
            oa_count = 0
            year_stats = {}
            
            for work in works:
                # 过滤日期范围
                year = work.get('publication_year')
                if year and (year < start_year or year > current_year):
                    continue
                    
                # 统计引用
                total_citations += work.get('cited_by_count', 0)
                
                # 统计开放获取
                open_access = work.get('open_access', {})
                if open_access.get('is_oa', False):
                    oa_count += 1
                
                # 按年统计
                if year:
                    year_stats[year] = year_stats.get(year, 0) + 1
                
                # 统计研究概念
                for concept in work.get('topics', []):
                    concept_name = concept.get('display_name')
                    if concept_name:
                        concept_counts[concept_name] = concept_counts.get(concept_name, 0) + 1
            
            # 排序研究领域
            top_concepts = sorted(concept_counts.items(), key=lambda x: x[1], reverse=True)[:20]
            
            return {
                'institution': {
                    'id': institution['id'],
                    'name': institution.get('display_name'),
                    'country': institution.get('country_code'),
                    'type': institution.get('type'),
                    'works_count': institution.get('works_count', 0),
                    'cited_by_count': institution.get('cited_by_count', 0)
                },
                'analysis_period': f"{start_year}-{current_year}",
                'total_papers': len(works),
                'total_citations': total_citations,
                'average_citations': total_citations / len(works) if works else 0,
                'open_access_ratio': oa_count / len(works) if works else 0,
                'papers_per_year': year_stats,
                'top_research_areas': top_concepts
            }
            
        except Exception as e:
            logger.error(f"Error analyzing institution: {e}")
            return {}
    
    # ==================== 辅助方法 ====================
    
    def _get_institution_ids(self, institution_names: List[str], country: Optional[str] = None) -> List[str]:
        """获取机构ID列表"""
        institution_ids = []
        for inst_name in institution_names:
            try:
                inst_results = self.institutions.search(inst_name).get(per_page=5)
                if inst_results:
                    if country:
                        # 优先选择匹配国家的机构
                        country_matches = [
                            inst for inst in inst_results 
                            if inst.get('country_code', '').lower() == country.lower()
                        ]
                        if country_matches:
                            institution_ids.append(country_matches[0]['id'])
                        else:
                            institution_ids.append(inst_results[0]['id'])
                    else:
                        institution_ids.append(inst_results[0]['id'])
            except Exception as e:
                logger.warning(f"Failed to get ID for institution {inst_name}: {e}")
                continue
        return institution_ids
    
    def _get_concept_ids(self, concept_names: List[str]) -> List[str]:
        """获取概念ID列表，支持中文关键词映射"""
        
        # 中文到英文的关键词映射
        chinese_to_english = {
            "机器学习": "machine learning",
            "深度学习": "deep learning", 
            "人工智能": "artificial intelligence",
            "计算机科学": "computer science",
            "自然语言处理": "natural language processing",
            "计算机视觉": "computer vision",
            "数据挖掘": "data mining",
            "神经网络": "neural network",
            "算法": "algorithm",
            "软件工程": "software engineering"
        }
        
        concept_ids = []
        for concept_name in concept_names:
            try:
                # 如果是中文关键词，先转换为英文
                search_term = chinese_to_english.get(concept_name, concept_name)
                
                concept_results = Topics().search(search_term).get(per_page=3)
                if concept_results:
                    concept_ids.append(concept_results[0]['id'])
                    logger.info(f"Found concept for '{concept_name}' -> '{search_term}': {concept_results[0]['id']}")
                else:
                    logger.warning(f"No concept found for '{concept_name}' -> '{search_term}'")
            except Exception as e:
                logger.warning(f"Failed to get ID for concept {concept_name}: {e}")
                continue
        return concept_ids
    
    def _enhance_author_info(self, author: Dict) -> Dict:
        """增强作者信息"""
        enhanced = author.copy()
        
        # 计算学术年龄
        first_year = author.get('first_publication_year')
        if first_year:
            enhanced['academic_age'] = datetime.now().year - first_year
        
        # 提取最新机构信息
        affiliations = author.get('affiliations', [])
        if affiliations:
            latest_aff = affiliations[0]  # 通常第一个是最新的
            enhanced['current_institution'] = {
                'name': latest_aff.get('institution', {}).get('display_name'),
                'country': latest_aff.get('institution', {}).get('country_code'),
                'type': latest_aff.get('institution', {}).get('type')
            }
        
        # 提取主要研究领域
        topics = author.get('topics', [])[:5]  # 取前5个
        enhanced['research_areas'] = [
            {
                'name': topic.get('display_name'),
                'score': topic.get('count', 0)  # 使用 count 而不是 score
            }
            for topic in topics
        ]
        
        return enhanced
    
    def _enhance_work_info(self, work: Dict) -> Dict:
        """增强论文信息"""
        enhanced = work.copy()
        
        # 提取作者信息
        authorships = work.get('authorships', [])
        authors = []
        institutions = set()
        
        for authorship in authorships:
            author_info = authorship.get('author', {})
            if author_info.get('display_name'):
                authors.append({
                    'name': author_info.get('display_name'),
                    'orcid': author_info.get('orcid'),
                    'is_corresponding': authorship.get('is_corresponding_author', False)
                })
            
            # 收集机构
            for institution in authorship.get('institutions', []):
                institutions.add(institution.get('display_name', ''))
        
        enhanced['authors'] = authors
        enhanced['institutions'] = list(institutions)
        
        # 处理摘要
        abstract_index = work.get('abstract_inverted_index')
        if abstract_index:
            try:
                # 重建摘要文本
                abstract_words = {}
                for word, positions in abstract_index.items():
                    for pos in positions:
                        abstract_words[pos] = word
                
                if abstract_words:
                    sorted_positions = sorted(abstract_words.keys())
                    enhanced['abstract'] = ' '.join(abstract_words[pos] for pos in sorted_positions)
            except:
                enhanced['abstract'] = None
        
        return enhanced
    
    def _is_likely_phd_candidate(self, author: Dict, start_year: int, min_works_count: int = 3, max_works_count: int = 20) -> bool:
        """判断是否可能是博士生的启发式规则"""
        works_count = author.get('works_count', 0)
        cited_by_count = author.get('cited_by_count', 0)
        
        # 从 summary_stats 中获取时间信息
        summary_stats = author.get('summary_stats', {})
        
        # 基本条件：论文数量在指定范围内
        if works_count < min_works_count or works_count > max_works_count:
            return False
        
        # 引用数不太高（博士生通常引用数较少）
        if cited_by_count > works_count * 50:  # 平均每篇论文引用不超过50
            return False
        
        return True
    
    def _calculate_phd_likelihood(self, author: Dict) -> float:
        """计算博士生可能性得分"""
        score = 0.0
        
        works_count = author.get('works_count', 0)
        cited_by_count = author.get('cited_by_count', 0)
        
        # 论文数量得分（3-15篇最佳）
        if 3 <= works_count <= 15:
            score += 0.4
        elif works_count < 3:
            score += 0.2
        
        # 引用数得分（适中最佳）
        avg_citations = cited_by_count / works_count if works_count > 0 else 0
        if 1 <= avg_citations <= 20:
            score += 0.3
        elif avg_citations < 1:
            score += 0.2
        
        # 从 summary_stats 获取更多信息
        summary_stats = author.get('summary_stats', {})
        h_index = summary_stats.get('h_index', 0)
        
        # H指数得分
        if 1 <= h_index <= 10:
            score += 0.3
        
        return min(score, 1.0)
    
    def _calculate_trending_score(self, work: Dict, time_period: int) -> float:
        """计算趋势得分"""
        citations = work.get('cited_by_count', 0)
        pub_year = work.get('publication_year', datetime.now().year)
        current_year = datetime.now().year
        
        # 基础引用得分
        citation_score = min(citations / 10.0, 1.0)  # 10引用归一化为1.0
        
        # 时间衰减因子（越新的论文权重越高）
        year_diff = current_year - pub_year
        time_factor = max(0.1, 1.0 - (year_diff / 5.0))  # 5年内的论文
        
        return citation_score * time_factor


# 全局实例
openalex_client = OpenAlexIntegration()


# 便捷函数
def search_authors_by_criteria(
    name: Optional[str] = None,
    institutions: Optional[List[str]] = None,
    country: Optional[str] = None,
    per_page: int = 25
) -> List[Dict]:
    """便捷的作者搜索函数"""
    if name and institutions:
        return openalex_client.search_authors_by_name_and_institution(
            name, institutions, country, per_page
        )
    elif name:
        try:
            results = Authors().search(name).select([
                "id", "display_name", "orcid", "works_count", "cited_by_count",
                "summary_stats", "affiliations", "topics"
            ]).get(per_page=per_page)
            return [openalex_client._enhance_author_info(author) for author in results]
        except Exception as e:
            logger.error(f"Error searching authors by name: {e}")
            return []
    else:
        return []


def find_phd_candidates(
    institutions: List[str],
    research_areas: List[str] = ["artificial intelligence", "machine learning", "computer science"],
    country: str = "CN"
) -> List[Dict]:
    """查找博士生候选人"""
    return openalex_client.find_phd_candidates_by_institutions(
        institution_names=institutions,  # 参数名匹配
        research_areas=research_areas,
        country=country
    )


def search_papers_by_criteria(**kwargs) -> List[Dict]:
    """便捷的论文搜索函数"""
    return openalex_client.search_papers_advanced(**kwargs)


def get_institution_profile(institution_name: str) -> Dict[str, Any]:
    """获取机构研究概况"""
    return openalex_client.analyze_institution_research_profile(institution_name)
