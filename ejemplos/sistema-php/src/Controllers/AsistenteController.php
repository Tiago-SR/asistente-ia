<?php
declare(strict_types=1);

namespace Ejemplo\Controllers;

use Ejemplo\Auth\EmisorToken;
use Ejemplo\Auth\TokenInvalido;
use Ejemplo\Auth\ValidadorToken;
use Ejemplo\Config;
use Ejemplo\Datos\Almacen;
use Ejemplo\Datos\Repositorio;
use Ejemplo\Respuesta;
use Ejemplo\Tools\Accion;
use Ejemplo\Tools\Herramienta;
use Ejemplo\Tools\Registro;
use Ejemplo\Tools\Resultado;

/**
 * Los endpoints del contrato (más la propuesta de la sección 8). Cada método recibe datos simples y devuelve una Respuesta,
 * sin tocar $_SERVER ni echo: así se prueba sin servidor y se porta a un controlador de CI4.
 */
final class AsistenteController
{
    public function __construct(
        private readonly Config $cfg,
        private readonly Repositorio $repo,
        private readonly Almacen $almacen,
        private readonly Registro $registro,
        private readonly EmisorToken $emisor,
        private readonly ValidadorToken $validador,
    ) {
    }

    public function salud(): Respuesta
    {
        return Respuesta::json(['ok' => true]);
    }

    /**
     * GET /asistente/token (sección 1). La identidad sale de la sesión del sistema.
     * Con `confirmacion` y `huella` (sección 8.3) emite el token de escritura de esa confirmación.
     * @param string|null $usuarioSesion login del usuario con sesión iniciada (null si no hay)
     * @param string|null $usuarioPrueba parámetro `?usuario=`: SOLO se atiende con APP_ENV=local
     */
    public function token(?string $usuarioSesion, ?string $usuarioPrueba = null, ?string $confirmacion = null, ?string $huella = null): Respuesta
    {
        $login = $this->cfg->local && $usuarioPrueba !== null ? $usuarioPrueba : $usuarioSesion;
        if ($login === null) {
            return Respuesta::http(401, 'sin sesión');
        }
        $usuario = $this->repo->usuarioPorLogin($login);
        if ($usuario === null) { // también: usuarios sin permiso de usar el asistente
            return Respuesta::http(403, 'usuario sin acceso al asistente');
        }
        if ($confirmacion === null && $huella === null) {
            return Respuesta::json($this->emisor->emitir($usuario));
        }
        if ($confirmacion === null || $huella === null || !preg_match('/^[A-Za-z0-9._-]{1,128}$/', $confirmacion)) {
            return Respuesta::http(400, 'confirmacion y huella van juntas');
        }
        // Solo para una propuesta que este sistema produjo, vigente y de este usuario. Un usuario sin
        // permiso de escritura (rol de solo consulta, p. ej.) también recibiría 403 aquí.
        $propuesta = $this->almacen->propuestaVigente($huella);
        if ($propuesta === null || $propuesta['sub'] !== $usuario['id']) {
            return Respuesta::http(403, 'no hay una propuesta vigente con esa huella');
        }
        return Respuesta::json($this->emisor->emitirEscritura($usuario, $propuesta['tool'], $huella, $confirmacion));
    }

    /** GET /asistente/tools (sección 2): solo con la credencial de manifiesto. */
    public function manifiesto(?string $authorization): Respuesta
    {
        $bearer = self::bearer($authorization);
        if ($bearer === null) {
            return Respuesta::http(401, 'falta Authorization: Bearer');
        }
        if (hash_equals($this->cfg->tokenManifiesto, $bearer)) {
            return Respuesta::json($this->registro->manifiesto());
        }
        try { // un JWT de usuario es una credencial legítima usada donde no corresponde
            $this->validador->validar($bearer);
            return Respuesta::http(403, 'un token de usuario no sirve para leer el manifiesto');
        } catch (TokenInvalido) {
            return Respuesta::http(401, 'credencial de manifiesto inválida');
        }
    }

    /**
     * POST /asistente/tools/{nombre}/propuesta (sección 8.2): valida y resume una acción SIN escribir
     * nada. Token de LECTURA. El sistema recuerda la huella hasta que vence la propuesta.
     */
    public function propuesta(string $nombre, ?string $authorization, string $cuerpoCrudo): Respuesta
    {
        $claims = $this->autenticar($authorization, 'asistente:lectura', $falla);
        if ($claims === null) {
            return $falla;
        }
        $tool = $this->registro->buscar($nombre);
        if (!$tool instanceof Accion) {
            return Respuesta::json(Resultado::error('no_disponible', "tool desconocida: $nombre"));
        }
        [$parametros, $falla] = $this->parametros($tool, $cuerpoCrudo);
        if ($parametros === null) {
            return $falla;
        }
        $sub = $claims['sub'];
        $p = $tool->preparar($parametros, $sub);
        if (($p['ok'] ?? null) === false) {
            return Respuesta::json($p);
        }
        $huella = hash('sha256', Almacen::canonico([
            'sub' => $sub, 'tool' => $nombre, 'parametros' => $parametros, 'version' => $p['version'],
        ]));
        $this->almacen->guardarPropuesta($huella, $sub, $nombre, $parametros, $p['version'], time() + Config::TTL_PROPUESTA_S);
        return Respuesta::json([
            'ok' => true, 'resumen' => $p['resumen'], 'detalle' => $p['detalle'],
            'huella' => $huella, 'expira_s' => Config::TTL_PROPUESTA_S,
        ]);
    }

    /**
     * POST /asistente/tools/{nombre} (secciones 3 y 8.4). Las lecturas piden token de lectura; una
     * acción con confirmación, el token de escritura de esa confirmación y `Idempotency-Key`.
     */
    public function ejecutar(string $nombre, ?string $authorization, string $cuerpoCrudo, ?string $idempotencyKey = null): Respuesta
    {
        $tool = $this->registro->buscar($nombre);
        $esAccion = $tool !== null && $this->registro->esAccion($tool);
        $claims = $this->autenticar($authorization, $esAccion ? 'asistente:escritura' : 'asistente:lectura', $falla);
        if ($claims === null) {
            return $falla;
        }
        if ($tool === null) {
            return Respuesta::json(Resultado::error('no_disponible', "tool desconocida: $nombre"));
        }
        if (!$esAccion && !$this->registro->esLectura($tool)) { // capa de solo lectura: vale aunque la tool exista
            return Respuesta::http(403, 'escritura no permitida con scope de lectura');
        }
        if ($esAccion) {
            return $this->ejecutarAccion($tool, $claims, $cuerpoCrudo, $idempotencyKey);
        }

        [$parametros, $falla] = $this->parametros($tool, $cuerpoCrudo);
        if ($parametros === null) {
            return $falla;
        }
        return Respuesta::json($tool->ejecutar($parametros, $claims['sub']));
    }

    private function ejecutarAccion(Accion $tool, array $claims, string $cuerpoCrudo, ?string $clave): Respuesta
    {
        $nombre = $tool->nombre();
        $sub = $claims['sub'];
        foreach (['act', 'ph', 'cid'] as $claim) {
            if (!isset($claims[$claim]) || !is_string($claims[$claim]) || $claims[$claim] === '') {
                return Respuesta::http(403, "el token de escritura no trae $claim");
            }
        }
        if ($claims['act'] !== $nombre) { // un token sirve para una sola tool
            return Respuesta::http(403, 'el token no es para esta tool');
        }
        if ($clave === null || $clave === '') {
            return Respuesta::http(400, 'falta Idempotency-Key');
        }
        // Reintento con la misma clave: el resultado anterior, sin reejecutar (y sin gastar otro token).
        $previo = $this->almacen->resultadoPrevio($clave, $sub);
        if ($previo !== null) {
            return $previo['tool'] === $nombre && $previo['huella'] === $claims['ph']
                ? Respuesta::json($previo['respuesta'])
                : Respuesta::http(403, 'Idempotency-Key usada con otra acción');
        }
        if (!$this->almacen->gastarJti($claims['jti'])) { // un solo uso
            return Respuesta::http(403, 'token de escritura ya usado');
        }
        [$parametros, $falla] = $this->parametros($tool, $cuerpoCrudo);
        if ($parametros === null) {
            return $falla;
        }
        // Debe ser EXACTAMENTE lo que el usuario vio y confirmó: la huella la emitió este sistema.
        $propuesta = $this->almacen->propuestaVigente($claims['ph']);
        if ($propuesta === null || $propuesta['sub'] !== $sub || $propuesta['tool'] !== $nombre
            || Almacen::canonico($propuesta['parametros']) !== Almacen::canonico($parametros)) {
            return Respuesta::http(403, 'los parámetros no coinciden con los confirmados');
        }
        $actual = $tool->preparar($parametros, $sub);
        if (($actual['ok'] ?? null) === false) {
            return Respuesta::json($actual);
        }
        if ($actual['version'] !== $propuesta['version']) { // el dato cambió desde la propuesta
            return Respuesta::json(Resultado::error('conflicto', 'El dato cambió desde que se propuso'));
        }
        // Ojo en un sistema real: comprobar la versión y escribir en una sola sentencia
        // (UPDATE … WHERE version = ?), no en dos pasos como aquí.
        $resultado = $tool->ejecutar($parametros, $sub);
        $this->almacen->guardarResultado($clave, $sub, $nombre, $claims['ph'], $resultado);
        return Respuesta::json($resultado);
    }

    /**
     * Valida el Bearer y exige el scope dado. Devuelve los claims, o null con `$falla` rellena.
     * @param-out Respuesta $falla
     */
    private function autenticar(?string $authorization, string $scope, ?Respuesta &$falla): ?array
    {
        $bearer = self::bearer($authorization);
        if ($bearer === null) {
            $falla = Respuesta::http(401, 'falta Authorization: Bearer');
            return null;
        }
        if (hash_equals($this->cfg->tokenManifiesto, $bearer)) {
            $falla = Respuesta::http(403, 'el token de manifiesto no sirve para ejecutar');
            return null;
        }
        try {
            $claims = $this->validador->validar($bearer);
        } catch (TokenInvalido) {
            $falla = Respuesta::http(401, 'token inválido');
            return null;
        }
        if (($claims['scope'] ?? null) !== $scope) {
            $falla = Respuesta::http(403, 'scope insuficiente');
            return null;
        }
        return $claims;
    }

    /** @return array{0: ?array, 1: ?Respuesta} parámetros ya validados contra el schema, o el error de negocio */
    private function parametros(Herramienta $tool, string $cuerpoCrudo): array
    {
        $cuerpo = json_decode($cuerpoCrudo);
        $parametros = is_object($cuerpo) ? ($cuerpo->parametros ?? null) : null;
        if (!is_object($parametros)) {
            return [null, Respuesta::json(Resultado::error('parametros_invalidos', 'cuerpo debe ser {parametros: {...}}'))];
        }
        if (($error = $this->registro->validar($tool, $parametros)) !== null) {
            return [null, Respuesta::json(Resultado::error('parametros_invalidos', $error))];
        }
        return [json_decode(json_encode($parametros), true), null];
    }

    private static function bearer(?string $authorization): ?string
    {
        if ($authorization === null || !str_starts_with($authorization, 'Bearer ')) {
            return null;
        }
        $t = trim(substr($authorization, 7));
        return $t === '' ? null : $t;
    }
}
