import { Card, Input, List, Tag, Typography, Space, message } from 'antd'
import { useState } from 'react'
import { searchAuthor } from '../api'

export default function AuthorSearch() {
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<any[]>([])

  async function onSearch(v: string) {
    if (!v?.trim()) return
    setLoading(true)
    try {
      const data = await searchAuthor(v.trim())
      setItems(data.results || [])
    } catch (e: any) {
      message.error(e?.message || 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card title="Author Search" extra={<Typography.Text type="secondary">Case-insensitive fuzzy</Typography.Text>}>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Input.Search placeholder="Type an author name..." enterButton loading={loading} onSearch={onSearch} />
        <List
          loading={loading}
          dataSource={items}
          renderItem={(it) => (
            <List.Item>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Typography.Title level={5} style={{ margin: 0 }}>{it.author?.name}</Typography.Title>
                <Space wrap>
                  {(it.affiliations || []).map((a: any) => <Tag key={a.id}>{a.aff_name}</Tag>)}
                </Space>
                <Typography.Text strong>Recent papers</Typography.Text>
                <ul style={{ paddingLeft: 18, margin: 0 }}>
                  {(it.recent_papers || []).map((p: any) => (
                    <li key={p.id}>
                      <a href={`https://arxiv.org/abs/${p.arxiv_entry}`} target="_blank" rel="noreferrer">{p.paper_title}</a>
                      {p.published ? <Typography.Text type="secondary"> — {p.published}</Typography.Text> : null}
                    </li>
                  ))}
                </ul>
                <Typography.Text strong>Top collaborators</Typography.Text>
                <Space wrap>
                  {(it.top_collaborators || []).map((c: any) => <Tag key={c.id}>{c.name} ×{c.count}</Tag>)}
                </Space>
              </Space>
            </List.Item>
          )}
        />
      </Space>
    </Card>
  )
} 