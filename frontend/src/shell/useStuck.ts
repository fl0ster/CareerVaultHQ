import { type RefObject, useEffect, useState } from 'react'

/** Whether a `position: sticky` element is currently stuck at its `top` offset. */
export function useStuck(ref: RefObject<HTMLElement | null>, enabled: boolean): boolean {
  const [stuck, setStuck] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || !enabled) return
    const check = () => {
      const top = parseFloat(getComputedStyle(el).top) || 0
      setStuck(el.getBoundingClientRect().top <= top + 0.5 && window.scrollY > 0)
    }
    check()
    window.addEventListener('scroll', check, { passive: true })
    window.addEventListener('resize', check)
    return () => {
      window.removeEventListener('scroll', check)
      window.removeEventListener('resize', check)
    }
  }, [ref, enabled])
  return stuck
}
