// Cliente de /admin/api. La sesión viaja en una cookie HttpOnly; lo que no es GET lleva el token CSRF.
export class ApiError extends Error {
  status: number
  code: string
  data: Record<string, unknown>
  constructor(status: number, code: string, data: Record<string, unknown>) {
    super(code)
    this.status = status
    this.code = code
    this.data = data
  }
}

let csrf: string | null = null
export const setCsrf = (valor: string | null) => {
  csrf = valor
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (csrf && method !== 'GET') headers['X-CSRF'] = csrf
  const r = await fetch(`/admin/api${path}`, {
    method,
    credentials: 'same-origin',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, String(data.error ?? 'error'), data)
  return data as T
}

export type Yo = { email: string; rol: 'admin' | 'operador'; csrf: string | null }
export type Config = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
export type Secreto = { configurado: boolean; huella?: string; actualizado_en?: string }
export type Vista = {
  id: string
  version: number
  config: Config
  secretos: Record<string, Secreto>
  tool_estado: Record<string, boolean>
  activo: boolean
  error: string | null
  aviso?: string
}
export type Resumen = {
  id: string
  nombre: string
  habilitado: boolean
  activo: boolean
  version: number
  base_url: string
  manifiesto_ok: boolean
  tools_lectura: number
  ultimo_error: string | null
}
export type ToolVista = {
  nombre: string
  descripcion: string
  efecto: string
  accionable: boolean
  destructiva: boolean
  habilitada: boolean
}
export type Usuario = { id: string; email: string; rol: string; activo: boolean; bloqueado: boolean; ultimo_login: string | null }

const MENSAJES: Record<string, string> = {
  credenciales_invalidas: 'Email o contraseña incorrectos.',
  demasiados_intentos: 'Demasiados intentos. Espere unos minutos.',
  permiso_insuficiente: 'Su rol no permite esta acción.',
  registro_en_yaml: 'El registro está en modo YAML: las escrituras requieren ASISTENTE_REGISTRO=bd.',
  version_obsoleta: 'Alguien cambió este sistema mientras lo editaba. Se recargó la versión actual.',
  sistema_existente: 'Ya existe un sistema con ese id.',
  sistema_inexistente: 'El sistema no existe.',
  config_invalida: 'La configuración no es válida.',
  base_url_requiere_token:
    'Cambiar base_url exige cargar un token del manifiesto nuevo (o deshabilitar el sistema).',
  faltan_secretos: 'Faltan secretos para habilitar el sistema.',
  secreto_requerido: 'Un sistema habilitado necesita ese secreto; deshabilítelo primero.',
  secreto_invalido: 'Secreto inválido: sin espacios en los extremos ni vacío.',
  secreto_corto: 'El secreto HS256 debe tener al menos 32 bytes.',
  secreto_no_aplica: 'Ese secreto no aplica al algoritmo de autenticación actual.',
  sin_claves_maestras: 'El servidor no tiene ASISTENTE_CLAVES_MAESTRAS: no puede cifrar secretos.',
  tool_no_accionable: 'Esa escritura no declara confirmación o es destructiva: no se puede habilitar.',
  ultimo_admin: 'Debe quedar al menos un admin activo.',
  auto_cambio: 'No puede quitarse a sí mismo el acceso de admin.',
  usuario_invalido: 'Datos de usuario inválidos.',
  csrf: 'La sesión no es válida para escribir. Vuelva a entrar.',
}

export function mensaje(e: unknown): string {
  if (!(e instanceof ApiError)) return 'No se pudo contactar con el servidor.'
  const base = MENSAJES[e.code] ?? `Error: ${e.code}`
  const detalle = e.data.detalle
  const extra = Array.isArray(detalle)
    ? ' ' + detalle.map((d: { campo: string; mensaje: string }) => `${d.campo}: ${d.mensaje}`).join('; ')
    : typeof e.data.mensaje === 'string'
      ? ' ' + e.data.mensaje
      : Array.isArray(e.data.faltan)
        ? ' (' + e.data.faltan.join(', ') + ')'
        : ''
  return base + extra
}
