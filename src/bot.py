import asyncio
import html
import io
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, constants
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from src import reminders
from src.config import TELEGRAM_BOT_TOKEN, ALLOWED_TELEGRAM_USER_ID, NOTIF_ATIVO
from src.storage import read_tasks_markdown
from src.history import clear_history
from src.guardrails import get_usage_summary
from src.agent import process_user_message
from src.telegram_format import reply_formatted
from src.notificacoes import telegram as notif_telegram

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# O httpx loga a URL de cada requisição, e a URL da API do Telegram contém o token do bot
logging.getLogger("httpx").setLevel(logging.WARNING)

def is_authorized(user_id: int) -> bool:
    """Verifica se o usuário é o dono autorizado do bot."""
    if ALLOWED_TELEGRAM_USER_ID is None:
        return True
    return user_id == ALLOWED_TELEGRAM_USER_ID

async def check_auth_or_warn(update: Update) -> bool:
    """Valida permissão e orienta caso não esteja autorizado."""
    user = update.effective_user
    if not user:
        return False
        
    if not is_authorized(user.id):
        await update.message.reply_text(
            f"⛔ Acesso restrito.\nSeu ID de usuário no Telegram é: `{user.id}`.\n"
            f"Adicione `ALLOWED_TELEGRAM_USER_ID={user.id}` no arquivo .env para autorizar.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return False
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_auth_or_warn(update):
        return
        
    user = update.effective_user
    warning = ""
    if ALLOWED_TELEGRAM_USER_ID is None:
        warning = (
            f"\n\n⚠️ *Atenção de Segurança:*\n"
            f"Seu Telegram ID é: `{user.id}`.\n"
            f"Adicione `ALLOWED_TELEGRAM_USER_ID={user.id}` no seu `.env` para travar o acesso apenas para você."
        )

    msg = (
        f"ALICE online. 🧠✨\n"
        f"*(ALICE Lembra, Integra, Cobra e Executa)*\n\n"
        f"Estou pronta como sua assistente pessoal.\n"
        f"• Mande texto ou áudio naturalmente (eu mantenho o contexto).\n"
        f"• `/tarefas` para ver seu arquivo Markdown completo.\n"
        f"• `/lembretes` para ver e cancelar os lembretes agendados.\n"
        f"• `/reset` para limpar o contexto da conversa ativa e começar do zero.{warning}"
    )
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)

async def consumo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_auth_or_warn(update):
        return
    await update.message.reply_text(get_usage_summary(), parse_mode=constants.ParseMode.MARKDOWN)

async def tarefas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_auth_or_warn(update):
        return
    tasks_md = read_tasks_markdown()
    await update.message.reply_text(tasks_md)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_auth_or_warn(update):
        return
    clear_history()
    await update.message.reply_text("🧹 Contexto de conversa limpo! Próxima mensagem iniciará um diálogo do zero.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_auth_or_warn(update):
        return
        
    text = update.message.text
    if not text:
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
    
    try:
        # Em outra thread: a chamada ao Gemini é síncrona e travaria o event loop (e o loop de lembretes)
        reply = await asyncio.to_thread(process_user_message, user_text=text, user_id=update.effective_user.id)
        await reply_formatted(update.message, reply)
    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocorreu um erro ao processar: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_auth_or_warn(update):
        return
        
    voice = update.message.voice or update.message.audio
    if not voice:
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.RECORD_VOICE)

    try:
        telegram_file = await context.bot.get_file(voice.file_id)
        audio_buffer = io.BytesIO()
        await telegram_file.download_to_memory(out=audio_buffer)
        audio_bytes = audio_buffer.getvalue()

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        caption = update.message.caption or ""
        reply = await asyncio.to_thread(
            process_user_message,
            user_text=caption if caption else None,
            audio_bytes=audio_bytes,
            mime_type="audio/ogg",
            user_id=update.effective_user.id
        )
        await reply_formatted(update.message, reply)
    except Exception as e:
        logger.error(f"Erro ao processar áudio: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocorreu um erro ao processar o áudio: {e}")

# --- Lembretes ---
# Um loop no próprio processo do bot acorda a cada REMINDER_POLL_SECONDS e manda os vencidos.
# O estado fica em data/lembretes.json (src/reminders.py), então nada se perde num restart:
# o que venceu com o bot fora do ar sai na volta, marcado como atrasado.

REMINDER_POLL_SECONDS = 30
GROUP_AFTER = 3  # mais vencidos que isso de uma vez viram uma mensagem só

def _reminder_text(reminder: dict, at) -> str:
    text = html.escape(reminder["texto"], quote=False)
    if reminders.is_late(reminder, at):
        text += f" <i>(atrasado: era {reminders.fmt_when(reminders.when_of(reminder))})</i>"
    return text

def _reminder_buttons(reminder: dict, number: int | None = None) -> list[InlineKeyboardButton]:
    rid = reminder["id"]
    if number is None:
        labels = ("✅ Feito", "⏰ +1h", "📅 Amanhã 9h")
    else:
        # Numa mensagem agrupada, o número na frente diz de qual item é o botão
        labels = (f"{number} ✅", f"{number} ⏰ +1h", f"{number} 📅 9h")
    return [
        InlineKeyboardButton(labels[0], callback_data=f"lem:ok:{rid}"),
        InlineKeyboardButton(labels[1], callback_data=f"lem:1h:{rid}"),
        InlineKeyboardButton(labels[2], callback_data=f"lem:am:{rid}"),
    ]

async def send_due_reminders(bot) -> None:
    due = await asyncio.to_thread(reminders.due)
    if not due:
        return
    at = reminders.now()
    if len(due) > GROUP_AFTER:
        lines = [f"{i}. {_reminder_text(r, at)}" for i, r in enumerate(due, 1)]
        keyboard = [_reminder_buttons(r, i) for i, r in enumerate(due, 1)]
        batches = [(f"⏰ <b>{len(due)} lembretes</b>\n" + "\n".join(lines), keyboard, due)]
    else:
        batches = [(f"⏰ {_reminder_text(r, at)}", [_reminder_buttons(r)], [r]) for r in due]

    for text, keyboard, items in batches:
        # Se o envio falhar, não marca: o próximo ciclo tenta de novo
        await bot.send_message(
            chat_id=ALLOWED_TELEGRAM_USER_ID,
            text=text,
            parse_mode=constants.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await asyncio.to_thread(reminders.mark_sent, [r["id"] for r in items])

async def reminder_loop(bot) -> None:
    while True:
        try:
            await send_due_reminders(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro ao enviar lembretes")
        await asyncio.sleep(REMINDER_POLL_SECONDS)

async def start_reminder_loop(app: Application) -> None:
    if ALLOWED_TELEGRAM_USER_ID is None:
        logger.warning("ALLOWED_TELEGRAM_USER_ID não definido: os lembretes não serão enviados.")
        return
    app.bot_data["reminder_task"] = asyncio.create_task(reminder_loop(app.bot))
    if NOTIF_ATIVO:
        # Filtro de e-mails (item 14): loop próprio, que nunca passa texto de e-mail ao agente
        app.bot_data["notif_task"] = asyncio.create_task(notif_telegram.loop(app.bot))

async def stop_reminder_loop(app: Application) -> None:
    for key in ("reminder_task", "notif_task"):
        task = app.bot_data.pop(key, None)
        if task:
            task.cancel()

async def lembretes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_auth_or_warn(update):
        return
    items = await asyncio.to_thread(reminders.pending)
    if not items:
        await update.message.reply_text("Nenhum lembrete pendente.")
        return
    lines = [
        f"{i}. <b>{reminders.fmt_when(reminders.when_of(r))}</b> · {html.escape(r['texto'], quote=False)}"
        for i, r in enumerate(items, 1)
    ]
    buttons = [InlineKeyboardButton(f"{i} 🗑", callback_data=f"lem:del:{r['id']}") for i, r in enumerate(items, 1)]
    keyboard = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    await update.message.reply_text(
        "⏰ <b>Lembretes pendentes</b>\n" + "\n".join(lines),
        parse_mode=constants.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def reminder_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Botões dos lembretes (feito, adiar, cancelar). Roda sem bloquear: não espera o Gemini terminar."""
    query = update.callback_query
    if not is_authorized(query.from_user.id):
        await query.answer("⛔ Acesso restrito.")
        return
    _, action, rid = query.data.split(":", 2)

    if action == "ok":
        note = "✅ feito"
    elif action == "del":
        result = await asyncio.to_thread(reminders.cancel, rid)
        note = "🗑 cancelado" if result.startswith("Lembrete cancelado") else "já não estava pendente"
    else:
        until = reminders.snooze_target("1h" if action == "1h" else "amanha")
        reminder = await asyncio.to_thread(reminders.snooze, rid, until)
        note = f"⏰ adiado para {reminders.fmt_when(until)}" if reminder else "esse lembrete não existe mais"
    await query.answer(note)

    # Tira da mensagem os botões desse lembrete e anota o que aconteceu com ele
    message = query.message
    if not isinstance(message, Message) or not message.reply_markup:
        return
    label = ""
    rows = []
    for row in message.reply_markup.inline_keyboard:
        kept = []
        for button in row:
            if button.callback_data and button.callback_data.endswith(f":{rid}"):
                first = button.text.split()[0]
                label = f"{first}: " if first.isdigit() else ""
            else:
                kept.append(button)
        if kept:
            rows.append(kept)
    try:
        await query.edit_message_text(
            f"{message.text_html}\n— {label}{note}",
            parse_mode=constants.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows) if rows else None,
        )
    except BadRequest as e:
        logger.warning(f"Não consegui editar a mensagem do lembrete: {e}")

def run_bot() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("\n❌ Erro: TELEGRAM_BOT_TOKEN não foi configurado no arquivo .env!\n")
        return

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(start_reminder_loop)
        .post_stop(stop_reminder_loop)
        .build()
    )

    app.add_handler(CommandHandler(["lembretes", "reminders"], lembretes_command))
    # block=False: o botão responde na hora mesmo com uma mensagem sendo processada pelo Gemini
    app.add_handler(CallbackQueryHandler(reminder_button, pattern=r"^lem:", block=False))
    if NOTIF_ATIVO:
        app.add_handler(CommandHandler("filtro", notif_telegram.filtro_command))
        app.add_handler(CallbackQueryHandler(notif_telegram.botao, pattern=r"^ntf:", block=False))

    app.add_handler(CommandHandler(["start", "ajuda", "help"], start_command))
    app.add_handler(CommandHandler(["tarefas", "tasks", "hoje"], tarefas_command))
    app.add_handler(CommandHandler(["consumo", "gastos", "budget"], consumo_command))
    app.add_handler(CommandHandler(["reset", "limpar"], reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    print("\n[OK] ALICE (bot do Telegram) iniciada com sucesso!\n")
    app.run_polling()
