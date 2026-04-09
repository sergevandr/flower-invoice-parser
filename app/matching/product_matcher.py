from rapidfuzz import fuzz

FLOWER_ALIASES = {
    "тюльпан": ["тюльпан", "tulipa", "tulip"],
    "роза": ["роза", "rose"],
    "гвоздика": ["гвоздика", "dianthus", "carnation"],
    "пион": ["пион", "paeonia", "peony"],
    "георгина": ["георгина", "георгин", "dahlia"],
    "хризантема": ["хризантема", "chrysanthemum"],
    "гортензия": ["гортензия", "hydrangea"],
    "эустома": ["эустома", "lisianthus", "eustoma"],
    "ранункулюс": ["ранункулюс", "ranunculus"],
    "анемона": ["анемона", "anemone"],
    "нарцисс": ["нарцисс", "narcissus"],
    "сирень": ["сирень", "syringa"],
    "дельфиниум": ["дельфиниум", "delphinium"],
    "фрезия": ["фрезия", "freesia"],
    "маттиола": ["маттиола", "matthiola"],
    "скабиоза": ["скабиоза", "scabiosa"],
    "астильба": ["астильба", "astilbe"],
    "мускари": ["мускари", "muscari"],
    "гиппеаструм": ["гиппеаструм", "hippeastrum", "амарилис"],
    "душистый горошек": ["душистый горошек", "lathyrus"],
    "антуриум": ["антуриум", "anthurium"],
    "вибурнум": ["вибурнум", "viburnum", "калина"],
    "трахелиум": ["трахелиум", "trachelium"],
    "цирсиум": ["цирсиум", "cirsium", "бодяк"],
}


def detect_flower_type(text: str):
    text = str(text).lower()
    for flower_type, variants in FLOWER_ALIASES.items():
        for variant in variants:
            if variant in text:
                return flower_type
    return None


def detect_item_class(text: str):
    text = str(text).lower()

    if any(x in text for x in ["корзин", "basket"]):
        return "basket"

    if any(x in text for x in ["букет", "bouquet"]):
        return "bouquet"

    if any(x in text for x in ["ваза", "vase"]):
        return "vase"

    if any(x in text for x in [
        "лента", "пленка", "бумага", "коробка", "каркас", "оазис",
        "foam", "ribbon", "wrap"
    ]):
        return "material"

    if detect_flower_type(text):
        return "flower"

    return "unknown"


def remove_flower_type(text: str):
    text = str(text).lower()

    for _, variants in FLOWER_ALIASES.items():
        for variant in variants:
            text = text.replace(variant, " ")

    return " ".join(text.split())


def get_sort_part(text: str):
    text = remove_flower_type(text)

    garbage = [
        "см", "cm", "/", "#", "шт", "одноголовая", "кустовая",
        "эквадор", "кения", "пионовидная", "садовая"
    ]

    for x in garbage:
        text = text.replace(x, " ")

    return " ".join(text.split())


def normalize_sort_text(text: str):
    text = str(text).lower()

    replacements = {
        "кантри": "country",
        "блюз": "blue",
        "блю": "blue",
        "ред": "red",
        "вайт": "white",
        "пинк": "pink",
        "йеллоу": "yellow",
        "грин": "green",
        "оранж": "orange",
        "перпл": "purple",
        "лавандер": "lavender",
        "крем": "cream",
        "айвори": "ivory",
        "peach": "peach",
        "пич": "peach",
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    return " ".join(text.split())


def find_top_products(raw_name: str, df, top_n=3):
    raw = str(raw_name).lower().strip()
    raw_type = detect_flower_type(raw)
    item_class = detect_item_class(raw)

    results = []

    for _, row in df.iterrows():
        product_name = str(row["product_name"])
        group_name = str(row["group_name"])

        product_name_l = product_name.lower()
        group_name_l = group_name.lower()

        base_score = fuzz.token_sort_ratio(raw, product_name_l)

        raw_sort = normalize_sort_text(get_sort_part(raw))
        product_sort = normalize_sort_text(get_sort_part(product_name_l))

        sort_score = 0
        partial_sort_score = 0

        if raw_sort and product_sort:
            sort_score = fuzz.token_sort_ratio(raw_sort, product_sort)
            partial_sort_score = fuzz.partial_ratio(raw_sort, product_sort)

        score = base_score + sort_score * 0.4 + partial_sort_score * 0.5

        if raw_type is None and raw_sort and product_sort:
            if raw_sort == product_sort:
                score += 140
            elif raw_sort in product_sort:
                score += 100

        if raw in product_name_l:
            score += 120

        if raw_sort and raw_sort in product_sort:
            score += 80

        if "цветы срезанные" in group_name_l:
            score += 15

        product_type = detect_flower_type(product_name_l + " " + group_name_l)

        if raw_type and product_type:
            if raw_type == product_type:
                score += 90
            else:
                score -= 140

        if raw_type and raw_type in group_name_l:
            score += 30

        if raw_type and raw_type in product_name_l:
            score += 25

        if item_class == "flower":
            if any(x in group_name_l for x in [
                "вазы", "флористические материалы", "упаковка", "ленты", "корзины"
            ]):
                score -= 80

        elif item_class == "basket":
            if "корзин" in group_name_l:
                score += 35
            else:
                score -= 20

        elif item_class == "bouquet":
            if "букет" in group_name_l:
                score += 35
            else:
                score -= 20

        elif item_class == "vase":
            if "ваз" in group_name_l:
                score += 35
            else:
                score -= 20

        elif item_class == "material":
            if any(x in group_name_l for x in [
                "материалы", "упаковка", "ленты", "каркасы"
            ]):
                score += 30
            else:
                score -= 15

        results.append({
            "score": score,
            "name": product_name,
            "id": row["product_id"],
            "group": group_name
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\nRAW: {raw_name}")
    print("TOP MATCHES:")
    for r in results[:top_n]:
        print(round(r["score"], 2), "-", r["name"], "|", r["group"])

    return results[:top_n]