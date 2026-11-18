"""Расчёт упаковок, сравнение корзин и проверка условий."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from itertools import product
import re


def dec(v):
    if isinstance(v, bool):
        raise ValueError("Вместо числа передано boolean")
    try:
        d = Decimal(
            str(v)
            .replace(" ", "")
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(",", ".")
        )
    except InvalidOperation:
        raise ValueError("Неверное число") from None
    if not d.is_finite() or d < 0 or d > Decimal("1e12"):
        raise ValueError("Число вне допустимого диапазона")
    return d


def ds(v):
    return format(v.normalize(), "f") if v else "0"


def rub(v):
    return v.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


UNITS = {
    "штук": "шт",
    "штуки": "шт",
    "штука": "шт",
    "шт": "шт",
    "мешков": "мешок",
    "мешка": "мешок",
    "мешки": "мешок",
    "мешок": "мешок",
    "упаковок": "уп",
    "упаковки": "уп",
    "упаковка": "уп",
    "уп": "уп",
    "литров": "л",
    "литра": "л",
    "л": "л",
    "кг": "кг",
    "м": "м",
    "м2": "м2",
    "м²": "м2",
    "м3": "м3",
    "м³": "м3",
}


def parse_lines(text):
    result = []
    unit = "(?:" + "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True)) + ")"
    for line in text.splitlines():
        line = re.sub(r"^\s*\d+[.)]\s*", "", line.strip())
        m = re.match(
            r"^(.*?)\s*(?:—|–|-|:|=)\s*(\d+(?:[.,]\d+)?)\s*(" + unit + r")\.?\s*$",
            line,
            re.I,
        )
        if m:
            name, qty, u = m.groups()
        else:
            m = re.match(r"^(\d+(?:[.,]\d+)?)\s*(" + unit + r")\s+(.+)$", line, re.I)
            if not m:
                continue
            qty, u, name = m.groups()
        if name.strip() and dec(qty) > 0:
            result.append(
                {
                    "name": name.strip(),
                    "quantity": ds(dec(qty)),
                    "unit": UNITS[u.lower()],
                    "requirements": name.strip(),
                    "query": name.strip(),
                }
            )
    return result


def price_evidenced(price, evidence, text):
    if not evidence or norm(evidence) not in norm(text):
        return False
    try:
        expected = dec(price)
    except ValueError:
        return False
    for token in re.findall(r"\d[\d\s\u00a0\u202f]*(?:[.,]\d{1,2})?", evidence):
        try:
            if dec(token) == expected:
                return True
        except ValueError:
            pass
    return False


def price_quote(q, quantity):
    q = dict(q)
    pack = dec(q["pack_quantity"])
    price = dec(q["pack_price"])
    if pack <= 0:
        raise ValueError("Упаковка должна быть больше нуля")
    packs = int((quantity / pack).to_integral_value(rounding=ROUND_CEILING))
    q.update(
        packs=packs,
        purchase_quantity=ds(pack * packs),
        unit_price=ds(price / pack),
        goods_total=ds(rub(price * packs)),
    )
    return q


def build_estimate(items, payload, model, questions=None):
    questions = list(questions or [])
    wanted = []
    all_quoted = bool(items)
    deadline = date.fromisoformat(payload["deadline"])
    for item in items:
        candidates = []
        for original in item.get("offers", []):
            try:
                q = price_quote(original, dec(item["quantity"]))
                q["fits"] = (
                    bool(q.get("fits"))
                    and q.get("availability") != "out_of_stock"
                    and q.get("unit") == item["unit"]
                )
                if q.get("delivery_date"):
                    due = date.fromisoformat(q["delivery_date"])
                    if due > deadline or due < date.today():
                        q["fits"] = False
                        q["reason"] = "Поставка не укладывается в требуемый срок"
                if q.get("stock_quantity") is not None and dec(
                    q["stock_quantity"]
                ) < dec(q["purchase_quantity"]):
                    q["fits"] = False
                    q["reason"] = "Подтверждённого количества недостаточно"
                if q["fits"]:
                    candidates.append(q)
                original.update(q)
            except (ValueError, KeyError):
                original["fits"] = False
                original["reason"] = "Не подтверждена цена или единица упаковки"
        candidates.sort(
            key=lambda q: (q.get("delivery_date") is None, dec(q["goods_total"]))
        )
        item["selected"] = None
        if candidates:
            wanted.append((item, candidates[:4]))
        else:
            all_quoted = False
            questions.append(
                {
                    "title": item["name"],
                    "detail": "Подходящее предложение с проверяемой ценой не найдено. Уточните характеристики или добавьте ссылку на товар к исходному запросу.",
                }
            )
    # Compare complete baskets when delivery terms are known. Otherwise compare goods only,
    # preserve unknown delivery and describe the result as preliminary.
    combinations = 1
    for _, quotes in wanted:
        combinations *= len(quotes)

    def basket_cost(basket):
        goods = sum((dec(q["goods_total"]) for q in basket), Decimal(0))
        fees = {}
        complete = all_quoted
        for q in basket:
            if (
                q.get("source_status") == "search_index"
                or q.get("stock_quantity") is None
            ):
                complete = False
            if (
                q.get("delivery_cost") is None
                or q.get("delivery_date") is None
                or q.get("delivery_scope") != "per_order"
                or q.get("availability") != "in_stock"
            ):
                complete = False
                continue
            sid = q["supplier"]
            fee = dec(q["delivery_cost"])
            if sid in fees and fees[sid] != fee:
                complete = False
            fees[sid] = fee
        shipping = sum(fees.values(), Decimal(0))
        return complete, goods, shipping

    baskets = (
        list(product(*(qs for _, qs in wanted)))
        if combinations <= 50000
        else [tuple(qs[0] for _, qs in wanted)]
    )
    if combinations > 50000:
        questions.append(
            {
                "title": "Область сравнения",
                "detail": "Слишком много сочетаний предложений. Показан предварительный вариант; глобальный минимум корзины не доказан.",
            }
        )
    ranked = sorted(
        ((basket_cost(b), b) for b in baskets),
        key=lambda pair: (
            not pair[0][0],
            pair[0][1] + pair[0][2] if pair[0][0] else pair[0][1],
        ),
    )
    chosen = ranked[0] if ranked else ((False, Decimal(0), Decimal(0)), [])
    (complete, goods, shipping), basket = chosen
    for (item, _), quote in zip(wanted, basket):
        item["selected"] = quote
    for item in items:
        q = item["selected"]
        if not q:
            continue
        if q.get("source_status") == "search_index":
            questions.append(
                {
                    "title": item["name"],
                    "detail": "Цена найдена в поисковом индексе, но товарная страница недоступна для проверки. Это ценовой ориентир: цену, упаковку и наличие нужно подтвердить у поставщика.",
                    "url": q["url"],
                }
            )
        missing = []
        if not q.get("delivery_date"):
            missing.append("срок доставки до указанного адреса")
        if q.get("delivery_cost") is None or q.get("delivery_scope") != "per_order":
            missing.append("полную стоимость доставки всей корзины")
        if q.get("availability") != "in_stock":
            missing.append("наличие")
        if q.get("stock_quantity") is None:
            missing.append(
                "наличие всего количества " + str(item["quantity"]) + " " + item["unit"]
            )
        if missing:
            questions.append(
                {
                    "title": item["name"],
                    "detail": "У поставщика "
                    + q["supplier"]
                    + " нужно подтвердить: "
                    + ", ".join(missing)
                    + ".",
                    "url": q["url"],
                }
            )
    comparison_total = goods + shipping if complete else goods
    if payload.get("budget") is not None and comparison_total > dec(payload["budget"]):
        questions.append(
            {
                "title": "Превышение бюджета",
                "detail": "Расчётная стоимость выше бюджета на "
                + ds(comparison_total - dec(payload["budget"]))
                + " ₽.",
            }
        )
    complete = complete and not questions and all_quoted
    return dict(
        items=items,
        goods_total=ds(goods) if wanted else None,
        delivery_total=ds(shipping) if complete else None,
        total=ds(goods + shipping) if complete else None,
        complete=complete,
        questions=questions,
        quotes_checked=sum(len(i.get("offers", [])) for i in items),
        quotes_verified=sum(
            q.get("source_status") != "search_index"
            for i in items
            for q in i.get("offers", [])
        ),
        checked_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        summary="Проект заявки составлен по найденным предложениям. "
        + (
            "Полная стоимость с доставкой подтверждена источниками."
            if complete
            else "Неподтверждённые условия вынесены в уточнения."
        ),
        selection_reason=(
            "Выбран минимум среди проверенных корзин с известной доставкой."
            if complete
            else "Предварительный выбор: подходящие предложения с минимальной найденной стоимостью товаров. Неизвестные сроки, количество и доставка не считаются подтверждёнными."
        ),
    )
