"""Чтение точных розничных цен из публичных API магазинов."""

import re
from html import unescape
from urllib.parse import quote, unquote, urljoin, urlsplit

from estimate import dec, ds, norm
from product_page import RUB, exact_ruble_price


class JsonPriceError(ValueError):
    """Поставщик не подтвердил цену для этой карточки."""


def origin(url):
    parts = urlsplit(url)
    return (
        parts.scheme,
        parts.hostname,
        parts.port or (443 if parts.scheme == "https" else 80),
    )


def field(record, path):
    for key in path.split("."):
        if not isinstance(record, dict) or key not in record:
            raise ValueError(f"В JSON магазина отсутствует поле {path}")
        record = record[key]
    return record


def checked_offer(name, amount, currency, availability, endpoint, evidence, city=None):
    if currency != "RUB":
        raise ValueError("В JSON не подтверждена валюта RUB")
    price = dec(amount)
    if price <= 0 or price != price.quantize(dec("0.01")):
        raise ValueError("Некорректная цена в рублях")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Не удалось установить название товара")
    return dict(
        name=unescape(name.strip()),
        price=ds(price),
        availability=availability,
        price_source_url=endpoint,
        price_evidence=evidence,
        price_region=city,
    )


def compare_visible(soup, selector, offer):
    if not selector:
        return
    for node in soup.select(selector):
        # WooCommerce размечает зачёркнутую старую цену через del.
        for old in node.select("del, s, .screen-reader-text"):
            old.decompose()
        label = node.get_text(" ", strip=True)
        amounts = list(RUB.finditer(label))
        if amounts and (
            len(amounts) != 1
            or not exact_ruble_price(offer["price"], amounts[0].group(), label)
        ):
            raise ValueError("Цена в JSON расходится с ценой карточки")


def regional_offer(rule, soup, url, city, fetch_json):
    try:
        region = next(
            (
                str(value)
                for key, value in rule["regions"].items()
                if norm(key) == norm(city)
            ),
            None,
        )
        if not region:
            raise ValueError("Для города не настроен источник цены")
        nodes = soup.select(rule["sku_selector"])
        if len(nodes) != 1:
            raise ValueError("Не удалось однозначно определить артикул карточки")
        sku = (
            nodes[0].get(rule["sku_attribute"])
            if rule.get("sku_attribute")
            else nodes[0].get_text(strip=True)
        )
        if not isinstance(sku, str) or not sku.strip() or sku.strip() in (".", ".."):
            raise ValueError("Нет артикула карточки")
        sku = sku.strip()
        template = rule["path"]
        if not template.startswith("/") or not all(
            key in template for key in ("{sku}", "{region}")
        ):
            raise ValueError("В настройках требуется путь с артикулом и регионом")
        endpoint = urljoin(
            url, template.format(sku=quote(sku, safe=""), region=quote(region, safe=""))
        )
        record, endpoint = fetch_json(endpoint, url)
        fields = rule["fields"]
        if (
            str(field(record, fields["sku"])) != sku
            or str(field(record, fields["region"])) != region
        ):
            raise ValueError("Артикул или регион JSON не совпадает с заявкой")
        amount = field(record, fields["price"])
        currency = field(record, fields["currency"])
        product_name = field(record, fields["name"])
        offer = checked_offer(
            product_name,
            amount,
            currency,
            "unknown",
            endpoint,
            f"{fields['price']} = {amount} {currency}, SKU {sku}, регион {region}",
            city,
        )
        compare_visible(soup, rule.get("visible_price_selector"), offer)
        return offer
    except (AttributeError, IndexError, KeyError, TypeError) as error:
        raise ValueError(
            "Некорректные настройки или ответ регионального магазина"
        ) from error


def woo_limits(soup, record):
    cart = record.get("add_to_cart") or {}
    if not isinstance(cart, dict):
        raise ValueError("Неизвестный формат ограничений количества")
    limits = [(cart.get("minimum"), cart.get("maximum"), cart.get("multiple_of"))]
    for node in soup.select(".summary form.cart input.qty"):
        limits.append((node.get("min"), node.get("max"), node.get("step")))
    return limits


def quantity_problem(limits, packs):
    for minimum, maximum, step in limits:
        if minimum and packs < dec(minimum):
            return f"Минимальная партия поставщика — {minimum} упак."
        if maximum and str(maximum) != "-1" and packs > dec(maximum):
            return f"Поставщик отпускает максимум {maximum} упак."
        if step and step != "any" and dec(step) > 0 and packs % dec(step):
            return f"Количество упаковок должно быть кратно {step}"
    return None


def woo_offer(soup, url, fetch_json):
    body = soup.select_one("body.single-product")
    if not body:
        return None
    identifiers = [
        c[7:] for c in body.get("class", []) if re.fullmatch(r"postid-[0-9]+", c)
    ]
    if len(identifiers) != 1:
        return None
    product_id = identifiers[0]
    api = soup.select_one('link[rel="https://api.w.org/"][href]')
    root = urljoin(url, api["href"]) if api else urljoin(url, "/wp-json/")
    if urlsplit(root).query or not urlsplit(root).path.endswith("/wp-json/"):
        return None
    endpoint = urljoin(root, "wc/store/v1/products/" + product_id)
    record, endpoint = fetch_json(endpoint, url)
    link = record.get("permalink")
    if (
        str(record.get("id")) != product_id
        or not isinstance(link, str)
        or origin(link) != origin(url)
        or unquote(urlsplit(link).path).rstrip("/")
        != unquote(urlsplit(url).path).rstrip("/")
    ):
        raise ValueError("Карточка и товар в Store API не совпадают")
    prices = record.get("prices")
    if (
        record.get("type") != "simple"
        or record.get("variations")
        or record.get("has_options")
        or record.get("is_password_protected")
        or record.get("is_on_backorder")
        or not isinstance(prices, dict)
        or prices.get("price_range")
    ):
        raise ValueError("У товара нет однозначной цены для обычной покупки")
    raw = prices.get("price")
    scale = prices.get("currency_minor_unit")
    if (
        type(scale) != int
        or scale not in range(5)
        or not re.fullmatch(r"[0-9]+", str(raw))
    ):
        raise ValueError("Неизвестный формат цены в Store API")
    stock = record.get("is_in_stock")
    availability = "unknown"
    if isinstance(stock, bool):
        availability = "in_stock" if stock else "out_of_stock"
    if record.get("is_purchasable") is False:
        availability = "out_of_stock"
    offer = checked_offer(
        record.get("name"),
        dec(raw).scaleb(-scale),
        prices.get("currency_code"),
        availability,
        endpoint,
        f"prices.price = {raw}, currency_minor_unit = {scale}, RUB, ID {product_id}",
    )
    offer["quantity_limits"] = woo_limits(soup, record)
    compare_visible(soup, ".summary > .price, .summary > div > p.price", offer)
    return offer
