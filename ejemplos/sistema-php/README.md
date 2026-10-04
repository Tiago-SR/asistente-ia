# Sistema PHP de referencia

Implementación del [contrato v1](../../contrato/CONTRATO.md) en PHP 8.2+ para que un equipo con CodeIgniter 4 (p. ej. SGAgro) la copie y adapte. Tools de ejemplo: dos de lectura y una de escritura (solo para la prueba de rechazo), datos ficticios en memoria (ana y beto, los mismos del [mock Python](../sistema-mock/app.py)).

## Por qué un router mínimo y no CI4

Un proyecto CI4 completo añade esqueleto, `writable/`, `spark` y decenas de MB de `vendor` que tapan lo único que importa: la lógica del contrato. Por eso:

- `src/` es PHP puro, sin dependencias del framework (solo `firebase/php-jwt` y `opis/json-schema`).
- `AsistenteController` recibe datos simples (cabecera `Authorization`, cuerpo crudo, login de sesión) y devuelve un objeto `Respuesta`. No usa `$_SERVER` ni `echo`, así que se prueba sin servidor y pasa casi tal cual a un controlador CI4.
- `public/index.php` es el único archivo que conoce HTTP: el router, que en CI4 reemplazan `Routes.php` y la clase `Response`.

```
public/index.php                    router + página de demostración con <asistente-chat>
src/Config.php                      lee variables de entorno
src/Controllers/AsistenteController salud, token, manifiesto, ejecutar
src/Auth/EmisorToken.php            emite el JWT (HS256 o RS256)
src/Auth/ValidadorToken.php         firma, alg fijo, iss, aud, exp, claims obligatorios
src/Tools/*                         tools de ejemplo (guía: ../../contrato/GUIA_TOOLS.md)
src/Datos/Repositorio.php           datos ficticios (aquí iría tu base de datos)
tests/ContratoTest.php              rechazos de token, aislamiento, scope, escritura, parámetros
```

## Ejecutar

```sh
# Servicio (puerto 8203) desde la raíz del repo
docker compose -f docker-compose.dev.yml up -d --build sistema-php
curl localhost:8203/asistente/salud
# Página con el widget: http://localhost:8203/?usuario=ana   (o beto)

# Tests (PHPUnit, en contenedor; no hace falta PHP en el host)
docker build --target test -t sistema-php-test ejemplos/sistema-php && docker run --rm sistema-php-test

# Verificador de conformidad
export V_MANIFIESTO=manifiesto-php V_SECRETO=secreto-php-0123456789-0123456789-ab
python herramientas/verificar_sistema.py --base-url http://localhost:8203 \
  --token-url "http://localhost:8203/asistente/token?usuario=ana" \
  --token-url-otro "http://localhost:8203/asistente/token?usuario=beto" \
  --token-manifiesto-env V_MANIFIESTO --secreto-firma-env V_SECRETO
```

Para que el asistente lo use, copiá la entrada de [`config/sistemas.example.yaml`](../../config/sistemas.example.yaml) a `config/sistemas.yaml` y poné `PHP_SECRETO` y `PHP_MANIFEST_TOKEN` en el `.env` del asistente (los valores de arriba, solo para desarrollo).

## Credenciales (sección 6 del contrato)

Son dos, independientes, y **ninguna va en el repositorio** (los valores de `docker-compose.dev.yml` son ficticios y solo para desarrollo):

| Variable | Qué es |
|---|---|
| `SISTEMA_SECRETO` | Clave de firma HS256, 32 bytes o más (`openssl rand -hex 32`). `php-jwt` ≥ 7 rechaza claves más cortas. |
| `SISTEMA_CLAVE_PRIVADA` / `SISTEMA_CLAVE_PRIVADA_ARCHIVO` | Con `SISTEMA_ALG=RS256`: clave privada PEM (RSA de 2048 bits o más). |
| `SISTEMA_TOKEN_MANIFIESTO` | Credencial con la que el asistente lee `/asistente/tools`. Se compara con `hash_equals`. |

Otras variables: `SISTEMA_ID` (= `iss` = `id` del registro), `SISTEMA_AUDIENCIA` (= `aud`, por defecto `asistente`), `SISTEMA_NOMBRE`, `ASISTENTE_URL` (solo la página de demo).

**RS256:** generá el par (`openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out priv.pem; openssl pkey -in priv.pem -pubout -out pub.pem`), dejá `priv.pem` solo en el sistema y poné el contenido de `pub.pem` en la variable `PHP_PUBKEY` del asistente (`clave_publica_env` en el registro, `algoritmo: RS256`). El verificador se ejecuta con `--algoritmo-firma RS256` y `V_SECRETO` con la privada.

## Reglas que hay que conservar al adaptarlo

- **`sub` = id estable y único por persona.** Usá la clave primaria del usuario, nunca el email, el login ni el nombre: pueden cambiar o reasignarse, y entonces una persona heredaría las conversaciones de otra. Un `sub` repetido para dos personas mezcla sus historiales.
- **La identidad sale de la sesión, nunca de un parámetro.** `?usuario=ana` solo se atiende con `APP_ENV=local`; en cualquier otro entorno se ignora. Una ruta de token pública emite tokens para cualquiera.
- **Algoritmo fijo al validar** (el de la configuración), nunca el que declara el token; así se rechazan `alg=none` y la confusión HS/RS.
- **Tools solo con `sub`:** el usuario viene del claim, el recurso se busca dentro de lo que ese usuario puede ver, y "no existe" y "es de otro" dan el mismo `no_encontrado`.
- **Respuestas HTTP:** token inválido o vencido → `401`; scope insuficiente, token de manifiesto en la ejecución, JWT de usuario en el manifiesto, tool de escritura → `403`; errores de negocio → `200` con `ok: false`.

## Adaptarlo a CodeIgniter 4

1. `composer require firebase/php-jwt opis/json-schema` y copiá `src/` a `app/Libraries/Asistente/` (cambiá el namespace).
2. Rutas (`app/Config/Routes.php`):
   ```php
   $routes->group('asistente', static function ($routes) {
       $routes->get('salud', 'Asistente::salud');
       $routes->get('token', 'Asistente::token', ['filter' => 'session']);   // tu filtro de login
       $routes->get('tools', 'Asistente::manifiesto');
       $routes->post('tools/(:segment)', 'Asistente::ejecutar/$1');
   });
   ```
3. Un controlador `Asistente` que llame a los métodos de `AsistenteController`: pasá `$this->request->getHeaderLine('Authorization')`, `$this->request->getBody()` y el id de `session()`; devolvé `$this->response->setStatusCode($r->estado)->setJSON($r->cuerpo)`.
4. Excluí `asistente/tools*` y `asistente/salud` del filtro CSRF (`$globals['before']`) y de tu filtro de sesión: se autentican con su propio token. `asistente/token` sí lleva sesión.
5. Reemplazá `Repositorio` por tus modelos y escribí tus tools siguiendo la [guía](../../contrato/GUIA_TOOLS.md). Cada una queda en `src/Tools/` e implementa `Herramienta`; se registra en `Fabrica` (en CI4, `Config\Services`).
6. Ejecutá el verificador contra el sistema real (con `--cabecera-token-env` para la cookie de sesión) antes de habilitarlo.

## Tools de ejemplo

| Tool | Efecto | Qué muestra |
|---|---|---|
| `listar_establecimientos` | lectura | listado con filtro `texto` y acciones `ui` |
| `resumen_establecimiento` | lectura | búsqueda por id: "no existe" y "es de otro" dan el mismo `no_encontrado` |
| `resumen_por_cultivo` | lectura | agregada del lado del sistema (`superficie_ha` por cultivo + total), sin parámetros ni geometrías |
| `eliminar_establecimiento` | **escritura** | figura en el manifiesto y el controlador la rechaza con `403` con scope de lectura; aunque se ejecutara no hace nada. Existe para que el verificador compruebe esa capa |

## Probado de punta a punta

Con `docker-compose.dev.yml` (asistente, Postgres y `sistema-php`) y la entrada `sistema-php` en `config/sistemas.yaml` (origen `http://localhost:8203`): ana y beto reciben su token del sistema, cada uno ve solo sus datos, sus conversaciones son distintas y `GET`/`DELETE /v1/conversaciones/{id}` o `POST /v1/chat` con el id del otro dan `404`. Igual con RS256 (`clave_publica_env`): el token sale con `alg: RS256` y un HS256 firmado con otro secreto da `401`. Esa prueba se hizo con un LLM falso (que pide `resumen_por_cultivo` y repite su resultado), así que valida el circuito y no la calidad de las respuestas del modelo.
