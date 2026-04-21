import base64
import json

from openai import OpenAI
from app.common.utils import retry
from app.config import OPENAI_API_KEY
from app.prompts import SUPPLIER_PARSE_PROMPT, INVOICE_PARSE_PROMPT, MANDRYKIN_PROMPT
from app.integrations.moysklad_client import map_supplier_name

client = OpenAI(api_key=OPENAI_API_KEY)


@retry(max_attempts=3, delay=2, backoff=2)
def parse_invoice_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    # 👇 сначала определяем поставщика
    supplier_raw = parse_supplier_only(image_path)
    supplier_cleaned = clean_json_text(supplier_raw)

    try:
        supplier_data = json.loads(supplier_cleaned)
        raw_supplier = supplier_data.get("supplier")
    except Exception:
        raw_supplier = None

    mapped_supplier = map_supplier_name(raw_supplier) if raw_supplier else None

    print("RAW SUPPLIER (PARSER):", raw_supplier)
    print("MAPPED SUPPLIER (PARSER):", mapped_supplier)

    # 👇 выбираем промпт
    if mapped_supplier == "ИП Мандрыкин / Премьер":
        prompt = MANDRYKIN_PROMPT
        print("USING MANDRYKIN PROMPT")
    else:
        prompt = INVOICE_PARSE_PROMPT

    # 👇 основной вызов GPT
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{image_base64}",
                    },
                ],
            }
        ],
    )

    return response.output_text


def parse_supplier_only(image_path: str) -> str:
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": SUPPLIER_PARSE_PROMPT},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{image_base64}",
                    },
                ],
            }
        ],
    )

    return response.output_text


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