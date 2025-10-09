# scheduler.py
import os
import asyncio
from typing import Dict, Set, List
from datetime import datetime

from db import SessionLocal, SavedSearch
from wallapop import search_items, search_items_fake

# ===== Config =====
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SEC", "10"))
USE_FAKE = os.getenv("WALLA_MODE", "real").lower() != "real"

BULK_THRESHOLD = int(os.getenv("BULK_THRESHOLD", "5"))     # >5 => listado sencillo
BULK_MAX_ITEMS = int(os.getenv("BULK_MAX_ITEMS", "25"))    # tope de items en listado
SEND_DELAY_MS  = int(os.getenv("SEND_DELAY_MS", "250"))    # delay entre envíos individuales (ms)

# ===== Estado de notificación por búsqueda =====
_notified_for_search: Dict[int, Set[str]] = {}

# ===== Helpers de formato =====
def _fmt_eur(n: float) -> str:
    try:
        # Formato europeo con dos decimales siempre
        return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"{n} €"

def _clean_title(t: str) -> str:
    # Evita que símbolos raros o saltos arruinen el mensaje
    t = (t or "").strip()
    return " ".join(t.split())

def _ship_badge(shipping: bool) -> str:
    return "📦" if shipping else ""

def _build_bulk_message(query_text: str, items: List) -> str:
    # Listado sencillo y bonito
    lines = []
    lines.append("🔔 Nuevos resultados")
    lines.append(f"🔎 [{query_text}]")
    lines.append("")

    # top en BULK_MAX_ITEMS
    take = items[:BULK_MAX_ITEMS]
    for i, it in enumerate(take, 1):
        title = _clean_title(it.title)
        price = _fmt_eur(it.price) if it.price else "—"
        ship = f" {_ship_badge(it.shipping)}" if it.shipping else ""
        lines.append(f"{i}. {title} — {price}{ship}")
        lines.append(f"   {it.url}")
    if len(items) > BULK_MAX_ITEMS:
        lines.append(f"... y {len(items) - BULK_MAX_ITEMS} más")

    return "\n".join(lines)

def _build_item_message(query_text: str, it) -> str:
    # Mensaje detallado por item (texto plano)
    lines = []
    lines.append("🔔 Nuevo resultado")
    lines.append(f"🔎 {query_text}")
    lines.append("")
    lines.append(f"📌 { _clean_title(it.title) }")
    if it.price:
        lines.append(f"💶 { _fmt_eur(it.price) }")
    if it.shipping:
        lines.append("📦 Envío disponible")
    lines.append(it.url)
    return "\n".join(lines)

# ===== Loop principal =====
async def loop_checks(app):
    print(f"🔁 Scheduler arrancado (intervalo {CHECK_INTERVAL}s, modo {'fake' if USE_FAKE else 'real'})")
    while True:
        try:
            # 1) Cargar búsquedas activas
            with SessionLocal() as s:
                searches = s.query(SavedSearch).filter_by(active=True).all()

            for ss in searches:
                # Parsear nombre y filtros embebidos (compat con tu bot.py)
                query_text = ss.query
                filters = {}
                if "(filtros:" in ss.query:
                    try:
                        base, tail = ss.query.split("(filtros:", 1)
                        query_text = base.strip()
                        import ast
                        filters = ast.literal_eval(tail.strip(" )")) if tail else {}
                    except Exception:
                        query_text = ss.query
                        filters = {}

                # 2) Buscar items
                items = []
                try:
                    if USE_FAKE:
                        items = search_items_fake(query_text)
                    else:
                        items = await search_items(query_text, filters)
                except Exception as e:
                    print("[SCHED] Error en search_items:", e)
                    items = []

                print(f"[SCHED] Búsqueda #{ss.id} '{query_text}': {len(items)} items recibidos")

                if not items:
                    continue

                # 3) Aplicar filtro omit (descartar palabras prohibidas en el título)
                omit_words = [w.lower() for w in filters.get("omit", [])]
                if omit_words:
                    before = len(items)
                    items = [it for it in items if all(w not in it.title.lower() for w in omit_words)]
                    print(f"[SCHED]   Tras omitir {omit_words}: {before} -> {len(items)}")

                if not items:
                    continue

                # 4) Preparar set de notificados
                notified = _notified_for_search.setdefault(ss.id, set())

                # 5) Filtrar solo los NO notificados
                fresh = [it for it in items if it.id not in notified]
                print(f"[SCHED]   Nuevos no notificados: {len(fresh)}")

                if not fresh:
                    continue

                # 6) Enviar según umbral
                try:
                    if len(fresh) > BULK_THRESHOLD:
                        # Listado sencillo en un solo mensaje
                        msg = _build_bulk_message(query_text, fresh)
                        await app.bot.send_message(chat_id=ss.user_id, text=msg)
                        # Marcar todos como notificados
                        for it in fresh:
                            notified.add(it.id)
                    else:
                        # Envío individual detallado con pequeño delay
                        for it in fresh:
                            text = _build_item_message(query_text, it)
                            await app.bot.send_message(chat_id=ss.user_id, text=text)
                            notified.add(it.id)
                            await asyncio.sleep(SEND_DELAY_MS / 1000.0)
                except Exception as send_err:
                    print("Error enviando mensaje:", send_err)

                # 7) Log pequeño para seguimiento
                try:
                    if fresh:
                        last = fresh[0]
                        print(f"[{datetime.now().isoformat()}] Enviado a {ss.user_id}: {last.id} ({query_text})")
                except Exception:
                    pass

        except Exception as loop_err:
            print("scheduler loop error:", loop_err)

        await asyncio.sleep(CHECK_INTERVAL)
