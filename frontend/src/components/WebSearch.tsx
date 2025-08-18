import { useState } from 'react'
import { Card, Input, Button, Space, Typography, Alert, Spin, Collapse, Tag, Divider } from 'antd'
import { SearchOutlined, UserOutlined, BankOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { webSearchPerson, searchPersonRole } from '../api'

const { Text, Title, Paragraph, Link } = Typography
const { Panel } = Collapse
const { TextArea } = Input

export default function WebSearchComponent() {
  const [name, setName] = useState('')
  const [affiliation, setAffiliation] = useState('')
  const [searchPrompt, setSearchPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [roleLoading, setRoleLoading] = useState(false)
  const [searchResult, setSearchResult] = useState<any>(null)
  const [roleResult, setRoleResult] = useState<any>(null)
  const [activeSearch, setActiveSearch] = useState<'general' | 'role' | null>(null)

  const handleGeneralSearch = async () => {
    if (!name.trim() || !affiliation.trim() || !searchPrompt.trim()) {
      return
    }

    setLoading(true)
    setActiveSearch('general')
    try {
      const result = await webSearchPerson(name.trim(), affiliation.trim(), searchPrompt.trim())
      setSearchResult(result)
    } catch (error) {
      console.error('Search failed:', error)
      setSearchResult({
        success: false,
        error: 'Search request failed',
        name: name.trim(),
        affiliation: affiliation.trim(),
        search_prompt: searchPrompt.trim()
      })
    } finally {
      setLoading(false)
    }
  }

  const handleRoleSearch = async () => {
    if (!name.trim() || !affiliation.trim()) {
      return
    }

    setRoleLoading(true)
    setActiveSearch('role')
    try {
      const result = await searchPersonRole(name.trim(), affiliation.trim())
      setRoleResult(result)
    } catch (error) {
      console.error('Role search failed:', error)
      setRoleResult({
        success: false,
        error: 'Role search request failed',
        name: name.trim(),
        affiliation: affiliation.trim()
      })
    } finally {
      setRoleLoading(false)
    }
  }

  const clearResults = () => {
    setSearchResult(null)
    setRoleResult(null)
    setActiveSearch(null)
  }

  const renderSearchResults = (results: any[], title: string) => {
    if (!results || results.length === 0) return null

    return (
      <div style={{ marginTop: 16 }}>
        <Title level={5}>{title}</Title>
        <Collapse ghost>
          {results.map((result, index) => (
            <Panel
              header={
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Link href={result.url} target="_blank" rel="noopener noreferrer">
                    <Text strong>{result.title}</Text>
                  </Link>
                  <Text type="secondary" style={{ fontSize: '12px' }}>
                    {result.url}
                  </Text>
                </Space>
              }
              key={index}
            >
              <Paragraph style={{ margin: 0, fontSize: '14px', lineHeight: '1.6' }}>
                {result.content}
              </Paragraph>
              {result.score && (
                <Tag color="blue" style={{ marginTop: 8 }}>
                  Score: {result.score.toFixed(2)}
                </Tag>
              )}
            </Panel>
          ))}
        </Collapse>
      </div>
    )
  }

  return (
    <Card
      title={
        <Space>
          <SearchOutlined />
          <span>Web Search Tool</span>
        </Space>
      }
      style={{ background: '#ffffff', borderRadius: 12 }}
      bodyStyle={{ padding: 24 }}
    >
      {/* Search Form */}
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space wrap style={{ width: '100%' }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <Text type="secondary">
              <UserOutlined /> Person Name
            </Text>
            <Input
              placeholder="Enter person's full name..."
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ marginTop: 4 }}
            />
          </div>
          
          <div style={{ flex: 1, minWidth: 200 }}>
            <Text type="secondary">
              <BankOutlined /> Institution/Organization
            </Text>
            <Input
              placeholder="Enter institution name..."
              value={affiliation}
              onChange={(e) => setAffiliation(e.target.value)}
              style={{ marginTop: 4 }}
            />
          </div>
        </Space>

        <div style={{ width: '100%' }}>
          <Text type="secondary">
            <QuestionCircleOutlined /> Search Prompt (for general search)
          </Text>
          <TextArea
            placeholder="What would you like to know? e.g., 'What research does', 'Tell me about the publications of', etc."
            value={searchPrompt}
            onChange={(e) => setSearchPrompt(e.target.value)}
            rows={2}
            style={{ marginTop: 4 }}
          />
        </div>

        <Space wrap>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={loading}
            onClick={handleGeneralSearch}
            disabled={!name.trim() || !affiliation.trim() || !searchPrompt.trim()}
          >
            General Search
          </Button>
          
          <Button
            icon={<UserOutlined />}
            loading={roleLoading}
            onClick={handleRoleSearch}
            disabled={!name.trim() || !affiliation.trim()}
          >
            Find Role/Position
          </Button>

          <Button onClick={clearResults} disabled={!searchResult && !roleResult}>
            Clear Results
          </Button>
        </Space>
      </Space>

      <Divider />

      {/* Results Section */}
      {(searchResult || roleResult) && (
        <div style={{ marginTop: 24 }}>
          <Title level={4}>Search Results</Title>
          
          {/* General Search Results */}
          {activeSearch === 'general' && searchResult && (
            <div>
              {searchResult.success ? (
                <div>
                  <Alert
                    type="success"
                    message={`Search completed for "${searchResult.name}" at "${searchResult.affiliation}"`}
                    style={{ marginBottom: 16 }}
                  />
                  
                  <Text strong>Query: </Text>
                  <Text code>{searchResult.query}</Text>
                  
                  {searchResult.answer && (
                    <div style={{ marginTop: 16 }}>
                      <Title level={5}>AI Summary</Title>
                      <Card size="small" style={{ background: '#f8f9fa' }}>
                        <Paragraph style={{ margin: 0 }}>{searchResult.answer}</Paragraph>
                      </Card>
                    </div>
                  )}
                  
                  {renderSearchResults(searchResult.results, 'Search Sources')}
                </div>
              ) : (
                <Alert
                  type="error"
                  message="Search Failed"
                  description={searchResult.error || searchResult.message}
                />
              )}
            </div>
          )}

          {/* Role Search Results */}
          {activeSearch === 'role' && roleResult && (
            <div>
              {roleResult.success ? (
                <div>
                  <Alert
                    type="success"
                    message={`Role search completed for "${roleResult.name}" at "${roleResult.affiliation}"`}
                    style={{ marginBottom: 16 }}
                  />
                  
                  <Text strong>Query: </Text>
                  <Text code>{roleResult.query}</Text>
                  
                  {roleResult.extracted_role && (
                    <div style={{ marginTop: 16 }}>
                      <Title level={5}>Extracted Role</Title>
                      <Tag color="green" style={{ fontSize: '14px', padding: '4px 12px' }}>
                        {roleResult.extracted_role}
                      </Tag>
                    </div>
                  )}
                  
                  {roleResult.answer && (
                    <div style={{ marginTop: 16 }}>
                      <Title level={5}>AI Summary</Title>
                      <Card size="small" style={{ background: '#f8f9fa' }}>
                        <Paragraph style={{ margin: 0 }}>{roleResult.answer}</Paragraph>
                      </Card>
                    </div>
                  )}
                  
                  {renderSearchResults(roleResult.results, 'Search Sources')}
                </div>
              ) : (
                <Alert
                  type="error"
                  message="Role Search Failed"
                  description={roleResult.error || roleResult.message}
                />
              )}
            </div>
          )}
        </div>
      )}

      {(loading || roleLoading) && (
        <div style={{ textAlign: 'center', marginTop: 24 }}>
          <Spin size="large" />
          <div style={{ marginTop: 16 }}>
            <Text type="secondary">
              {loading ? 'Searching the web for information...' : 'Extracting role information...'}
            </Text>
          </div>
        </div>
      )}
    </Card>
  )
}
