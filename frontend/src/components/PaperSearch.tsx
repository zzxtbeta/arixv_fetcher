import { Input, Button, Space, Select, Form } from 'antd'
import { SearchOutlined, ClearOutlined } from '@ant-design/icons'
import { useState } from 'react'
import styles from './PaperSearch.module.css'

interface PaperSearchProps {
  onSearch: (searchType: 'title' | 'arxiv', searchTerm: string) => void
  onClear: () => void
  loading?: boolean
}

export default function PaperSearch({ onSearch, onClear, loading = false }: PaperSearchProps) {
  const [searchType, setSearchType] = useState<'title' | 'arxiv'>('title')
  const [searchTerm, setSearchTerm] = useState('')

  const handleSearch = () => {
    const trimmed = searchTerm.trim()
    if (trimmed) {
      onSearch(searchType, trimmed)
    }
  }

  const handleClear = () => {
    setSearchTerm('')
    onClear()
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  return (
    <div className={styles.searchContainer}>
      <Space.Compact style={{ width: '100%', maxWidth: 600 }}>
        <Select
          value={searchType}
          onChange={setSearchType}
          style={{ width: 120 }}
          options={[
            { label: 'Paper Title', value: 'title' },
            { label: 'arXiv ID', value: 'arxiv' }
          ]}
        />
        <Input
          placeholder={searchType === 'title' ? 'Search by paper title...' : 'Search by arXiv ID...'}
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          onKeyPress={handleKeyPress}
          allowClear
        />
        <Button 
          type="primary" 
          icon={<SearchOutlined />}
          loading={loading}
          onClick={handleSearch}
          disabled={!searchTerm.trim()}
        >
          Search
        </Button>
        <Button 
          icon={<ClearOutlined />}
          onClick={handleClear}
          disabled={loading}
        >
          Clear
        </Button>
      </Space.Compact>
    </div>
  )
}
