import { useEffect, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, mensaje, type Resumen, type Yo } from '@/lib/api'

export function Sistemas({ yo, ir }: { yo: Yo; ir: (ruta: string) => void }) {
  const [lista, setLista] = useState<Resumen[] | null>(null)
  const [invalidos, setInvalidos] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [nuevo, setNuevo] = useState({ id: '', nombre: '', base_url: '' })
  const [creando, setCreando] = useState(false)

  const cargar = () =>
    api<{ sistemas: Resumen[]; invalidos: Record<string, string> }>('GET', '/sistemas')
      .then((r) => {
        setLista(r.sistemas)
        setInvalidos(r.invalidos)
      })
      .catch((e) => setError(mensaje(e)))
  useEffect(() => {
    void cargar()
  }, [])

  async function crear(ev: React.FormEvent) {
    ev.preventDefault()
    setError(null)
    try {
      // Plantilla mínima con RS256 + JWKS: el resto se completa en la página del sistema.
      await api('POST', '/sistemas', {
        config: {
          id: nuevo.id,
          nombre: nuevo.nombre,
          base_url: nuevo.base_url,
          conector: {},
          auth: { algoritmo: 'RS256', jwks_url: new URL('/.well-known/jwks.json', nuevo.base_url).href },
        },
      })
      ir(`/sistemas/${nuevo.id}`)
    } catch (e) {
      setError(mensaje(e))
    }
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
          <CardTitle>Sistemas</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Id</TableHead>
                <TableHead>Nombre</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Manifiesto</TableHead>
                <TableHead>base_url</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lista?.map((s) => (
                <TableRow key={s.id} className="cursor-pointer" onClick={() => ir(`/sistemas/${s.id}`)}>
                  <TableCell className="font-mono">{s.id}</TableCell>
                  <TableCell>{s.nombre}</TableCell>
                  <TableCell>
                    {!s.habilitado ? (
                      <Badge variant="secondary">deshabilitado</Badge>
                    ) : s.activo ? (
                      <Badge>activo</Badge>
                    ) : (
                      <Badge variant="destructive">con error</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {s.activo ? (s.manifiesto_ok ? `${s.tools_lectura} tools de lectura` : (s.ultimo_error ?? 'sin manifiesto')) : '—'}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{s.base_url}</TableCell>
                </TableRow>
              ))}
              {lista?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Sin sistemas. Importe el YAML con la CLI o cree uno abajo.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          {Object.keys(invalidos).length > 0 && (
            <p className="mt-4 text-sm text-muted-foreground">
              Inválidos:{' '}
              {Object.entries(invalidos).map(([id, m]) => (
                <span key={id} className="mr-3">
                  <span className="font-mono">{id}</span>: {m}
                </span>
              ))}
            </p>
          )}
        </CardContent>
      </Card>

      {yo.rol === 'admin' && (
        <Card>
          <CardHeader>
            <CardTitle>Nuevo sistema</CardTitle>
          </CardHeader>
          <CardContent>
            {!creando ? (
              <Button variant="outline" onClick={() => setCreando(true)}>
                Crear sistema
              </Button>
            ) : (
              <form onSubmit={crear} className="grid gap-4 max-w-lg">
                <div className="grid gap-2">
                  <Label htmlFor="id">Id (= claim iss)</Label>
                  <Input id="id" required pattern="[a-z0-9][a-z0-9_\-]{0,63}" value={nuevo.id}
                    onChange={(e) => setNuevo({ ...nuevo, id: e.target.value })} />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="nombre">Nombre</Label>
                  <Input id="nombre" required value={nuevo.nombre}
                    onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })} />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="base_url">base_url del sistema</Label>
                  <Input id="base_url" type="url" required placeholder="https://" value={nuevo.base_url}
                    onChange={(e) => setNuevo({ ...nuevo, base_url: e.target.value })} />
                </div>
                <p className="text-sm text-muted-foreground">
                  Se crea deshabilitado. Cargue el token del manifiesto y habilítelo desde su página.
                </p>
                <Button type="submit">Crear</Button>
              </form>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
