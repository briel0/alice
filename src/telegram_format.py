"""Converte o Markdown que o Gemini escreve no HTML que o Telegram entende.

O modo Markdown do próprio Telegram recusa a mensagem inteira por um caractere fora do lugar, e o modelo
erra com frequência; o HTML só exige escapar `&`, `<` e `>`. Se mesmo assim o Telegram recusar, quem envia
cai para texto puro (`reply_formatted`).
"""
import html
import re

from telegram import Message, constants
from telegram.error import BadRequest

# Código primeiro, para nada dentro dele virar negrito ou link
_CODE = re.compile(r"```(?:[\w+-]*\n)?([\s\S]*?)```|`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[*-]\s+", re.MULTILINE)


def _inline(text: str) -> str:
    """Formata um trecho sem código. Recebe texto cru e devolve HTML seguro."""
    text = html.escape(text, quote=False)
    text = _HEADING.sub(r"<b>\1</b>", text)
    text = _BULLET.sub(r"\1• ", text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    # A URL já foi escapada junto com o resto; falta só a aspa, que fecharia o atributo
    return _LINK.sub(lambda m: f'<a href="{m.group(2).replace(chr(34), "&quot;")}">{m.group(1)}</a>', text)


def to_telegram_html(text: str) -> str:
    parts = []
    last = 0
    for match in _CODE.finditer(text):
        parts.append(_inline(text[last:match.start()]))
        block, inline = match.group(1), match.group(2)
        if block is not None:
            parts.append(f"<pre>{html.escape(block.strip(), quote=False)}</pre>")
        else:
            parts.append(f"<code>{html.escape(inline, quote=False)}</code>")
        last = match.end()
    parts.append(_inline(text[last:]))
    return "".join(parts)


async def reply_formatted(message: Message, text: str) -> None:
    """Responde com a formatação convertida; se o Telegram recusar o HTML, manda o texto como veio."""
    try:
        await message.reply_text(to_telegram_html(text), parse_mode=constants.ParseMode.HTML)
    except BadRequest:
        await message.reply_text(text)
