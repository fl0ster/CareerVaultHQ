import { useEffect, useState } from 'react'
import { type Application, type OfferComparison, type OfferHints, applicationsApi } from '../applications/api.ts'
import { describeError } from '../cv/api.ts'

export type OfferComparisonState = {
  /** Hints per application id, from the latest comparison. */
  byId: Map<number, OfferHints>
  topPickId: number | null
  topPickReason: string | null
  /** A comparison of the offers on screen is being fetched or generated. */
  loading: boolean
  error: string | null
  /** Makes a new comparison even though the offers did not change. */
  refresh: () => void
}

type Loaded = { key: string; comparison: OfferComparison | null; error: string | null }

/** The LLM's comparison of the offers on the page. Asked for again whenever an offer is
 * added, removed or edited; the server answers from its stored comparison while nothing it
 * was made from changed, so reopening the page is cheap. */
export function useOfferComparison(offers: Application[] | null): OfferComparisonState {
  const key = (offers ?? [])
    .map((a) => `${a.id}:${a.updated_at}`)
    .sort()
    .join(',')
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    if (!key) return
    const controller = new AbortController()
    applicationsApi
      .compareOffers(false, controller.signal)
      .then((comparison) => setLoaded({ key, comparison, error: null }))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setLoaded({ key, comparison: null, error: describeError(e) })
      })
    return () => controller.abort()
  }, [key])

  const refresh = () => {
    setRefreshing(true)
    applicationsApi
      .compareOffers(true)
      .then((comparison) => setLoaded({ key, comparison, error: null }))
      .catch((e: unknown) => setLoaded((prev) => ({ key, comparison: prev?.comparison ?? null, error: describeError(e) })))
      .finally(() => setRefreshing(false))
  }

  const comparison = loaded?.comparison ?? null
  return {
    byId: new Map((comparison?.offers ?? []).map((o) => [o.application_id, o])),
    topPickId: comparison?.top_pick_id ?? null,
    topPickReason: comparison?.top_pick_reason ?? null,
    loading: refreshing || (key !== '' && loaded?.key !== key),
    error: loaded?.key === key ? loaded.error : null,
    refresh,
  }
}
