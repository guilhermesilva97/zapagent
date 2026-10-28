import re
import unicodedata

_HUMAN_REQUEST = re.compile(
    r"\b(atendente|humano|pessoa de verdade|falar com (alguem|uma pessoa|o suporte)"
    r"|quero um atendente|nao quero falar com (robo|bot))\b"
)

HANDOFF_BY_CUSTOMER = "cliente pediu atendimento humano"
HANDOFF_BY_FAILURE = "falha no assistente virtual"
HANDOFF_BY_LIMIT = "assistente não concluiu o atendimento"

HANDOFF_MESSAGE = (
    "Certo! Vou te transferir para um atendente. "
    "Em instantes alguém da nossa equipe continua por aqui."
)
FALLBACK_MESSAGE = (
    "Desculpe, estou com instabilidade agora. "
    "Já chamei um atendente da nossa equipe para continuar seu atendimento."
)
RELEASE_MESSAGE = "Obrigado pela paciência! Se precisar de algo mais, é só mandar mensagem."


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return decomposed.encode("ascii", "ignore").decode().lower()


def wants_human(text: str) -> bool:
    return bool(_HUMAN_REQUEST.search(_normalize(text)))
