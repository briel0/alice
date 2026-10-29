import io
import logging
from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from src.config import TELEGRAM_BOT_TOKEN, ALLOWED_TELEGRAM_USER_ID
from src.storage import read_tasks_markdown
from src.history import clear_history
from src.guardrails import get_usage_summary
from src.agent import process_user_message

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
        f"Estou pronta como sua Chefe de Gabinete.\n"
        f"• Mande texto ou áudio naturalmente (eu mantenho o contexto).\n"
        f"• `/tarefas` para ver seu arquivo Markdown completo.\n"
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
        reply = process_user_message(user_text=text, user_id=update.effective_user.id)
        await update.message.reply_text(reply)
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
        reply = process_user_message(
            user_text=caption if caption else None,
            audio_bytes=audio_bytes,
            mime_type="audio/ogg",
            user_id=update.effective_user.id
        )
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Erro ao processar áudio: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocorreu um erro ao processar o áudio: {e}")

def run_bot() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("\n❌ Erro: TELEGRAM_BOT_TOKEN não foi configurado no arquivo .env!\n")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler(["start", "ajuda", "help"], start_command))
    app.add_handler(CommandHandler(["tarefas", "tasks", "hoje"], tarefas_command))
    app.add_handler(CommandHandler(["consumo", "gastos", "budget"], consumo_command))
    app.add_handler(CommandHandler(["reset", "limpar"], reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    print("\n[OK] ALICE (bot do Telegram) iniciada com sucesso!\n")
    app.run_polling()
