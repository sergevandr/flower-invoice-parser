import json
import html
import requests
from openai import OpenAI

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

from app.matching.product_matcher import find_top_products
from app.config import (OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, MS_BASE_URL, MS_AUTH)

from app.parsing.invoice_parser import (parse_invoice_image, parse_supplier_only, clean_json_text)
from app.integrations.moysklad_client import (map_supplier_name, search_counterparty_best, create_supply_draft, normalize_text, )
from app.matching.product_catalog import load_products
from app.matching.supplier_mapping import AUTO_PAYMENT_SUPPLIERS
from app.integrations.moysklad_client import create_payment_out_for_supply
from app.config import DEFAULT_ORGANIZATION_ACCOUNT_META
from app.integrations.moysklad_client import normalize_text

from app.config import DEFAULT_ORGANIZATION_ACCOUNT_META

client = OpenAI(api_key=OPENAI_API_KEY)
print("client accepted")

TOKEN = TELEGRAM_BOT_TOKEN

FALLBACK_SUPPLIER_NAME = "Прочие поставщики"

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("PHOTO RECEIVED")
    supplier = None

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    file_path = "../invoice.jpg"
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

        invoice_number = data.get("invoice_number")
        invoice_date = data.get("invoice_date")

        supply = create_supply_draft(
            counterparty["meta"],
            matched,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
        )
        print("SUPPLY CREATED:", supply.get("name"), supply.get("id"))

        supply_link = supply.get("meta", {}).get("uuidHref")
        print("SUPPLY LINK:", supply_link)

        payment = None
        payment_link = None

        print("COUNTERPARTY NAME:", counterparty["name"])

        normalized_name = normalize_text(counterparty["name"])

        print("NORMALIZED COUNTERPARTY NAME:", normalized_name)
        print("AUTO PAYMENT SUPPLIERS:", AUTO_PAYMENT_SUPPLIERS)

        if normalized_name in AUTO_PAYMENT_SUPPLIERS:
            print("AUTO PAYMENT TRIGGERED")
            supply_sum = supply.get("sum")
            print("SUPPLY SUM:", supply_sum)

            if supply_sum:
                payment = create_payment_out_for_supply(
                    counterparty_meta=counterparty["meta"],
                    organization_meta=supply["organization"]["meta"],
                    organization_account_meta=DEFAULT_ORGANIZATION_ACCOUNT_META,
                    supply_meta=supply["meta"],
                    payment_sum=supply_sum,
                    invoice_date=invoice_date,
                    payment_purpose=f"Оплата по приёмке {supply.get('name')}",
                )

                payment_link = payment.get("meta", {}).get("uuidHref")
                print("PAYMENT LINK:", payment_link)

        positions_count = len([x for x in matched if x["id"]])

        extra_info = ""

        if invoice_number:
            extra_info += f"\nНомер накладной: {invoice_number}"

        if invoice_date:
            extra_info += f"\nДата накладной: {invoice_date}"

        text = ""

        if supplier_warning:
            text += "⚠️ <b>Поставщик не распознан уверенно</b>\n"
            text += f"⚠️ <b>В приёмку подставлен контрагент:</b> {html.escape(FALLBACK_SUPPLIER_NAME)}\n\n"

        if payment:
            text += "<b>❗️Платёж:</b> создан\n"

        if payment_link:
            text += f"<a href=\"{html.escape(payment_link)}\">Открыть платёж</a>\n"

        text += f"<b>Поставщик из накладной:</b> {html.escape(str(supplier))}\n"
        text += f"<b>Контрагент в МойСклад:</b> {html.escape(str(counterparty['name']))}\n"
        text += "<b>Статус:</b> Черновик приёмки создан\n"

        if supply_link:
            text += f"<b>Ссылка:</b> <a href=\"{html.escape(supply_link)}\">Открыть приёмку в МойСклад</a>\n"

        text += f"<b>Позиций:</b> {positions_count}\n"
        text += "\n<b>Позиции:</b>\n"

        for m in matched:
            raw_text = html.escape(str(m["raw"]))
            matched_text = html.escape(str(m["matched"]))
            qty_text = html.escape(str(m["qty"]))
            price_text = html.escape(str(m["price"]))

            text += f"• {raw_text} — {qty_text} шт × {price_text}\n"
            text += f"  → <i>{matched_text}</i>\n"

        if invoice_number:
            text += f"<b>Номер накладной:</b> {html.escape(str(invoice_number))}\n"

        if invoice_date:
            text += f"<b>Дата накладной:</b> {html.escape(str(invoice_date))}\n"

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
if __name__ == "__main__":
    app.run_polling()