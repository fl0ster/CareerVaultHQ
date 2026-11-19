import { useEffect, useState } from 'react'

function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = window.localStorage.getItem(key)
    return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
  } catch {
    return fallback
  }
}

/** A small string preference remembered in localStorage (silently in-memory when storage is blocked). */
export function useStoredState<T extends string>(key: string, allowed: readonly T[], fallback: T) {
  const [value, setValue] = useState<T>(() => read(key, allowed, fallback))

  useEffect(() => {
    try {
      window.localStorage.setItem(key, value)
    } catch {
      // Storage unavailable (private mode, blocked site data): keep the in-memory value.
    }
  }, [key, value])

  return [value, setValue] as const
}
