import axios from 'axios'

const apiBase = import.meta.env?.VITE_API_BASE || 'http://localhost:8000'

export const api = axios.create({ baseURL: apiBase })

export async function getOverview() {
  const { data } = await api.get('/dashboard/overview')
  return data as { papers: number; authors: number; affiliations: number; categories: number }
}

export async function searchAuthor(q: string) {
  const { data } = await api.get('/dashboard/author', { params: { q } })
  return data as {
    query: string
    results: Array<{
      author: { id: number; name: string; orcid?: string }
      affiliations: Array<{ id: number; aff_name: string; country?: string; role?: string; start_date?: string; end_date?: string; latest_time?: string; qs?: { y2025?: string; y2024?: string } }>
      recent_papers: Array<{ id: number; paper_title: string; published: string; pdf_source: string; arxiv_entry: string }>
      top_collaborators: Array<{ id: number; name: string; count: number }>
    }>
  }
}

export async function triggerFetch({ categories, max_results, start_date, end_date }: { categories?: string; max_results?: number; start_date?: string; end_date?: string }) {
  const params = new URLSearchParams()
  if (categories) params.set('categories', categories)
  if (max_results) params.set('max_results', String(max_results))
  if (start_date && end_date) {
    params.set('start_date', start_date)
    params.set('end_date', end_date)
  }
  const { data } = await api.post(`/data/fetch-arxiv-today?${params.toString()}`)
  return data as { status: string; inserted: number; skipped: number; fetched: number }
}

export async function triggerFetchById({ ids }: { ids: string }) {
  const params = new URLSearchParams()
  params.set('ids', ids)
  const { data } = await api.post(`/data/fetch-arxiv-by-id?${params.toString()}`)
  return data as { status: string; inserted: number; skipped: number; fetched: number }
}

export async function getLatestPapers(page = 1, limit = 20, titleSearch?: string, arxivSearch?: string) {
  const params: any = { page, limit }
  if (titleSearch?.trim()) params.title_search = titleSearch.trim()
  if (arxivSearch?.trim()) params.arxiv_search = arxivSearch.trim()
  const { data } = await api.get('/dashboard/latest-papers', { params })
  return data as { items: Array<any>; total: number; page: number; limit: number }
}

export async function getAffiliationPaperCount(days = 7) {
  const { data } = await api.get('/dashboard/charts/affiliation-paper-count', { params: { days } })
  return data as { items: Array<{ affiliation: string; count: number }>; days: number }
}

export async function getAffiliationAuthorCount(days = 7) {
  const { data } = await api.get('/dashboard/charts/affiliation-author-count', { params: { days } })
  return data as { items: Array<{ affiliation: string; count: number }>; days: number }
}

export async function webSearchPerson(name: string, affiliation: string, searchPrompt: string) {
  const params = new URLSearchParams()
  params.set('name', name)
  params.set('affiliation', affiliation)
  params.set('search_prompt', searchPrompt)
  const { data } = await api.post(`/dashboard/web-search?${params.toString()}`)
  return data as {
    success: boolean
    name: string
    affiliation: string
    search_prompt: string
    query: string
    answer: string
    results: Array<{
      title: string
      url: string
      content: string
      score: number
    }>
    error?: string
  }
}

export async function searchPersonRole(name: string, affiliation: string) {
  const params = new URLSearchParams()
  params.set('name', name)
  params.set('affiliation', affiliation)
  const { data } = await api.post(`/dashboard/search-role?${params.toString()}`)
  return data as {
    success: boolean
    name: string
    affiliation: string
    query: string
    answer: string
    extracted_role?: string
    results: Array<{
      title: string
      url: string
      content: string
      score: number
    }>
    error?: string
  }
}

// ==================== OpenAlex API Functions ====================

export interface OpenAlexAuthor {
  id: string
  display_name: string
  orcid?: string
  works_count: number
  cited_by_count: number
  h_index: number
  i10_index?: number
  academic_age?: number
  current_institution?: {
    name: string
    country: string
    type: string
  }
  research_areas?: Array<{
    name: string
    score: number
  }>
  phd_likelihood_score?: number
}

export interface OpenAlexPaper {
  id: string
  title: string
  publication_year: number
  cited_by_count: number
  is_oa: boolean
  authors: Array<{
    name: string
    orcid?: string
    is_corresponding: boolean
  }>
  institutions: string[]
  abstract?: string
  trending_score?: number
}

export interface OpenAlexInstitution {
  id: string
  display_name: string
  country_code: string
  type: string
  works_count: number
  cited_by_count: number
  homepage_url?: string
}

export async function searchOpenAlexAuthors(params: {
  name?: string
  institutions?: string
  country?: string
  per_page?: number
}) {
  const { data } = await api.get('/openalex/authors/search', { params })
  return data as {
    success: boolean
    count: number
    authors: OpenAlexAuthor[]
    message: string
  }
}

export async function findPhdCandidates(params: {
  institutions: string
  research_areas?: string
  country?: string
  min_works?: number
  max_works?: number
  recent_years?: number
}) {
  const { data } = await api.get('/openalex/authors/phd-candidates', { params })
  return data as {
    success: boolean
    count: number
    candidates: OpenAlexAuthor[]
    query_parameters: any
    message: string
  }
}

export async function getAuthorCollaboration(authorId: string, limit = 50) {
  const { data } = await api.get(`/openalex/authors/${authorId}/collaboration`, { params: { limit } })
  return data as {
    success: boolean
    author_id: string
    collaboration_network: {
      total_collaborators: number
      frequent_collaborators: Array<{
        id: string
        name: string
        collaboration_count: number
        total_citations: number
        recent_collaborations: Array<{
          title: string
          year: number
          citations: number
        }>
      }>
      total_papers_analyzed: number
    }
    message: string
  }
}

export async function searchOpenAlexPapers(params: {
  title?: string
  author_name?: string
  institutions?: string
  concepts?: string
  publication_year_start?: number
  publication_year_end?: number
  is_oa?: boolean
  min_citations?: number
  sort_by?: string
  per_page?: number
}) {
  const { data } = await api.get('/openalex/papers/search', { params })
  return data as {
    success: boolean
    count: number
    papers: OpenAlexPaper[]
    query_parameters: any
    message: string
  }
}

export async function getTrendingPapers(params: {
  research_areas?: string
  time_period?: number
  min_citations?: number
  per_page?: number
}) {
  const { data } = await api.get('/openalex/papers/trending', { params })
  return data as {
    success: boolean
    count: number
    trending_papers: OpenAlexPaper[]
    query_parameters: any
    message: string
  }
}

export async function searchOpenAlexInstitutions(params: {
  query: string
  country?: string
  institution_type?: string
  per_page?: number
}) {
  const { data } = await api.get('/openalex/institutions/search', { params })
  return data as {
    success: boolean
    count: number
    institutions: OpenAlexInstitution[]
    message: string
  }
}

export async function getInstitutionProfile(params: {
  name: string
  years_back?: number
}) {
  const { data } = await api.get('/openalex/institutions/profile', { params })
  return data as {
    success: boolean
    institution_profile: {
      institution: {
        id: string
        name: string
        country: string
        type: string
        works_count: number
        cited_by_count: number
      }
      analysis_period: string
      total_papers: number
      total_citations: number
      average_citations: number
      open_access_ratio: number
      papers_per_year: Record<string, number>
      top_research_areas: Array<[string, number]>
    }
    message: string
  }
}

export async function searchOpenAlexConcepts(params: {
  query: string
  level?: number
  per_page?: number
}) {
  const { data } = await api.get('/openalex/concepts/search', { params })
  return data as {
    success: boolean
    count: number
    concepts: Array<{
      id: string
      display_name: string
      description: string
      level: number
      works_count: number
      cited_by_count: number
      subfield: any
      field: any
      domain: any
    }>
    message: string
  }
}

// Session Management APIs
export async function listSessions() {
  const { data } = await api.get('/data/sessions')
  return data as {
    status: string
    sessions: Array<{
      session_id: string
      status: string
      total_papers: number
      completed_papers: number
      failed_papers: number
      pending_papers: number
      total_inserted: number
      total_skipped: number
      created_at: string
      updated_at: string | null
      error_message: string | null
    }>
  }
}

export async function getSessionDetails(sessionId: string) {
  const { data } = await api.get(`/data/sessions/${sessionId}`)
  return data as {
    status: string
    session: {
      session_id: string
      status: string
      total_papers: number
      total_inserted: number
      total_skipped: number
      created_at: string
      updated_at: string | null
      error_message: string | null
      papers: Record<string, {
        status: string
        error_message: string | null
        processing_time: number | null
        created_at: string
        updated_at: string | null
      }>
    }
  }
}

export async function resumeSession(sessionId: string) {
  const { data } = await api.post('/data/fetch-arxiv-by-id', null, {
    params: {
      ids: '',
      resume_session_id: sessionId
    }
  })
  return data as {
    status: string
    session_id: string
    inserted: number
    skipped: number
    fetched: number
    message?: string
    resume_endpoint?: string
  }
}

export async function deleteSession(sessionId: string) {
  const { data } = await api.delete(`/data/sessions/${sessionId}`)
  return data as {
    status: string
    message: string
  }
}

export async function getPendingPapers(sessionId: string) {
  const { data } = await api.get(`/data/sessions/${sessionId}/pending-papers`)
  return data as {
    status: string
    session_id: string
    pending_paper_ids: string[]
    count: number
  }
}