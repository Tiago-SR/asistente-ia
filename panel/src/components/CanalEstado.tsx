import { useCallback, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, mensaje } from '@/lib/api'

type Vinculo = { ref: string; numero: string; activo: boolean; creado_en: string; ultimo_uso: string }
type Fallo = { numero: string; tipo: string; codigo: string | null; motivo: string | null; cuando: string }

const fecha = (iso: string) => new Date(iso).toLocaleString()

/** Números vinculados (con revocar) y envíos fallidos de las últimas 24 h del canal de un sistema. */
export function CanalEstado({ id, puede }: { id: string; puede: boolean }) {
  const [vinculos, setVinculos] = useState<Vinculo[]>([])
  const [fallos, setFallos] = useState<Fallo[]>([])
  const [error, setError] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    try {
      const [v, f] = await Promise.all([
        api<{ vinculos: Vinculo[] }>('GET', `/sistemas/${id}/canal/vinculos`),
        api<{ errores: Fallo[] }>('GET', `/sistemas/${id}/canal/errores`),
      ])
      setVinculos(v.vinculos)
      setFallos(f.errores)
      setError(null)
    } catch (e) {
      setError(mensaje(e))
    }
  }, [id])
  useEffect(() => void cargar(), [cargar])

  const revocar = async (v: Vinculo) => {
    if (!window.confirm(`¿Cortar el acceso de ${v.numero}? Para borrarlo del todo, revóquelo también en el sistema.`)) return
    try {
      await api('POST', `/sistemas/${id}/canal/vinculos/revocar`, { ref: v.ref })
      await cargar()
    } catch (e) {
      setError(mensaje(e))
    }
  }

  return (
    <div className="grid gap-4 rounded-md border p-4">
      {error && <p className="text-sm text-destructive">{error}</p>}
      <h3 className="font-medium">Números vinculados</h3>
      {vinculos.length === 0 ? (
        <p className="text-sm text-muted-foreground">Ninguno.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Número</TableHead>
              <TableHead>Vinculado</TableHead>
              <TableHead>Último uso</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {vinculos.map((v) => (
              <TableRow key={v.ref}>
                <TableCell className="font-mono">
                  {v.numero} {!v.activo && <Badge variant="secondary">revocado</Badge>}
                </TableCell>
                <TableCell>{fecha(v.creado_en)}</TableCell>
                <TableCell>{fecha(v.ultimo_uso)}</TableCell>
                <TableCell>
                  {puede && v.activo && (
                    <Button type="button" variant="outline" size="sm" onClick={() => void revocar(v)}>Revocar</Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <h3 className="font-medium">Envíos fallidos (24 h)</h3>
      {fallos.length === 0 ? (
        <p className="text-sm text-muted-foreground">Ninguno.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Cuándo</TableHead>
              <TableHead>Número</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Motivo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {fallos.map((f, i) => (
              <TableRow key={i}>
                <TableCell>{fecha(f.cuando)}</TableCell>
                <TableCell className="font-mono">{f.numero}</TableCell>
                <TableCell>{f.tipo}</TableCell>
                <TableCell>{f.motivo ?? 'desconocido'} {f.codigo && <span className="font-mono">({f.codigo})</span>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => void cargar()}>Actualizar</Button>
    </div>
  )
}
