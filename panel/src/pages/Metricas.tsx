import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  api,
  mensaje,
  type RespSeries,
  type RespTools,
  type RespUsuarios,
  type Resumen,
} from '@/lib/api'

const DIAS = [7, 30, 90] as const
const compacto = new Intl.NumberFormat('es', { notation: 'compact', maximumFractionDigits: 1 })
const entero = new Intl.NumberFormat('es')
const usd = (v: number) => `US$ ${v.toLocaleString('es', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const ms = (v: number | null) => (v === null ? '—' : `${entero.format(v)} ms`)

// Días UTC, como el servidor (`hasta` inclusivo).
const dia = (d: Date) => d.toISOString().slice(0, 10)
function rango(dias: number): string[] {
  const hoy = new Date()
  return Array.from({ length: dias }, (_, i) => dia(new Date(hoy.getTime() - (dias - 1 - i) * 86_400_000)))
}

type Punto = {
  dia: string
  turnos: number
  errores: number
  rechazos: number
  costo_valle: number
  costo_pico: number
}

const CFG_TURNOS = { turnos: { label: 'Turnos', color: 'var(--viz-1)' } } satisfies ChartConfig
const CFG_PROBLEMAS = {
  errores: { label: 'Errores', color: 'var(--viz-critico)' },
  rechazos: { label: 'Rechazos por límite', color: 'var(--viz-aviso)' },
} satisfies ChartConfig
const CFG_COSTO = {
  costo_valle: { label: 'Costo, cota inferior (valle)', color: 'var(--viz-1)' },
  costo_pico: { label: 'Costo, cota superior (pico)', color: 'var(--viz-2)' },
} satisfies ChartConfig

function Tile({ titulo, valor, nota }: { titulo: string; valor: string; nota?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{titulo}</CardDescription>
        <CardTitle className="text-2xl">{valor}</CardTitle>
        {nota && <CardDescription>{nota}</CardDescription>}
      </CardHeader>
    </Card>
  )
}

const ejeX = (d: string) => d.slice(5) // MM-DD

export function Metricas() {
  const [sistemas, setSistemas] = useState<Resumen[]>([])
  const [sistema, setSistema] = useState('')
  const [dias, setDias] = useState<(typeof DIAS)[number]>(30)
  const [tabla, setTabla] = useState(false)
  const [series, setSeries] = useState<RespSeries | null>(null)
  const [usuarios, setUsuarios] = useState<RespUsuarios | null>(null)
  const [tools, setTools] = useState<RespTools | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)

  useEffect(() => {
    api<{ sistemas: Resumen[] }>('GET', '/sistemas').then((r) => setSistemas(r.sistemas), () => undefined)
  }, [])

  useEffect(() => {
    let vigente = true
    const dd = rango(dias)
    const q = new URLSearchParams({ desde: dd[0], hasta: dd[dd.length - 1] })
    if (sistema) q.set('sistema_id', sistema)
    setCargando(true)
    setError(null)
    Promise.all([
      api<RespSeries>('GET', `/metricas/series?agrupar=tipo&${q}`),
      api<RespUsuarios>('GET', `/metricas/usuarios?${q}&limite=20`),
      api<RespTools>('GET', `/metricas/tools?${q}`),
    ])
      .then(([s, u, t]) => {
        if (!vigente) return
        setSeries(s)
        setUsuarios(u)
        setTools(t)
      })
      .catch((e) => vigente && setError(mensaje(e)))
      .finally(() => vigente && setCargando(false))
    return () => {
      vigente = false
    }
  }, [sistema, dias])

  const { puntos, totales } = useMemo(() => {
    const porDia = new Map<string, Punto>(
      rango(dias).map((d) => [d, { dia: d, turnos: 0, errores: 0, rechazos: 0, costo_valle: 0, costo_pico: 0 }]),
    )
    let tokens = 0
    let sinTarifa = 0
    for (const f of series?.filas ?? []) {
      const p = porDia.get(f.dia)
      if (!p) continue
      if (f.tipo === 'llm' && f.resultado === 'ok') {
        p.turnos += f.n
        tokens += f.tokens_in + f.tokens_out
      }
      if (f.resultado === 'error') p.errores += f.n
      if (f.resultado === 'limite') p.rechazos += f.n
      if (f.tipo === 'llm' || f.tipo === 'tts') {
        p.costo_valle += f.costo_valle_usd ?? 0
        p.costo_pico += f.costo_pico_usd ?? 0
        sinTarifa += f.n_sin_tarifa
      }
    }
    const pts = [...porDia.values()]
    const suma = (k: keyof Omit<Punto, 'dia'>) => pts.reduce((a, p) => a + p[k], 0)
    return {
      puntos: pts,
      totales: {
        turnos: suma('turnos'),
        errores: suma('errores'),
        rechazos: suma('rechazos'),
        valle: suma('costo_valle'),
        pico: suma('costo_pico'),
        tokens,
        sinTarifa,
      },
    }
  }, [series, dias])

  const nombre = (id: string) => sistemas.find((s) => s.id === id)?.nombre ?? id
  const cob = series?.cobertura

  return (
    <div className="grid gap-6">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Métricas de uso</CardTitle>
          <CardDescription>
            Días en UTC. {cob?.resumido_hasta ? `Resumen diario hasta ${cob.resumido_hasta}; ` : ''}
            lo posterior se calcula al vuelo
            {cob?.crudos_desde ? `. Eventos detallados desde ${cob.crudos_desde}` : ''}.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="m-sistema">Sistema</Label>
            <select
              id="m-sistema"
              value={sistema}
              onChange={(e) => setSistema(e.target.value)}
              className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm"
            >
              <option value="">Todos</option>
              {sistemas.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.nombre}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-1" role="group" aria-label="Rango">
            {DIAS.map((d) => (
              <Button key={d} size="sm" variant={dias === d ? 'default' : 'outline'} onClick={() => setDias(d)}>
                {d} días
              </Button>
            ))}
          </div>
          <Button size="sm" variant="outline" onClick={() => setTabla(!tabla)} aria-pressed={tabla}>
            {tabla ? 'Ver gráficos' : 'Ver como tabla'}
          </Button>
          {cargando && <span className="text-sm text-muted-foreground">Cargando…</span>}
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Tile titulo="Turnos de chat" valor={entero.format(totales.turnos)} />
        <Tile titulo="Tokens" valor={compacto.format(totales.tokens)} />
        <Tile
          titulo="Costo estimado"
          valor={`${usd(totales.valle)} – ${usd(totales.pico)}`}
          nota={totales.sinTarifa > 0 ? `Incompleto: ${totales.sinTarifa} eventos sin tarifa` : 'Cota inferior – superior'}
        />
        <Tile
          titulo="Errores y rechazos"
          valor={`${entero.format(totales.errores)} · ${entero.format(totales.rechazos)}`}
          nota="Errores · límites"
        />
      </div>

      {tabla ? (
        <Card>
          <CardHeader>
            <CardTitle>Por día</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Día</TableHead>
                  <TableHead className="text-right">Turnos</TableHead>
                  <TableHead className="text-right">Errores</TableHead>
                  <TableHead className="text-right">Rechazos</TableHead>
                  <TableHead className="text-right">Costo valle</TableHead>
                  <TableHead className="text-right">Costo pico</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {puntos.map((p) => (
                  <TableRow key={p.dia}>
                    <TableCell>{p.dia}</TableCell>
                    <TableCell className="text-right tabular-nums">{entero.format(p.turnos)}</TableCell>
                    <TableCell className="text-right tabular-nums">{entero.format(p.errores)}</TableCell>
                    <TableCell className="text-right tabular-nums">{entero.format(p.rechazos)}</TableCell>
                    <TableCell className="text-right tabular-nums">{usd(p.costo_valle)}</TableCell>
                    <TableCell className="text-right tabular-nums">{usd(p.costo_pico)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Turnos por día</CardTitle>
              <CardDescription>Turnos de chat completados.</CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer config={CFG_TURNOS} className="h-56 w-full">
                <BarChart data={puntos} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="var(--viz-rejilla)" />
                  <XAxis dataKey="dia" tickFormatter={ejeX} tickLine={false} axisLine={false} minTickGap={24} />
                  <YAxis tickFormatter={(v: number) => compacto.format(v)} tickLine={false} axisLine={false} width={40} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="turnos" fill="var(--color-turnos)" radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                </BarChart>
              </ChartContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Errores y rechazos por día</CardTitle>
              <CardDescription>
                Errores del turno, y mensajes rechazados por cuota o ritmo (no llegaron al modelo).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer config={CFG_PROBLEMAS} className="h-56 w-full">
                <LineChart data={puntos} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="var(--viz-rejilla)" />
                  <XAxis dataKey="dia" tickFormatter={ejeX} tickLine={false} axisLine={false} minTickGap={24} />
                  <YAxis tickFormatter={(v: number) => compacto.format(v)} tickLine={false} axisLine={false} width={40} allowDecimals={false} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Line dataKey="errores" type="monotone" stroke="var(--color-errores)" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line dataKey="rechazos" type="monotone" stroke="var(--color-rechazos)" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ChartContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Costo estimado por día (USD)</CardTitle>
              <CardDescription>
                La tarifa depende del horario del proveedor: el costo real queda entre las dos líneas. Lo que no
                tiene tarifa no se suma
                {totales.sinTarifa > 0 ? ` (${totales.sinTarifa} eventos en este rango)` : ''}.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer config={CFG_COSTO} className="h-56 w-full">
                <LineChart data={puntos} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="var(--viz-rejilla)" />
                  <XAxis dataKey="dia" tickFormatter={ejeX} tickLine={false} axisLine={false} minTickGap={24} />
                  <YAxis tickFormatter={(v: number) => `$${v.toLocaleString('es', { maximumFractionDigits: 2 })}`} tickLine={false} axisLine={false} width={52} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Line dataKey="costo_valle" type="monotone" stroke="var(--color-costo_valle)" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line dataKey="costo_pico" type="monotone" stroke="var(--color-costo_pico)" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ChartContainer>
            </CardContent>
          </Card>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Tools</CardTitle>
          <CardDescription>
            La duración incluye la espera del semáforo del conector: un p95 alto puede ser cola y no lentitud del
            sistema externo.
            {tools?.cobertura.tools_desde ? ` Datos desde ${tools.cobertura.tools_desde}.` : ''}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                {!sistema && <TableHead>Sistema</TableHead>}
                <TableHead>Tool</TableHead>
                <TableHead className="text-right">Llamadas</TableHead>
                <TableHead className="text-right">Errores</TableHead>
                <TableHead className="text-right">p50</TableHead>
                <TableHead className="text-right">p95</TableHead>
                <TableHead className="text-right">Máx.</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(tools?.filas ?? []).map((t) => (
                <TableRow key={`${t.sistema_id}/${t.tool}`}>
                  {!sistema && <TableCell>{nombre(t.sistema_id)}</TableCell>}
                  <TableCell className="font-mono text-xs">{t.tool}</TableCell>
                  <TableCell className="text-right tabular-nums">{entero.format(t.n)}</TableCell>
                  <TableCell className="text-right tabular-nums">{entero.format(t.errores)}</TableCell>
                  <TableCell className="text-right tabular-nums">{ms(t.p50_ms)}</TableCell>
                  <TableCell className="text-right tabular-nums">{ms(t.p95_ms)}</TableCell>
                  <TableCell className="text-right tabular-nums">{ms(t.max_ms)}</TableCell>
                </TableRow>
              ))}
              {tools && tools.filas.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    Sin llamadas en el rango.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Usuarios con más actividad</CardTitle>
          <CardDescription>
            La cuota diaria se cuenta por día UTC
            {usuarios ? ` y se reinicia a las ${new Date(usuarios.reinicia_dia).toISOString().slice(11, 16)} UTC` : ''}
            ; los rechazos también cuentan.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {usuarios && usuarios.cuota_mes.length > 0 && (
            <ul className="grid gap-1 text-sm">
              {usuarios.cuota_mes.map((c) => (
                <li key={c.sistema_id}>
                  <span className="font-medium">{nombre(c.sistema_id)}</span>: {compacto.format(c.usados)} de{' '}
                  {compacto.format(c.limite)} tokens este mes (restan {compacto.format(c.restante)})
                </li>
              ))}
            </ul>
          )}
          <Table>
            <TableHeader>
              <TableRow>
                {!sistema && <TableHead>Sistema</TableHead>}
                <TableHead>Usuario</TableHead>
                <TableHead className="text-right">Turnos</TableHead>
                <TableHead className="text-right">Rechazos</TableHead>
                <TableHead className="text-right">Errores</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead className="text-right">Cuota de hoy</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(usuarios?.filas ?? []).map((u) => (
                <TableRow key={`${u.sistema_id}/${u.usuario_ref}`}>
                  {!sistema && <TableCell>{nombre(u.sistema_id)}</TableCell>}
                  <TableCell>{u.usuario_ref}</TableCell>
                  <TableCell className="text-right tabular-nums">{entero.format(u.turnos)}</TableCell>
                  <TableCell className="text-right tabular-nums">{entero.format(u.rechazos)}</TableCell>
                  <TableCell className="text-right tabular-nums">{entero.format(u.errores)}</TableCell>
                  <TableCell className="text-right tabular-nums">{compacto.format(u.tokens)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {u.cuota_dia ? `${u.cuota_dia.usados}/${u.cuota_dia.limite} (restan ${u.cuota_dia.restante})` : '—'}
                  </TableCell>
                </TableRow>
              ))}
              {usuarios && usuarios.filas.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    Sin actividad en el rango.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
