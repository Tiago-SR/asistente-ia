import { useEffect, useState } from 'react'

// Enrutado por hash (#/sistemas/acme): el servidor solo sirve archivos estáticos, sin fallback de SPA.
export function useHash(): [string, (ruta: string) => void] {
  const leer = () => window.location.hash.replace(/^#/, '') || '/sistemas'
  const [ruta, setRuta] = useState(leer)
  useEffect(() => {
    const f = () => setRuta(leer())
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])
  return [ruta, (r) => (window.location.hash = r)]
}
