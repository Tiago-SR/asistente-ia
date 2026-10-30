import { useCallback, useEffect, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { CanalEstado } from '@/components/CanalEstado'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsiblePanel, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ArrowLeftIcon, ChevronDownIcon } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { api, ApiError, mensaje, type Config, type ToolVista, type Vista, type Yo } from '@/lib/api'

const CAMPOS_SECRETOS: Record<string, string> = {
  token_manifiesto: 'Token del manifiesto (el conector lo envía a base_url)',
  auth_hs256: 'Secreto HS256 (solo si el algoritmo es HS256, 32 bytes o más)',
  llm_api_key: 'API key del LLM propio (solo con llm.base_url propio)',
  token_canal: 'Token de canal (el sistema lo exige en /asistente/canal/*; vincular y emitir tokens por mensaje)',
  wa_token: 'WhatsApp (Meta): token permanente del System User',
  wa_app_secret: 'WhatsApp (Meta): App Secret (valida la firma del webhook)',
  wa_verify_token: 'WhatsApp (Meta): verify token (handshake del webhook)',
  owa_api_key: 'OpenWA: API key (cabecera X-API-Key)',
  owa_webhook_secret: 'OpenWA: secret del webhook (firma HMAC; sin él el canal no se activa)',
}

// Secretos del canal de mensajería: van dentro de su sección, no en «Secretos».
const SECRETOS_CANAL_UI = ['token_canal', 'wa_token', 'wa_app_secret', 'wa_verify_token', 'owa_api_key', 'owa_webhook_secret']

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
  const [prueba, setPrueba] = useState<string | null>(null)
  const [aprobar, setAprobar] = useState<ToolVista | null>(null)
  const [nombreConf, setNombreConf] = useState('')
  const [elegirAcc, setElegirAcc] = useState(false)
  const [verTools, setVerTools] = useState(false)
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
  // Canal de mensajería (strategy): elegir proveedor habilita sus campos y sus secretos; «ninguno» lo quita entero.
  const proveedor = String(leer(config, 'canal_mensajeria.proveedor') ?? '')
  const elegirProveedor = (p: string) => {
    const c = structuredClone(config)
    if (p === '') delete c.canal_mensajeria
    else c.canal_mensajeria = { ...(c.canal_mensajeria as object | undefined), proveedor: p }
    setConfig(c)
  }
  const probarCanal = async () => {
    setPrueba(null)
    try {
      const r = await api<{ ok: boolean; numero?: string; nombre?: string; error?: string }>('POST', `/sistemas/${id}/canal/probar`)
      setPrueba(r.ok ? `Conexión correcta: ${r.nombre ?? ''} ${r.numero ?? ''}` : `Falló: ${r.error}`)
    } catch (e) {
      setPrueba(mensaje(e))
    }
  }
  const interruptor = (ruta: string, etiqueta: string) => (
    <div className="flex items-center gap-3">
      <Switch id={ruta} disabled={!puede} checked={Boolean(leer(config, ruta))}
        onCheckedChange={(v) => setConfig(poner(config, ruta, v))} />
      <Label htmlFor={ruta} className="h-[18.4px]">{etiqueta}</Label>
    </div>
  )

  // un número vacío equivale a null (techo global): borrar un campo que ya era null no es un cambio
  const igual = (x: unknown, y: unknown) => JSON.stringify(x, (_, v) => (v === '' ? null : v)) === JSON.stringify(y, (_, v) => (v === '' ? null : v))
  const accionesCanal = (leer(config, 'canal_mensajeria.acciones') as string[] | undefined) ?? []
  const ofrecibles = (tools?.tools ?? []).filter((t) => t.habilitada && t.accionable && !t.destructiva)
  const bloqueadasCanal = (leer(config, 'canal_mensajeria.lecturas_bloqueadas') as string[] | undefined) ?? []
  const activaEnCanal = (t: ToolVista) => (t.efecto === 'escritura' ? accionesCanal.includes(t.nombre) : !bloqueadasCanal.includes(t.nombre))
  const alternarEnCanal = (t: ToolVista, v: boolean) => {
    const [campo, lista, agregar] = t.efecto === 'escritura'
      ? ['acciones', accionesCanal, v] : ['lecturas_bloqueadas', bloqueadasCanal, !v]
    setConfig(poner(config, `canal_mensajeria.${campo}`, agregar ? [...lista, t.nombre] : lista.filter((x) => x !== t.nombre)))
  }
  const hayCambios = !igual(config, vista.config) || ['token_manifiesto', 'llm_api_key', 'auth_hs256'].some((k) => nuevos[k])

  const filaSecreto = (c: string, etiqueta: string) => {
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
  }

  const guardar = (ev?: React.FormEvent) => {
    ev?.preventDefault()
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
        <Button variant="ghost" onClick={() => ir('/sistemas')}><ArrowLeftIcon className="size-4" />Sistemas</Button>
        <h2 className="text-xl font-semibold">{String(vista.config.nombre)}</h2>
        <span className="font-mono text-sm text-muted-foreground">{id}</span>
        {vista.config.habilitado ? (vista.activo ? <Badge>activo</Badge> : <Badge variant="destructive">con error</Badge>) : <Badge variant="secondary">deshabilitado</Badge>}
        <span className="text-xs text-muted-foreground">versión {vista.version}</span>
        <div className="ml-auto flex items-center gap-3">
          {interruptor('habilitado', 'Habilitado')}
          {puede && hayCambios && <Button type="button" size="sm" onClick={() => guardar()}>Guardar</Button>}
        </div>
      </div>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      {ok && <Alert><AlertDescription>{ok}</AlertDescription></Alert>}
      {vista.error && <Alert variant="destructive"><AlertDescription>{vista.error}</AlertDescription></Alert>}
      {!puede && <Alert><AlertDescription>Su rol es de solo lectura.</AlertDescription></Alert>}
      {vista.config.canal_mensajeria && !vista.secretos.token_canal?.configurado && (
        <Alert>
          <AlertDescription>
            Hay un canal de mensajería configurado pero falta el token de canal: sin él el asistente no puede vincular
            números ni emitir tokens por mensaje, y el canal no responde. Cárguelo en la sección Canal de mensajería.
          </AlertDescription>
        </Alert>
      )}

      <form onSubmit={guardar} className="grid gap-6">
        <Seccion titulo="Configuración">
          <div className="grid gap-4">
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
              <Select id="auth.algoritmo" disabled={!puede} value={String(leer(config, 'auth.algoritmo') ?? '')}
                onChange={(e) => {
                  const a = e.target.value
                  let c = poner(config, 'auth.algoritmo', a)
                  // HS256 no admite fuente de clave pública; al salir de HS256 el secreto nuevo ya no aplica
                  if (a === 'HS256') c = poner(poner(c, 'auth.jwks_url', ''), 'auth.clave_publica', '')
                  else setNuevos({ ...nuevos, auth_hs256: '' })
                  setConfig(c)
                }}>
                {['RS256', 'EdDSA', 'HS256'].map((a) => <option key={a}>{a}</option>)}
              </Select>
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
            <div className="grid gap-2">
              <Label htmlFor="prompt_dominio">Prompt de dominio</Label>
              <Textarea id="prompt_dominio" disabled={!puede} value={String(leer(config, 'prompt_dominio') ?? '')}
                onChange={(e) => setConfig(poner(config, 'prompt_dominio', e.target.value))} />
            </div>
            {puede && urlCambio && (
              <Alert>
                <AlertDescription className="grid gap-2">
                  Cambiar base_url descarta el token del manifiesto actual: cárguelo de nuevo aquí o deshabilite el sistema.
                  {vista.secretos.token_canal?.configurado && ' También descarta el token de canal: cárguelo de nuevo en la sección Canal de mensajería tras guardar.'}
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
          </div>
        </Seccion>

        <Seccion titulo="Funciones y adjuntos">
          <div className="grid gap-4">
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
            {puede && <Button type="submit" className="w-fit" disabled={!hayCambios}>Guardar</Button>}
          </div>
        </Seccion>

        <Seccion titulo="Límites y retención">
          <div className="grid gap-4">
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
            {puede && <Button type="submit" className="w-fit" disabled={!hayCambios}>Guardar</Button>}
          </div>
        </Seccion>
      </form>

      <Seccion titulo="Canal de mensajería (WhatsApp)">
        <form onSubmit={guardar} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="canal">Canal de mensajería</Label>
              <Select id="canal" disabled={!puede} value={proveedor}
                onChange={(e) => elegirProveedor(e.target.value)}>
                <option value="">Ninguno</option>
                <option value="meta">WhatsApp (Meta Cloud API)</option>
                <option value="openwa">WhatsApp (OpenWA, no oficial)</option>
              </Select>
            </div>
            {proveedor === 'openwa' && (
              <div className="grid gap-4 rounded-md border p-4">
                <Alert variant="destructive">
                  <AlertDescription>
                    No oficial: automatiza WhatsApp Web y puede provocar el baneo del número. Sin botones: las escrituras se confirman escribiendo un código. Uso recomendado: pruebas.
                  </AlertDescription>
                </Alert>
                {campo('canal_mensajeria.base_url', 'URL del servidor OpenWA (un host interno debe figurar en ASISTENTE_HOSTS_INTERNOS_PERMITIDOS)')}
                {campo('canal_mensajeria.session_id', 'ID de la sesión de OpenWA')}
                <p className="text-sm text-muted-foreground">
                  Registre en OpenWA un webhook a <span className="font-mono">/canal/{id}/webhook</span> con el evento
                  message.received y el mismo secret que cargue abajo. Active RESOLVE_LID_TO_PHONE=true en OpenWA.
                </p>
              </div>
            )}
            {proveedor !== '' && (
              <div className="flex items-center gap-3">
                {puede && (
                  <Button type="button" variant="outline" disabled={!vista.config.canal_mensajeria || hayCambios}
                    onClick={() => void probarCanal()}>Probar conexión</Button>
                )}
                {prueba && <span className="text-sm">{prueba}</span>}
                {(!vista.config.canal_mensajeria || hayCambios) && (
                  <span className="text-sm text-muted-foreground">Guarde los cambios para probar.</span>
                )}
              </div>
            )}
            {proveedor !== '' && !hayCambios && vista.config.canal_mensajeria && <CanalEstado id={id} puede={puede} />}
            {proveedor === 'meta' && (
              <div className="grid gap-4 rounded-md border p-4">
                {campo('canal_mensajeria.phone_number_id', 'Phone number ID (no es el teléfono)')}
                {campo('canal_mensajeria.graph_version', 'Versión de Graph (vacío = v23.0)')}
                <p className="text-sm text-muted-foreground">
                  Webhook para Meta: <span className="font-mono">/canal/{id}/webhook</span> bajo el dominio público. Cargue abajo
                  los tres secretos de WhatsApp. Una App de Meta por sistema.
                </p>
              </div>
            )}
          {puede && <Button type="submit" className="w-fit" disabled={!hayCambios}>Guardar</Button>}
        </form>
        {proveedor !== '' && (
          <div className="mt-6 grid gap-4">
            <h3 className="text-sm font-medium">Secretos del canal</h3>
            <p className="text-sm text-muted-foreground">Se guardan cifrados. Se pueden escribir y reemplazar, nunca leer.</p>
            {Object.entries(CAMPOS_SECRETOS).filter(([c]) => c in vista.secretos && SECRETOS_CANAL_UI.includes(c)).map(([c, etiqueta]) => filaSecreto(c, etiqueta))}
          </div>
        )}
      </Seccion>

      <Seccion titulo="Secretos">
        <div className="grid gap-4">
          <p className="text-sm text-muted-foreground">Se guardan cifrados. Se pueden escribir y reemplazar, nunca leer.</p>
          {Object.entries(CAMPOS_SECRETOS).filter(([c]) => c in vista.secretos && !SECRETOS_CANAL_UI.includes(c)).map(([c, etiqueta]) => filaSecreto(c, etiqueta))}
        </div>
      </Seccion>

      <Seccion titulo="Tools">
        <div className="grid gap-3">
          <Button type="button" size="sm" variant="outline" className="w-fit" disabled={releyendo} onClick={() => void releer()}>{releyendo ? 'Releyendo…' : 'Releer manifiesto'}</Button>
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
          {tools && tools.tools.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" variant="outline" onClick={() => setVerTools(true)}>
                Tools del sistema ({tools.tools.filter((t) => t.habilitada).length} de {tools.tools.length} habilitadas)
              </Button>
              <span className="text-sm text-muted-foreground">Los cambios se aplican al instante.</span>
            </div>
          )}
          {proveedor !== '' && (
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" variant="outline" disabled={!puede} onClick={() => setElegirAcc(true)}>
                Tools por WhatsApp
              </Button>
              <span className="text-sm text-muted-foreground">
                Escrituras: {accionesCanal.length ? accionesCanal.join(', ') : 'ninguna'}
                {bloqueadasCanal.length > 0 && ` · Lecturas bloqueadas: ${bloqueadasCanal.join(', ')}`}
              </span>
            </div>
          )}
          {tools && tools.huerfanas.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Con excepción pero ausentes del manifiesto: {tools.huerfanas.map((h) => `${h.nombre} (${h.habilitada ? 'sí' : 'no'})`).join(', ')}
            </p>
          )}
        </div>
      </Seccion>

      <Dialog open={verTools} onOpenChange={setVerTools}>
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>Tools del sistema</DialogTitle>
            <DialogDescription>
              Marque las que el asistente puede usar (pase el mouse por un nombre para ver qué hace). Cada cambio se
              guarda al instante. Las destructivas piden aprobación y las escrituras «no accionables» no se pueden activar.
            </DialogDescription>
          </DialogHeader>
          <div className="grid max-h-[60vh] gap-4 overflow-y-auto overflow-x-hidden">
            <RejillaTools tools={tools?.tools ?? []} activa={(t) => t.habilitada}
              deshabilitada={(t) => !puede || (t.efecto === 'escritura' && !t.accionable)}
              alternar={(t, v) => {
                if (v && t.destructiva) {
                  setNombreConf('')
                  setAprobar(t)
                } else void escribir(() => api('PUT', `/sistemas/${id}/tools/${t.nombre}`, { habilitada: v }), `Tool ${t.nombre} ${v ? 'habilitada' : 'deshabilitada'}.`)
              }}
              sufijo={(t) => (
                <>
                  {t.destructiva && <Badge variant="destructive">destructiva</Badge>}
                  {t.efecto === 'escritura' && !t.accionable && <Badge variant="outline">no accionable</Badge>}
                  {t.aprobacion === 'obsoleta' && <Badge variant="outline">reaprobar</Badge>}
                </>
              )} />
          </div>
          <DialogFooter>
            <Button type="button" onClick={() => setVerTools(false)}>Listo</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={elegirAcc} onOpenChange={setElegirAcc}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Tools por WhatsApp</DialogTitle>
            <DialogDescription>
              Marque cuáles de las tools habilitadas en el widget también se ofrecen por WhatsApp (pase el mouse por un
              nombre para ver qué hace). Las lecturas vienen marcadas; las escrituras hay que marcarlas y cada una se
              confirma en el chat antes de ejecutarse. Las destructivas nunca se ofrecen por este canal. Los cambios se
              aplican al guardar la configuración.
            </DialogDescription>
          </DialogHeader>
          <div className="grid max-h-[50vh] grid-cols-1 gap-x-4 gap-y-2 overflow-y-auto overflow-x-hidden sm:grid-cols-2">
            <RejillaTools tools={ofrecibles} activa={activaEnCanal} alternar={alternarEnCanal} />
            {tools && ofrecibles.length === 0 && (
              <p className="col-span-full text-sm text-muted-foreground">No hay tools habilitadas en el widget.</p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setElegirAcc(false)}>Cerrar</Button>
            <Button type="button" disabled={!hayCambios || !puede} onClick={() => { setElegirAcc(false); guardar() }}>Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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

// Tarjeta colapsable, cerrada al entrar: el título y el chevron (a la derecha) pliegan todo.
function Seccion({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <Card>
      <Collapsible>
        <CardHeader>
          <CollapsibleTrigger className="group flex w-full items-center justify-between text-left">
            <CardTitle>{titulo}</CardTitle>
            <ChevronDownIcon className="size-4 transition-transform group-data-[panel-open]:rotate-180" />
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsiblePanel>
          <CardContent className="pt-4">{children}</CardContent> {/* el Collapsible rompe el gap entre cabecera y contenido de la tarjeta */}
        </CollapsiblePanel>
      </Collapsible>
    </Card>
  )
}

// Rejilla de tools en dos grupos (lecturas y escrituras): checkbox con el nombre y, al pasar el mouse, su descripción.
function RejillaTools({ tools, activa, alternar, deshabilitada, sufijo }: {
  tools: ToolVista[]
  activa: (t: ToolVista) => boolean
  alternar: (t: ToolVista, v: boolean) => void
  deshabilitada?: (t: ToolVista) => boolean
  sufijo?: (t: ToolVista) => React.ReactNode
}) {
  return (
    <TooltipProvider delay={200}>
      {(['lectura', 'escritura'] as const).map((efecto) => {
        const grupo = tools.filter((t) => t.efecto === efecto)
        return grupo.length > 0 && (
          <div key={efecto} className="col-span-full grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
            <p className="col-span-full text-sm font-medium">{efecto === 'lectura' ? 'Lecturas' : 'Escrituras'}</p>
            {grupo.map((t) => (
              // nombre y descripción los escribe un tercero: siempre como texto
              <Tooltip key={t.nombre}>
                <TooltipTrigger render={<label className="flex min-w-0 cursor-pointer items-center gap-2 font-mono text-sm" />}>
                  <Checkbox checked={activa(t)} disabled={deshabilitada?.(t)}
                    onChange={(e) => alternar(t, e.target.checked)} />
                  <span className="truncate">{t.nombre}</span>
                  {sufijo?.(t)}
                </TooltipTrigger>
                <TooltipContent><span className="font-mono">{t.nombre}</span>: {t.descripcion}</TooltipContent>
              </Tooltip>
            ))}
          </div>
        )
      })}
    </TooltipProvider>
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
