import httpx
import pytest

from asistente.config import Settings
from asistente.core.voz.base import AudioInvalido, VozError
from asistente.core.voz.openai_compat import SttOpenAICompat
from asistente.servicios import _fabrica_stt


def stt_con(handler, **kw) -> SttOpenAICompat:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SttOpenAICompat("http://stt/v1", "whisper-test", cliente=cliente, **kw)


async def test_transcribe_y_envia_modelo_idioma_y_credencial():
    visto = {}

    def handler(req: httpx.Request) -> httpx.Response:
        visto["url"] = str(req.url)
        visto["auth"] = req.headers.get("authorization")
        visto["cuerpo"] = req.content
        return httpx.Response(200, json={"text": "  ¿cuántas hectáreas tengo?  "})

    stt = stt_con(handler, api_key="k")
    texto = await stt.transcribir(b"AUDIO", tipo_mime="audio/webm;codecs=opus", idioma="es")
    assert texto == "¿cuántas hectáreas tengo?"
    assert visto["url"] == "http://stt/v1/audio/transcriptions"
    assert visto["auth"] == "Bearer k"
    for fragmento in (b"whisper-test", b'name="language"', b"audio.webm", b"AUDIO"):
        assert fragmento in visto["cuerpo"]


@pytest.mark.parametrize("status", [400, 415, 422])
async def test_audio_rechazado(status):
    stt = stt_con(lambda r: httpx.Response(status))
    with pytest.raises(AudioInvalido):
        await stt.transcribir(b"x", tipo_mime="audio/webm")


@pytest.mark.parametrize(
    "respuesta",
    [httpx.Response(500), httpx.Response(200, text="no es json"), httpx.Response(200, json={"x": 1}),
     httpx.Response(200, json={"text": 5})],
)
async def test_fallas_del_proveedor(respuesta):
    stt = stt_con(lambda r: respuesta)
    with pytest.raises(VozError):
        await stt.transcribir(b"x", tipo_mime="audio/webm")


async def test_red_caida_no_filtra_detalles():
    def handler(req):
        raise httpx.ConnectError("boom http://interno:9/secreto")

    with pytest.raises(VozError) as e:
        await stt_con(handler).transcribir(b"x", tipo_mime="audio/webm")
    assert "secreto" not in str(e.value)


async def test_disponible():
    assert await stt_con(lambda r: httpx.Response(200, json={"data": []})).disponible()
    assert not await stt_con(lambda r: httpx.Response(503)).disponible()

    def cae(req):
        raise httpx.ConnectError("x")

    assert not await stt_con(cae).disponible()


def test_fabrica_sin_proveedor_deshabilita_el_dictado():
    assert _fabrica_stt(Settings(database_url="x")) is None


def test_fabrica_exige_url_y_modelo():
    with pytest.raises(ValueError):
        _fabrica_stt(Settings(database_url="x", STT_PROVEEDOR="openai_compat"))
    with pytest.raises(ValueError):
        _fabrica_stt(Settings(database_url="x", STT_PROVEEDOR="otro"))
    stt = _fabrica_stt(
        Settings(database_url="x", STT_PROVEEDOR="openai_compat",
                 STT_BASE_URL="http://stt/v1", STT_MODELO="m")
    )
    assert isinstance(stt, SttOpenAICompat)
