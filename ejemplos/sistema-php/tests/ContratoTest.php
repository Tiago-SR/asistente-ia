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
        foreach ($r->cuerpo['tools'] as $t) {
            $this->assertSame('lectura', $t['efecto']);
        }
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
        $this->assertCount(2, $lista['datos']['establecimientos']);
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
}
