import { Card, List, Typography, Space, Tag, Pagination, Button, InputNumber, Select, message, Input, DatePicker, Upload, Tooltip } from 'antd'
import { UploadOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { getLatestPapers, triggerFetch, triggerFetchById } from '../api'
import dayjs from 'dayjs'
import PaperSearch from './PaperSearch'

export default function LatestPapers() {
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(10)
  const [total, setTotal] = useState(0)
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  // Search states
  const [titleSearch, setTitleSearch] = useState('')
  const [arxivSearch, setArxivSearch] = useState('')
  const [isSearching, setIsSearching] = useState(false)

  const [categories, setCategories] = useState<string | undefined>('cs.AI,cs.CV')
  const [maxResults, setMaxResults] = useState<number | undefined>(50)
  const [fetching, setFetching] = useState(false)

  const [ids, setIds] = useState('')
  const [fetchingById, setFetchingById] = useState(false)
  const [fetchingByJson, setFetchingByJson] = useState(false)

  const [dateRange, setDateRange] = useState<[string, string]>(() => {
    const today = dayjs().format('YYYY-MM-DD')
    const yest = dayjs().subtract(1, 'day').format('YYYY-MM-DD')
    return [yest, today]
  })

  async function load() {
    setLoading(true)
    try {
      const data = await getLatestPapers(page, limit, titleSearch, arxivSearch)
      setItems(data.items || [])
      setTotal(data.total || 0)
    } catch (e: any) {
      message.error(e?.message || 'Load latest papers failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [page, limit, titleSearch, arxivSearch])

  // Handle search functionality
  const handleSearch = (searchType: 'title' | 'arxiv', searchTerm: string) => {
    if (searchType === 'title') {
      setTitleSearch(searchTerm)
      setArxivSearch('')
    } else {
      setArxivSearch(searchTerm)  
      setTitleSearch('')
    }
    setPage(1) // Reset to first page when searching
    setIsSearching(true)
  }

  const handleClearSearch = () => {
    setTitleSearch('')
    setArxivSearch('')
    setPage(1)
    setIsSearching(false)
  }

  // Get display title for card header
  const getCardTitle = () => {
    if (titleSearch) {
      return `Papers matching "${titleSearch}" (${total} results)`
    }
    if (arxivSearch) {
      return `Papers matching arXiv "${arxivSearch}" (${total} results)`
    }
    return `Latest Papers (${total} total)`
  }

  async function onTrigger() {
    setFetching(true)
    try {
      const [start, end] = dateRange
      const res = await triggerFetch({
        categories,
        max_results: maxResults,
        start_date: start,
        end_date: end,
      })
      message.success(`Fetched=${res.fetched}, Inserted=${res.inserted}, Skipped=${res.skipped}`)
      setPage(1)
      // Clear search when refreshing data
      handleClearSearch()
      await load()
    } catch (e: any) {
      message.error(e?.message || 'Trigger failed')
    } finally {
      setFetching(false)
    }
  }

  async function onTriggerById() {
    const trimmed = ids.trim()
    if (!trimmed) {
      message.warning('Please input arXiv ID(s), comma-separated')
      return
    }
    setFetchingById(true)
    try {
      const res = await triggerFetchById({ ids: trimmed })
      message.success(`Fetched=${res.fetched}, Inserted=${res.inserted}, Skipped=${res.skipped}`)
      setIds('')
      setPage(1)
      // Clear search when refreshing data
      handleClearSearch()
      await load()
    } catch (e: any) {
      message.error(e?.message || 'Trigger by ID failed')
    } finally {
      setFetchingById(false)
    }
  }

  async function onTriggerByJson(file: File) {
    setFetchingByJson(true)
    try {
      const text = await file.text()
      const jsonData = JSON.parse(text)
      
      if (!Array.isArray(jsonData)) {
        message.error('JSON file must contain an array of papers')
        return
      }
      
      const arxivIds = jsonData.map((paper: any) => {
        if (!paper.id) {
          throw new Error('Each paper must have an "id" field')
        }
        return paper.id
      }).join(',')
      
      if (!arxivIds) {
        message.warning('No valid arXiv IDs found in the JSON file')
        return
      }
      
      const res = await triggerFetchById({ ids: arxivIds })
      message.success(`Fetched=${res.fetched}, Inserted=${res.inserted}, Skipped=${res.skipped}`)
      setPage(1)
      // Clear search when refreshing data
      handleClearSearch()
      await load()
    } catch (e: any) {
      message.error(e?.message || 'Failed to process JSON file')
    } finally {
      setFetchingByJson(false)
    }
  }

  const disabledEndDate = (current: any) => {
    const today = dayjs().endOf('day')
    return current && current > today
  }

  return (
    <Card
      title={getCardTitle()}
      extra={
        <Space direction="vertical" size="middle">
          <Space wrap>
            <Typography.Text type="secondary">Date Range</Typography.Text>
            <DatePicker.RangePicker
              disabledDate={disabledEndDate}
              value={[dayjs(dateRange[0]), dayjs(dateRange[1])]}
              onChange={(vals) => {
                const start = vals?.[0]?.format('YYYY-MM-DD') || dateRange[0]
                const end = vals?.[1]?.format('YYYY-MM-DD') || dateRange[1]
                setDateRange([start, end])
              }}
            />
            <Typography.Text type="secondary">Categories</Typography.Text>
            <Select
              style={{ width: 200 }}
              value={categories}
              onChange={setCategories}
              options={[
                { label: 'AI + CV', value: 'cs.AI,cs.CV' },
                { label: 'ALL', value: 'all' },
                { label: 'AI only', value: 'cs.AI' },
                { label: 'CV only', value: 'cs.CV' },
                { label: 'ML (cs.LG)', value: 'cs.LG' },
                { label: 'NLP (cs.CL)', value: 'cs.CL' },
                { label: 'IR (cs.IR)', value: 'cs.IR' },
                { label: 'HCI (cs.HC)', value: 'cs.HC' },
                { label: 'Robotics (cs.RO)', value: 'cs.RO' },
                { label: 'Security (cs.CR)', value: 'cs.CR' },
                { label: 'Databases (cs.DB)', value: 'cs.DB' },
                { label: 'Data Structures/Algorithms (cs.DS)', value: 'cs.DS' },
                { label: 'Graphics (cs.GR)', value: 'cs.GR' },
                { label: 'Distributed/Cluster (cs.DC)', value: 'cs.DC' },
                { label: 'Operating Systems (cs.OS)', value: 'cs.OS' },
                { label: 'Networking (cs.NI)', value: 'cs.NI' },
                { label: 'Theory/Complexity (cs.CC)', value: 'cs.CC' },
                { label: 'Logic (cs.LO)', value: 'cs.LO' },
                { label: 'Computational Geometry (cs.CG)', value: 'cs.CG' },
                // useful combined presets
                { label: 'AI + ML + NLP + CV', value: 'cs.AI,cs.LG,cs.CL,cs.CV' },
              ]}
            />
            <Typography.Text type="secondary">Max</Typography.Text>
            <InputNumber min={10} max={200} step={10} value={maxResults} onChange={(v) => setMaxResults(Number(v))} />
            <Button type="primary" loading={fetching} onClick={onTrigger}>Fetch & Refresh</Button>
            <Typography.Text type="secondary">arXiv ID(s)</Typography.Text>
            <Input placeholder="e.g. 2504.14636,2504.14645" value={ids} onChange={(e) => setIds(e.target.value)} style={{ width: 240 }} />
            <Button loading={fetchingById} onClick={onTriggerById}>Fetch by ID</Button>
          </Space>
          <Space wrap>
             <Upload
               accept=".json"
               showUploadList={false}
               beforeUpload={(file) => {
                 onTriggerByJson(file)
                 return false // Prevent default upload
               }}
             >
               <Button loading={fetchingByJson} icon={<UploadOutlined />}>Upload JSON</Button>
             </Upload>
             <Tooltip
               title={
                 <div>
                   <div>JSON format example:</div>
                   <pre style={{ margin: '8px 0', fontSize: '12px' }}>
{`[
  {
    "id": "2504.12526v1",
    "title": "MOM: Memory-Efficient Offloaded Mini-Sequence Inference for Long Context Language Models"
  },
  {
    "id": "2504.14775v2",
    "title": "gLLM: Global Balanced Pipeline Parallelism System for Distributed LLM Serving with Token Throttling"
  }
]`}
                   </pre>
                 </div>
               }
               placement="bottom"
             >
               <InfoCircleOutlined style={{ color: '#1890ff', cursor: 'help' }} />
             </Tooltip>
           </Space>
        </Space>
      }
      style={{ background: '#ffffff', borderRadius: 12 }}
      bodyStyle={{ padding: 16 }}
    >
      {/* Search Component */}
      <PaperSearch
        onSearch={handleSearch}
        onClear={handleClearSearch}
        loading={loading}
      />

      <List
        loading={loading}
        dataSource={items}
        renderItem={(p) => (
          <List.Item>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Typography.Title level={5} style={{ margin: 0 }}>
                <a href={`https://arxiv.org/abs/${p.arxiv_entry}`} target="_blank" rel="noreferrer">{p.paper_title}</a>
              </Typography.Title>
              <Space wrap>
                {(p.categories || []).map((c: string, idx: number) => <Tag key={idx} color="geekblue">{c}</Tag>)}
              </Space>
              <Typography.Text type="secondary">
                {p.published || ''}
              </Typography.Text>
              <Space wrap>
                {(p.authors || []).map((a: any) => <Tag key={a.id} color="cyan">{a.name}</Tag>)}
              </Space>
            </Space>
          </List.Item>
        )}
        locale={{
          emptyText: isSearching ? 'No papers found matching your search criteria' : 'No papers available'
        }}
      />
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
        <Pagination current={page} pageSize={limit} total={total} onChange={(cp, ps) => { setPage(cp); setLimit(ps) }} showSizeChanger />
      </div>
    </Card>
  )
}