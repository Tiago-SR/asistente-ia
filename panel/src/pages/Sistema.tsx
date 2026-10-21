import { useCallback, useEffect, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { api, ApiError, mensaje, type Config, type ToolVista, type Vista, type Yo } from '@/lib/api'

const CAMPOS_SECRETOS: Record<string, string> = {
  token_manifiesto: 'Token del manifiesto (el conector lo envía a base_url)',
  auth_hs256: 'Secreto HS256 (solo si el algoritmo es HS256, 32 bytes o más)',
  llm_api_key: 'API key del LLM propio (solo con llm.base_url propio)',
}

const leer = (o: Config, ruta: string): unknown => ruta.split('.').reduce<any>((a, k) => a?.[k], o) // eslint-disable-line @typescript-eslint/no-explicit-any

function poner(o: Config, ruta: string, valor: unknown): Config {
  const c = structuredClone(o)
  const ks = ruta.split('.')
  let t = c
  for (const k of ks.slice(0, -1)) t = t[k] ??= {}
  const ultimo = ks[ks.length - 1]
  if (valor === '' || valor === undefined || valor === null) delete t[ultimo]
  else t[ultimo] = valor
  return c
}

type Relectura = {
  conservado: string | null
  primera: boolean
  agregadas?: string[]
  quitadas?: string[]
  modificadas?: string[]
  version?: { antes: string | null; ahora: string | null }
}

export function Sistema({ id, yo, ir }: { id: string; yo: Yo; ir: (r: string) => void }) {
  const [vista, setVista] = useState<Vista | null>(null)
  const [config, setConfig] = useState<Config>({})
  const [nuevos, setNuevos] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [tools, setTools] = useState<{ manifiesto_ok: boolean; error: string | null; tools: ToolVista[]; huerfanas: { nombre: string; habilitada: boolean }[]; rechazadas: { nombre: string | null; motivo: string }[]; relectura: Relectura | null; destructivas_hora: { total: number; maximo_usuario: number; usuarios: number; limite: number } } | null>(null)
  const [uso, setUso] = useState<{
    desde: string
    tokens_mes: { usados: number; limite: number }
    imagenes: number
    imagenes_max_turno: number
    imagen_max_kb: number | null
    rechazos: { demasiadas_imagenes: number; imagen_demasiado_grande: number }
    excel: number
  } | null>(null)
  const [releyendo, setReleyendo] = useState(false)
  const [aprobar, setAprobar] = useState<ToolVista | null>(null)
  const [nombreConf, setNombreConf] = useState('')
  const puede = yo.rol === 'admin'

  const cargarTools = useCallback(
    (refrescar = false) =>
      api<NonNullable<typeof tools>>('GET', `/sistemas/${id}/tools${refrescar ? '?refrescar=true' : ''}`)
        .then(setTools)
        .catch((e) => setError(mensaje(e))),
    [id],
  )
  const releer = async () => {
    setReleyendo(true)
    setError(null)
    await cargarTools(true)
    setReleyendo(false)
  }
  const cargar = useCallback(async () => {
    try {
      const v = await api<Vista>('GET', `/sistemas/${id}`)
      setVista(v)
      setConfig(v.config)
      setNuevos({})
      await cargarTools()
      api<NonNullable<typeof uso>>('GET', `/sistemas/${id}/uso`).then(setUso).catch(() => setUso(null)) // sin permiso de métricas: no se muestra
    } catch (e) {
      setError(mensaje(e))
    }
  }, [id, cargarTools])
  useEffect(() => {
    void cargar()
  }, [cargar])

  // Escritura común: muestra el error en español y, ante un conflicto de versión, recarga lo vigente.
  async function escribir(f: () => Promise<Vista | unknown>, exito: string) {
    setError(null)
    setOk(null)
    try {
      await f()
      setOk(exito)
      await cargar()
    } catch (e) {
      setError(mensaje(e))
      if (e instanceof ApiError && e.code === 'version_obsoleta') await cargar()
    }
  }

  if (!vista) return error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : <p>Cargando…</p>

  const urlCambio = leer(config, 'base_url') !== leer(vista.config, 'base_url')
  const llmCambio = (leer(config, 'llm.base_url') ?? '') !== (leer(vista.config, 'llm.base_url') ?? '')
  const campo = (ruta: string, etiqueta: string, tipo = 'text') => (
    <div className="grid gap-2">
      <Label htmlFor={ruta}>{etiqueta}</Label>
      <Input id={ruta} type={tipo} disabled={!puede} value={String(leer(config, ruta) ?? '')}
        onChange={(e) => setConfig(poner(config, ruta, tipo === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value))} />
    </div>
  )
  const interruptor = (ruta: string, etiqueta: string) => (
    <div className="flex items-center gap-3">
      <Switch id={ruta} disabled={!puede} checked={Boolean(leer(config, ruta))}
        onCheckedChange={(v) => setConfig(poner(config, ruta, v))} />
      <Label htmlFor={ruta}>{etiqueta}</Label>
    </div>
  )

  // un número vacío equivale a null (techo global): borrar un campo que ya era null no es un cambio
  const igual = (x: unknown, y: unknown) => JSON.stringify(x, (_, v) => (v === '' ? null : v)) === JSON.stringify(y, (_, v) => (v === '' ? null : v))
  const hayCambios = !igual(config, vista.config) || ['token_manifiesto', 'llm_api_key', 'auth_hs256'].some((k) => nuevos[k])

  const guardar = (ev: React.FormEvent) => {
    ev.preventDefault()
    const secretos: Record<string, string> = {}
    for (const [k, v] of Object.entries(nuevos)) if (v) secretos[k] = v
    // un número vacío en los límites de adjuntos significa «techo global»
    const adj = { ...(config.adjuntos as Record<string, unknown> | undefined) }
    for (const k of ['max_archivos', 'max_kb']) if (adj[k] === '') adj[k] = null
    const cfg = config.adjuntos ? { ...config, adjuntos: adj } : config
    void escribir(() => api('PUT', `/sistemas/${id}`, { version: vista.version, config: cfg, secretos }), 'Configuración guardada.')
  }

  return (
    <div className="grid gap-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" onClick={() => ir('/sistemas')}>← Sistemas</Button>
        <h2 className="text-xl font-semibold">{String(vista.config.nombre)}</h2>
        <span className="font-mono text-sm text-muted-foreground">{id}</span>
        {vista.config.habilitado ? (vista.activo ? <Badge>activo</Badge> : <Badge variant="destructive">con error</Badge>) : <Badge variant="secondary">deshabilitado</Badge>}
        <span className="text-xs text-muted-foreground">versión {vista.version}</span>
      </div>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      {ok && <Alert><AlertDescription>{ok}</AlertDescription></Alert>}
      {vista.error && <Alert variant="destructive"><AlertDescription>{vista.error}</AlertDescription></Alert>}
      {!puede && <Alert><AlertDescription>Su rol es de solo lectura.</AlertDescription></Alert>}

      <form onSubmit={guardar} className="grid gap-6">
        <Card>
          <CardHeader><CardTitle>Configuración</CardTitle></CardHeader>
          <CardContent className="grid gap-4 max-w-2xl">
            {interruptor('habilitado', 'Habilitado')}
            {campo('nombre', 'Nombre')}
            {campo('nombre_asistente', 'Nombre del asistente en el widget')}
            {campo('base_url', 'base_url del sistema')}
            <div className="grid gap-2">
              <Label htmlFor="origenes">Orígenes permitidos (CORS del widget), uno por línea</Label>
              <Textarea id="origenes" disabled={!puede} value={((leer(config, 'origenes_permitidos') as string[]) ?? []).join('\n')}
                onChange={(e) => setConfig(poner(config, 'origenes_permitidos', e.target.value.split('\n').map((x) => x.trim()).filter(Boolean)))} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="auth.algoritmo">Algoritmo de los tokens</Label>
              <select id="auth.algoritmo" disabled={!puede} value={String(leer(config, 'auth.algoritmo') ?? '')}
                onChange={(e) => {
                  const a = e.target.value
                  let c = poner(config, 'auth.algoritmo', a)
                  // HS256 no admite fuente de clave pública; al salir de HS256 el secreto nuevo ya no aplica
                  if (a === 'HS256') c = poner(poner(c, 'auth.jwks_url', ''), 'auth.clave_publica', '')
                  else setNuevos({ ...nuevos, auth_hs256: '' })
                  setConfig(c)
                }}
                className="h-9 rounded-md border bg-background px-3 text-sm">
                {['RS256', 'EdDSA', 'HS256'].map((a) => <option key={a}>{a}</option>)}
              </select>
            </div>
            {leer(config, 'auth.algoritmo') !== 'HS256' && (
              <>
                {campo('auth.jwks_url', 'auth.jwks_url (o clave pública, no ambas)')}
                <div className="grid gap-2">
                  <Label htmlFor="auth.clave_publica">auth.clave_publica (PEM)</Label>
                  <Textarea id="auth.clave_publica" disabled={!puede} className="font-mono text-xs"
                    value={String(leer(config, 'auth.clave_publica') ?? '')}
                    onChange={(e) => setConfig(poner(config, 'auth.clave_publica', e.target.value))} />
                </div>
              </>
            )}
            {puede && leer(config, 'auth.algoritmo') === 'HS256' && leer(vista.config, 'auth.algoritmo') !== 'HS256' && (
              <Alert>
                <AlertDescription className="grid gap-2">
                  Al pasar a HS256 cargue el secreto compartido (32 bytes o más) en este mismo guardado.
                  <Input type="password" autoComplete="off" placeholder="Secreto HS256" value={nuevos.auth_hs256 ?? ''}
                    onChange={(e) => setNuevos({ ...nuevos, auth_hs256: e.target.value })} />
                </AlertDescription>
              </Alert>
            )}
            {campo('auth.audiencia', 'Audiencia')}
            {campo('llm.modelo', 'Modelo del LLM (vacío = global)')}
            {campo('llm.base_url', 'URL del LLM propio (vacío = global)')}
            {interruptor('memoria_habilitada', 'Memoria por usuario')}
            {interruptor('busqueda_web', 'Búsqueda web')}
            {interruptor('consultas_recientes', 'Consultas recientes')}
            {interruptor('exportar_excel', 'Exportar a Excel')}
            {interruptor('adjuntos.habilitado', 'Adjuntar imágenes (además requiere un modelo con visión)')}
            {interruptor('leer_imagenes', 'Leer imágenes de cualquier tema y conservar su texto en la conversación (el texto leído, no la imagen, queda guardado y se envía al proveedor del modelo)')}
            <div className="grid gap-4 sm:grid-cols-2">
              {campo('adjuntos.max_archivos', 'Imágenes por mensaje (vacío = máximo global)', 'number')}
              {campo('adjuntos.max_kb', 'KB por imagen (vacío = máximo global)', 'number')}
            </div>
            {uso && (
              <p className="text-sm text-muted-foreground">
                Uso desde {uso.desde} (el registro de imágenes empieza con este despliegue): {uso.imagenes} imágenes; máximo en un
                mensaje {uso.imagenes_max_turno}, la mayor {uso.imagen_max_kb ?? 0} KB; rechazos: {uso.rechazos.demasiadas_imagenes} por
                cantidad y {uso.rechazos.imagen_demasiado_grande} por tamaño; Excel generados: {uso.excel}.
              </p>
            )}
            <div className="grid gap-4 sm:grid-cols-3">
              {campo('limites.mensajes_por_usuario_min', 'Mensajes/usuario/min', 'number')}
              {campo('limites.mensajes_por_usuario_dia', 'Mensajes/usuario/día', 'number')}
              {campo('limites.tokens_por_mes', 'Tokens/mes', 'number')}
              {campo('limites.destructivas_por_usuario_hora', 'Destructivas/usuario/hora (0 = bloqueadas)', 'number')}
            </div>
            {uso && (
              <p className="text-sm text-muted-foreground">
                Tokens este mes: {uso.tokens_mes.usados.toLocaleString()} de {uso.tokens_mes.limite.toLocaleString()}.
              </p>
            )}
            {campo('retencion_dias', 'Retención (días)', 'number')}
            <div className="grid gap-2">
              <Label htmlFor="prompt_dominio">Prompt de dominio</Label>
              <Textarea id="prompt_dominio" disabled={!puede} value={String(leer(config, 'prompt_dominio') ?? '')}
                onChange={(e) => setConfig(poner(config, 'prompt_dominio', e.target.value))} />
            </div>
            {puede && urlCambio && (
              <Alert>
                <AlertDescription className="grid gap-2">
                  Cambiar base_url descarta el token del manifiesto actual: cárguelo de nuevo aquí o deshabilite el sistema.
                  <Input type="password" autoComplete="off" placeholder="Nuevo token del manifiesto" value={nuevos.token_manifiesto ?? ''}
                    onChange={(e) => setNuevos({ ...nuevos, token_manifiesto: e.target.value })} />
                </AlertDescription>
              </Alert>
            )}
            {puede && llmCambio && (
              <Alert>
                <AlertDescription className="grid gap-2">
                  Cambiar la URL del LLM descarta su API key: cárguela de nuevo aquí si el nuevo servidor la necesita.
                  <Input type="password" autoComplete="off" placeholder="Nueva API key del LLM" value={nuevos.llm_api_key ?? ''}
                    onChange={(e) => setNuevos({ ...nuevos, llm_api_key: e.target.value })} />
                </AlertDescription>
              </Alert>
            )}
            {puede && <Button type="submit" className="w-fit" disabled={!hayCambios}>Guardar</Button>}
          </CardContent>
        </Card>
      </form>

      <Card>
        <CardHeader><CardTitle>Secretos</CardTitle></CardHeader>
        <CardContent className="grid gap-4 max-w-2xl">
          <p className="text-sm text-muted-foreground">Se guardan cifrados. Se pueden escribir y reemplazar, nunca leer.</p>
          {Object.entries(CAMPOS_SECRETOS).map(([c, etiqueta]) => {
            const s = vista.secretos[c]
            return (
              <div key={c} className="grid gap-2 border-b pb-4 last:border-0">
                <Label>{etiqueta}</Label>
                <div className="text-sm">
                  {s?.configurado ? <>configurado · huella <span className="font-mono">{s.huella}</span> · {s.actualizado_en && new Date(s.actualizado_en).toLocaleString()}</> : <span className="text-muted-foreground">sin configurar</span>}
                </div>
                {puede && (
                  <div className="flex gap-2">
                    <Input type="password" autoComplete="off" placeholder="Nuevo valor" value={nuevos[`s:${c}`] ?? ''}
                      onChange={(e) => setNuevos({ ...nuevos, [`s:${c}`]: e.target.value })} />
                    <Button type="button" variant="outline" disabled={!nuevos[`s:${c}`]}
                      onClick={() => escribir(() => api('PUT', `/sistemas/${id}/secretos/${c}`, { version: vista.version, valor: nuevos[`s:${c}`] }), 'Secreto guardado.')}>
                      Guardar
                    </Button>
                    {s?.configurado && (
                      <Button type="button" variant="destructive"
                        onClick={() => escribir(() => api('DELETE', `/sistemas/${id}/secretos/${c}?version=${vista.version}`), 'Secreto borrado.')}>
                        Borrar
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            Tools
            <Button type="button" size="sm" variant="outline" disabled={releyendo} onClick={() => void releer()}>{releyendo ? 'Releyendo…' : 'Releer manifiesto'}</Button>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          {tools && (
            <p className="text-sm text-muted-foreground">
              Destructivas en la última hora: {tools.destructivas_hora.total} en total
              ({tools.destructivas_hora.usuarios} usuario(s)); el que más lleva: {tools.destructivas_hora.maximo_usuario} de {tools.destructivas_hora.limite} permitidas por usuario.
              El límite se cambia en Configuración → Límites.
            </p>
          )}
          {tools && !tools.manifiesto_ok && <Alert><AlertDescription>Sin manifiesto: {tools.error}</AlertDescription></Alert>}
          {tools?.relectura && <ResumenRelectura r={tools.relectura} />}
          {tools && tools.rechazadas.length > 0 && (
            <Alert>
              <AlertDescription>
                El sistema declara tools que el asistente descartó por inválidas:
                <ul className="mt-1 list-disc pl-5">
                  {tools.rechazadas.map((r, i) => <li key={i}><span className="font-mono">{r.nombre ?? '(sin nombre)'}</span>: {r.motivo}</li>)}
                </ul>
              </AlertDescription>
            </Alert>
          )}
          {tools?.tools.map((t) => (
            <div key={t.nombre} className="flex items-start gap-3 border-b pb-3 last:border-0">
              <Switch aria-label={t.nombre} checked={t.habilitada} disabled={!puede || (t.efecto === 'escritura' && !t.accionable)}
                onCheckedChange={(v) => {
                  if (v && t.destructiva) {
                    setNombreConf('')
                    setAprobar(t)
                  } else void escribir(() => api('PUT', `/sistemas/${id}/tools/${t.nombre}`, { habilitada: v }), `Tool ${t.nombre} ${v ? 'habilitada' : 'deshabilitada'}.`)
                }} />
              <div className="grid gap-1">
                {/* nombre y descripción los escribe un tercero: siempre como texto */}
                <div><span className="font-mono">{t.nombre}</span>{' '}
                  <Badge variant={t.efecto === 'escritura' ? 'destructive' : 'secondary'}>{t.efecto}</Badge>
                  {t.efecto === 'escritura' && !t.accionable && <Badge variant="outline" className="ml-1">no accionable</Badge>}
                  {t.destructiva && <Badge variant="destructive" className="ml-1">destructiva</Badge>}
                  {t.aprobacion === 'obsoleta' && <Badge variant="outline" className="ml-1">requiere reaprobación</Badge>}
                </div>
                <p className="text-sm text-muted-foreground">{t.descripcion}</p>
              </div>
            </div>
          ))}
          {tools && tools.huerfanas.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Con excepción pero ausentes del manifiesto: {tools.huerfanas.map((h) => `${h.nombre} (${h.habilitada ? 'sí' : 'no'})`).join(', ')}
            </p>
          )}
        </CardContent>
      </Card>

      <Dialog open={aprobar !== null} onOpenChange={(o) => { if (!o) setAprobar(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Aprobar tool destructiva</DialogTitle>
            <DialogDescription>
              Esta tool puede borrar o anular datos en el sistema cliente. Cada uso lo confirma el usuario en pantalla,
              pero no se puede deshacer. La aprobación vale solo para la definición actual: si el sistema la cambia,
              se apaga sola. Escriba <span className="font-mono">{aprobar?.nombre}</span> para confirmar.
            </DialogDescription>
          </DialogHeader>
          <Input value={nombreConf} onChange={(e) => setNombreConf(e.target.value)} autoComplete="off" />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAprobar(null)}>Cancelar</Button>
            <Button type="button" variant="destructive" disabled={nombreConf !== aprobar?.nombre}
              onClick={() => {
                const t = aprobar!
                setAprobar(null)
                void escribir(() => api('PUT', `/sistemas/${id}/tools/${t.nombre}`, { habilitada: true, confirmo_nombre: nombreConf }), `Tool ${t.nombre} aprobada y habilitada.`)
              }}>Aprobar y habilitar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

const lista = (xs?: string[]) => (xs ?? []).join(', ')

// Los nombres y versiones los escribe un tercero: texto, nunca HTML.
function ResumenRelectura({ r }: { r: Relectura }) {
  const cambios = [
    r.agregadas?.length ? `Agregadas: ${lista(r.agregadas)}.` : '',
    r.quitadas?.length ? `Quitadas: ${lista(r.quitadas)}.` : '',
    r.modificadas?.length ? `Modificadas (las destructivas piden reaprobación): ${lista(r.modificadas)}.` : '',
    r.version && r.version.antes !== r.version.ahora ? `Versión: ${r.version.antes ?? '—'} → ${r.version.ahora ?? '—'}.` : '',
  ].filter(Boolean)
  return (
    <Alert variant={r.conservado ? 'destructive' : 'default'}>
      <AlertDescription>
        {r.conservado
          ? `El manifiesto nuevo no es válido (${r.conservado}); se conserva el anterior.`
          : r.primera
            ? 'Manifiesto leído (no había uno previo para comparar).'
            : cambios.length === 0
              ? 'Manifiesto releído: sin cambios.'
              : `Manifiesto releído. ${cambios.join(' ')}`}
      </AlertDescription>
    </Alert>
  )
}
