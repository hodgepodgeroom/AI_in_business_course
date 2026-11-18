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


def price_notice(text):
    return bool(
        re.search(
            r"\b(?:цен[ауые]|стоимость)(?:\s*/\s*[\w.]+){0,5}\s+(?:обязательно\s+)?уточн(?:яйте|ите)|"
            r"\bуточн(?:яйте|ите)\s+(?:актуальную\s+)?цену\b",
            text,
            re.I,
        )
    )


def unverified_basis(text, price):
    """Catch explicit weight, pallet or wholesale pricing without a verified conversion."""
    for hit in RUB.finditer(text):
        if dec(hit["amount"]) != dec(price):
            continue
        before = norm(text[max(0, hit.start() - 65) : hit.start()])
        after = norm(text[hit.end() : hit.end() + 55])
        if re.match(
            r"^(?:/\s*|за\s+)(?:1\s*)?(?:кг|килограмм|тонн|т\b|литр|м[²³23]|поддон|палл[еэ]т|парти)",
            after,
        ) or re.search(
            r"(?:цена|стоимость)\s+(?:за\s+)?(?:парти[ию]|поддона|тонны|килограмма)\s*[:—-]?$",
            before,
        ):
            return True
    return False


def matching_pack_size(request, name, unit):
    if unit not in ("мешок", "уп", "шт"):
        return True
    # Обязательная масса или объём упаковки, включая записи «50кг» и «0,5 л».
    measure = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(кг|мл|л|г)(?!\w)", re.I)

    def amounts(text):
        result = set()
        for number, symbol in measure.findall(norm(text)):
            base = "г" if symbol in ("кг", "г") else "мл"
            value = dec(number) * (1000 if symbol in ("кг", "л") else 1)
            result.add((base, value))
        return result

    return amounts(request) <= amounts(name)


def products(node):
    if isinstance(node, list):
        for entry in node:
            yield from products(entry)
    elif isinstance(node, dict):
        kind = node.get("@type", "")
        if "Product" in (kind if isinstance(kind, list) else [kind]):
            yield node
        yield from products(node.get("@graph"))


def structured_price(raw):
    """Normalize an explicitly priced number of sale units, preserving order limits."""
    conditions = {
        "eligibleRegion",
        "eligibleCustomerType",
        "validFrom",
        "validThrough",
        "eligibleTransactionVolume",
    }
    spec = raw.get("priceSpecification", {})
    if (
        not isinstance(spec, dict)
        or conditions.intersection(raw)
        or conditions.intersection(spec)
    ):
        raise ValueError("Цена зависит от условий предложения")
    if spec and (
        spec.get("@type") != "UnitPriceSpecification"
        or set(spec)
        - {"@type", "price", "priceCurrency", "referenceQuantity", "eligibleQuantity"}
    ):
        raise ValueError("Неоднозначная спецификация цены")
    currency = raw.get("priceCurrency", spec.get("priceCurrency"))
    if currency != "RUB" or spec.get("priceCurrency", currency) != currency:
        raise ValueError("Нет однозначной цены карточки в рублях")
    amount = dec(spec.get("price", raw.get("price")))
    basis = spec.get("referenceQuantity")
    reference = dec(1)
    if basis is not None:
        if (
            not isinstance(basis, dict)
            or basis.get("unitCode") not in ("C62", "H87")
            or set(basis) - {"@type", "unitCode", "value"}
        ):
            raise ValueError("Не подтверждена единица цены")
        reference = dec(basis.get("value"))
    if not reference or reference != reference.to_integral_value() or not amount:
        raise ValueError("Не подтверждена цена за единицу")
    price = amount / reference
    if price != price.quantize(dec("0.01")) or (
        "price" in raw and dec(raw["price"]) != price
    ):
        raise ValueError("Цены за единицу расходятся")
    limits = []
    for source in (raw, spec):
        if "eligibleQuantity" not in source:
            continue
        interval = source["eligibleQuantity"]
        if (
            not isinstance(interval, dict)
            or interval.get("unitCode") not in ("C62", "H87")
            or set(interval) - {"@type", "unitCode", "minValue", "maxValue", "value"}
        ):
            raise ValueError("Не подтверждена единица ограничения заказа")
        lo, hi = interval.get("minValue", interval.get("value")), interval.get(
            "maxValue", interval.get("value")
        )
        if (
            lo is None
            and hi is None
            or (lo is not None and hi is not None and dec(lo) > dec(hi))
        ):
            raise ValueError("Не подтверждены границы заказа")
        limits.append((lo, hi, None))
    evidence = (
        f"priceSpecification.price = {ds(amount)} RUB за {ds(reference)} ед."
        if spec
        else f"Offer.price = {ds(price)} RUB"
    )
    return price, limits, evidence


def extract_product(html, url, json_loader=None):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.h1 or soup.title
    title = heading.get_text(" ", strip=True) if heading else ""
    if re.search(
        r"captcha|access denied|just a moment|проверка браузера|доступ ограничен",
        title,
        re.I,
    ):
        raise ValueError("Страница проверки доступа")
    notice = price_notice(
        (soup.find("main") or soup.body or soup).get_text(" ", strip=True)
    )
    lot = lot_offer(soup, title)
    external = json_loader(soup) if json_loader else None
    if lot and external and dec(external["price"]) != dec(lot["price"]):
        raise ValueError("Цена API и цена мешка в партии расходятся")
    if lot:
        if external:
            external.setdefault("quantity_limits", []).extend(lot["quantity_limits"])
        else:
            external = lot
    if external:
        if notice:
            external.update(
                source_status="needs_confirmation",
                review_reason="Магазин просит уточнить цену при заказе",
            )
        primary = soup.select_one(".summary, .product-main, [itemtype$='/Product']")
        if (
            not lot
            and primary
            and unverified_basis(primary.get_text(" ", strip=True), external["price"])
        ):
            raise ValueError("Требуется проверить, за какую единицу указана цена")
        return {
            "title": title,
            "text": external["name"],
            "url": url,
            "supplier": urlsplit(url).hostname.removeprefix("www."),
            "offer": external,
        }
    retail = visible_retail(soup, title)
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
    for related in soup.select(
        ".related, .upsells, .cross-sells, [itemprop='isRelatedTo']"
    ):
        related.decompose()
    scope = (
        soup.select_one(".summary.entry-summary, .product-main")
        or soup.find("main")
        or soup
    )
    marked_prices = {
        tag["content"] for tag in scope.select('meta[itemprop="price"][content]')
    }
    body = scope.get_text(" ", strip=True)
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
        if not isinstance(raw, dict) or raw.get("@type") != "Offer":
            raise ValueError("Нет однозначной цены карточки в рублях")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("У предложения нет названия товара")
        price, limits, evidence = structured_price(raw)
        expired = (
            raw.get("priceValidUntil")
            and str(raw["priceValidUntil"])[:10] < date.today().isoformat()
        )
        if expired and not retail:
            raise ValueError("Срок действия цены истёк")
        availability = str(raw.get("availability", "")).rsplit("/", 1)[-1]
        offer = dict(
            name=name,
            price=ds(price),
            quantity_limits=limits,
            price_evidence=evidence,
            availability={
                "InStock": "in_stock",
                "OutOfStock": "out_of_stock",
                "SoldOut": "out_of_stock",
            }.get(availability, "unknown"),
        )
        if retail and (expired or price != dec(retail[0])):
            offer.update(
                price=retail[0],
                price_evidence=retail[1],
                source_status="needs_confirmation",
                review_reason=(
                    "Срок цены в разметке истёк"
                    if expired
                    else "Разметка и розничная цена расходятся"
                ),
            )
        if unverified_basis(body, offer["price"]):
            raise ValueError("Требуется проверить, за какую единицу указана цена")
        parts.insert(0, f"{name}\n{offer['price_evidence']}")
        if notice:
            offer.update(
                source_status="needs_confirmation",
                review_reason="Магазин просит уточнить цену при заказе",
            )
    elif len(records) > 1:
        raise ValueError("На странице несколько товаров без выделенной карточки")
    return {
        "title": title,
        "text": "\n".join(parts),
        "price_notice": notice,
        "marked_prices": sorted(marked_prices),
        "url": url,
        "supplier": urlsplit(url).hostname.removeprefix("www."),
        "offer": offer,
    }


def units_per_pack(name, unit):
    """Quantity sold for one pack, expressed in the request's units."""
    aliases = {
        "кг": {"кг": "1", "г": "0.001"},
        "л": {"л": "1", "мл": "0.001"},
        "м": {"м": "1"},
        "м2": {"м²": "1", "м2": "1"},
        "м3": {"м³": "1", "м3": "1"},
    }
    scales = aliases.get(unit, {k: "1" for k, v in UNITS.items() if v == unit})
    if not scales:
        return None
    tokens = "|".join(sorted(map(re.escape, scales), key=len, reverse=True))
    matches = list(
        re.finditer(
            r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(" + tokens + r")(?![\w²³])", norm(name)
        )
    )
    if len(matches) == 1:
        hit = matches[0]
        if re.search(
            r"(?:\d\s*[xх×*–—-]|\bот)\s*$", norm(name)[: hit.start()]
        ) or re.match(r"\s*[xх×*]\s*\d", norm(name)[hit.end() :]):
            return None
        return dec(hit[1]) * dec(scales[hit[2]])
    if matches or unit in aliases:
        return None
    if (
        unit == "шт"
        or (unit == "мешок" and re.search(r"меш[оаек]|\d\s*кг\b", norm(name)))
        or (unit == "уп" and re.search(r"упаковк|пачк", norm(name)))
    ):
        return dec(1)
    return None


def lot_offer(soup, title):
    # Check the supplier's quantity control, labelled tier and displayed order total together.
    block = soup.select_one(".payments:has(.min-opt)")
    if not block:
        return None
    buttons = block.select(".min-opt .prices button")
    if len(buttons) != 1 or not buttons[0].has_attr("data-count"):
        raise ValueError("Требуется уточнить тарифы для партии")
    tier = buttons[0].get_text(" ", strip=True)
    count = re.search(r"\bот\s+(\d+)\s+мешк", tier, re.I)
    price = RUB.search(tier)
    total_node = block.select_one(".price")
    total = RUB.search(total_node.get_text(" ", strip=True)) if total_node else None
    if (
        not count
        or not price
        or not total
        or count[1] != buttons[0]["data-count"]
        or dec(count[1]) <= 0
        or dec(total["amount"]) != dec(count[1]) * dec(price["amount"])
    ):
        raise ValueError("Цена партии не согласуется с количеством и ценой мешка")
    return dict(
        name=title,
        price=ds(dec(price["amount"])),
        availability="unknown",
        quantity_limits=[(count[1], None, None)],
        price_evidence=tier,
    )


def visible_retail(soup, title):
    heading = soup.h1
    if not heading or norm(heading.get_text(" ", strip=True)) != norm(title):
        return None
    for parent in heading.parents:
        rows = parent.select(".card-prices .card-price-wrapper")
        if not rows:
            continue
        prices = []
        for row in rows:
            label = row.select_one(".card-price-title")
            if label and norm(label.get_text(" ", strip=True)) == "розничная цена":
                text = row.get_text(" ", strip=True)
                matches = list(RUB.finditer(text))
                if len(matches) == 1 and exact_ruble_price(
                    matches[0]["amount"], matches[0].group(), text
                ):
                    prices.append((ds(dec(matches[0]["amount"])), text))
        if parent.select_one("h1") and len(parent.select("h1")) == 1:
            return prices[0] if len(prices) == 1 else None
        return None
    return None
