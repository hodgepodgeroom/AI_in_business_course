import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "procurement", ROOT / "scripts/procurement.py"
)
engine = importlib.util.module_from_spec(SPEC)
if SPEC.loader and (ROOT / "scripts/procurement.py").exists():
    SPEC.loader.exec_module(engine)


class ProcurementTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "assets/demo/input.json").read_text())

    def run_case(self):
        self.assertTrue(
            hasattr(engine, "calculate"),
            "The reusable calculation engine is not implemented",
        )
        return engine.calculate(self.data)

    def line(self, result, mid="plaster"):
        return next(x for x in result["materials"] if x["material_id"] == mid)

    def codes(self, result):
        return {x["code"] for x in result["deviations"]}

    def test_remaining_scope_stock_reservations_and_pack_rounding(self):
        r = self.run_case()
        p = self.line(r)
        self.assertEqual(p["base_need"], "1020")
        self.assertEqual(p["need_with_reserve"], "1071")
        self.assertEqual(p["available_stock"], "90")
        self.assertEqual(p["on_order"], "240")
        self.assertEqual(p["net_need"], "741")
        self.assertEqual(p["purchase_quantity"], "750")
        self.assertEqual(p["packs"], 25)
        self.assertEqual(self.line(r, "primer")["purchase_quantity"], "20")

    def test_basket_uses_delivery_once_per_supplier(self):
        r = self.run_case()
        self.assertEqual(r["selection"]["total"], "12440")
        self.assertEqual(r["selection"]["goods_total"], "11940")
        self.assertEqual(r["selection"]["delivery_total"], "500")
        self.assertEqual(r["selection"]["supplier_ids"], ["B"])
        self.assertIn("BUDGET_EXCEEDED", self.codes(r))

    def test_duplicate_orders_late_orders_consumption_and_unconfirmed_price(self):
        r = self.run_case()
        self.assertTrue(
            {
                "DUPLICATE_ORDER",
                "LATE_ORDER",
                "CONSUMPTION_EXCESS",
                "UNCONFIRMED_PRICE",
                "DELIVERY_COST_UNKNOWN",
            }
            <= self.codes(r)
        )
        self.assertEqual(self.line(r)["on_order"], "240")

    def test_unknown_inventory_is_not_zero(self):
        self.data["inventory"]["known"] = False
        r = self.run_case()
        self.assertIsNone(self.line(r)["purchase_quantity"])
        self.assertIsNone(r["selection"])
        self.assertIn("INVENTORY_UNKNOWN", self.codes(r))

    def test_unknown_orders_is_not_zero(self):
        self.data["orders"]["known"] = False
        r = self.run_case()
        self.assertIsNone(self.line(r)["net_need"])
        self.assertIsNone(r["selection"])

    def test_stale_inventory_blocks_recommendation(self):
        self.data["inventory"]["as_of"] = "2026-10-01"
        r = self.run_case()
        self.assertIsNone(r["selection"])
        self.assertIn("STALE_INVENTORY", self.codes(r))

    def test_missing_norm_blocks_complete_recommendation(self):
        self.data["works"].append(
            {
                "id": "W3",
                "kind": "unknown",
                "quantity": "10",
                "unit": "m2",
                "source": "task",
            }
        )
        r = self.run_case()
        self.assertIn("MISSING_NORM", self.codes(r))
        self.assertIsNone(r["selection"])

    def test_conflicting_duplicate_order_is_rejected(self):
        self.data["orders"]["items"][1]["quantity"] = "301"
        with self.assertRaisesRegex(ValueError, "O1"):
            self.run_case()

    def test_negative_and_nonfinite_inputs_rejected(self):
        for v in ["-1", "NaN", "Infinity", True]:
            with self.subTest(v=v):
                self.data["works"][0]["quantity"] = v
                with self.assertRaises(ValueError):
                    self.run_case()

    def test_unknown_source_is_rejected(self):
        self.data["works"][0]["source"] = "fabricated"
        with self.assertRaisesRegex(ValueError, "fabricated"):
            self.run_case()

    def test_offer_units_specs_dates_and_price_are_checked(self):
        for change, code in [
            ({"unit": "l"}, "OFFER_UNIT_MISMATCH"),
            ({"specs": {"type": "cement"}}, "SPEC_MISMATCH"),
            ({"verified_at": "2026-10-01"}, "STALE_PRICE"),
            ({"delivery_date": "2026-11-25"}, "OFFER_LATE"),
            ({"price_per_pack": None}, "PRICE_MISSING"),
        ]:
            with self.subTest(change=change):
                d = copy.deepcopy(self.data)
                d["offers"][2].update(change)
                r = engine.calculate(d)
                self.assertIn(code, self.codes(r))
                self.assertNotIn(
                    "B-plaster",
                    [x["offer_id"] for x in (r["selection"] or {}).get("items", [])],
                )

    def test_missing_required_attribute_is_not_accepted(self):
        self.data["offers"][2]["specs"] = {}
        r = self.run_case()
        self.assertIn("SPEC_MISMATCH", self.codes(r))

    def test_zero_need_does_not_require_supplier(self):
        self.data["inventory"]["items"][0]["quantity"] = "5000"
        self.data["inventory"]["items"][1]["quantity"] = "500"
        self.data["offers"] = []
        r = self.run_case()
        self.assertEqual(r["selection"]["total"], "0")
        self.assertEqual(r["selection"]["items"], [])

    def test_missing_offer_does_not_look_like_complete_subtotal(self):
        self.data["offers"] = [
            o for o in self.data["offers"] if o["material_id"] == "plaster"
        ]
        r = self.run_case()
        self.assertIsNone(r["selection"])
        self.assertIn("NO_ELIGIBLE_OFFER", self.codes(r))

    def test_actuals_not_subtracted_from_remaining_scope(self):
        before = self.run_case()
        self.data["consumption"]["items"][0]["issued"] = "10000"
        after = self.run_case()
        self.assertEqual(
            self.line(before)["purchase_quantity"],
            self.line(after)["purchase_quantity"],
        )

    def test_scope_must_explicitly_be_remaining(self):
        self.data["project"]["remaining_scope_confirmed"] = False
        r = self.run_case()
        self.assertIsNone(r["selection"])
        self.assertIn("SCOPE_UNCONFIRMED", self.codes(r))

    def test_missing_real_product_link_excluded(self):
        self.data["demo"] = False
        for s in self.data["sources"]:
            s["demo"] = False
        r = self.run_case()
        self.assertIsNone(r["selection"])
        self.assertIn("PRODUCT_LINK_MISSING", self.codes(r))

    def test_reserve_above_policy_flagged(self):
        self.data["rules"]["reserve_pct"] = "12"
        r = self.run_case()
        self.assertIn("RESERVE_EXCEEDED", self.codes(r))

    def test_selected_supplier_packaging_governs_purchase_quantity(self):
        self.data["offers"][2]["pack_size"] = "40"
        self.data["offers"][2]["price_per_pack"] = "420"
        r = self.run_case()
        self.assertEqual(self.line(r)["purchase_quantity"], "760")
        self.assertEqual(self.line(r)["packs"], 19)
        self.assertEqual(self.line(r)["pack_size"], "40")

    def test_received_orders_must_be_in_inventory_snapshot(self):
        self.data["inventory"]["includes_received_orders"] = False
        r = self.run_case()
        self.assertIsNone(r["selection"])
        self.assertIn("STOCK_RECEIPTS_UNCONFIRMED", self.codes(r))

    def test_future_quote_not_treated_as_verified_today(self):
        self.data["offers"][2]["verified_at"] = "2026-11-13"
        r = self.run_case()
        self.assertIn("STALE_PRICE", self.codes(r))

    def test_empty_requirements_do_not_confirm_suitability(self):
        self.data["materials"][0]["requirements"] = {}
        r = self.run_case()
        self.assertIsNone(r["selection"])
        self.assertIn("REQUIREMENTS_UNKNOWN", self.codes(r))

    def test_null_or_blank_required_attribute_is_unknown(self):
        for value in (None, "", "  "):
            with self.subTest(value=value):
                self.data["materials"][0]["requirements"] = {"type": value}
                for offer in self.data["offers"]:
                    if offer["material_id"] == "plaster":
                        offer["specs"] = {}
                r = self.run_case()
                self.assertIsNone(r["selection"])
                self.assertIn("REQUIREMENTS_UNKNOWN", self.codes(r))

    def test_csv_contains_line_level_source_provenance(self):
        self.data["sources"].append(
            {
                "id": "warehouse-row",
                "title": "Separate receipt",
                "locator": "stock.csv#S1",
                "demo": True,
            }
        )
        self.data["inventory"]["items"][0]["source"] = "warehouse-row"
        r = self.run_case()
        self.assertIn("warehouse-row", self.line(r)["sources"])

    def test_exports_escape_untrusted_text_and_include_sources(self):
        self.data["project"]["name"] = "<script>alert(1)</script>"
        self.data["materials"][0]["name"] = "=2+2"
        r = self.run_case()
        with tempfile.TemporaryDirectory() as tmp:
            engine.export_report(r, Path(tmp))
            page = (Path(tmp) / "report.html").read_text()
            self.assertNotIn("<script>alert(1)</script>", page)
            self.assertIn("&lt;script&gt;", page)
            csv = (Path(tmp) / "materials.csv").read_text(encoding="utf-8-sig")
            self.assertIn("'=2+2", csv)
            self.assertTrue((Path(tmp) / "offers.csv").exists())
            self.assertTrue((Path(tmp) / "deviations.csv").exists())
            saved = json.loads((Path(tmp) / "result.json").read_text())
            self.assertEqual(saved["selection"]["total"], "12440")
            self.assertTrue(saved["input_sha256"])
            self.assertEqual(len(saved["sources"]), 8)


if __name__ == "__main__":
    unittest.main()
