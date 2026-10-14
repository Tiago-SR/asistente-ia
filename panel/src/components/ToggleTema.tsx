import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTema } from '@/lib/tema'

export function ToggleTema({ className }: { className?: string }) {
  const { tema, alternar } = useTema()
  const etiqueta = tema === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'
  return (
    <Button variant="ghost" size="icon" className={className} onClick={alternar}
      aria-label={etiqueta} title={etiqueta}>
      {tema === 'dark' ? <Sun /> : <Moon />}
    </Button>
  )
}
