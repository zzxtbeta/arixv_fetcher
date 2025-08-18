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