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
      author: { id: number; name: string }
      affiliations: Array<{ id: number; aff_name: string }>
      recent_papers: Array<{ id: number; paper_title: string; published: string; pdf_source: string; arxiv_entry: string }>
      top_collaborators: Array<{ id: number; name: string; count: number }>
    }>
  }
}

export async function triggerFetch({ thread_id, days, categories, max_results }: { thread_id: string; days: number; categories?: string; max_results?: number }) {
  const params = new URLSearchParams()
  params.set('thread_id', thread_id)
  params.set('days', String(days))
  if (categories) params.set('categories', categories)
  if (max_results) params.set('max_results', String(max_results))
  const { data } = await api.post(`/data/fetch-arxiv-today?${params.toString()}`)
  return data as { status: string; inserted: number; skipped: number; fetched: number }
}

export async function getLatestPapers(page = 1, limit = 20) {
  const { data } = await api.get('/dashboard/latest-papers', { params: { page, limit } })
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