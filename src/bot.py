# bot.py
import os, asyncio, ast, re
from typing import Tuple, Dict, Any, List

from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters,
)
from db import init_db, ensure_user, SessionLocal, SavedSearch, User
from scheduler import loop_checks

TOKEN = os.getenv("TELEGRAM_TOKEN")

# ======================
# Helpers comunes
# ======================
def normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def parse_saved_query(raw_query: str) -> Tuple[str, Dict[str, Any]]:
    filters = {}
    query_text = raw_query
    if "(filtros:" in raw_query:
        try:
            base, filt_str = raw_query.split("(filtros:", 1)
            query_text = base.strip()
            filt_dict = filt_str.strip(" )")
            filters = ast.literal_eval(filt_dict) if filt_dict else {}
        except Exception:
            query_text = raw_query
            filters = {}
    return query_text, filters

def format_filters_pretty(filters: dict) -> str:
    if not filters:
        return ""
    lines = ["Filtros:"]
    if "min" in filters:
        lines.append(f"  💶 Min: {filters['min']:.2f} €")
    if "max" in filters:
        lines.append(f"  💰 Max: {filters['max']:.2f} €")
    if "km" in filters:
        lines.append(f"  📍 Distancia: {int(filters['km'])} km")
    if filters.get("shipping"):
        lines.append("  📦 Con envío")
    strict = filters.get("strict", True)
    lines.append(f"  🎯 Coincidencia: {'Estricta' if strict else 'Flexible'}")
    if filters.get("omit"):
        lines.append(f"  🚫 Omitir: {', '.join(filters['omit'])}")
    return "\n".join(lines)

# ======================
# /start /stop simples
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user.id, update.effective_user.username)
    with SessionLocal() as s:
        user = s.get(User, update.effective_user.id)
        if user:
            user.active = True
            s.commit()
    await update.message.reply_text("✅ Bot activado. Usa /buscar <texto> para crear una búsqueda.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as s:
        user = s.get(User, update.effective_user.id)
        if user:
            user.active = False
            s.commit()
    await update.message.reply_text("⛔ Bot desactivado. No recibirás más alertas.")

# ======================
# /mis_busquedas con botones toggle/borrar/editar
# ======================
async def mis_busquedas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as s:
        searches = s.query(SavedSearch).filter_by(user_id=update.effective_user.id).all()
        if not searches:
            await update.message.reply_text("📭 No tienes búsquedas guardadas.")
            return

        await update.message.reply_text("📋 Tus búsquedas guardadas\nPulsa los botones para gestionarlas")

        for ss in searches:
            query_text, filters = parse_saved_query(ss.query)
            estado_text = "🟢 Activa" if ss.active else "🔴 Inactiva"

            text = f"#{ss.id}  🔎 {query_text}\nEstado: {estado_text}"
            pretty = format_filters_pretty(filters)
            if pretty:
                text += f"\n{pretty}"

            toggle_text = "🟥 Desactivar" if ss.active else "🟩 Activar"
            keyboard = [[
                InlineKeyboardButton(toggle_text, callback_data=f"toggle:{ss.id}"),
                InlineKeyboardButton("✏️ Editar", callback_data=f"edit:{ss.id}"),
                InlineKeyboardButton("🗑️ Borrar", callback_data=f"del:{ss.id}"),
            ]]
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def manage_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split(":")
    action, search_id = data[0], int(data[1])

    with SessionLocal() as s:
        ss = s.get(SavedSearch, search_id)
        if not ss or ss.user_id != q.from_user.id:
            await q.edit_message_text("❌ No encontré esa búsqueda.")
            return

        if action == "del":
            s.delete(ss)
            s.commit()
            await q.edit_message_text(f"🗑️ Búsqueda {search_id} eliminada.")
            return

        if action == "toggle":
            ss.active = not ss.active
            s.commit()

            query_text, filters = parse_saved_query(ss.query)
            estado_text = "🟢 Activa" if ss.active else "🔴 Inactiva"
            text = f"#{ss.id}  🔎 {query_text}\nEstado: {estado_text}"
            pretty = format_filters_pretty(filters)
            if pretty:
                text += f"\n{pretty}"

            toggle_text = "🟥 Desactivar" if ss.active else "🟩 Activar"
            kb = [[
                InlineKeyboardButton(toggle_text, callback_data=f"toggle:{ss.id}"),
                InlineKeyboardButton("✏️ Editar", callback_data=f"edit:{ss.id}"),
                InlineKeyboardButton("🗑️ Borrar", callback_data=f"del:{ss.id}"),
            ]]
            await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ======================
# Conversación /buscar y edición
# ======================
FILTER_MENU, AWAIT_VALUE = range(2)

def _render_menu_text(state: dict) -> str:
    name = state.get("name") or "(sin nombre)"
    f = state.get("filters") or {}
    lines = [f"🧭 Configura filtros para: {name}"]
    pretty = format_filters_pretty(f)
    if pretty:
        lines.append("")
        lines.append(pretty)
    else:
        lines.append("\nFiltros: (ninguno)")
    lines.append("\nElige opción:")
    return "\n".join(lines)

def _render_menu_kb(state: dict) -> InlineKeyboardMarkup:
    f = state.get("filters") or {}
    def label_num(key, icon, suf):
        val = f.get(key)
        return f"{icon} {key.upper()}: {val if val is not None else '—'}{suf}"

    envio = "Sí" if f.get("shipping") else "No"
    strict = f.get("strict", True)
    omit_txt = ", ".join(f.get("omit", [])) if f.get("omit") else "—"
    keyboard = [
        [InlineKeyboardButton("✏️ Nombre", callback_data="ask:name")],
        [
            InlineKeyboardButton(label_num("min", "💶", "€"), callback_data="ask:min"),
            InlineKeyboardButton(label_num("max", "💰", "€"), callback_data="ask:max"),
        ],
        [
            InlineKeyboardButton(label_num("km", "📍", " km"), callback_data="ask:km"),
            InlineKeyboardButton(f"📦 Envío: {envio}", callback_data="toggle:shipping"),
        ],
        [InlineKeyboardButton(f"🎯 Coincidencia: {'Estricta' if strict else 'Flexible'}", callback_data="toggle:strict")],
        [InlineKeyboardButton(f"🚫 Omitir: {omit_txt}", callback_data="ask:omit")],
        [
            InlineKeyboardButton("✅ Guardar", callback_data="save"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def _validate_min_max(filters: Dict[str, Any]) -> Tuple[bool, str]:
    if "min" in filters and "max" in filters:
        try:
            mn = float(filters["min"]); mx = float(filters["max"])
        except Exception:
            return False, "❌ Min/Max deben ser números."
        if mx < mn:
            return False, "❌ Max no puede ser menor que Min."
    return True, ""

# --- /buscar (crear nueva) ---
async def buscar_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /buscar <texto>")
        return ConversationHandler.END

    name = " ".join(context.args).strip()
    context.user_data["new_search"] = {"name": name, "filters": {"strict": True}, "edit_id": None}
    await update.message.reply_text(_render_menu_text(context.user_data["new_search"]),
                                    reply_markup=_render_menu_kb(context.user_data["new_search"]))
    return FILTER_MENU

# --- /editar (desde botón edit) ---
async def edit_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sid = int(q.data.split(":")[1])
    with SessionLocal() as s:
        ss = s.get(SavedSearch, sid)
        if not ss or ss.user_id != q.from_user.id:
            await q.edit_message_text("❌ No encontré esa búsqueda.")
            return ConversationHandler.END
        qtext, filters = parse_saved_query(ss.query)
        context.user_data["new_search"] = {"name": qtext, "filters": filters or {"strict": True}, "edit_id": sid}
    state = context.user_data["new_search"]
    await q.edit_message_text(_render_menu_text(state), reply_markup=_render_menu_kb(state))
    return FILTER_MENU

# --- menú y valores ---
async def buscar_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    state = context.user_data.get("new_search")

    if data.startswith("ask:"):
        key = data.split(":")[1]
        context.user_data["await_key"] = key
        await q.edit_message_text(f"Introduce valor para {key.upper()}:" if key != "omit"
                                  else "Introduce palabras a omitir, separadas por comas:")
        return AWAIT_VALUE

    if data == "toggle:shipping":
        state["filters"]["shipping"] = not state["filters"].get("shipping", False)
    if data == "toggle:strict":
        state["filters"]["strict"] = not state["filters"].get("strict", True)

    if data == "save":
        ok, msg = _validate_min_max(state["filters"])
        if not ok:
            await q.edit_message_text(msg + "\n\n" + _render_menu_text(state),
                                      reply_markup=_render_menu_kb(state))
            return FILTER_MENU

        name, filters, sid = state["name"], state["filters"], state.get("edit_id")
        with SessionLocal() as s:
            ensure_user(q.from_user.id, q.from_user.username)
            query_display = f"{name} (filtros: {filters})" if filters else name
            if sid:
                ss = s.get(SavedSearch, sid)
                if ss:
                    ss.query = query_display
                    s.commit()
            else:
                s.add(SavedSearch(user_id=q.from_user.id, query=query_display))
                s.commit()

        confirm = f"🔎 Guardada búsqueda: {name}"
        pretty = format_filters_pretty(filters)
        if pretty: confirm += f"\n{pretty}"
        await q.edit_message_text(confirm)
        context.user_data.clear()
        return ConversationHandler.END

    if data == "cancel":
        msg = "❌ Búsqueda cancelada."
        if state.get("edit_id"):
            msg = "❌ Edición cancelada."
        await q.edit_message_text(msg)
        context.user_data.clear()
        return ConversationHandler.END

    await q.edit_message_text(_render_menu_text(state), reply_markup=_render_menu_kb(state))
    return FILTER_MENU

async def buscar_await_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("new_search")
    key = context.user_data.get("await_key")
    txt = (update.message.text or "").strip()

    if key == "name":
        state["name"] = txt
    elif key == "omit":
        words = [w.strip().lower() for w in txt.split(",") if w.strip()]
        state["filters"]["omit"] = words
    else:
        try:
            if key == "km":
                val = int(txt)
            else:
                val = float(txt)
            if val < 0: raise ValueError()
        except Exception:
            await update.message.reply_text("❌ Valor no válido.")
            return AWAIT_VALUE
        state["filters"][key] = val

    context.user_data["await_key"] = None
    await update.message.reply_text(_render_menu_text(state), reply_markup=_render_menu_kb(state))
    return FILTER_MENU

async def buscar_cancel_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Usa /buscar <texto> o pulsa EDITAR en una búsqueda.")
    return ConversationHandler.END

# ======================
# Arranque y comandos
# ======================
async def on_startup(app):
    await asyncio.sleep(1)
    app.create_task(loop_checks(app))

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("mis_busquedas", mis_busquedas))
    app.add_handler(CallbackQueryHandler(manage_button_handler, pattern=r"^(toggle|del):\d+$"))

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("buscar", buscar_entry),
            CallbackQueryHandler(edit_entry, pattern=r"^edit:\d+$"),
        ],
        states={
            FILTER_MENU: [CallbackQueryHandler(buscar_menu_cb,
                       pattern=r"^(ask:(min|max|km|name|omit)|toggle:shipping|toggle:strict|save|cancel)$")],
            AWAIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buscar_await_value)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, buscar_cancel_fallback)],
        allow_reentry=True,
    )
    app.add_handler(conv)

    commands = [
        BotCommand("start", "Activar el bot"),
        BotCommand("stop", "Desactivar el bot"),
        BotCommand("buscar", "Crear búsqueda nueva"),
        BotCommand("mis_busquedas", "Listar y gestionar búsquedas"),
    ]

    async def post_init(app_: Application):
        await app_.bot.set_my_commands(commands)
        await on_startup(app_)

    app.post_init = post_init
    print("🤖 Bot arrancando con edición funcionando...")
    app.run_polling()

if __name__ == "__main__":
    main()
