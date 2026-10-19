import { Fragment, useEffect, useRef, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, mensaje, type EventoAuditoria } from '@/lib/api'

type Pagina = { eventos: EventoAuditoria[]; siguiente: number | null }

export function Auditoria() {
  const [eventos, setEventos] = useState<EventoAuditoria[]>([])
  const [siguiente, setSiguiente] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filtro, setFiltro] = useState({ actor: '', accion: '' })
  const [abierto, setAbierto] = useState<number | null>(null)
  const [cargando, setCargando] = useState(false)
  const pedido = useRef(0) // solo vale la última respuesta: cambiar el filtro descarta las anteriores

  async function cargar(desde: number | null, reemplazar: boolean) {
    const mio = ++pedido.current
    setError(null)
    setCargando(true)
    const q = new URLSearchParams({ limite: '50' })
    if (desde !== null) q.set('antes_id', String(desde))
    if (filtro.actor.trim()) q.set('actor', filtro.actor.trim())
    if (filtro.accion.trim()) q.set('accion', filtro.accion.trim())
    try {
      const r = await api<Pagina>('GET', `/auditoria?${q}`)
      if (mio !== pedido.current) return
      setEventos((prev) => (reemplazar ? r.eventos : [...prev, ...r.eventos]))
      setSiguiente(r.siguiente)
    } catch (e) {
      if (mio === pedido.current) setError(mensaje(e))
    } finally {
      if (mio === pedido.current) setCargando(false)
    }
  }
  useEffect(() => {
    void cargar(null, true)
  }, [])

  const filtrar = (ev: React.FormEvent) => {
    ev.preventDefault()
    void cargar(null, true)
  }

  return (
    <div className="grid gap-6">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Auditoría</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <form onSubmit={filtrar} className="flex flex-wrap items-end gap-4">
            <div className="grid gap-2">
              <Label htmlFor="a-actor">Actor (email exacto)</Label>
              <Input id="a-actor" value={filtro.actor}
                onChange={(e) => setFiltro({ ...filtro, actor: e.target.value })} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="a-accion">Acción (exacta)</Label>
              <Input id="a-accion" value={filtro.accion}
                onChange={(e) => setFiltro({ ...filtro, accion: e.target.value })} />
            </div>
            <Button type="submit" variant="outline">Filtrar</Button>
          </form>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fecha</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Acción</TableHead>
                <TableHead>Objetivo</TableHead>
                <TableHead>IP</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {eventos.map((e) => (
                <Fragment key={e.id}>
                  <TableRow>
                    <TableCell>{new Date(e.fecha).toLocaleString()}</TableCell>
                    <TableCell>{e.actor}</TableCell>
                    <TableCell>{e.accion}</TableCell>
                    <TableCell>{e.objetivo ?? '—'}</TableCell>
                    <TableCell>{e.ip ?? '—'}</TableCell>
                    <TableCell className="text-right">
                      {(e.antes || e.despues) && (
                        <Button size="sm" variant="ghost" onClick={() => setAbierto(abierto === e.id ? null : e.id)}>
                          {abierto === e.id ? 'Ocultar' : 'Detalle'}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                  {abierto === e.id && (
                    <TableRow>
                      <TableCell colSpan={6}>
                        {/* texto plano: los valores pueden venir de terceros (manifiesto), nunca como HTML */}
                        <pre className="text-xs whitespace-pre-wrap break-all">
                          {JSON.stringify({ antes: e.antes, despues: e.despues }, null, 2)}
                        </pre>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
              {eventos.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground">Sin eventos.</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          {siguiente !== null && (
            <Button variant="outline" className="justify-self-start" disabled={cargando} onClick={() => void cargar(siguiente, false)}>
              Cargar más
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
