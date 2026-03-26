from prompts import INVOICE_PARSE_PROMPT
import base64
import json
import pandas as pd
from openai import OpenAI
from telegram import Update
import requests
from utils import retry
from matcher import find_top_products
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from config import (
    OPENAI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    MS_BASE_URL,
    MS_AUTH,
)

# --- OpenAI ---
client = OpenAI(api_key=OPENAI_API_KEY)
print("clinet accepted")

@retry(max_attempts=3, delay=2, backoff=2)
def parse_invoice_image(image_path):
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = INVOICE_PARSE_PROMPT
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{image_base64}"}]}])

    return response.output_text

TOKEN = TELEGRAM_BOT_TOKEN

@retry(max_attempts=3, delay=1, backoff=2)
def load_products():
    df = pd.read_csv(
        "products.csv",
        sep=";",
        usecols=["group_name", "product_id", "product_name"]
    )

    print("COLUMNS:", df.columns.tolist())
    print(df.head())

    return df

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        print("PHOTO RECEIVED")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    await update.message.reply_text("Обрабатываю...")

    result = parse_invoice_image(file_path)
    print("RAW RESULT:")
    print(result)

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

    try:
        cleaned = clean_json_text(result)
        print("CLEANED RESULT:")
        print(cleaned)

        data = json.loads(cleaned)

        supplier = data.get("supplier")
        items = data.get("items", [])
        print("SUPPLIER:", supplier)
        print("ITEMS:", items)

        df = load_products()

        matched = []

        matched = []

        for item in items:
            print("ITEM:", item)

            raw_name = item["raw_name"]

            top = find_top_products(raw_name, df, top_n=1)
            print("TOP:", top)

            if not top:
                matched.append({
                    "raw": raw_name,
                    "matched": "НЕ НАЙДЕНО",
                    "id": None,
                    "qty": item.get("qty"),
                    "price": item.get("price")
                })
                continue

            best = top[0]

            matched.append({
                "raw": raw_name,
                "matched": best["name"],
                "id": best["id"],
                "qty": item.get("qty"),
                "price": item.get("price")
            })

        text = f"Поставщик: {supplier}\n\n"

        for item in items:
            text += f"{item['raw_name']} — {item['qty']} шт × {item['price']}\n"

        await update.message.reply_text(text)


    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        await update.message.reply_text(f"Ошибка обработки: {e}")


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

#app.run_polling()

def test_moylad_connection():
    url = f"{MS_BASE_URL}/entity/product?limit=1"
    response = requests.get(url, auth=MS_AUTH)
    print("MS STATUS:", response.status_code)
    print(response.text[:500])

def normalize_text(text: str) -> str:
    return (
        text.lower()
        .replace('"', '')
        .replace('«', '')
        .replace('»', '')
        .replace("  ", " ")
        .strip()
    )

def find_counterparty(name: str):
    url = f"{MS_BASE_URL}/entity/counterparty"
    params = {"limit": 100}

    response = requests.get(url, auth=MS_AUTH, params=params)
    data = response.json()
    rows = data.get("rows", [])

    target = normalize_text(name)

    scored = []

    for r in rows:
        ms_name = normalize_text(r["name"])
        score = fuzz.ratio(target, ms_name)

        scored.append((score, r))

    # сортируем по похожести
    scored.sort(reverse=True, key=lambda x: x[0])

    print("TOP MATCHES:")
    for score, r in scored[:5]:
        print(score, "-", r["name"])

    return [r for score, r in scored[:3] if score > 60]

@retry(max_attempts=3, delay=2, backoff=2)
def search_counterparty_best(query: str):
    url = f"{MS_BASE_URL}/entity/counterparty"
    params = {"search": query, "limit": 20}

    response = requests.get(url, auth=MS_AUTH, params=params)
    print("STATUS:", response.status_code)

    data = response.json()
    rows = data.get("rows", [])

    if not rows:
        print("FOUND: 0")
        return None

    target = normalize_text(query)

    scored = []
    for r in rows:
        score = fuzz.ratio(target, normalize_text(r["name"]))
        scored.append((score, r))

    scored.sort(reverse=True, key=lambda x: x[0])

    print("TOP MATCHES:")
    for score, r in scored[:5]:
        print(score, "-", r["name"])

    best = scored[0][1]
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


    print(f"\nRAW: {raw_name}")
    print("TOP MATCHES:")
    for r in results[:top_n]:
        print(round(r["score"], 2), "-", r["name"], "|", r["group"])

    return results[:top_n]
