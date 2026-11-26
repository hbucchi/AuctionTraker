"""Daily alerts: find listings that newly match each user's strategies.

Firestore layout
  users/{uid}         written by the user's browser: {email, name, strategies: [...]}
  alert_state/{uid}   written only by this job: per strategy, the ids already
                      seen and the ids that were new in the last run
                      {strategies: {sid: {seen: [...], new: [...], count, run_at}}}

How "new" works
  seen = every id that matched before. A listing is new when it matches now
  and isn't in seen. The first time a strategy runs, everything that matches
  becomes the baseline: no email (it would list every current match), the
  app shows them all anyway.

Email
  Sent through Resend (https://resend.com) when RESEND_API_KEY is set; the
  sender is ALERT_FROM (default "AuctionTraker <onboarding@resend.dev>",
  which Resend only lets you send to your own account's address until you
  verify a domain).
"""

from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from .strategy import matches

log = logging.getLogger("alerts")
SITE_URL = os.environ.get("ALERT_SITE_URL", "https://auctiontraker.web.app")
SITES = {"zuk": "Portal Zuk", "biasi": "Biasi", "frazao": "Frazão", "superbid": "Superbid",
         "picelli": "Picelli", "alfa": "Alfa", "pgfn": "PGFN Comprei"}


def evaluate(strategies: list[dict], items: list[dict], state: dict, now: float) -> tuple[dict, dict[str, list[dict]]]:
    """Pure function: returns (new_state, {strategy_id: [new items]})."""
    current_ids = {i["id"] for i in items}
    new_state: dict[str, Any] = {"strategies": {}}
    news: dict[str, list[dict]] = {}
    for st in strategies:
        sid = st.get("id")
        if not sid or not st.get("enabled", True):
            continue
        matched = [i for i in items if matches(st, i, now)]
        prev = (state.get("strategies") or {}).get(sid)
        seen = set(prev["seen"]) if prev else None
        fresh = [] if seen is None else [i for i in matched if i["id"] not in seen]
        # forget ids that disappeared from the sites, so the list can't grow forever
        keep = ((seen or set()) & current_ids) | {i["id"] for i in matched}
        new_state["strategies"][sid] = {
            "seen": sorted(keep),
            "new": [i["id"] for i in fresh],
            "count": len(matched),
            "baseline": seen is None,
            "run_at": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        }
        if fresh:
            news[sid] = fresh
    return new_state, news


def _brl(v: float | None) -> str:
    if v is None:
        return "—"
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def render_email(user: dict, strategies: list[dict], news: dict[str, list[dict]]) -> tuple[str, str]:
    total = sum(len(v) for v in news.values())
    subject = f"{total} novo{'s' if total > 1 else ''} imóve{'is' if total > 1 else 'l'} na sua estratégia"
    parts = [
        '<div style="font-family:Arial,sans-serif;max-width:640px;color:#15202c">',
        f"<p>Olá{(' ' + html.escape(user.get('name').split()[0])) if user.get('name') else ''},</p>",
        f"<p>Encontramos <b>{total}</b> oportunidade{'s' if total > 1 else ''} que atende{'m' if total > 1 else ''} aos seus critérios desde o último aviso.</p>",
    ]
    by_id = {s["id"]: s for s in strategies}
    for sid, items in news.items():
        parts.append(f'<h3 style="margin:24px 0 8px">{html.escape(by_id[sid].get("name") or "Estratégia")}</h3>')
        for i in sorted(items, key=lambda i: i.get("ptm") or 999)[:30]:
            ptm = f" · lance = {i['ptm']:.0f}% do valor de mercado" if i.get("ptm") is not None else ""
            debts = {True: " · dívidas ficam com o arrematante", False: " · vendedor paga as dívidas"}.get(i.get("debts"), "")
            where = ", ".join(x for x in [i.get("hood"), f"{i.get('city')}/{i.get('uf')}" if i.get("city") else None] if x)
            parts.append(
                '<div style="padding:10px 0;border-top:1px solid #dce2ea">'
                f'<a href="{html.escape(i["url"])}" style="color:#1f4fd1;font-weight:bold">{html.escape(i["title"])}</a><br>'
                f'<span style="color:#5a6676">{html.escape(where)} · {SITES.get(i["src"], i["src"])}</span><br>'
                f"<b>{_brl(i.get('price'))}</b>{html.escape(ptm)}{html.escape(debts)}</div>"
            )
        if len(items) > 30:
            parts.append(f"<p>…e mais {len(items) - 30} no app.</p>")
    parts.append(
        f'<p style="margin-top:24px"><a href="{SITE_URL}">Abrir o AuctionTraker</a> para ver todos, '
        "ajustar os filtros ou desativar estes avisos.</p>"
        '<p style="color:#5a6676;font-size:12px">Confira sempre o edital antes de dar um lance: valores de mercado '
        "e responsabilidade por dívidas são extraídos automaticamente e podem conter erros.</p></div>"
    )
    return subject, "".join(parts)


def send_resend(to: str, subject: str, body_html: str) -> None:
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        log.info("RESEND_API_KEY not set; skipping email to %s", to.split("@")[0][:2] + "***")
        return
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "from": os.environ.get("ALERT_FROM", "AuctionTraker <onboarding@resend.dev>"),
            "to": [to],
            "subject": subject,
            "html": body_html,
        },
        timeout=30,
    )
    if r.status_code >= 400:
        log.error("email failed: HTTP %s %s", r.status_code, r.text[:200])
    r.raise_for_status()


def run(db: Any, items: list[dict], now: float | None = None, send: Callable[[str, str, str], None] = send_resend) -> dict:
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    stats = {"users": 0, "emails": 0, "new": 0}
    for doc in db.collection("users").stream():
        user = doc.to_dict() or {}
        strategies = [s for s in user.get("strategies") or [] if isinstance(s, dict)]
        if not strategies:
            continue
        stats["users"] += 1
        ref = db.collection("alert_state").document(doc.id)
        snap = ref.get()
        state = (snap.to_dict() or {}) if snap.exists else {}
        new_state, news = evaluate(strategies, items, state, now)
        ref.set(new_state)
        stats["new"] += sum(len(v) for v in news.values())
        emailable = {sid: v for sid, v in news.items() if next((s for s in strategies if s.get("id") == sid), {}).get("email")}
        if emailable and user.get("email"):
            subject, body = render_email(user, strategies, emailable)
            try:
                send(user["email"], subject, body)
                stats["emails"] += 1
            except requests.RequestException:
                log.exception("could not email user %s", doc.id)
    return stats
