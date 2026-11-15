import { useEffect, useState } from 'react'
import { listCompanies, type Company } from './api.ts'
import CompanyDialog from './CompanyDialog.tsx'
import './companies.css'

const PAGE_SIZE = 50
const SEARCH_DEBOUNCE_MS = 300

/** What the list should show: the search text and a counter bumped by Refresh. */
type Request = { q: string; n: number }

export default function CompaniesPage() {
  const [query, setQuery] = useState('')
  const [request, setRequest] = useState<Request>({ q: '', n: 0 })
  // ``n`` of the request whose first page was last received; differs while loading.
  const [loadedFor, setLoadedFor] = useState(-1)
  const [companies, setCompanies] = useState<Company[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(null)

  const search = request.q
  const loading = loadedFor !== request.n || loadingMore

  useEffect(() => {
    const handle = setTimeout(() => {
      const q = query.trim()
      setRequest((prev) => (prev.q === q ? prev : { q, n: prev.n + 1 }))
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [query])

  const refresh = () => setRequest((prev) => ({ ...prev, n: prev.n + 1 }))

  // First page for the current request; a newer request aborts the previous fetch.
  useEffect(() => {
    const controller = new AbortController()
    listCompanies({ offset: 0, limit: PAGE_SIZE, q: request.q }, controller.signal)
      .then((page) => {
        setCompanies(page.items)
        setTotal(page.total)
        setHasMore(page.has_more)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load companies: ${String(e)}`)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedFor(request.n)
      })
    return () => controller.abort()
  }, [request])

  const loadMore = async () => {
    if (loading || !hasMore) return
    setLoadingMore(true)
    try {
      const page = await listCompanies({ offset: companies.length, limit: PAGE_SIZE, q: search })
      setCompanies((prev) => [...prev, ...page.items])
      setTotal(page.total)
      setHasMore(page.has_more)
      setError(null)
    } catch (e) {
      setError(`Could not load companies: ${String(e)}`)
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <>
      <h1 className="title">Companies</h1>
      <p>
        {total === null ? 'Loading…' : `${companies.length} of ${total} companies.`}{' '}
        <button type="button" className="secondary small" onClick={refresh} disabled={loading}>
          Refresh
        </button>
      </p>

      <input
        type="search"
        className="company-search"
        placeholder="Search by name or alias…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search companies"
      />

      {error && <p className="error">{error}</p>}

      {total === 0 ? (
        <p>{search ? 'No companies match your search.' : 'No companies yet. Parsed jobs fill this list.'}</p>
      ) : (
        <ul className="company-list">
          {companies.map((company) => (
            <li key={company.id}>
              <button type="button" className="company-row" onClick={() => setSelected(company.id)}>
                <span className="company-name">{company.name}</span>
                <span className="company-jobs-count">
                  {company.job_count} {company.job_count === 1 ? 'job' : 'jobs'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="sentinel">
        {loading && <span className="spinner" aria-hidden="true" />}
        {!loading && hasMore && (
          <button type="button" className="secondary small" onClick={loadMore}>
            Load more
          </button>
        )}
        {!loading && !hasMore && companies.length > 0 && (
          <span className="muted">All companies loaded.</span>
        )}
      </div>

      {selected !== null && (
        <CompanyDialog key={selected} companyId={selected} onClose={() => setSelected(null)} />
      )}
    </>
  )
}
