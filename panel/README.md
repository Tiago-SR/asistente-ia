# Panel de administración

React + TypeScript + Vite + shadcn/ui (Tailwind v4). Se sirve en `/panel`; habla con `/admin/api`.
Dev, build y despliegue: ver la sección «Panel de administración» del README de la raíz.

- `npm run dev` (proxy de `/admin/api` hacia `PANEL_API`), `npm run build`, `npm run lint`.
- Nuevos componentes: `npx shadcn@latest add <componente>`.
- Nunca renderizar con `dangerouslySetInnerHTML` datos del manifiesto: los escribe un tercero.
