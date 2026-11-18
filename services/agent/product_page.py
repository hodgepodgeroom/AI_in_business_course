"""Короткие фрагменты карточки для локальной модели и проверка цены поставщика."""

from datetime import date
import json
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from estimate import UNITS, dec, ds, norm

RUB = re.compile(
    r"(?<![\d.,])(?P<amount>(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|ль|ля|лей)?\b|RUB\b)",
    re.I,
)


def exact_ruble_price(price, evidence, text):
    """The number must be attached to RUB in a verbatim excerpt, outside a price range."""
    if not isinstance(evidence, str) or not evidence.strip():
        return False
    excerpt = norm(evidence)
    value = dec(price)
    if value <= 0:
        return False
    source = norm(text)
    spans = [(m.start(), m.end()) for m in re.finditer(re.escape(excerpt), source)]
    for match in RUB.finditer(source):
        if not any(a <= match.start() and match.end() <= b for a, b in spans):
            continue
        if re.search(
            r"(?:\bот|\d\s*[-–—])\s*$",
            source[max(0, match.start() - 25) : match.start()],
        ):
            continue
        if dec(match["amount"]) == value:
            return True
    return False


def pack_supported(quantity, unit, evidence):
    aliases = [
        re.escape(word) for word, canonical in UNITS.items() if canonical == unit
    ]
    if not aliases:
        return quantity == 1
    pattern = r"(\d+(?:[.,]\d+)?)\s*(?:" + "|".join(aliases) + r")(?![\w²³])"
    amounts = [dec(n) for n in re.findall(pattern, evidence, re.I)]
    return quantity in amounts if amounts else quantity == 1


def products(node):
    if isinstance(node, list):
        for entry in node:
            yield from products(entry)
    elif isinstance(node, dict):
        kind = node.get("@type", "")
        if "Product" in (kind if isinstance(kind, list) else [kind]):
            yield node
        yield from products(node.get("@graph"))


def extract_product(html, url):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.h1 or soup.title
    title = heading.get_text(" ", strip=True) if heading else ""
    if re.search(
        r"captcha|access denied|just a moment|проверка браузера|доступ ограничен",
        title,
        re.I,
    ):
        raise ValueError("Страница проверки доступа")
    records = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            records.extend(products(json.loads(script.get_text())))
        except (ValueError, RecursionError):
            continue
    for tag in soup(
        [
            "script",
            "style",
            "nav",
            "header",
            "footer",
            "noscript",
            "svg",
            "aside",
            "s",
            "del",
        ]
    ):
        tag.decompose()
    body = (soup.find("main") or soup).get_text(" ", strip=True)
    body = re.sub(r"\s+", " ", body)
    # Price can occur after thousands of characters of navigation. Keep the nearby unit and terms.
    parts = [title, body[:700]]
    last = 0
    for hit in RUB.finditer(body):
        if hit.start() < last:
            continue
        parts.append(body[max(0, hit.start() - 140) : hit.end() + 200])
        last = hit.end() + 160
        if len(parts) >= 10:
            break
    named = [p for p in records if norm(p.get("name", "")) == norm(title)]
    product = (
        named[0] if len(named) == 1 else (records[0] if len(records) == 1 else None)
    )
    offer = None
    if product and product.get("offers"):
        name = product.get("name")
        raw = product["offers"]
        if isinstance(raw, list) and len(raw) == 1:
            raw = raw[0]
        if (
            not isinstance(raw, dict)
            or raw.get("@type") != "Offer"
            or raw.get("priceCurrency") != "RUB"
        ):
            raise ValueError("Нет однозначной цены карточки в рублях")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("У предложения нет названия товара")
        if any(
            key in raw
            for key in (
                "eligibleQuantity",
                "eligibleCustomerType",
                "priceSpecification",
                "eligibleRegion",
                "validFrom",
                "validThrough",
            )
        ):
            raise ValueError("Цена зависит от условий предложения")
        if (
            raw.get("priceValidUntil")
            and str(raw["priceValidUntil"])[:10] < date.today().isoformat()
        ):
            raise ValueError("Срок действия цены истёк")
        price = dec(raw.get("price"))
        if price <= 0:
            raise ValueError("Нет положительной цены")
        availability = str(raw.get("availability", "")).rsplit("/", 1)[-1]
        offer = dict(
            name=name,
            price=ds(price),
            availability={
                "InStock": "in_stock",
                "OutOfStock": "out_of_stock",
                "SoldOut": "out_of_stock",
            }.get(availability, "unknown"),
        )
        parts.insert(0, f"{name}\nOffer.price = {offer['price']} RUB")
    elif len(records) > 1:
        raise ValueError("На странице несколько товаров без выделенной карточки")
    return {
        "title": title,
        "text": "\n".join(parts),
        "url": url,
        "supplier": urlsplit(url).hostname.removeprefix("www."),
        "offer": offer,
    }
