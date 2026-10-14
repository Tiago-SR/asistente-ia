import { lazy, Suspense, useEffect, useState } from 'react'
import { ToggleTema } from '@/components/ToggleTema'
import { Button } from '@/components/ui/button'
import { api, onSesionCaducada, setCsrf, type Yo } from '@/lib/api'
import { useHash } from '@/lib/hash'
import { Auditoria } from '@/pages/Auditoria'
import { Cuenta } from '@/pages/Cuenta'
import { Login } from '@/pages/Login'
import { Sistema } from '@/pages/Sistema'
import { Sistemas } from '@/pages/Sistemas'
import { Usuarios } from '@/pages/Usuarios'

// recharts pesa más que el resto del panel: solo se descarga al abrir Métricas.
const Metricas = lazy(() => import('@/pages/Metricas').then((m) => ({ default: m.Metricas })))

export default function App() {
  // undefined = comprobando la sesión; null = sin sesión
  const [yo, setYo] = useState<Yo | null | undefined>(undefined)
  const [ruta, ir] = useHash()

  const entrar = (y: Yo | null) => {
    setCsrf(y?.csrf ?? null)
    setYo(y)
  }
  useEffect(() => {
    onSesionCaducada(() => entrar(null))
    api<Yo>('GET', '/yo').then(entrar, () => entrar(null))
    return () => onSesionCaducada(null)
  }, [])

  if (yo === undefined) return null
  if (yo === null) return <Login onEntrar={entrar} />

  const salir = async () => {
    await api('POST', '/logout').catch(() => undefined)
    entrar(null)
  }
  const partes = ruta.split('/').filter(Boolean)
  return (
    <div className="mx-auto max-w-5xl p-4 grid gap-6">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="text-lg font-semibold">Asistente · Administración</h1>
        <nav className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={() => ir('/sistemas')}>Sistemas</Button>
          <Button variant="ghost" onClick={() => ir('/metricas')}>Métricas</Button>
          {yo.rol === 'admin' && <Button variant="ghost" onClick={() => ir('/usuarios')}>Usuarios</Button>}
          {yo.rol === 'admin' && <Button variant="ghost" onClick={() => ir('/auditoria')}>Auditoría</Button>}
        </nav>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => ir('/cuenta')}>
          {yo.email} · {yo.rol}
        </Button>
        <ToggleTema />
        <Button variant="outline" size="sm" onClick={salir}>Salir</Button>
      </header>
      {partes[0] === 'cuenta' ? (
        <Cuenta yo={yo} />
      ) : partes[0] === 'metricas' ? (
        <Suspense fallback={null}>
          <Metricas />
        </Suspense>
      ) : partes[0] === 'usuarios' && yo.rol === 'admin' ? (
        <Usuarios yo={yo} />
      ) : partes[0] === 'auditoria' && yo.rol === 'admin' ? (
        <Auditoria />
      ) : partes[0] === 'sistemas' && partes[1] ? (
        <Sistema key={partes[1]} id={partes[1]} yo={yo} ir={ir} />
      ) : (
        <Sistemas yo={yo} ir={ir} />
      )}
    </div>
  )
}
