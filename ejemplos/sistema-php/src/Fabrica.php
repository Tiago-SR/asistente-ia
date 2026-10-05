<?php
declare(strict_types=1);

namespace Ejemplo;

use Ejemplo\Auth\EmisorToken;
use Ejemplo\Auth\ValidadorToken;
use Ejemplo\Controllers\AsistenteController;
use Ejemplo\Datos\Almacen;
use Ejemplo\Datos\Repositorio;
use Ejemplo\Tools\AgregarNota;
use Ejemplo\Tools\EliminarEstablecimiento;
use Ejemplo\Tools\ListarEstablecimientos;
use Ejemplo\Tools\ListarNotas;
use Ejemplo\Tools\ModificarNota;
use Ejemplo\Tools\Registro;
use Ejemplo\Tools\ResumenEstablecimiento;
use Ejemplo\Tools\ResumenPorCultivo;

/** Cableado de dependencias (en CI4: Config\Services). */
final class Fabrica
{
    public static function controlador(Config $cfg): AsistenteController
    {
        $repo = new Repositorio();
        $almacen = new Almacen($cfg->rutaDb);
        $registro = new Registro(
            $cfg->nombre,
            '0.1.0',
            new ListarEstablecimientos($repo),
            new ResumenEstablecimiento($repo),
            new ResumenPorCultivo($repo),
            new ListarNotas($almacen),
            new AgregarNota($repo, $almacen),
            new ModificarNota($repo, $almacen),
            new EliminarEstablecimiento(),
        );
        return new AsistenteController($cfg, $repo, $almacen, $registro, new EmisorToken($cfg), new ValidadorToken($cfg));
    }
}
