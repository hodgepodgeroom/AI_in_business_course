import json
import unittest
from unittest.mock import MagicMock, Mock, patch

from agent import Agent, offers_from_page
from sources import fetch_page
from test_pages import NAME, ITEM, PAYLOAD

URL = "https://shop.example/product/cement"
WOO = "https://shop.example/wp-json/wc/store/v1/products/17"
HTML = f'<body class="single-product postid-17"><h1>{NAME}</h1></body>'
REGIONAL = {
    "shop.example": {
        "sku_selector": "main[data-sku]",
        "sku_attribute": "data-sku",
        "path": "/api/price/{sku}?city={region}",
        "regions": {"Казань": "16"},
        "fields": {
            "sku": "id",
            "region": "city",
            "price": "retail.amount",
            "currency": "retail.currency",
            "name": "title",
        },
        "visible_price_selector": "main .current-price",
    }
}
REG_HTML = f'<main data-sku="C/50"><h1>{NAME}</h1></main>'
REG_DATA = {
    "id": "C/50",
    "city": "16",
    "title": NAME,
    "retail": {"amount": 575, "currency": "RUB"},
}
WOO_DATA = {
    "id": 17,
    "permalink": URL,
    "type": "simple",
    "name": NAME,
    "is_in_stock": True,
    "prices": {"price": "57550", "currency_minor_unit": 2, "currency_code": "RUB"},
}


class JsonPriceTests(unittest.TestCase):
    def setUp(self):
        session = self.enter_patch("sources.requests.Session")
        self.client = session.return_value.__enter__.return_value
        self.enter_patch("sources.public_url", return_value=True)

    def enter_patch(self, target, **kwargs):
        p = patch(target, **kwargs)
        self.addCleanup(p.stop)
        return p.start()

    def serve(self, html, record, mime="application/json"):
        responses = []
        for content, content_type in ((html, "text/html"), (json.dumps(record), mime)):
            response = Mock(
                is_redirect=False,
                status_code=200,
                headers={"content-type": content_type},
                encoding="utf8",
            )
            response.iter_content.return_value = [content.encode()]
            context = MagicMock()
            context.__enter__.return_value = response
            responses.append(context)
        self.client.get.side_effect = responses

    def test_regional_json_through_worker(self):
        self.serve(REG_HTML, REG_DATA)
        self.enter_patch(
            "agent.chat",
            return_value={"fits": True, "pack_quantity": 1, "evidence": NAME},
        )
        search = self.enter_patch("agent.search_web")
        agent = Agent(
            {
                "site": "http://127.0.0.1:5173",
                "worker_secret": "example",
                "supplier_json": REGIONAL,
            }
        )
        agent.update = Mock()
        result = agent.process(
            {"payload": {**PAYLOAD, "text": PAYLOAD["text"] + "\n" + URL}}
        )
        quote = result["items"][0]["selected"]
        self.assertEqual(
            quote["price_source_url"], "https://shop.example/api/price/C%2F50?city=16"
        )
        self.assertEqual(
            (result["goods_total"], quote["price_region"], quote["url"]),
            ("3450", "Казань", URL),
        )
        self.assertIn("retail.amount", quote["price_evidence"])
        search.assert_not_called()

    def test_region_sku_currency_and_visible_price(self):
        cases = [
            (REG_HTML, {**REG_DATA, "id": "C/25"}),
            (REG_HTML, {**REG_DATA, "city": "77"}),
            (REG_HTML, {**REG_DATA, "retail": {"amount": 575, "currency": "USD"}}),
            (
                REG_HTML.replace(
                    "</main>", '<b class="current-price">590 ₽</b></main>'
                ),
                REG_DATA,
            ),
        ]
        for html, record in cases:
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.serve(html, record)
                fetch_page(URL, "Казань", REGIONAL)
        self.serve(REG_HTML, REG_DATA)
        self.client.get.reset_mock()
        with self.assertRaisesRegex(ValueError, "города"):
            fetch_page(URL, "Москва", REGIONAL)
        self.assertEqual(self.client.get.call_count, 1)

    def test_woo_scale_stock_and_limits(self):
        self.serve(
            HTML.replace(
                "</body>",
                '<div class="summary"><form class="cart"><input class="qty" min="20"></form></div></body>',
            ),
            WOO_DATA,
        )
        page = fetch_page(URL)
        o = page["offer"]
        self.assertEqual(
            (o["price"], o["price_source_url"], o["availability"], o["price_region"]),
            ("575.5", WOO, "in_stock", None),
        )
        self.enter_patch(
            "agent.chat",
            return_value={"fits": True, "pack_quantity": 1, "evidence": NAME},
        )
        (short,) = offers_from_page(page, ITEM, PAYLOAD, "test")
        self.assertFalse(short["fits"])
        self.assertIn("20", short["reason"])
        (quote,) = offers_from_page(page, {**ITEM, "quantity": "20"}, PAYLOAD, "test")
        self.assertEqual(quote["pack_price"], "575.5")

    def test_cement_for_another_pack_size_is_rejected(self):
        self.serve(HTML, {**WOO_DATA, "name": "Цемент М500, мешок 25кг"})
        page = fetch_page(URL)
        chat = self.enter_patch("agent.chat")
        self.assertEqual(list(offers_from_page(page, ITEM, PAYLOAD, "test")), [])
        chat.assert_not_called()

    def test_rejected_region_cannot_reenter_from_index(self):
        self.serve(REG_HTML, {**REG_DATA, "city": "77"})
        self.enter_patch("agent.search_web", return_value=[{"href": URL}])
        self.enter_patch("agent.local_catalog_links", return_value=[])
        indexed = self.enter_patch("agent.indexed_offer")
        worker = Agent(
            {
                "site": "http://127.0.0.1:5173",
                "worker_secret": "example",
                "supplier_json": REGIONAL,
            }
        )
        worker.update = Mock()
        result = worker.process(
            {"payload": {**PAYLOAD, "text": PAYLOAD["text"] + "\n" + URL}}
        )
        self.assertIsNone(result["items"][0]["selected"])
        indexed.assert_not_called()

    def test_woo_rejects_other_product_range_and_bad_mime(self):
        for changes in (
            {"id": 18},
            {"permalink": URL + "25"},
            {"type": "variable"},
            {"prices": {**WOO_DATA["prices"], "price_range": {"min": "10"}}},
        ):
            self.serve(HTML, {**WOO_DATA, **changes})
            with self.assertRaises(ValueError):
                fetch_page(URL)
        self.serve(HTML, WOO_DATA, "text/html")
        with self.assertRaisesRegex(ValueError, "JSON"):
            fetch_page(URL)

    def test_cross_origin_redirect_is_not_requested(self):
        self.serve(HTML, WOO_DATA)
        contexts = list(self.client.get.side_effect)
        redirect = contexts[1].__enter__.return_value
        redirect.is_redirect = True
        redirect.headers = {"Location": "https://other.example/price"}
        self.client.get.side_effect = contexts
        with self.assertRaisesRegex(ValueError, "HTTPS-сайте поставщика"):
            fetch_page(URL)
        self.assertEqual(self.client.get.call_count, 2)
