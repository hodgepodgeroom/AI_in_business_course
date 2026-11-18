import json
import unittest
from unittest.mock import Mock, patch
from agent import Agent, offers_from_page
from product_page import extract_product, exact_ruble_price, pack_supported
from sources import fetch_page, local_catalog_links

URL = "https://supplier.example/cement"
NAME = "Цемент М500, мешок 50 кг"
ITEM = dict(name=NAME, requirements=NAME, unit="мешок", quantity="6")
PAYLOAD = dict(
    text=NAME + " — 6 мешков", city="Казань", address="Склад", deadline="2026-12-18"
)


def page(**changes):
    offer = {"@type": "Offer", "priceCurrency": "RUB", "price": 575, **changes}
    markup = {"@graph": [{"@type": "Product", "name": NAME, "offers": offer}]}
    return extract_product(
        f'<h1>{NAME}</h1><script type="application/ld+json">{json.dumps(markup)}</script>',
        URL,
    )


class PageTests(unittest.TestCase):
    @patch(
        "agent.chat", return_value={"fits": True, "pack_quantity": 1, "evidence": NAME}
    )
    def test_price_from_supplier_not_model(self, chat):
        (q,) = offers_from_page(page(), ITEM, PAYLOAD, "local")
        self.assertEqual(
            (q["pack_price"], q["pack_quantity"], q["url"]), ("575", "1", URL)
        )
        self.assertNotIn("price", chat.call_args.args[2]["properties"])

    def test_conditional_or_ambiguous_prices(self):
        for fields in (
            {"priceCurrency": "USD"},
            {"@type": "AggregateOffer"},
            {"eligibleQuantity": 6},
            {"priceValidUntil": "2020-01-01"},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                page(**fields)

    def test_late_html_price_and_amount(self):
        html = (
            "<h1>"
            + NAME
            + "</h1><main>"
            + ("Описание товара. " * 3000)
            + "Мешок 50 кг: 575 ₽</main>"
        )
        p = extract_product(html, URL)
        self.assertIn("50 кг: 575 ₽", p["text"])
        self.assertTrue(exact_ruble_price(575, "50 кг: 575 ₽", p["text"]))
        self.assertFalse(exact_ruble_price(50, "50 кг: 575 ₽", p["text"]))
        self.assertFalse(exact_ruble_price(575, "575 ₽", "Цена от 575 ₽"))

        self.assertFalse(exact_ruble_price(575, "575 ₽", "Товар 1 575 ₽"))
        self.assertTrue(pack_supported(1, "мешок", "мешок 50 кг"))
        self.assertFalse(pack_supported(50, "мешок", "мешок 50 кг"))
        self.assertTrue(pack_supported(50, "кг", "мешок 50 кг"))

    def test_challenge_is_not_product(self):
        with self.assertRaisesRegex(ValueError, "проверки доступа"):
            extract_product("<title>Just a moment</title>", URL)

    @patch("sources.public_url", return_value=True)
    @patch("sources.requests.Session")
    def test_access_refusal_stops_at_supplier(self, session, _):
        client = session.return_value.__enter__.return_value
        for code in (403, 429):
            client.get.reset_mock()
            client.get.return_value.__enter__.return_value.status_code = code
            client.get.return_value.__enter__.return_value.is_redirect = False
            with self.assertRaisesRegex(ValueError, str(code)):
                fetch_page(URL)
            client.get.assert_called_once()

    @patch(
        "agent.indexed_offer", side_effect=AssertionError("search snippets unnecessary")
    )
    @patch(
        "agent.chat", return_value={"fits": True, "pack_quantity": 1, "evidence": NAME}
    )
    @patch("agent.search_web", return_value=[{"href": URL + str(n)} for n in range(3)])
    @patch("agent.fetch_page")
    def test_request_continues_after_two_failures(self, fetch, search, chat, index):
        fetch.side_effect = [ValueError("HTTP 403"), ValueError("HTTP 429"), page()]
        worker = Agent({"site": "http://127.0.0.1:5173", "worker_secret": "test"})
        worker.update = Mock()
        result = worker.process({"payload": PAYLOAD})
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(result["goods_total"], "3450")
        self.assertIsNone(result["delivery_total"])


class CatalogTests(unittest.TestCase):
    @patch("sources.fetch_html")
    def test_catalog_fallback_keeps_matching_pack_and_region(self, fetch):
        root = "https://kamacement.ru/catalog/cement-v-meshkah/"
        fetch.return_value = (
            '<div class="product-item__name"><a href="p50/">Цемент М500 50 кг</a><a href="p25/">Цемент М500 25 кг</a></div>',
            root,
        )
        self.assertEqual(local_catalog_links(ITEM, "Москва"), [])
        fetch.assert_not_called()
        self.assertEqual(local_catalog_links(ITEM, "Казань"), [root + "p50/"])
