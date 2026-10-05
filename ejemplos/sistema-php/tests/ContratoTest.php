<?php
declare(strict_types=1);

namespace Ejemplo\Tests;

use Ejemplo\Config;
use Ejemplo\Controllers\AsistenteController;
use Ejemplo\Fabrica;
use Firebase\JWT\JWT;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class ContratoTest extends TestCase
{
    private const SECRETO = 'secreto-de-prueba-0123456789-0123456789-0123456789-0123456789';
    private const MANIFIESTO = 'manifiesto-de-prueba';

    private Config $cfg;
    private AsistenteController $ctl;

    protected function setUp(): void
    {
        $this->cfg = new Config('sis', 'Sis', 'asistente', 'HS256', self::SECRETO, self::SECRETO, self::MANIFIESTO, true, 'http://a');
        $this->ctl = Fabrica::controlador($this->cfg);
    }

    private function claims(array $cambios = []): array
    {
        $ahora = time();
        return array_replace([
            'iss' => 'sis', 'aud' => 'asistente', 'sub' => 'u-1001', 'iat' => $ahora, 'exp' => $ahora + 300,
            'jti' => 'x', 'scope' => 'asistente:lectura',
        ], $cambios);
    }

    private function jwt(array $cambios = [], string $clave = self::SECRETO): string
    {
        return JWT::encode($this->claims($cambios), $clave, 'HS256');
    }

    private function ejecutar(?string $token, string $tool = 'listar_establecimientos', string $cuerpo = '{"parametros":{}}'): array
    {
        $r = $this->ctl->ejecutar($tool, $token === null ? null : "Bearer $token", $cuerpo);
        return [$r->estado, $r->cuerpo];
    }

    private function sinFirma(array $claims): string
    {
        $b = fn(array $x) => rtrim(strtr(base64_encode(json_encode($x)), '+/', '-_'), '=');
        return $b(['alg' => 'none', 'typ' => 'JWT']) . '.' . $b($claims) . '.';
    }

    // ── 401: token inválido ──
    public static function tokensInvalidos(): iterable
    {
        yield 'sin cabecera' => [fn(self $t) => null];
        yield 'ilegible' => [fn(self $t) => 'basura'];
        yield 'otra clave' => [fn(self $t) => $t->jwt([], 'otra-clave-0123456789-0123456789-xx')];
        yield 'alg=none' => [fn(self $t) => $t->sinFirma($t->claims())];
        yield 'vencido' => [fn(self $t) => $t->jwt(['iat' => time() - 900, 'exp' => time() - 300])];
        yield 'otra audiencia' => [fn(self $t) => $t->jwt(['aud' => 'otro'])];
        yield 'otro iss' => [fn(self $t) => $t->jwt(['iss' => 'otro-sistema'])];
        yield 'sin sub' => [fn(self $t) => $t->jwt(['sub' => ''])];
        yield 'sin jti' => [fn(self $t) => JWT::encode(array_diff_key($t->claims(), ['jti' => 1]), self::SECRETO, 'HS256')];
        yield 'HS384 en vez de HS256' => [fn(self $t) => JWT::encode($t->claims(), self::SECRETO, 'HS384')];
    }

    #[DataProvider('tokensInvalidos')]
    public function testEjecucionRechazaTokenInvalidoCon401(callable $token): void
    {
        [$estado] = $this->ejecutar($token($this));
        $this->assertSame(401, $estado);
    }

    // ── 403 ──
    public function testRechazaTokenDeManifiestoEnLaEjecucion(): void
    {
        [$estado] = $this->ejecutar(self::MANIFIESTO);
        $this->assertSame(403, $estado);
    }

    public function testRechazaScopeAjeno(): void
    {
        [$estado] = $this->ejecutar($this->jwt(['scope' => 'asistente:escritura']));
        $this->assertSame(403, $estado);
    }

    public function testManifiestoConJwtDeUsuarioDa403(): void
    {
        $this->assertSame(403, $this->ctl->manifiesto('Bearer ' . $this->jwt())->estado);
    }

    public function testManifiestoSinCredencialOFalsaDa401(): void
    {
        $this->assertSame(401, $this->ctl->manifiesto(null)->estado);
        $this->assertSame(401, $this->ctl->manifiesto('Bearer falsa')->estado);
        $this->assertSame(401, $this->ctl->manifiesto('Bearer ' . $this->jwt([], 'otra-clave-0123456789-0123456789-xx'))->estado);
    }

    public function testManifiestoConCredencialCorrecta(): void
    {
        $r = $this->ctl->manifiesto('Bearer ' . self::MANIFIESTO);
        $this->assertSame(200, $r->estado);
        $this->assertSame('1', $r->cuerpo['contrato']);
        $efectos = array_column($r->cuerpo['tools'], 'efecto', 'nombre');
        $acciones = ['agregar_nota', 'modificar_nota'];
        $this->assertSame('escritura', $efectos['eliminar_establecimiento']);
        foreach ($acciones as $a) {
            $this->assertSame('escritura', $efectos[$a]);
        }
        foreach (array_diff_key($efectos, array_flip([...$acciones, 'eliminar_establecimiento'])) as $efecto) {
            $this->assertSame('lectura', $efecto);
        }
        // solo las acciones con propuesta declaran `confirmacion`; borrar no se ofrece
        $con = array_column(array_filter($r->cuerpo['tools'], fn($t) => isset($t['confirmacion'])), 'nombre');
        $this->assertSame($acciones, $con);
    }

    // ── Negocio ──
    public function testParametrosInvalidos(): void
    {
        $t = $this->jwt();
        foreach ([
            ['resumen_establecimiento', '{"parametros":{}}'],               // falta id
            ['resumen_establecimiento', '{"parametros":{"id":5}}'],         // tipo
            ['listar_establecimientos', '{"parametros":{"inventado":1}}'],  // additionalProperties
            ['listar_establecimientos', '{"parametros":[]}'],               // no es objeto
            ['listar_establecimientos', 'no es json'],
        ] as [$tool, $cuerpo]) {
            [$estado, $c] = $this->ejecutar($t, $tool, $cuerpo);
            $this->assertSame(200, $estado);
            $this->assertSame('parametros_invalidos', $c['error'], $cuerpo);
        }
    }

    public function testEscrituraSeRechazaConScopeDeLecturaYNoHaceNada(): void
    {
        $cuerpo = '{"parametros":{"id":"1"}}';
        [$estado] = $this->ejecutar($this->jwt(), 'eliminar_establecimiento', $cuerpo);
        $this->assertSame(403, $estado);
        // aun con scope de escritura, la capa de lectura del ejemplo no la ejecuta y los datos siguen
        [$estado] = $this->ejecutar($this->jwt(['scope' => 'asistente:escritura']), 'eliminar_establecimiento', $cuerpo);
        $this->assertSame(403, $estado);
        [, $c] = $this->ejecutar($this->jwt(), 'resumen_establecimiento', '{"parametros":{"id":"1"}}');
        $this->assertTrue($c['ok']);
    }

    public function testResumenPorCultivoSumaSoloLoDelUsuario(): void
    {
        [, $c] = $this->ejecutar($this->jwt(['sub' => 'u-1001']), 'resumen_por_cultivo');
        $this->assertSame([
            ['superficie_ha' => 660.5, 'cultivo' => 'soja', 'establecimientos' => 2],
            ['superficie_ha' => 210.0, 'cultivo' => 'maíz', 'establecimientos' => 1],
        ], $c['datos']['por_cultivo']);
        $this->assertSame(870.5, $c['datos']['superficie_total_ha']);
        [, $c] = $this->ejecutar($this->jwt(['sub' => 'u-1002']), 'resumen_por_cultivo');
        $this->assertSame(['trigo'], array_column($c['datos']['por_cultivo'], 'cultivo'));
        $this->assertSame(88.2, $c['datos']['superficie_total_ha']);
        [, $c] = $this->ejecutar($this->jwt(['sub' => 'u-9999']), 'resumen_por_cultivo');
        $this->assertSame([], $c['datos']['por_cultivo']);
        [, $c] = $this->ejecutar($this->jwt(), 'resumen_por_cultivo', '{"parametros":{"usuario_id":"u-1002"}}');
        $this->assertSame('parametros_invalidos', $c['error']);
    }

    public function testToolDesconocida(): void
    {
        [$estado, $c] = $this->ejecutar($this->jwt(), 'eliminar_todo');
        $this->assertSame([200, 'no_disponible'], [$estado, $c['error']]);
    }

    public function testAislamientoEntreUsuarios(): void
    {
        $ana = $this->jwt(['sub' => 'u-1001']);
        $beto = $this->jwt(['sub' => 'u-1002']);
        [, $lista] = $this->ejecutar($ana);
        $this->assertSame(['1', '2', '4'], array_column($lista['datos']['establecimientos'], 'id'));
        [, $lista] = $this->ejecutar($beto);
        $this->assertSame(['3'], array_column($lista['datos']['establecimientos'], 'id'));
        // id de ana (1) pedido por beto: igual que si no existiera
        [$estado, $c] = $this->ejecutar($beto, 'resumen_establecimiento', '{"parametros":{"id":"1"}}');
        $this->assertSame([200, 'no_encontrado'], [$estado, $c['error']]);
        [, $c2] = $this->ejecutar($beto, 'resumen_establecimiento', '{"parametros":{"id":"999"}}');
        $this->assertSame($c['detalle'], $c2['detalle']);
        // usuario inexistente en el repositorio: nada que ver
        [, $lista] = $this->ejecutar($this->jwt(['sub' => 'u-9999']));
        $this->assertSame([], $lista['datos']['establecimientos']);
    }

    public function testFiltroPorTextoSinTildesNiMayusculas(): void
    {
        [, $c] = $this->ejecutar($this->jwt(), 'listar_establecimientos', '{"parametros":{"texto":"ESPERANZA"}}');
        $this->assertSame(['2'], array_column($c['datos']['establecimientos'], 'id'));
    }

    // ── Token de usuario ──
    public function testTokenSoloConSesionYElParametroDePruebaSoloEnLocal(): void
    {
        $this->assertSame(401, $this->ctl->token(null)->estado);
        $this->assertSame(403, $this->ctl->token('nadie')->estado);
        $r = $this->ctl->token(null, 'ana'); // local: ?usuario=ana
        $this->assertSame(200, $r->estado);

        $prod = new Config('sis', 'Sis', 'asistente', 'HS256', self::SECRETO, self::SECRETO, self::MANIFIESTO, false, 'http://a');
        $ctlProd = Fabrica::controlador($prod);
        $this->assertSame(401, $ctlProd->token(null, 'ana')->estado, '?usuario= se ignora fuera de local');
        $this->assertSame(200, $ctlProd->token('beto', 'ana')->estado);
    }

    public function testTokenEmitidoTraeLosClaimsDelContrato(): void
    {
        $r = $this->ctl->token(null, 'beto');
        $claims = (array) JWT::decode($r->cuerpo['token'], new \Firebase\JWT\Key(self::SECRETO, 'HS256'));
        $this->assertSame(['sis', 'asistente', 'u-1002', 'asistente:lectura'], [$claims['iss'], $claims['aud'], $claims['sub'], $claims['scope']]);
        $this->assertLessThanOrEqual(900, $claims['exp'] - $claims['iat']);
        $this->assertNotEmpty($claims['jti']);
        // y lo que se emite se acepta en la ejecución
        [$estado, $c] = $this->ejecutar($r->cuerpo['token']);
        $this->assertSame([200, true], [$estado, $c['ok']]);
    }

    public function testRS256(): void
    {
        $par = openssl_pkey_new(['private_key_bits' => 2048]);
        openssl_pkey_export($par, $priv);
        $pub = openssl_pkey_get_details($par)['key'];
        $cfg = new Config('sis', 'Sis', 'asistente', 'RS256', $priv, $pub, self::MANIFIESTO, true, 'http://a');
        $ctl = Fabrica::controlador($cfg);
        $token = $ctl->token(null, 'ana')->cuerpo['token'];
        $this->assertSame(200, $ctl->ejecutar('listar_establecimientos', "Bearer $token", '{"parametros":{}}')->estado);
        // un HS256 firmado con la PÚBLICA como secreto (confusión de algoritmos) se rechaza
        $falso = JWT::encode($this->claims(), $pub, 'HS256');
        $this->assertSame(401, $ctl->ejecutar('listar_establecimientos', "Bearer $falso", '{"parametros":{}}')->estado);
    }

    // ── Acciones con confirmación (sección 8) ──
    private const AGREGAR = ['establecimiento_id' => '1', 'texto' => 'Helada'];

    private function proponer(string $tool = 'agregar_nota', array $params = self::AGREGAR, string $sub = 'u-1001'): array
    {
        $r = $this->ctl->propuesta($tool, 'Bearer ' . $this->jwt(['sub' => $sub]), json_encode(['parametros' => $params]));
        $this->assertSame(200, $r->estado);
        return $r->cuerpo;
    }

    private function tokenEscritura(string $huella, string $cid = 'c-1', string $login = 'ana'): ?string
    {
        return $this->ctl->token(null, $login, $cid, $huella)->cuerpo['token'] ?? null;
    }

    /** Propone y obtiene el token de escritura, como hace el usuario al confirmar. */
    private function listo(string $tool = 'agregar_nota', array $params = self::AGREGAR): array
    {
        $p = $this->proponer($tool, $params);
        return [$p, $this->tokenEscritura($p['huella'])];
    }

    private function escribir(?string $token, string $tool = 'agregar_nota', array $params = self::AGREGAR, ?string $clave = 'k1'): array
    {
        $r = $this->ctl->ejecutar($tool, $token === null ? null : "Bearer $token", json_encode(['parametros' => $params]), $clave);
        return [$r->estado, $r->cuerpo];
    }

    private function notas(string $sub = 'u-1001'): array
    {
        return $this->ejecutar($this->jwt(['sub' => $sub]), 'listar_notas')[1]['datos']['notas'];
    }

    public function testLaPropuestaNoEscribeYTraeResumenYHuella(): void
    {
        $antes = $this->notas();
        $p = $this->proponer();
        $this->assertTrue($p['ok']);
        $this->assertSame(64, strlen($p['huella']));
        $this->assertSame(Config::TTL_PROPUESTA_S, $p['expira_s']);
        $this->assertStringContainsString('El Matorral', $p['resumen']);
        $this->assertSame($antes, $this->notas());
    }

    public function testModificarMuestraAntesYDespues(): void
    {
        $p = $this->proponer('modificar_nota', ['nota_id' => 'n1', 'texto' => 'nuevo']);
        $this->assertSame(['Antes: Revisar el alambrado del potrero norte', 'Después: nuevo'], $p['detalle']);
    }

    public function testPropuestaConParametrosInvalidosOAjenos(): void
    {
        $t = 'Bearer ' . $this->jwt();
        foreach ([
            ['agregar_nota', '{"parametros":{}}', 'parametros_invalidos'],
            ['agregar_nota', '{"parametros":{"establecimiento_id":"3","texto":"x"}}', 'no_encontrado'], // de beto
            ['modificar_nota', '{"parametros":{"nota_id":"n999","texto":"x"}}', 'no_encontrado'],
            ['listar_establecimientos', '{"parametros":{}}', 'no_disponible'], // no es una acción
        ] as [$tool, $cuerpo, $error]) {
            $r = $this->ctl->propuesta($tool, $t, $cuerpo);
            $this->assertSame([200, $error], [$r->estado, $r->cuerpo['error']], $cuerpo);
        }
    }

    public function testLaPropuestaPideTokenDeLecturaNoDeEscritura(): void
    {
        [, $tok] = $this->listo();
        $this->assertSame(403, $this->ctl->propuesta('agregar_nota', "Bearer $tok", '{"parametros":{}}')->estado);
        $this->assertSame(401, $this->ctl->propuesta('agregar_nota', null, '{}')->estado);
    }

    public function testNoEmiteTokenDeEscrituraParaUnaHuellaAjenaDesconocidaOMalPedida(): void
    {
        $p = $this->proponer();
        $this->assertSame(403, $this->ctl->token(null, 'ana', 'c', str_repeat('f', 64))->estado);
        $this->assertSame(403, $this->ctl->token(null, 'beto', 'c', $p['huella'])->estado, 'huella de otro usuario');
        $this->assertSame(400, $this->ctl->token(null, 'ana', null, $p['huella'])->estado);
        $this->assertSame(400, $this->ctl->token(null, 'ana', 'c', null)->estado);
        $this->assertSame(400, $this->ctl->token(null, 'ana', 'c con espacios', $p['huella'])->estado);
    }

    public function testElTokenDeEscrituraEsCortoYEstaAtado(): void
    {
        [$p, $tok] = $this->listo();
        $c = (array) JWT::decode($tok, new \Firebase\JWT\Key(self::SECRETO, 'HS256'));
        $this->assertSame(['asistente:escritura', 'agregar_nota', $p['huella'], 'c-1'], [$c['scope'], $c['act'], $c['ph'], $c['cid']]);
        $this->assertLessThanOrEqual(60, $c['exp'] - $c['iat']);
    }

    public function testEjecucionConformeEIdempotente(): void
    {
        [$p, $tok] = $this->listo();
        [$estado, $r1] = $this->escribir($tok);
        $this->assertSame([200, true, 'Nota agregada.'], [$estado, $r1['ok'], $r1['datos']['mensaje']]);
        $this->assertCount(2, $this->notas());
        // reintento con la misma clave y otro token (p. ej. se perdió el primero): mismo resultado, no reejecuta
        [$estado, $r2] = $this->escribir($this->tokenEscritura($p['huella']));
        $this->assertSame([200, $r1], [$estado, $r2]);
        $this->assertCount(2, $this->notas());
    }

    public function testElTokenDeEscrituraNoSeReutiliza(): void
    {
        [, $tok] = $this->listo();
        $this->assertSame(200, $this->escribir($tok, clave: 'k1')[0]);
        $this->assertSame(403, $this->escribir($tok, clave: 'k2')[0]);
        $this->assertCount(2, $this->notas());
    }

    public function testElTokenNoSirveParaOtraToolNiOtrosParametros(): void
    {
        [, $tok] = $this->listo();
        $this->assertSame(403, $this->escribir($tok, 'modificar_nota', ['nota_id' => 'n1', 'texto' => 'x'])[0]);
        [, $tok] = $this->listo();
        $this->assertSame(403, $this->escribir($tok, params: [...self::AGREGAR, 'texto' => 'OTRO TEXTO'], clave: 'k9')[0]);
        $this->assertCount(1, $this->notas());
    }

    public function testLaEscrituraExigeTokenDeEscrituraEIdempotencyKey(): void
    {
        [, $tok] = $this->listo();
        $this->assertSame(400, $this->escribir($tok, clave: null)[0]);
        $this->assertSame(403, $this->escribir($this->jwt())[0], 'token de lectura');
        $this->assertSame(401, $this->escribir(null)[0]);
        [$estado] = $this->ejecutar($tok, 'listar_establecimientos');
        $this->assertSame(403, $estado, 'lectura con token de escritura');
        $this->assertCount(1, $this->notas());
    }

    public function testUnTokenDeEscrituraVencidoOSinSuHuellaSeRechaza(): void
    {
        $p = $this->proponer();
        $ahora = time();
        $viejo = $this->jwt(['scope' => 'asistente:escritura', 'act' => 'agregar_nota', 'ph' => $p['huella'], 'cid' => 'c',
            'iat' => $ahora - 200, 'exp' => $ahora - 100, 'jti' => 'viejo']);
        $this->assertSame(401, $this->escribir($viejo)[0]);
        $inventado = $this->jwt(['scope' => 'asistente:escritura', 'act' => 'agregar_nota', 'ph' => str_repeat('a', 64), 'cid' => 'c', 'jti' => 'inv']);
        $this->assertSame(403, $this->escribir($inventado)[0], 'huella que el sistema no emitió');
        $sinCid = $this->jwt(['scope' => 'asistente:escritura', 'act' => 'agregar_nota', 'ph' => $p['huella'], 'jti' => 'sc']);
        $this->assertSame(403, $this->escribir($sinCid)[0]);
        $this->assertCount(1, $this->notas());
    }

    public function testModificarDetectaQueElDatoCambio(): void
    {
        $params = ['nota_id' => 'n1', 'texto' => 'nuevo'];
        [, $tok] = $this->listo('modificar_nota', $params);
        // alguien más la modifica entre la propuesta y la confirmación
        [, $otro] = $this->listo('modificar_nota', ['nota_id' => 'n1', 'texto' => 'de otro']);
        $this->assertSame(200, $this->escribir($otro, 'modificar_nota', ['nota_id' => 'n1', 'texto' => 'de otro'], 'k2')[0]);
        [$estado, $r] = $this->escribir($tok, 'modificar_nota', $params);
        $this->assertSame([200, 'conflicto'], [$estado, $r['error']]);
        $this->assertSame('de otro', $this->notas()[0]['texto']);
    }

    public function testLasNotasSonDeCadaUsuario(): void
    {
        $this->assertSame([], $this->notas('u-1002'));
        $p = $this->proponer('modificar_nota', ['nota_id' => 'n1', 'texto' => 'x'], 'u-1001');
        $this->assertTrue($p['ok']);
        $r = $this->ctl->propuesta('modificar_nota', 'Bearer ' . $this->jwt(['sub' => 'u-1002']), '{"parametros":{"nota_id":"n1","texto":"x"}}');
        $this->assertSame('no_encontrado', $r->cuerpo['error']);
    }
}
