import { useEffect, useRef } from 'react'
import { useStoredState } from './useStoredState.ts'

export const THEMES = ['system', 'light', 'dark'] as const
export type Theme = (typeof THEMES)[number]

/** Light, dark or follow the OS; applied as `data-theme` on <html>. */
export function useTheme() {
  const [theme, setTheme] = useStoredState<Theme>('cv-theme', THEMES, 'system')
  const first = useRef(true)

  useEffect(() => {
    const root = document.documentElement
    // Cross-fade colours on a user-initiated switch, but not on the first paint.
    let timer: number | undefined
    if (!first.current) {
      root.classList.add('theme-switching')
      timer = window.setTimeout(() => root.classList.remove('theme-switching'), 320)
    }
    first.current = false
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    return () => {
      if (timer) window.clearTimeout(timer)
      root.classList.remove('theme-switching')
    }
  }, [theme])

  return [theme, setTheme] as const
}
