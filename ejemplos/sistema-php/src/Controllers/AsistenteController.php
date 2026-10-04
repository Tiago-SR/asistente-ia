<?php
declare(strict_types=1);

namespace Ejemplo\Controllers;

use Ejemplo\Auth\EmisorToken;
use Ejemplo\Auth\TokenInvalido;
use Ejemplo\Auth\ValidadorToken;
use Ejemplo\Config;
use Ejemplo\Datos\Repositorio;
use Ejemplo\Respuesta;
use Ejemplo\Tools\Registro;
use Ejemplo\Tools\Resultado;

/**
 * Los cuatro endpoints del contrato. Cada método recibe datos simples y devuelve una Respuesta,
 * sin tocar $_SERVER ni echo: así se prueba sin servidor y se porta a un controlador de CI4.
 */
final class AsistenteController
{
    public function __construct(
        private readonly Config $cfg,
        private readonly Repositorio $repo,
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
     * @param string|null $usuarioSesion login del usuario con sesión iniciada (null si no hay)
     * @param string|null $usuarioPrueba parámetro `?usuario=`: SOLO se atiende con APP_ENV=local
     */
    public function token(?string $usuarioSesion, ?string $usuarioPrueba = null): Respuesta
    {
        $login = $this->cfg->local && $usuarioPrueba !== null ? $usuarioPrueba : $usuarioSesion;
        if ($login === null) {
            return Respuesta::http(401, 'sin sesión');
        }
        $usuario = $this->repo->usuarioPorLogin($login);
        if ($usuario === null) { // también: usuarios sin permiso de usar el asistente
            return Respuesta::http(403, 'usuario sin acceso al asistente');
        }
        return Respuesta::json($this->emisor->emitir($usuario));
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

    /** POST /asistente/tools/{nombre} (sección 3). */
    public function ejecutar(string $nombre, ?string $authorization, string $cuerpoCrudo): Respuesta
    {
        $bearer = self::bearer($authorization);
        if ($bearer === null) {
            return Respuesta::http(401, 'falta Authorization: Bearer');
        }
        if (hash_equals($this->cfg->tokenManifiesto, $bearer)) {
            return Respuesta::http(403, 'el token de manifiesto no sirve para ejecutar');
        }
        try {
            $claims = $this->validador->validar($bearer);
        } catch (TokenInvalido $e) {
            return Respuesta::http(401, 'token inválido');
        }
        if (($claims['scope'] ?? null) !== 'asistente:lectura') {
            return Respuesta::http(403, 'scope insuficiente');
        }

        $tool = $this->registro->buscar($nombre);
        if ($tool === null) {
            return Respuesta::json(Resultado::error('no_disponible', "tool desconocida: $nombre"));
        }
        if (!$this->registro->esLectura($tool)) { // capa de solo lectura: vale aunque la tool exista
            return Respuesta::http(403, 'escritura no permitida con scope de lectura');
        }

        $cuerpo = json_decode($cuerpoCrudo);
        $parametros = is_object($cuerpo) ? ($cuerpo->parametros ?? null) : null;
        if (!is_object($parametros)) {
            return Respuesta::json(Resultado::error('parametros_invalidos', 'cuerpo debe ser {parametros: {...}}'));
        }
        if (($error = $this->registro->validar($tool, $parametros)) !== null) {
            return Respuesta::json(Resultado::error('parametros_invalidos', $error));
        }

        $resultado = $tool->ejecutar(json_decode(json_encode($parametros), true), $claims['sub']);
        return Respuesta::json($resultado);
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
