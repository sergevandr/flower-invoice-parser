from prompts import INVOICE_PARSE_PROMPT
import base64
import json
import html

import pandas as pd
import requests

from openai import OpenAI
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from rapidfuzz import fuzz

from suppliers import SUPPLIER_MAP
from utils import retry
from matcher import find_top_products
from config import (
    OPENAI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    MS_BASE_URL,
    MS_AUTH,
)

# --- OpenAI ---
client = OpenAI(api_key=OPENAI_API_KEY)
print("client accepted")

TOKEN = TELEGRAM_BOT_TOKEN


def clean_json_text(text: str) -> str:
    text = text.strip()

    if text.startswith("```json"):
        text = text.removeprefix("```json").strip()
    if text.startswith("```"):
        text = text.removeprefix("```").strip()
    if text.endswith("```"):
        text = text.removesuffix("```").strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1:
        text = text[start:end + 1]

    return text


@retry(max_attempts=3, delay=2, backoff=2)
def parse_invoice_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": INVOICE_PARSE_PROMPT},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{image_base64}",
                    },
                ],
            }
        ],
    )

    return response.output_text


@retry(max_attempts=3, delay=1, backoff=2)
def load_products():
    df = pd.read_csv(
        "products.csv",
        sep=";",
        usecols=["group_name", "product_id", "product_name"],
    )
    print("COLUMNS:", df.columns.tolist())
    print(df.head())
    return df


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

    garbage = ["ип", "ооо", "зао", "ao", "llc"]

    for g in garbage:
        name = name.replace(g, " ")

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


def test_moysklad_connection():
    url = f"{MS_BASE_URL}/entity/product?limit=1"
    response = requests.get(url, auth=MS_AUTH)
    print("MS STATUS:", response.status_code)
    print(response.text[:500])


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


def search_product(query: str):
    url = f"{MS_BASE_URL}/entity/product"
    params = {"search": query, "limit": 10}

    response = requests.get(url, auth=MS_AUTH, params=params)
    print("STATUS:", response.status_code)

    data = response.json()
    rows = data.get("rows", [])

    print("FOUND:", len(rows))
    for r in rows:
        print("-", r["name"])

    return rows


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


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("PHOTO RECEIVED")
    supplier = None

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    file_path = "invoice.jpg"
    await file.download_to_drive(file_path)

    await update.message.reply_text("Обрабатываю...")

    result = parse_invoice_image(file_path)
    print("RAW RESULT:")
    print(result)

    try:
        cleaned = clean_json_text(result)
        print("CLEANED RESULT:")
        print(cleaned)

        data = json.loads(cleaned)

        supplier = data.get("supplier")
        items = data.get("items", [])

        mapped_supplier = map_supplier_name(supplier)
        print("RAW SUPPLIER:", supplier)
        print("MAPPED SUPPLIER:", mapped_supplier)

        counterparty = search_counterparty_best(mapped_supplier)
        if not counterparty:
            await update.message.reply_text(f"Не найден контрагент: {supplier}")
            return

        print("SUPPLIER:", supplier)
        print("ITEMS:", items)

        df = load_products()
        matched = []

        for item in items:
            print("ITEM:", item)

            raw_name = item["raw_name"]
            top = find_top_products(raw_name, df, top_n=1)
            print("TOP:", top)

            if not top:
                matched.append(
                    {
                        "raw": raw_name,
                        "matched": "НЕ НАЙДЕНО",
                        "id": None,
                        "qty": item.get("qty"),
                        "price": item.get("price"),
                    }
                )
                continue

            best = top[0]

            matched.append(
                {
                    "raw": raw_name,
                    "matched": best["name"],
                    "id": best["id"],
                    "qty": item.get("qty"),
                    "price": item.get("price"),
                }
            )

        supply = create_supply_draft(counterparty["meta"], matched)
        print("SUPPLY CREATED:", supply.get("name"), supply.get("id"))

        supply_link = supply.get("meta", {}).get("uuidHref")
        print("SUPPLY LINK:", supply_link)

        positions_count = len([x for x in matched if x["id"]])

        text = ""
        text += f"<b>Поставщик:</b> {html.escape(str(supplier))}\n"
        text += f"<b>Контрагент в МойСклад:</b> {html.escape(str(counterparty['name']))}\n"
        text += "<b>Статус:</b> Черновик приёмки создан\n"
        text += f"<b>Позиций:</b> {positions_count}\n"

        if supply_link:
            text += f"<b>Ссылка:</b> <a href=\"{html.escape(supply_link)}\">Открыть приёмку в МойСклад</a>\n"

        text += "\n<b>Позиции:</b>\n"

        for m in matched:
            raw_text = html.escape(str(m["raw"]))
            matched_text = html.escape(str(m["matched"]))
            qty_text = html.escape(str(m["qty"]))
            price_text = html.escape(str(m["price"]))

            text += f"• {raw_text} — {qty_text} шт × {price_text}\n"
            text += f"  → <i>{matched_text}</i>\n"

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    except Exception as e:
        import traceback

        print("ERROR:", e)
        print("RAW SUPPLIER:", supplier)
        if supplier:
            print("NORMALIZED:", normalize_text(supplier))
        traceback.print_exc()

        await update.message.reply_text(f"Ошибка обработки: {e}")


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.run_polling()