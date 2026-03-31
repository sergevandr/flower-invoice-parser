from rapidfuzz import fuzz
from app.matching.supplier_mapping import SUPPLIER_MAP
from app.common.utils import retry
import json
import requests
from app.config import MS_BASE_URL, MS_AUTH

def normalize_text(text: str) -> str:
    return (
        str(text)
        .lower()
        .replace('"', "")
        .replace("«", "")
        .replace("»", "")
        .replace("  ", " ")
        .strip()
    )

def simplify_counterparty_name(name: str) -> str:
    name = normalize_text(name)

    garbage_phrases = [
        "общество с ограниченной ответственностью",
        "индивидуальный предприниматель",
        "акционерное общество",
        "закрытое акционерное общество",
        "открытое акционерное общество",
    ]

    for phrase in garbage_phrases:
        name = name.replace(phrase, " ")

    garbage_words = ["ип", "ооо", "зао", "оао", "ао", "llc"]

    for word in garbage_words:
        name = name.replace(word, " ")

    return " ".join(name.split())


def extract_last_name(name: str):
    words = simplify_counterparty_name(name).split()
    if not words:
        return None
    return words[0]

def map_supplier_name(raw_supplier: str):
    normalized = normalize_text(raw_supplier)

    # 1. точное совпадение
    for key, value in SUPPLIER_MAP.items():
        if normalize_text(key) == normalized:
            return value

    # 2. похожее совпадение
    best_score = 0
    best_value = raw_supplier

    for key, value in SUPPLIER_MAP.items():
        score = fuzz.ratio(normalize_text(key), normalized)
        if score > best_score:
            best_score = score
            best_value = value

    print("SUPPLIER MAP BEST SCORE:", best_score)

    if best_score >= 85:
        return best_value

    return raw_supplier

@retry(max_attempts=3, delay=2, backoff=2)
def search_counterparty_best(query: str):
    url = f"{MS_BASE_URL}/entity/counterparty"

    target_full = normalize_text(query)
    target_simple = simplify_counterparty_name(query)
    last_name = extract_last_name(query)

    print("QUERY:", query)
    print("TARGET_FULL:", target_full)
    print("TARGET_SIMPLE:", target_simple)
    print("LAST_NAME:", last_name)

    rows = []

    # Поиск по полной строке
    if query:
        response = requests.get(url, auth=MS_AUTH, params={"search": query, "limit": 50})
        response.raise_for_status()
        rows.extend(response.json().get("rows", []))

    # Поиск по упрощённой строке
    if target_simple:
        response = requests.get(url, auth=MS_AUTH, params={"search": target_simple, "limit": 50})
        response.raise_for_status()
        rows.extend(response.json().get("rows", []))

    # Поиск по фамилии
    if last_name:
        response = requests.get(url, auth=MS_AUTH, params={"search": last_name, "limit": 50})
        response.raise_for_status()
        rows.extend(response.json().get("rows", []))

    # Убираем дубли
    unique_rows = {}
    for r in rows:
        unique_rows[r["id"]] = r
    rows = list(unique_rows.values())

    print("ROWS AFTER SEARCH:", len(rows))

    if not rows:
        return None

    scored = []

    for r in rows:
        candidate_name = r["name"]
        candidate_full = normalize_text(candidate_name)
        candidate_simple = simplify_counterparty_name(candidate_name)

        score_full = fuzz.ratio(target_full, candidate_full)
        score_partial = fuzz.partial_ratio(target_simple, candidate_simple) if target_simple else 0
        score_token = fuzz.token_sort_ratio(target_simple, candidate_simple) if target_simple else 0

        score = max(score_full, score_partial, score_token)
        scored.append((score, r))

    scored.sort(reverse=True, key=lambda x: x[0])

    print("TOP MATCHES:")
    for score, r in scored[:10]:
        print(score, "-", r["name"])

    best_score, best = scored[0]

    if best_score < 60:
        print("BEST SCORE TOO LOW:", best_score)
        return None

    print("BEST:", best["name"])
    return best

def get_organization_meta_by_name(name: str):
    url = f"{MS_BASE_URL}/entity/organization"
    response = requests.get(url, auth=MS_AUTH)
    response.raise_for_status()

    rows = response.json().get("rows", [])
    for row in rows:
        if normalize_text(row["name"]) == normalize_text(name):
            return row["meta"]

    return None

def get_store_meta_by_name(name: str):
    url = f"{MS_BASE_URL}/entity/store"
    response = requests.get(url, auth=MS_AUTH)
    response.raise_for_status()

    rows = response.json().get("rows", [])
    for row in rows:
        if normalize_text(row["name"]) == normalize_text(name):
            return row["meta"]

    return None


def create_supply_draft(counterparty_meta, matched_items):
    url = f"{MS_BASE_URL}/entity/supply"

    organization_meta = get_organization_meta_by_name("ИП Губайдуллина Аида Рушановна")
    store_meta = get_store_meta_by_name("Склад материалов")

    if not organization_meta:
        raise ValueError("Не найдена организация в МойСклад")

    if not store_meta:
        raise ValueError("Не найден склад в МойСклад")

    positions = []

    for item in matched_items:
        if not item["id"]:
            continue

        positions.append(
            {
                "quantity": item["qty"],
                "price": int(float(item["price"]) * 100),
                "assortment": {
                    "meta": {
                        "href": f"{MS_BASE_URL}/entity/product/{item['id']}",
                        "type": "product",
                        "mediaType": "application/json",
                    }
                },
            }
        )

    payload = {
        "applicable": False,
        "organization": {
            "meta": organization_meta,
        },
        "store": {
            "meta": store_meta,
        },
        "agent": {
            "meta": counterparty_meta,
        },
        "positions": positions,
    }

    print("SUPPLY PAYLOAD:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    response = requests.post(url, auth=MS_AUTH, json=payload)

    print("SUPPLY STATUS:", response.status_code)
    print("SUPPLY RESPONSE:", response.text)

    response.raise_for_status()
    return response.json()