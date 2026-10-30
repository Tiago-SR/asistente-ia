import { useEffect, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, mensaje, type Usuario, type Yo } from '@/lib/api'

export function Usuarios({ yo }: { yo: Yo }) {
  const [lista, setLista] = useState<Usuario[]>([])
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ email: '', clave: '', rol: 'operador' })

  const cargar = () =>
    api<{ usuarios: Usuario[] }>('GET', '/usuarios')
      .then((r) => setLista(r.usuarios))
      .catch((e) => setError(mensaje(e)))
  useEffect(() => {
    void cargar()
  }, [])

  async function accion(f: () => Promise<unknown>) {
    setError(null)
    try {
      await f()
      await cargar()
    } catch (e) {
      setError(mensaje(e))
    }
  }

  const crear = (ev: React.FormEvent) => {
    ev.preventDefault()
    void accion(async () => {
      await api('POST', '/usuarios', form)
      setForm({ email: '', clave: '', rol: 'operador' })
    })
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
          <CardTitle>Usuarios del panel</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Rol</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Último acceso</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {lista.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>{u.email}</TableCell>
                  <TableCell>
                    <Badge variant={u.rol === 'admin' ? 'default' : 'secondary'}>{u.rol}</Badge>
                  </TableCell>
                  <TableCell>{u.bloqueado ? 'bloqueado' : u.activo ? 'activo' : 'inactivo'}</TableCell>
                  <TableCell>{u.ultimo_login ? new Date(u.ultimo_login).toLocaleString() : '—'}</TableCell>
                  <TableCell className="text-right space-x-2">
                    <Button size="sm" variant="outline" disabled={u.email === yo.email}
                      onClick={() => accion(() => api('PATCH', `/usuarios/${u.id}`, { rol: u.rol === 'admin' ? 'operador' : 'admin' }))}>
                      {u.rol === 'admin' ? 'Pasar a operador' : 'Pasar a admin'}
                    </Button>
                    <Button size="sm" variant="outline" disabled={u.email === yo.email}
                      onClick={() => accion(() => api('PATCH', `/usuarios/${u.id}`, { activo: !u.activo }))}>
                      {u.activo ? 'Desactivar' : 'Activar'}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Nuevo usuario</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={crear} className="grid gap-4 max-w-lg">
            <div className="grid gap-2">
              <Label htmlFor="u-email">Email</Label>
              <Input id="u-email" type="email" required value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="u-clave">Contraseña (12 caracteres o más)</Label>
              <Input id="u-clave" type="password" autoComplete="new-password" required minLength={12}
                value={form.clave} onChange={(e) => setForm({ ...form, clave: e.target.value })} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="u-rol">Rol</Label>
              <Select id="u-rol" value={form.rol} onChange={(e) => setForm({ ...form, rol: e.target.value })}>
                <option value="operador">operador (solo lectura)</option>
                <option value="admin">admin (todo)</option>
              </Select>
            </div>
            <Button type="submit">Crear usuario</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
