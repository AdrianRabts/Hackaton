# app/bot_assistant.py
import json
import os
import random
from typing import Any, Dict, List, Optional, Tuple

import requests

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _extract_output_text(resp_json: dict) -> str:
    chunks: List[str] = []
    for item in resp_json.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                chunks.append(c.get("text", ""))
    return "\n".join(chunks).strip()


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _make_schema(categories: List[str]) -> Dict[str, Any]:
    # Schema “lean” para que no se reviente el demo y sea 100% compatible con tus templates.
    return {
        "name": "itinerary_schema",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "route": {"type": "string"},
                "days": {"type": "integer", "minimum": 1, "maximum": 7},
                "budget": {"type": "number", "minimum": 0},
                "estimate_total": {"type": "number", "minimum": 0},
                "estimate_per_person": {"type": "number", "minimum": 0},
                "party_size": {"type": "integer", "minimum": 1, "maximum": 10},
                "language": {"type": "string"},
                "package_name": {"type": "string"},
                "narrative": {"type": "string"},
                "plan_b": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                "sustainability": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                "itinerary": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "day": {"type": "integer", "minimum": 1, "maximum": 3},
                            "day_theme": {"type": "string"},
                            "items": {
                                "type": "array",
                                "maxItems": 4,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "listing_id": {"type": "string"},
                                        "title": {"type": "string"},
                                        "category": {"type": "string", "enum": categories},
                                        "why": {"type": "string"},
                                        "price_usd": {"type": "number", "minimum": 0},
                                        "duration_min": {"type": "integer", "minimum": 1, "maximum": 600},
                                        "address": {"type": "string"},
                                        "maps_url": {"type": ["string", "null"]},
                                        "tiktok_url": {"type": ["string", "null"]},
                                    },
                                    "required": [
                                        "listing_id",
                                        "title",
                                        "category",
                                        "why",
                                        "price_usd",
                                        "duration_min",
                                        "address",
                                        "maps_url",
                                        "tiktok_url",
                                    ],
                                },
                            },
                        },
                        "required": ["day", "day_theme", "items"],
                    },
                },
            },
            "required": [
                "route",
                "days",
                "budget",
                "estimate_total",
                "estimate_per_person",
                "party_size",
                "language",
                "package_name",
                "narrative",
                "plan_b",
                "sustainability",
                "itinerary",
            ],
        },
        "strict": True,
    }


def _openai_structured(messages: List[dict], schema: Dict[str, Any], max_output_tokens: int = 900) -> dict:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en .env")

    model = (os.getenv("OPENAI_MODEL") or "").strip() or "gpt-4.1-mini"

    payload = {
        "model": model,
        "input": messages,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema["name"],
                "schema": schema["schema"],
                "strict": True,
            }
        },
        "store": False,
        "max_output_tokens": max_output_tokens,
    }

    r = requests.post(
        OPENAI_RESPONSES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=35,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {r.status_code}: {r.text[:500]}")

    resp_json = r.json()
    txt = _extract_output_text(resp_json)
    if not txt:
        raise RuntimeError("OpenAI no devolvió texto")
    return json.loads(txt)


def _recalc_per_person(itinerary: List[dict]) -> float:
    total = 0.0
    for day in itinerary or []:
        for it in (day.get("items") or []):
            total += _safe_float(it.get("price_usd"), 0.0)
    return round(total, 2)


def build_itinerary_pro(
    *,
    route: str,
    days: int,
    budget_per_person: float,
    interests: List[str],
    candidates: List[dict],
    party_size: int = 2,
    language_pref: str = "ES/EN",
    categories: Optional[List[str]] = None,
) -> dict:
    categories = categories or ["comida", "historico", "parque", "artesania"]

    route_clean = (route or "").strip()
    days = _clamp(_safe_int(days, 2), 1, 7)
    party_size = _clamp(_safe_int(party_size, 2), 1, 10)
    budget_per_person = max(0.0, _safe_float(budget_per_person, 60.0))

    interests_norm = [_norm(x) for x in (interests or []) if _norm(x) in categories]

    # Candidatos “slim” (para no mandar una biblia)
    slim: List[dict] = []
    for l in (candidates or [])[:50]:
        slim.append(
            {
                "id": l.get("id", ""),
                "title": l.get("title", ""),
                "category": _norm(l.get("category", "")),
                "short_desc": l.get("short_desc", ""),
                "price_usd": _safe_float(l.get("price_usd"), 0.0),
                "duration_min": _safe_int(l.get("duration_min"), 60),
                "address": l.get("address", ""),
                "maps_url": (l.get("maps_url") or None) if str(l.get("maps_url") or "").strip() else None,
                "tiktok_url": (l.get("tiktok_url") or None) if str(l.get("tiktok_url") or "").strip() else None,
                "tags": l.get("tags", []),
            }
        )

    schema = _make_schema(categories)

    system = (
        "Eres un asistente para planificar rutas culturales sostenibles en Ecuador.\n"
        "REGLAS DURAS:\n"
        "1) NO inventes lugares.\n"
        "2) SOLO usa listing_id de los candidatos.\n"
        "3) Mantén el itinerario vendible: claro, logístico, realista.\n"
        "4) Máximo 4 items por día.\n"
        "5) Si no hay intereses, mezcla categorías.\n"
        "6) Escribe en el idioma indicado por user_language.\n"
        "7) budget es por persona. estimate_per_person es suma del plan por persona. estimate_total = estimate_per_person * party_size.\n"
    )

    user_payload = {
        "route": route_clean,
        "days": days,
        "party_size": party_size,
        "budget_usd_per_person": budget_per_person,
        "user_language": language_pref,
        "interests_categories": interests_norm,
        "candidates": slim,
        "constraints": {"max_items_per_day": 4},
    }

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]

    listing_map = {l.get("id"): l for l in (candidates or []) if l.get("id")}
    valid_ids = set(listing_map.keys())

    # Intento IA (con retry)
    try:
        try:
            result = _openai_structured(messages, schema, max_output_tokens=1000)
        except Exception:
            # retry: más corto
            messages2 = [
                {"role": "system", "content": system + "\nSé más breve en narrative."},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ]
            result = _openai_structured(messages2, schema, max_output_tokens=800)

        # Sanitizar: anti-inventos + completar campos desde db.json
        clean_days: List[dict] = []
        for day in (result.get("itinerary") or []):
            items_ok: List[dict] = []
            for it in (day.get("items") or []):
                lid = it.get("listing_id")
                if lid not in valid_ids:
                    continue
                src = listing_map[lid]

                it["title"] = (it.get("title") or src.get("title") or "Experiencia").strip()
                cat = _norm(it.get("category") or src.get("category") or categories[0])
                it["category"] = cat if cat in categories else _norm(src.get("category") or categories[0])
                it["price_usd"] = _safe_float(it.get("price_usd"), _safe_float(src.get("price_usd"), 0.0))
                it["duration_min"] = _safe_int(it.get("duration_min"), _safe_int(src.get("duration_min"), 60))
                it["address"] = (it.get("address") or src.get("address") or "-").strip()
                it["maps_url"] = it.get("maps_url") if it.get("maps_url") else (src.get("maps_url") or None)
                it["tiktok_url"] = it.get("tiktok_url") if it.get("tiktok_url") else (src.get("tiktok_url") or None)

                items_ok.append(it)

            clean_days.append(
                {
                    "day": _safe_int(day.get("day"), 1),
                    "day_theme": (day.get("day_theme") or "Ruta cultural optimizada").strip(),
                    "items": items_ok,
                }
            )

        result["itinerary"] = clean_days

        # Recalcular costos (para que no se invente números raros)
        per_person = _recalc_per_person(result.get("itinerary") or [])
        result["estimate_per_person"] = per_person
        result["estimate_total"] = round(per_person * party_size, 2)

        # Completar campos base si faltan
        result["route"] = result.get("route") or route_clean
        result["days"] = _safe_int(result.get("days"), days)
        result["budget"] = _safe_float(result.get("budget"), budget_per_person)
        result["party_size"] = _safe_int(result.get("party_size"), party_size)
        result["language"] = (result.get("language") or language_pref).strip() or "ES/EN"
        result["package_name"] = (result.get("package_name") or f"Ruta Cultural: {route_clean}").strip()
        result["narrative"] = (result.get("narrative") or "Itinerario diseñado para maximizar cultura y economía local.").strip()
        result["plan_b"] = result.get("plan_b") or ["Si llueve: prioriza talleres/museos.", "Si está lleno: cambia por un spot similar cercano."]
        result["sustainability"] = result.get("sustainability") or [
            "Compra local (directo a emprendimientos).",
            "Respeta la cultura: pide permiso antes de grabar.",
            "Evita saturar sitios pequeños en horas pico.",
        ]

        return result

    except Exception as e:
        # Fallback: IA se fue a producción sin tests, pero el demo no muere
        pool = list(candidates or [])
        random.shuffle(pool)

        itinerary: List[dict] = []
        budget_left = budget_per_person

        def pick_items(pool_items: List[dict], interest_list: List[str], budget_left_val: float, max_items: int = 4) -> Tuple[List[dict], float]:
            p = pool_items[:]
            if interest_list:
                filtered = [x for x in p if _norm(x.get("category", "")) in interest_list]
                if filtered:
                    p = filtered

            p = sorted(p, key=lambda x: _safe_float(x.get("price_usd"), 0.0))
            picked: List[dict] = []
            total = 0.0
            for item in p:
                if len(picked) >= max_items:
                    break
                price = _safe_float(item.get("price_usd"), 0.0)
                if total + price <= budget_left_val:
                    picked.append(item)
                    total += price
            return picked, round(total, 2)

        for d in range(1, days + 1):
            day_items, day_total = pick_items(pool, interests_norm, budget_left, 4)
            budget_left = max(0.0, budget_left - day_total)
            itinerary.append(
                {
                    "day": d,
                    "day_theme": "Selección por presupuesto",
                    "items": [
                        {
                            "listing_id": it.get("id", ""),
                            "title": it.get("title", "Experiencia"),
                            "category": _norm(it.get("category") or categories[0]),
                            "why": "Selección automática por presupuesto/categoría (fallback).",
                            "price_usd": _safe_float(it.get("price_usd"), 0.0),
                            "duration_min": _safe_int(it.get("duration_min"), 60),
                            "address": it.get("address", "-"),
                            "maps_url": it.get("maps_url") or None,
                            "tiktok_url": it.get("tiktok_url") or None,
                        }
                        for it in day_items
                    ],
                }
            )

        per_person = _recalc_per_person(itinerary)
        return {
            "route": route_clean,
            "days": days,
            "budget": budget_per_person,
            "party_size": party_size,
            "language": language_pref,
            "package_name": f"Ruta Cultural: {route_clean}",
            "estimate_per_person": per_person,
            "estimate_total": round(per_person * party_size, 2),
            "narrative": f"Modo fallback (sin IA): {str(e)[:120]}",
            "plan_b": ["Si llueve: cambia a actividades bajo techo.", "Si está lleno: busca alternativa similar cercana."],
            "sustainability": ["Compra local y respeta la cultura."],
            "itinerary": itinerary,
        }
