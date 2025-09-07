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
def _normalize_institution_name(institution_name: str) -> str:
    """
    标准化机构名称，去除常见的变体和缩写
    """
    if not institution_name:
        return ""
    
    # 转换为小写并去除多余空格
    normalized = re.sub(r'\s+', ' ', institution_name.lower().strip())
    
    # 去除常见的后缀和前缀
    suffixes_to_remove = [
        r'\s*,?\s*usa?$',
        r'\s*,?\s*united states$',
        r'\s*,?\s*china$',
        r'\s*,?\s*uk$',
        r'\s*,?\s*united kingdom$',
        r'\s*,?\s*inc\.?$',
        r'\s*,?\s*ltd\.?$',
        r'\s*,?\s*corp\.?$',
        r'\s*,?\s*corporation$',
        r'\s*,?\s*company$',
        r'\s*,?\s*co\.?$'
    ]
    
    for suffix in suffixes_to_remove:
        normalized = re.sub(suffix, '', normalized)
    
    # 标准化常见词汇
    word_replacements = {
        r'\buniv\.?\b': 'university',
        r'\binst\.?\b': 'institute',
        r'\btech\.?\b': 'technology',
        r'\bcoll\.?\b': 'college',
        r'\bdept\.?\b': 'department',
        r'\blab\.?\b': 'laboratory',
        r'\bres\.?\b': 'research',
        r'\bctr\.?\b': 'center',
        r'\bcentre\b': 'center',
        r'\b&\b': 'and',
        r'\bint\'?l\b': 'international'
    }
    
    for pattern, replacement in word_replacements.items():
        normalized = re.sub(pattern, replacement, normalized)
    
    # 去除标点符号和多余空格
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized


def _get_institution_aliases() -> Dict[str, List[str]]:
    """
    获取机构名称别名映射
    """
    return {
        # MIT 相关
        'massachusetts institute of technology': ['mit', 'mass inst tech', 'massachusetts inst technology'],
        'mit': ['massachusetts institute of technology', 'mass inst tech'],
        
        # Stanford 相关
        'stanford university': ['stanford', 'stanford univ'],
        'stanford': ['stanford university'],
        
        # Harvard 相关
        'harvard university': ['harvard', 'harvard univ'],
        'harvard': ['harvard university'],
        
        # UC Berkeley 相关
        'university of california berkeley': ['uc berkeley', 'berkeley', 'ucb', 'cal berkeley'],
        'uc berkeley': ['university of california berkeley', 'berkeley'],
        'berkeley': ['university of california berkeley', 'uc berkeley'],
        
        # CMU 相关
        'carnegie mellon university': ['cmu', 'carnegie mellon', 'carnegie mellon univ'],
        'cmu': ['carnegie mellon university'],
        
        # Caltech 相关
        'california institute of technology': ['caltech', 'cal tech'],
        'caltech': ['california institute of technology'],
        
        # 清华大学相关
        'tsinghua university': ['tsinghua', 'tsinghua univ', 'thu'],
        'tsinghua': ['tsinghua university'],
        
        # 北京大学相关
        'peking university': ['pku', 'beijing university', 'peking univ'],
        'pku': ['peking university'],
        
        # 中科院相关
        'chinese academy of sciences': ['cas', 'chinese acad sci'],
        'cas': ['chinese academy of sciences'],
        
        # 其他常见机构
        'university of washington': ['uw', 'washington university'],
        'georgia institute of technology': ['georgia tech', 'gatech'],
        'university of illinois urbana champaign': ['uiuc', 'illinois'],
        'new york university': ['nyu'],
        'university of southern california': ['usc'],
        'university of california los angeles': ['ucla'],
        'university of california san diego': ['ucsd'],
        'university of michigan': ['umich', 'michigan'],
        'princeton university': ['princeton'],
        'yale university': ['yale'],
        'columbia university': ['columbia'],
        'cornell university': ['cornell'],
        'university of pennsylvania': ['upenn', 'penn'],
        'johns hopkins university': ['jhu', 'johns hopkins'],
        'northwestern university': ['northwestern'],
        'duke university': ['duke'],
        'university of chicago': ['uchicago'],
        'rice university': ['rice'],
        'vanderbilt university': ['vanderbilt'],
        'emory university': ['emory'],
        'university of texas austin': ['ut austin', 'texas'],
        'texas a m university': ['tamu', 'texas am'],
        'university of wisconsin madison': ['uw madison', 'wisconsin'],
        'university of minnesota': ['umn', 'minnesota'],
        'ohio state university': ['osu', 'ohio state'],
        'pennsylvania state university': ['penn state', 'psu'],
        'purdue university': ['purdue'],
        'university of florida': ['uf', 'florida'],
        'university of north carolina chapel hill': ['unc', 'north carolina'],
        'virginia tech': ['vt', 'virginia polytechnic'],
        'arizona state university': ['asu', 'arizona state']
    }


def _calculate_institution_similarity(inst1: str, inst2: str) -> float:
    """
    计算两个机构名称的相似度
    结合标准化、别名匹配和字符串相似度
    """
    if not inst1 or not inst2:
        return 0.0
    
    # 标准化机构名称
    norm1 = _normalize_institution_name(inst1)
    norm2 = _normalize_institution_name(inst2)
    
    # 完全匹配
    if norm1 == norm2:
        return 1.0
    
    # 检查别名映射
    aliases = _get_institution_aliases()
    
    # 检查 inst1 是否是 inst2 的别名
    if norm2 in aliases:
        if norm1 in aliases[norm2]:
            return 0.95
    
    # 检查 inst2 是否是 inst1 的别名
    if norm1 in aliases:
        if norm2 in aliases[norm1]:
            return 0.95
    
    # 检查是否都是某个机构的别名
    for canonical, alias_list in aliases.items():
        if norm1 in alias_list and norm2 in alias_list:
            return 0.9
        if (norm1 == canonical and norm2 in alias_list) or (norm2 == canonical and norm1 in alias_list):
            return 0.95
    
    # 字符串相似度匹配
    similarity = SequenceMatcher(None, norm1, norm2).ratio()
    
    # 检查关键词包含关系
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    # 如果一个是另一个的子集，给予较高分数
    if words1.issubset(words2) or words2.issubset(words1):
        similarity = max(similarity, 0.8)
    
    # 检查重要关键词重叠
    important_words = {'university', 'institute', 'technology', 'college', 'academy', 'school'}
    common_important = words1.intersection(words2).intersection(important_words)
    if common_important:
        # 计算重叠比例
        overlap_ratio = len(words1.intersection(words2)) / max(len(words1), len(words2))
        similarity = max(similarity, overlap_ratio * 0.9)
    
    return similarity


def get_author_academic_metrics(
    author_name: str,
    institution_name: Optional[str] = None
) -> Optional[Dict[str, Union[int, str]]]:
    """
    根据作者姓名和机构获取学术指标
    支持模糊机构匹配，包括别名和相似度匹配
    """
    try:
        # 直接按姓名搜索作者
        query = openalex_client.authors.search(author_name)
        results = query.select([
            "id", "display_name", "orcid", "works_count", "cited_by_count", 
            "summary_stats", "affiliations", "topics", "last_known_institutions"
        ]).get(per_page=20)  # 增加搜索结果数量以提高匹配机会
        
        if not results:
            logger.warning(f"No authors found for {author_name}")
            return None
        
        # 如果没有提供机构信息，返回第一个匹配的作者
        if not institution_name:
            logger.info(f"No institution provided for {author_name}, using first match")
            best_match = results[0]
        else:
            # 寻找机构匹配的作者
            best_match = None
            best_name_similarity = 0
            best_institution_similarity = 0
            
            for author in results:
                # 计算姓名匹配度
                name_similarity = SequenceMatcher(None, 
                                                author_name.lower(), 
                                                author.get('display_name', '').lower()).ratio()
                
                # 检查机构是否匹配
                author_institutions = []
                
                # 从 affiliations 获取机构信息
                for aff in author.get('affiliations', []):
                    institution = aff.get('institution', {})
                    if institution and institution.get('display_name'):
                        author_institutions.append(institution['display_name'])
                
                # 从 last_known_institutions 获取机构信息
                for inst in author.get('last_known_institutions', []):
                    if inst.get('display_name'):
                        author_institutions.append(inst['display_name'])
                
                # 计算最佳机构匹配度
                max_inst_similarity = 0
                matched_institution = None
                
                for oa_inst in author_institutions:
                    inst_similarity = _calculate_institution_similarity(institution_name, oa_inst)
                    if inst_similarity > max_inst_similarity:
                        max_inst_similarity = inst_similarity
                        matched_institution = oa_inst
                
                logger.info(f"Author '{author.get('display_name', '')}' - Name similarity: {name_similarity:.2f}, Institution similarity: {max_inst_similarity:.2f} (matched: {matched_institution})")
                
                # 综合评分：姓名相似度 * 0.6 + 机构相似度 * 0.4
                combined_score = name_similarity * 0.6 + max_inst_similarity * 0.4
                
                # 设置最低阈值：姓名必须完全匹配，机构相似度 >= 0.7
                if name_similarity >= 1.0 and max_inst_similarity >= 0.7:
                    if combined_score > (best_name_similarity * 0.6 + best_institution_similarity * 0.4):
                        best_name_similarity = name_similarity
                        best_institution_similarity = max_inst_similarity
                        best_match = author
                        logger.info(f"New best match: '{author.get('display_name', '')}' at '{matched_institution}' (combined score: {combined_score:.2f})")
            
            # 如果没有找到高置信度匹配，记录并返回 None
            if not best_match:
                logger.info(f"No high-confidence match found for {author_name} at {institution_name}")
                logger.info(f"Available authors: {[author.get('display_name', '') for author in results[:5]]}")
                return None
        
        if not best_match:
            logger.warning(f"No suitable author match found for {author_name}")
            return None
        
        # 提取学术指标
        summary_stats = best_match.get('summary_stats', {})
        
        metrics = {
            'citations': best_match.get('cited_by_count', 0),
            'h_index': summary_stats.get('h_index', 0),
            'i10_index': summary_stats.get('i10_index', 0),
            'orcid': best_match.get('orcid')
        }
        
        logger.info(f"Successfully matched {author_name} at {institution_name}: {metrics}")
        return metrics
        
    except Exception as e:
        logger.error(f"Error getting academic metrics for {author_name}: {e}")
        return None


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
