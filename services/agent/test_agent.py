import unittest
from datetime import date, timedelta
from decimal import Decimal
import estimate
import sources


class EstimateTests(unittest.TestCase):
    def quote(self, **kw):
        d = dict(
            id="a",
            supplier="shop.test",
            url="https://shop.test/product",
            fits=True,
            pack_quantity="10",
            pack_price="50",
            unit="шт",
            availability="in_stock",
            stock_quantity=None,
            delivery_date=(date.today() + timedelta(days=1)).isoformat(),
            delivery_cost="100",
            delivery_scope="per_order",
        )
        d.update(kw)
        return d

    def test_round_to_pack(self):
        q = estimate.price_quote(self.quote(), Decimal("25"))
        self.assertEqual(q["purchase_quantity"], "30")
        self.assertEqual(q["goods_total"], "150")
        self.assertEqual(q["unit_price"], "5")

    def test_delivery_not_invented(self):
        r = estimate.build_estimate(
            [
                dict(
                    id="1",
                    name="Саморез",
                    quantity="25",
                    unit="шт",
                    requirements="",
                    offers=[self.quote(delivery_cost=None, delivery_date=None)],
                )
            ],
            {
                "deadline": (date.today() + timedelta(days=5)).isoformat(),
                "budget": None,
            },
            "test",
        )
        self.assertEqual(r["goods_total"], "150")
        self.assertIsNone(r["delivery_total"])
        self.assertFalse(r["complete"])
        self.assertTrue(r["questions"])

    def test_late_cheap_offer_not_selected(self):
        r = estimate.build_estimate(
            [
                dict(
                    id="1",
                    name="Саморез",
                    quantity="25",
                    unit="шт",
                    requirements="",
                    offers=[
                        self.quote(
                            id="late",
                            pack_price="1",
                            delivery_date=(
                                date.today() + timedelta(days=9)
                            ).isoformat(),
                        ),
                        self.quote(id="on-time"),
                    ],
                )
            ],
            {
                "deadline": (date.today() + timedelta(days=5)).isoformat(),
                "budget": None,
            },
            "test",
        )
        self.assertEqual(r["items"][0]["selected"]["id"], "on-time")

    def test_price_evidence_must_exist_on_opened_page(self):
        self.assertFalse(estimate.price_evidenced("99", "99 ₽", "Цена 150 ₽"))
        self.assertTrue(
            estimate.price_evidenced("150", "150 ₽", "Цена 150 ₽ в наличии")
        )

    def test_private_network_not_fetched(self):
        for url in [
            "http://127.0.0.1/a",
            "http://192.168.0.1/a",
            "file:///etc/passwd",
            "http://user:pass@example.com",
        ]:
            with self.subTest(url=url):
                self.assertFalse(sources.public_url(url))

    def test_explicit_material_list_preserves_package_size_and_quantity(self):
        items = estimate.parse_lines(
            "Цемент М500, мешок 50 кг — 6 мешков.\n100 штук саморезов 3,5х35 мм"
        )
        self.assertEqual(items[0]["quantity"], "6")
        self.assertIn("50 кг", items[0]["name"])
        self.assertEqual(items[1]["quantity"], "100")
        self.assertEqual(items[1]["unit"], "шт")

    def test_search_index_price_is_always_preliminary(self):
        q = self.quote(source_status="search_index", stock_quantity="100")
        r = estimate.build_estimate(
            [
                dict(
                    id="1",
                    name="Саморез",
                    quantity="25",
                    unit="шт",
                    requirements="",
                    offers=[q],
                )
            ],
            {
                "deadline": (date.today() + timedelta(days=5)).isoformat(),
                "budget": None,
            },
            "test",
        )
        self.assertFalse(r["complete"])
        self.assertTrue(any("цен" in x["detail"] for x in r["questions"]))

    def test_exact_matching_keeps_brand_and_size_constraints(self):
        self.assertTrue(
            sources.lexical_match(
                "Цемент М500 мешок 50 кг", "Цемент Akkermann M500 50 кг"
            )
        )
        self.assertFalse(
            sources.lexical_match(
                "Штукатурка Кнауф Ротбанд 30 кг", "Штукатурка Волма 30 кг"
            )
        )
        self.assertFalse(
            sources.lexical_match(
                "Саморезы по дереву 3,5х35 мм", "Саморезы по дереву 3.5х55 мм"
            )
        )


if __name__ == "__main__":
    unittest.main()
