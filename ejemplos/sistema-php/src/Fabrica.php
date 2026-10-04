<?php
declare(strict_types=1);

namespace Ejemplo;

use Ejemplo\Auth\EmisorToken;
use Ejemplo\Auth\ValidadorToken;
use Ejemplo\Controllers\AsistenteController;
use Ejemplo\Datos\Repositorio;
use Ejemplo\Tools\ListarEstablecimientos;
use Ejemplo\Tools\Registro;
use Ejemplo\Tools\ResumenEstablecimiento;

/** Cableado de dependencias (en CI4: Config\Services). */
final class Fabrica
{
    public static function controlador(Config $cfg): AsistenteController
    {
        $repo = new Repositorio();
        $registro = new Registro(
            $cfg->nombre,
            '0.1.0',
            new ListarEstablecimientos($repo),
            new ResumenEstablecimiento($repo),
        );
        return new AsistenteController($cfg, $repo, $registro, new EmisorToken($cfg), new ValidadorToken($cfg));
    }
}
