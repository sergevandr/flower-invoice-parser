import json
import html
import requests
from openai import OpenAI

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

from matcher import find_top_products
from config import (OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, MS_BASE_URL, MS_AUTH)

from invoice_parser import (parse_invoice_image, parse_supplier_only, clean_json_text)
from moysklad import (map_supplier_name, search_counterparty_best, create_supply_draft, normalize_text,)
from catalog import load_products

client = OpenAI(api_key=OPENAI_API_KEY)
print("client accepted")

TOKEN = TELEGRAM_BOT_TOKEN

FALLBACK_SUPPLIER_NAME = "Прочие поставщики"

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
        items = data.get("items", [])

        # --- отдельный запрос на поставщика ---
        supplier_result = parse_supplier_only(file_path)
        print("RAW SUPPLIER RESULT:")
        print(supplier_result)

        supplier_cleaned = clean_json_text(supplier_result)
        print("CLEANED SUPPLIER RESULT:")
        print(supplier_cleaned)

        supplier_data = json.loads(supplier_cleaned)
        supplier = supplier_data.get("supplier")

        mapped_supplier = map_supplier_name(supplier)
        print("RAW SUPPLIER:", supplier)
        print("MAPPED SUPPLIER:", mapped_supplier)

        counterparty = search_counterparty_best(mapped_supplier)

        supplier_warning = False

        if not counterparty:
            supplier_warning = True
            counterparty = search_counterparty_best(FALLBACK_SUPPLIER_NAME)

            if not counterparty:
                await update.message.reply_text(
                    f"Не найден ни контрагент поставщика, ни fallback-контрагент: {supplier}"
                )
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

        if supplier_warning:
            text += "⚠️ <b>Поставщик не распознан уверенно</b>\n"
            text += f"⚠️ <b>В приёмку подставлен контрагент:</b> {html.escape(FALLBACK_SUPPLIER_NAME)}\n\n"

        text += f"<b>Поставщик из накладной:</b> {html.escape(str(supplier))}\n"
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

def test_moysklad_connection():
    url = f"{MS_BASE_URL}/entity/product?limit=1"
    response = requests.get(url, auth=MS_AUTH)
    print("MS STATUS:", response.status_code)
    print(response.text[:500])

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.run_polling()