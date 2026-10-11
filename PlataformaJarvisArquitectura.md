# Plataforma Jarvis — Arquitectura del Sistema

Oct 10, 2026 · @Tiago Silva

El proyecto evoluciona de un widget asistente embebido en el navegador hacia una plataforma con aplicacion de escritorio descargable, con dos caras: un panel de administracion interno y una app para empresas clientes y sus usuarios.

## Vision general

Hoy el producto es un widget asistente embebido en el navegador (JavaScript) que permite consultar datos y ejecutar acciones sobre el sistema en el que esta instalado. El objetivo es evolucionarlo hacia una plataforma con dos caras bien diferenciadas:

1. **Panel de administracion** — uso interno nuestro, para gestionar toda la plataforma.
2. **Aplicacion de escritorio del cliente** — descargable por las empresas y sus usuarios finales, en Windows, macOS y Linux.

El asistente opera a traves de tools / integraciones que el propio cliente implementa segun un contrato que nosotros definimos.

## Panel de administracion (lado interno)

Es la consola central desde la que nosotros gestionamos toda la plataforma. Sus capacidades clave:

- **Gestion de empresas:** registrar, editar y dar de baja a las empresas clientes.
- **Usuarios por empresa:** cada empresa tiene su propio conjunto de usuarios finales; el panel permite verlos y administrarlos agrupados por empresa.
- **Habilitar / deshabilitar integraciones por empresa:** control granular de que integraciones (tools) quedan activas para cada empresa, segun lo que haya contratado. Esta es la pieza central del panel.
- **Listado de tools por empresa:** poder ver que tools tiene cada empresa. Deseable, pero no critico.
- **Permisos administrativos:** definir que acciones puede realizar cada administrador dentro del panel.

La jerarquia de datos es: la plataforma (nosotros) contiene empresas; cada empresa contiene tanto sus usuarios finales como su conjunto de integraciones habilitadas.

## Aplicacion de escritorio del cliente

Es la evolucion del widget de JavaScript actual, ahora como aplicacion nativa descargable e instalable en la computadora, multiplataforma (Windows, macOS y Linux).

- Reproduce la experiencia del widget actual, pero como app instalable en la PC.
- Se conecta a la configuracion de su empresa: solo expone las integraciones que el panel de administracion haya habilitado para esa empresa.
- Permite al usuario final conversar con Jarvis y ejecutar las tools disponibles para su empresa.
- Multiplataforma desde el inicio: Windows, macOS y Linux.

## Modelo de tools e integraciones (contrato)

El corazon del sistema es un modelo de contrato que desacopla nuestra plataforma de la implementacion de cada cliente:

- Nosotros definimos un **archivo de contrato** (una especificacion / interfaz) que describe como deben ser las tools.
- **El cliente implementa las tools en su propio backend**, cumpliendo ese contrato. No nos involucramos en la implementacion interna; solo exigimos que respeten la forma acordada.
- Nosotros **orquestamos y consultamos** contra esas tools del lado del cliente.

### Formato del contrato (hibrido)

- Un **esquema JSON propio** donde guardamos la definicion de cada tool.
- Elementos **compatibles con el function calling de OpenAI**, de modo que las definiciones puedan alimentar directamente al LLM.

Asi, un mismo contrato sirve para dos propositos a la vez: documentar que debe implementar el cliente, y alimentar al modelo con las definiciones de las tools que puede invocar.

### Infraestructura central

La plataforma ya cuenta con una infraestructura central compartida (un unico cerebro, ya implementado), donde la separacion entre empresas se da por permisos y propiedad de los datos, no por instancias aisladas. Dentro de esa infraestructura existe un punto de configuracion en YAML que actua como registro central de integraciones: declara que sistemas estan integrados en cada momento. Desde el panel de administracion se activa o desactiva cuales de esas integraciones aplican a cada empresa.

### Ventajas

- **Desacoplamiento:** no dependemos del backend de cada cliente.
- **Flexibilidad:** cada cliente adapta las tools a su realidad mientras cumpla el contrato.
- **Escalabilidad:** se habilitan o deshabilitan capacidades por empresa, casi como un marketplace de integraciones.

## Proximos pasos sugeridos

- [ ] Definir el versionado de los contratos y como se valida que la implementacion de un cliente cumple el contrato.
- [ ] Disenar el esquema de permisos y roles del panel de administracion.
- [ ] Elegir el framework para la app de escritorio multiplataforma (por ejemplo Electron, Tauri u otro).
- [ ] Detallar el flujo de autenticacion entre empresa, usuario y plataforma.
- [ ] Definir como se distribuyen las actualizaciones de la app a los clientes.
