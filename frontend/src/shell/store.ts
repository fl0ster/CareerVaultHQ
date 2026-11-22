import { useSyncExternalStore } from 'react'

/**
 * A value kept outside React at module level. Only the page on screen is mounted, so state
 * that has to outlive a page (a running job, manually added jobs still being processed)
 * lives here, and the page picks it up again when it is entered.
 */
export type Store<T> = {
  get: () => T
  set: (next: T | ((prev: T) => T)) => void
  subscribe: (listener: () => void) => () => void
}

export function createStore<T>(initial: T): Store<T> {
  let value = initial
  const listeners = new Set<() => void>()
  return {
    get: () => value,
    set: (next) => {
      value = typeof next === 'function' ? (next as (prev: T) => T)(value) : next
      listeners.forEach((l) => l())
    },
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}

/** The store's current value; re-renders when it changes. */
export function useStore<T>(store: Store<T>): T {
  return useSyncExternalStore(store.subscribe, store.get)
}
