import { useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ToggleTema } from '@/components/ToggleTema'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, mensaje, type Yo } from '@/lib/api'

export function Login({ onEntrar }: { onEntrar: (yo: Yo) => void }) {
  const [email, setEmail] = useState('')
  const [clave, setClave] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)

  async function enviar(ev: React.FormEvent) {
    ev.preventDefault()
    setCargando(true)
    setError(null)
    try {
      onEntrar(await api<Yo>('POST', '/login', { email, clave }))
    } catch (e) {
      setError(mensaje(e))
    } finally {
      setCargando(false)
    }
  }

  return (
    <main className="min-h-screen grid place-items-center p-4">
      <ToggleTema className="absolute top-4 right-4" />
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Panel de administración</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={enviar} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="username" required value={email}
                onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="clave">Contraseña</Label>
              <Input id="clave" type="password" autoComplete="current-password" required value={clave}
                onChange={(e) => setClave(e.target.value)} />
            </div>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Button type="submit" disabled={cargando}>
              {cargando ? 'Entrando…' : 'Entrar'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
