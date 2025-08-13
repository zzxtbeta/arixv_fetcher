import { Card, Input, List, Tag, Typography, Space, message } from 'antd'
import { useState } from 'react'
import { searchAuthor } from '../api'
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
import { CalendarOutlined } from '@ant-design/icons'

export default function AuthorSearch() {
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<any[]>([])

  function parseRankValue(v?: string): number | null {
    if (!v) return null
    const m = String(v).match(/\d+/)
    return m ? Number(m[0]) : null
  }

  function formatDate(d?: string | null): string {
    if (!d) return ''
    const s = String(d)
    if (s.length >= 7) return s.slice(0, 7)
    if (s.length >= 4) return s.slice(0, 4)
    return s
  }

  function formatRange(start?: string | null, end?: string | null): string {
    const sd = formatDate(start) || '?'
    const ed = formatDate(end) || 'present'
    return `${sd} — ${ed}`
  }

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
                <Space align="center" wrap>
                  <Typography.Title level={5} style={{ margin: 0 }}>{it.author?.name}</Typography.Title>
                  {it.author?.orcid ? (
                    <Tag color="success">
                      <a href={`https://orcid.org/${it.author.orcid}`} target="_blank" rel="noreferrer">
                        ORCID: {it.author.orcid}
                      </a>
                    </Tag>
                  ) : null}
                </Space>
                <Space wrap>
                  {(it.affiliations || []).map((a: any) => {
                    const y25n = parseRankValue(a?.qs?.y2025)
                    const y24n = parseRankValue(a?.qs?.y2024)
                    let arrow: any = null
                    if (y25n !== null && y24n !== null && y25n !== y24n) {
                      if (y25n < y24n) {
                        arrow = <ArrowUpOutlined style={{ color: '#cf1322' }} />
                      } else if (y25n > y24n) {
                        arrow = <ArrowDownOutlined style={{ color: '#52c41a' }} />
                      }
                    }
                    return (
                      <Card key={a.id} size="small" style={{ borderRadius: 8 }}>
                        <Space direction="vertical" size={4}>
                          <Typography.Text strong>{a.aff_name}</Typography.Text>
                          {/* line 1: role */}
                          {a.role ? (
                            <Space wrap size={6}>
                              <Tag color="magenta">{a.role}</Tag>
                            </Space>
                          ) : null}
                          {/* line 2: dates (range + latest) */}
                          {(a.start_date || a.end_date || a.latest_time) ? (
                            <Space wrap size={6}>
                              {(a.start_date || a.end_date) ? (
                                <Tag icon={<CalendarOutlined />}>{formatRange(a.start_date, a.end_date)}</Tag>
                              ) : null}
                              {a.latest_time ? <Tag>latest: {formatDate(a.latest_time)}</Tag> : null}
                            </Space>
                          ) : null}
                          {/* line 3: QS ranks with trend arrow placed before qs25 */}
                          {a?.qs?.y2025 || a?.qs?.y2024 ? (
                            <Space size={6} align="center">
                              {arrow}
                              <Tag color="geekblue">qs25: {a.qs?.y2025}</Tag>
                              <Tag>qs24: {a.qs?.y2024}</Tag>
                            </Space>
                          ) : null}
                        </Space>
                      </Card>
                    )
                  })}
                </Space>
                <Typography.Text strong>Recent papers</Typography.Text>
                <ul style={{ paddingLeft: 18, margin: 0 }}>
                  {(it.recent_papers || []).map((p: any) => (
                    <li key={p.id}>
                      <a href={`https://arxiv.org/abs/${p.arxiv_entry}`} target="_blank" rel="noreferrer">{p.paper_title}</a>
                      {p.published ? <Typography.Text type="secondary"> — {formatDate(p.published)}</Typography.Text> : null}
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