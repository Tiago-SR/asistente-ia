import httpx
import pytest

from asistente.config import Settings
from asistente.core.voz.base import VozError
from asistente.core.voz.elevenlabs import TtsElevenLabs
from asistente.servicios import _fabrica_tts


def tts_con(handler) -> TtsElevenLabs:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TtsElevenLabs("k", "voz/1", "eleven_flash_v2_5", base_url="http://tts/v1", cliente=cliente)


async def test_sintetiza_con_clave_modelo_y_voz():
    visto = {}

    def handler(req: httpx.Request) -> httpx.Response:
        visto["url"] = str(req.url)
        visto["clave"] = req.headers.get("xi-api-key")
        visto["cuerpo"] = req.content
        return httpx.Response(200, content=b"MP3")

    assert await tts_con(handler).sintetizar("Hola") == b"MP3"
    assert visto["url"] == "http://tts/v1/text-to-speech/voz%2F1?output_format=mp3_44100_128"
    assert visto["clave"] == "k"
    assert b"eleven_flash_v2_5" in visto["cuerpo"] and b"Hola" in visto["cuerpo"]


@pytest.mark.parametrize("respuesta", [httpx.Response(401), httpx.Response(429), httpx.Response(200, content=b"")])
async def test_errores_del_proveedor_son_voz_error(respuesta):
    with pytest.raises(VozError):
        await tts_con(lambda req: respuesta).sintetizar("Hola")


async def test_red_caida_es_voz_error():
    def handler(req):
        raise httpx.ConnectError("x")

    with pytest.raises(VozError):
        await tts_con(handler).sintetizar("Hola")


async def test_disponible_no_gasta_llamadas():
    def handler(req):
        raise AssertionError("no debe llamar al proveedor")

    assert await tts_con(handler).disponible() is True


@pytest.fixture(autouse=True)
def _sin_tts_del_entorno(monkeypatch):
    """Los tests no dependen de los TTS_* del .env de quien los corre."""
    for nombre in ("TTS_PROVEEDOR", "TTS_API_KEY", "TTS_VOZ_ID", "TTS_MODELO"):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setenv("ASISTENTE_VOCES_PATH", "/no/existe.yaml")   # ni del config/voces.yaml del repo


def _settings(**kw) -> Settings:
    base = {"ASISTENTE_DATABASE_URL": "sqlite+aiosqlite://"}
    return Settings(**base, **kw)


def test_fabrica_sin_proveedor_no_hay_tts():
    assert _fabrica_tts(_settings()) is None


def test_fabrica_exige_clave_voz_y_modelo():
    with pytest.raises(ValueError):
        _fabrica_tts(_settings(TTS_PROVEEDOR="elevenlabs", TTS_API_KEY="k"))
    with pytest.raises(ValueError):
        _fabrica_tts(_settings(TTS_PROVEEDOR="otro"))
    assert _fabrica_tts(_settings(TTS_PROVEEDOR="elevenlabs", TTS_API_KEY="k", TTS_VOZ_ID="v", TTS_MODELO="m"))


async def test_el_motivo_del_proveedor_queda_en_el_error():
    cuerpo = {"detail": {"status": "paid_plan_required", "message": "Free users cannot use library voices."}}
    with pytest.raises(VozError, match=r"402.*paid_plan_required.*library voices"):
        await tts_con(lambda req: httpx.Response(402, json=cuerpo)).sintetizar("Hola")


# --- streaming ------------------------------------------------------------------------------------


async def _juntar(it) -> bytes:
    return b"".join([t async for t in it])


async def test_stream_usa_el_endpoint_stream_y_entrega_el_audio():
    visto = {}

    def handler(req: httpx.Request) -> httpx.Response:
        visto["url"] = str(req.url)
        visto["clave"] = req.headers.get("xi-api-key")
        return httpx.Response(200, content=b"MP3-STREAM")

    audio = await _juntar(tts_con(handler).sintetizar_stream("Hola", voz_id="otra"))
    assert audio == b"MP3-STREAM"
    assert visto["url"] == "http://tts/v1/text-to-speech/otra/stream?output_format=mp3_44100_128" and visto["clave"] == "k"


@pytest.mark.parametrize("respuesta", [httpx.Response(401), httpx.Response(429), httpx.Response(200, content=b"")])
async def test_stream_con_error_o_vacio_lanza_voz_error_en_la_primera_iteracion(respuesta):
    with pytest.raises(VozError):
        await anext(tts_con(lambda req: respuesta).sintetizar_stream("Hola"))


async def test_stream_con_red_caida_es_voz_error():
    def handler(req):
        raise httpx.ConnectError("x")

    with pytest.raises(VozError):
        await anext(tts_con(handler).sintetizar_stream("Hola"))
