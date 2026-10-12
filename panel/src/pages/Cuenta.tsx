import { useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, mensaje, type Yo } from '@/lib/api'

const CLAVE_MIN = 12

export function Cuenta({ yo }: { yo: Yo }) {
  const [form, setForm] = useState({ actual: '', nueva: '', repetida: '' })
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState(false)
  const [enviando, setEnviando] = useState(false)

  const cambiar = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setOk(false)
    if (form.nueva !== form.repetida) return setError('Las contraseñas nuevas no coinciden.')
    setError(null)
    setEnviando(true)
    try {
      await api('POST', '/yo/clave', { actual: form.actual, nueva: form.nueva })
      setForm({ actual: '', nueva: '', repetida: '' })
      setOk(true)
    } catch (e) {
      setError(mensaje(e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Card className="max-w-md">
      <CardHeader>
        <CardTitle>Mi cuenta · {yo.email}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={cambiar} className="grid gap-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {ok && (
            <Alert>
              <AlertDescription>Contraseña cambiada. Las demás sesiones abiertas se cerraron.</AlertDescription>
            </Alert>
          )}
          <div className="grid gap-2">
            <Label htmlFor="actual">Contraseña actual</Label>
            <Input id="actual" type="password" autoComplete="current-password" required value={form.actual}
              onChange={(e) => setForm({ ...form, actual: e.target.value })} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="nueva">Contraseña nueva (mínimo {CLAVE_MIN} caracteres)</Label>
            <Input id="nueva" type="password" autoComplete="new-password" required minLength={CLAVE_MIN}
              maxLength={200} value={form.nueva} onChange={(e) => setForm({ ...form, nueva: e.target.value })} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="repetida">Repetir la nueva</Label>
            <Input id="repetida" type="password" autoComplete="new-password" required minLength={CLAVE_MIN}
              maxLength={200} value={form.repetida}
              onChange={(e) => setForm({ ...form, repetida: e.target.value })} />
          </div>
          <Button type="submit" disabled={enviando}>Cambiar contraseña</Button>
        </form>
      </CardContent>
    </Card>
  )
}
