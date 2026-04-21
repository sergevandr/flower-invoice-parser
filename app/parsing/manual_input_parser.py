import re


def parse_manual_input(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if len(lines) < 2:
        raise ValueError(
            "Недостаточно данных.\n\n"
            "Формат:\n"
            "поставщик\n"
            "-сумма название количество\n\n"
            "Пример:\n"
            "рига\n"
            "-3000 роза аваланш 20"
        )

    supplier = lines[0]

    if supplier.startswith("-"):
        raise ValueError(
            "Не указан поставщик.\n\n"
            "Первая строка должна быть названием поставщика.\n\n"
            "Пример:\n"
            "рига\n"
            "-3000 роза аваланш 20"
        )

    items = []

    pattern = re.compile(
        r"^-\s*(?P<total>\d+(?:[.,]\d+)?)\s+(?P<raw_name>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)$"
    )

    for line in lines[1:]:
        match = pattern.match(line)
        if not match:
            raise ValueError(
                f"Не удалось разобрать строку:\n{line}\n\n"
                f"Ожидаемый формат:\n"
                f"-сумма название количество\n\n"
                f"Пример:\n"
                f"-3000 роза аваланш 20"
            )

        total = float(match.group("total").replace(",", "."))
        raw_name = match.group("raw_name").strip()
        qty = float(match.group("qty").replace(",", "."))

        if qty <= 0:
            raise ValueError(f"Количество должно быть больше нуля: {line}")

        price = round(total / qty, 2)

        if qty.is_integer():
            qty = int(qty)

        items.append(
            {
                "raw_name": raw_name,
                "qty": qty,
                "price": price,
            }
        )

    return {
        "supplier": supplier,
        "items": items,
        "invoice_number": None,
        "invoice_date": None,
    }