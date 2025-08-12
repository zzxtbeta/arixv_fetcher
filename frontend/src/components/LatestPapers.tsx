import { Card, List, Typography, Space, Tag, Pagination, Button, InputNumber, Select, message, Input } from 'antd'
import { useEffect, useState } from 'react'
import { getLatestPapers, triggerFetch } from '../api'

export default function LatestPapers() {
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(10)
  const [total, setTotal] = useState(0)
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const [threadId, setThreadId] = useState('dashboard')
  const [days, setDays] = useState(1)
  const [categories, setCategories] = useState<string | undefined>('cs.AI,cs.CV')
  const [maxResults, setMaxResults] = useState<number | undefined>(50)
  const [fetching, setFetching] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const data = await getLatestPapers(page, limit)
      setItems(data.items || [])
      setTotal(data.total || 0)
    } catch (e: any) {
      message.error(e?.message || 'Load latest papers failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [page, limit])

  async function onTrigger() {
    setFetching(true)
    try {
      const res = await triggerFetch({ thread_id: threadId, days, categories, max_results: maxResults })
      message.success(`Fetched=${res.fetched}, Inserted=${res.inserted}, Skipped=${res.skipped}`)
      setPage(1)
      await load()
    } catch (e: any) {
      message.error(e?.message || 'Trigger failed')
    } finally {
      setFetching(false)
    }
  }

  return (
    <Card
      title="Latest Papers"
      extra={
        <Space>
          <Typography.Text type="secondary">Thread</Typography.Text>
          <Input value={threadId} onChange={(e) => setThreadId(e.target.value)} style={{ width: 140 }} />
          <Typography.Text type="secondary">Days</Typography.Text>
          <InputNumber min={1} max={14} value={days} onChange={(v) => setDays(Number(v))} />
          <Typography.Text type="secondary">Categories</Typography.Text>
          <Select
            style={{ width: 200 }}
            value={categories}
            onChange={setCategories}
            options={[
              { label: 'AI + CV', value: 'cs.AI,cs.CV' },
              { label: 'ALL', value: 'all' },
              { label: 'CV only', value: 'cs.CV' },
              { label: 'AI only', value: 'cs.AI' },
            ]}
          />
          <Typography.Text type="secondary">Max</Typography.Text>
          <InputNumber min={10} max={200} step={10} value={maxResults} onChange={(v) => setMaxResults(Number(v))} />
          <Button type="primary" loading={fetching} onClick={onTrigger}>Fetch & Refresh</Button>
        </Space>
      }
      style={{ background: '#ffffff', borderRadius: 12 }}
      bodyStyle={{ padding: 16 }}
    >
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
      />
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
        <Pagination current={page} pageSize={limit} total={total} onChange={(cp, ps) => { setPage(cp); setLimit(ps) }} showSizeChanger />
      </div>
    </Card>
  )
} 