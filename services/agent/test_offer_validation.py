import json
import unittest
from unittest.mock import Mock, patch

from agent import Agent, offers_from_page
from estimate import build_estimate
from json_prices import confirm_cart
from product_page import extract_product, units_per_pack
from sources import feed_links, registered_links, relevant_results
from test_pages import NAME, URL, ITEM, PAYLOAD


def structured(name, price, **changes):
    offer = {"@type": "Offer", "priceCurrency": "RUB", "price": price, **changes}
    return (
        '<script type="application/ld+json">'
        + json.dumps({"@type": "Product", "name": name, "offers": offer})
        + "</script>"
    )


LOT = f"""<h1>{NAME}</h1><div class="payments"><p class="price">210000 ₽</p>
<div class="min-opt"><ul class="prices"><li><button data-count="400">Мелкий опт от 400 мешков 525 ₽</button></li></ul></div></div>"""
RETAIL = f"""<main><h1>{NAME}</h1><div class="card-prices">
<div class="card-price-wrapper"><span class="card-price-title">Розничная цена</span> 365 ₽</div>
<div class="card-price-wrapper"><span class="card-price-title">Оптовая цена</span> 346 ₽</div>
</div></main>""" + structured(
    NAME, 365, priceValidUntil="2001-01-01"
)


class OfferValidationTests(unittest.TestCase):
    def estimate(self, cards, quantity, unit):
        item = {**ITEM, "offers": [], "quantity": quantity, "unit": unit}
        with patch("agent.chat", return_value={"fits": True}):
            for supplier, markup in cards.items():
                page = extract_product(markup, "https://" + supplier + "/cement")
                item["offers"].extend(offers_from_page(page, item, PAYLOAD, "local"))
        return build_estimate([item], PAYLOAD, "local")

    def test_round_physical_packs_and_report_excess(self):
        result = self.estimate({"regular.example": structured(NAME, 600)}, "125", "кг")
        q = result["items"][0]["selected"]
        self.assertEqual(
            (
                q["packs"],
                q["purchase_quantity"],
                q["excess_quantity"],
                q["goods_total"],
            ),
            (3, "150", "25", "1800"),
        )
        for name in (
            "цемент",
            "цемент 25–50 кг",
            "упаковка 2 × 50 кг",
            "цемент 25 кг или 50 кг",
        ):
            self.assertIsNone(units_per_pack(name, "кг"), name)
        self.assertEqual(units_per_pack("Смесь 500 г", "кг"), 0.5)

    def test_six_bags_four_hundred_bags_and_uncertain_price(self):
        cards = {
            "lot.example": LOT,
            "retail.example": RETAIL,
            "regular.example": structured(NAME, 380),
        }
        r = self.estimate(cards, "6", "мешок")
        item = r["items"][0]
        self.assertEqual(item["selected"]["supplier"], "regular.example")
        self.assertEqual(r["goods_total"], "2280")
        quotes = {q["supplier"]: q for q in item["offers"]}
        self.assertFalse(quotes["lot.example"]["fits"])
        self.assertEqual(
            quotes["retail.example"]["source_status"], "needs_confirmation"
        )
        self.assertTrue(any("90 ₽" in q["detail"] for q in r["questions"]))
        self.assertEqual(
            self.estimate({"lot.example": LOT}, "400", "мешок")["goods_total"], "210000"
        )
        self.assertIsNone(
            self.estimate({"retail.example": RETAIL}, "6", "мешок")["goods_total"]
        )
        with self.assertRaises(ValueError):
            extract_product(LOT.replace("210000", "190000"), URL)

    def test_supplier_requires_price_confirmation(self):
        card = (
            structured(NAME, 380)
            + "<p>Цена/наличие/ед.изм./комплектацию уточняйте при подтверждении заказа.</p>"
        )
        result = self.estimate({"shop.example": card}, "6", "мешок")
        self.assertIsNone(result["items"][0]["selected"])
        self.assertEqual(
            result["items"][0]["offers"][0]["source_status"], "needs_confirmation"
        )

    def test_eligible_quantity_and_reference_quantity(self):
        offer = {
            "@type": "Offer",
            "priceCurrency": "RUB",
            "priceSpecification": {
                "@type": "UnitPriceSpecification",
                "price": 210000,
                "referenceQuantity": {"value": 400, "unitCode": "C62"},
                "eligibleQuantity": {"minValue": 400, "unitCode": "C62"},
            },
        }
        card = (
            '<script type="application/ld+json">'
            + json.dumps({"@type": "Product", "name": NAME, "offers": offer})
            + "</script>"
        )
        self.assertIsNone(
            self.estimate({"lot.example": card}, "6", "мешок")["goods_total"]
        )
        self.assertEqual(
            self.estimate({"lot.example": card}, "400", "мешок")["goods_total"],
            "210000",
        )

    def test_catalog_and_search_both_contribute_without_links(self):
        title = "Валик ANZA Elite Титекс 250 мм"
        self.assertEqual(
            relevant_results(
                [{"href": "https://example.org", "title": "Latest news"}], title
            ),
            [],
        )
        registry = registered_links({"name": title}, "Москва", [])
        self.assertEqual(len(registry), 1)
        worker = Agent({"site": "http://127.0.0.1:5173", "worker_secret": "test"})
        worker.update = Mock()
        other = "https://other.example/roller"
        for found in ([], [{"href": other}]):
            with self.subTest(found=found), patch(
                "agent.chat", return_value={"fits": True}
            ), patch("agent.search_web", return_value=found), patch(
                "agent.fetch_page",
                side_effect=lambda url, *a: extract_product(
                    structured(title, 1200 if url == other else 1298), url
                ),
            ) as fetch:
                r = worker.process(
                    {
                        "payload": {
                            **PAYLOAD,
                            "city": "Москва",
                            "text": title + " — 3 шт",
                        }
                    }
                )
                self.assertEqual(r["goods_total"], "3600" if found else "3894")
                self.assertEqual(fetch.call_count, len(found) + 1)

    @patch("sources.fetch_document")
    def test_feed_only_discovers_available_matching_products(self, fetch):
        feed = b'<yml_catalog><shop><offers><offer><name>Test Brand 50</name><url>/good</url></offer><offer available="false"><name>Test Brand 50</name><url>/absent</url></offer><offer><name>Test Brand 25</name><url>/wrong</url></offer></offers></shop></yml_catalog>'
        fetch.return_value = (feed, URL)
        self.assertEqual(
            feed_links(URL, {"name": "Test Brand 50"}),
            ["https://supplier.example/good"],
        )

    def test_per_kilo_price_does_not_become_a_bag_price(self):
        with self.assertRaisesRegex(ValueError, "единицу"):
            extract_product(
                f"<h1>{NAME}</h1><main>10 ₽ / кг</main>" + structured(NAME, 10), URL
            )

    def test_readonly_cart_checks_region_quantity_and_actual_goods_total(self):
        rule = {
            "path": "/quote/{sku}/{region}/{packs}",
            "fields": {
                key: key
                for key in ("sku", "region", "packs", "currency", "goods_total")
            },
        }
        offer = {"price": "380", "cart": (rule, "C/50", "77")}
        record = dict(
            sku="C/50", region="77", packs=6, currency="RUB", goods_total="2280"
        )
        endpoint = "https://supplier.example/quote/C%2F50/77/6"
        fetch = Mock(return_value=(record, endpoint))
        self.assertEqual(confirm_cart(offer, 6, URL, fetch)["cart_goods_total"], "2280")
        fetch.assert_called_once_with(endpoint, URL)
        for changes in (
            {"goods_total": "2700"},
            {"packs": 20},
            {"region": "16"},
            {"currency": "USD"},
        ):
            fetch.return_value = ({**record, **changes}, endpoint)
            self.assertEqual(
                confirm_cart(offer, 6, URL, fetch)["source_status"],
                "needs_confirmation",
            )
