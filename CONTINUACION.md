Continúo el proyecto asistente-mvp (~/dev/asistente-mvp): un servicio de asistente conversacional multi-sistema (FastAPI, Postgres, widget Web Component, solo lectura). Responde siempre en español.

ANTES DE NADA, lee: PLAN_ASISTENTE.md (§16 checklist y Fase 4), README.md y la memoria del proyecto en ~/.claude/projects/-home-tiagosr-dev-asistente-mvp/memory/ (estado-proyecto, voz-decisiones, feedback-sin-commits, pruebas-y-e2e). No rehagas lo ya hecho ni reabras lo decidido.

ESTADO
- Hechas las Fases 0, 1 y 2: servicio, widget, verificador de conformidad, guía de tools, referencia PHP y mock.
- Hecho y probado en local el kit de despliegue (deploy/: VPS.md, deploy.sh con rollback que baja migraciones, backup.sh, Caddy/nginx de ejemplo), composes por entorno y CI ampliado (tests con Postgres, PHP, imagen prod).
- El despliegue en el VPS nuevo NO es aún: no lo propongas.
- Voz decidida: Web Speech del navegador como camino principal. El widget ya dicta con SpeechRecognition y lee con speechSynthesis (atributos idioma, voz, voz-motor). Acepté, por ahora, que el audio del dictado vaya a Google en Chrome; voz-motor="servidor" lo evita. Whisper small y Kokoro locales quedan descartados por calidad. Prefiero la voz es-ES.
- Ya hay un modelo de LLM elegido (no te he dicho cuál; no lo asumas).
- Hay un banco de pruebas de audio en herramientas/probar_audio/.
- Los cambios más recientes pueden estar sin commitear: mira git status. No hagas commits (un hook los bloquea): sugiéreme el mensaje y evita esa palabra dentro de los comandos de shell.

PENDIENTE (por prioridad, sin orden fijo)
1. Prueba manual del widget en Chrome real (voces es-UY/es-ES, lectura automática, dictado seguido de lectura, móvil).
2. Modo manos libres «Jarvis» (conversación continua con interrupción por voz). Hay que decidir conmigo: ¿envío automático al terminar de hablar o confirmo?, ¿palabra de activación o un botón de «conversar»?, y el eco de los parlantes. Ya validé en el banco que el detector de voz por energía interrumpe bien.
3. Purga de retención: Repo.purgar existe y tiene test, pero nada la invoca (falta tarea diaria que recorra los sistemas con su retencion_dias).
4. Test de arquitectura: core/ no debe importar api/, sistemas/ ni store/.
5. evals/ (set de ~30 preguntas por sistema, §12.2) y línea base con el modelo elegido, con medición de tokens y costo por pregunta.
6. Opcional: respaldo remoto de voz (PROVEEDORES_VOZ.md), solo si un cliente no puede usar Google o quiero una voz más natural.

CÓMO PROBAR (detalle en la memoria pruebas-y-e2e)
- docker compose -f docker-compose.dev.yml run --rm asistente sh -c 'ruff check . && pytest -q'
- El contenedor dev no tiene node: los tests de widget que ejecutan JS se saltan salvo que se instale nodejs ahí.
- e2e con el MCP de Playwright (tests_e2e/README.md); tras editar widget.js hay que reiniciar el contenedor asistente.

Empieza resumiéndome en 5 líneas qué entendiste del estado y proponme por dónde seguir, sin tocar nada todavía.
