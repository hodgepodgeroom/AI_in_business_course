"""Поиск предложений, проверка источников и чтение публичных страниц."""

import re, socket, ipaddress, json, uuid
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from model import chat, MATCH_SCHEMA
from product_page import extract_product, RUB, exact_ruble_price
from estimate import norm, ds, dec


def public_url(url):
    try:
        p = urlparse(url)
        if (
            p.scheme not in ("http", "https")
            or not p.hostname
            or p.username
            or p.password
            or p.port not in (None, 80, 443)
        ):
            return False
        addresses = socket.getaddrinfo(p.hostname, None)
        return bool(addresses) and all(
            ipaddress.ip_address(a[4][0]).is_global for a in addresses
        )
    except (ValueError, OSError):
        return False


def search_web(name, city):
    query = re.sub(r"\b(?:мешок|канистра|упаковка)\b", " ", name, flags=re.I).replace(
        ", ", " "
    )
    query = re.sub(r"\s+", " ", query).strip() + " купить " + city + " цена"
    try:
        response = requests.get(
            "https://www.bing.com/search",
            params={"q": query, "format": "rss"},
            timeout=25,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        results = [
            {
                "title": n.findtext("title") or "",
                "href": n.findtext("link") or "",
                "body": n.findtext("description") or "",
            }
            for n in root.findall(".//item")
        ]
        if results:
            return results[:6]
    except (requests.RequestException, ET.ParseError):
        pass
    return DDGS(timeout=20).text(query, region="ru-ru", max_results=5)


def lexical_match(request, title):
    stop = {
        "мешок",
        "мешки",
        "мешка",
        "канистра",
        "канистры",
        "упаковка",
        "упаковки",
        "штук",
        "штуки",
        "литров",
        "килограмм",
        "шт",
        "мм",
        "кг",
        "для",
        "по",
        "уп",
        "пачка",
    }
    words = [
        w
        for w in re.findall(r"[a-zа-яё]+", norm(request))
        if len(w) > 2 and w not in stop
    ]
    source_words = re.findall(r"[a-zа-яё]+", norm(title))
    if not words or not all(
        any(s.startswith(w[:6]) for s in source_words) for w in words
    ):
        return False
    numbers = lambda text: {ds(dec(n)) for n in re.findall(r"\d+(?:[.,]\d+)?", text)}
    return numbers(request) <= numbers(title)


def indexed_offer(entry, item, model):
    text = BeautifulSoup(
        entry["title"] + " " + entry.get("body", ""), "html.parser"
    ).get_text(" ", strip=True)
    match = next(
        (
            m
            for m in RUB.finditer(text)
            if exact_ruble_price(m["amount"], m.group(), text)
        ),
        None,
    )
    if not match:
        return None
    # A local model checks product suitability; arithmetic and the quoted price stay in code.
    answer = chat(
        model,
        "Сравни товары. Если бренд не указан, любой допустим. Слова мешок, упаковка и канистра обозначают тару: отсутствие слова мешок в названии не мешает совпадению. fits=true если тип товара, обязательный бренд и размеры соответствуют. Если это общая категория с разными товарами — false.\nЗАПРОС: "
        + item["name"]
        + "\nПРЕДЛОЖЕНИЕ: "
        + text[:1600],
        MATCH_SCHEMA,
    )
    if not answer.get("fits") and not lexical_match(item["name"], entry["title"]):
        return None
    pack = Decimal(1)
    if item["unit"] == "шт":
        found = re.search(r"(\d+)\s*(?:шт\.?|штук)(?:\b|\s|\))", entry["title"], re.I)
        if found:
            pack = dec(found.group(1))
    elif item["unit"] in ("кг", "л", "м2", "м3", "м"):
        found = re.search(
            r"(\d+(?:[.,]\d+)?)\s*" + re.escape(item["unit"]) + r"(?:\b|\s)",
            entry["title"],
            re.I,
        )
        if not found:
            return None
        pack = dec(found.group(1))
    return {
        "id": str(uuid.uuid4()),
        "supplier": urlparse(entry["href"]).hostname.removeprefix("www."),
        "url": entry["href"],
        "product_name": entry["title"],
        "fits": True,
        "reason": "Предварительная цена из поискового индекса; требуется подтверждение товарной страницей",
        "pack_price": ds(dec(match.group(1))),
        "price_evidence": match.group(0),
        "pack_quantity": ds(pack),
        "unit": item["unit"],
        "availability": "unknown",
        "stock_quantity": None,
        "delivery_date": None,
        "delivery_cost": None,
        "delivery_scope": "unknown",
        "delivery_evidence": "",
        "source_status": "search_index",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_html(url):
    with requests.Session() as session:
        session.headers["User-Agent"] = (
            "OsnovaProcurementPrototype/0.2 (public product information)"
        )
        for _ in range(4):
            if not public_url(url):
                raise ValueError("Нет подтверждённого публичного адреса")
            with session.get(
                url, timeout=20, allow_redirects=False, stream=True
            ) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                if response.status_code == 403:
                    raise ValueError("Магазин закрыл доступ (HTTP 403)")
                if response.status_code == 429:
                    raise ValueError("Магазин ограничил частоту запросов (HTTP 429)")
                response.raise_for_status()
                if "html" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Источник не является HTML-карточкой")
                data = bytearray()
                for chunk in response.iter_content(32768):
                    data.extend(chunk)
                    if len(data) > 2500000:
                        raise ValueError("Страница слишком велика")
                encoding = response.encoding
                html = (
                    bytes(data)
                    if not encoding or encoding.upper() == "ISO-8859-1"
                    else data.decode(encoding, errors="replace")
                )
                return html, url
    raise ValueError("Слишком много переадресаций")


def fetch_page(url):
    html, final_url = fetch_html(url)
    return extract_product(html, final_url)


def local_catalog_links(item, city):
    """Резервный публичный каталог для сценария закупки цемента в Казани."""
    if norm(city) != "казань" or "цемент" not in norm(item["name"]):
        return []
    base = "https://kamacement.ru/catalog/cement-v-meshkah/"
    html, final_url = fetch_html(base)
    if final_url.rstrip("/") != base.rstrip("/"):
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for link in soup.select(".product-item__name a[href]"):
        url = urljoin(base, link["href"])
        if url.startswith(base) and lexical_match(
            item["name"], link.get_text(" ", strip=True)
        ):
            links.append(url)
    return list(dict.fromkeys(links))
