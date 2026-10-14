import { useSyncExternalStore } from 'react'

export type Tema = 'dark' | 'light'
const CLAVE = 'panel-tema'

function guardado(): Tema {
  try {
    return localStorage.getItem(CLAVE) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

let actual: Tema = guardado()
const oyentes = new Set<() => void>()

function aplicar(t: Tema) {
  const el = document.documentElement
  el.classList.toggle('dark', t === 'dark')
  el.style.colorScheme = t
}

/** Llamar al principio de main.tsx, antes de createRoot. */
export function iniciarTema() {
  aplicar(actual)
}

function fijar(t: Tema) {
  actual = t
  aplicar(t)
  try {
    localStorage.setItem(CLAVE, t)
  } catch {
    /* sin almacenamiento: el cambio vale solo para esta sesión */
  }
  oyentes.forEach((f) => f())
}

export function useTema() {
  const tema = useSyncExternalStore(
    (f) => {
      oyentes.add(f)
      return () => oyentes.delete(f)
    },
    () => actual,
  )
  return { tema, alternar: () => fijar(tema === 'dark' ? 'light' : 'dark') }
}
