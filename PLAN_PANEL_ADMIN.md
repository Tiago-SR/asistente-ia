# Plan: panel de administración de sistemas (Jarvis)

> Solo quedan los pendientes; lo resuelto se quitó del documento (2026-10-19).
>
> Reglas del proyecto para quien continúe: responder en español, **no hacer `git commit`** (sugerir el mensaje),
> no usar worktrees salvo en jobs en segundo plano. Ver la memoria del proyecto (`pruebas-y-e2e`, `feedback-sin-commits`).

## Pendiente

- **Rol `admin` en los endpoints de escritura.** Aplicar `rol == admin` a los endpoints de escritura de la Fase 3
  (base_url, auth, llm) y a la gestión de usuarios (hoy los admite cualquier rol, incl. `operador`).
- **Retención de `admin_auditoria`.** Política sin decidir (y la de `evento_uso`, si no está cerrada).
- **Cambio de contraseña propia desde el panel.** Hoy solo existe la CLI `cambiar-clave-admin`.
