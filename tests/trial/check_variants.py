import copy, importlib.util, json, hashlib
from pathlib import Path

root = Path(__file__).parent
script = (
    Path(__file__).resolve().parents[2]
    / "skills/prepare-construction-purchase/scripts/procurement.py"
)
spec = importlib.util.spec_from_file_location("engine", script)
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
base = json.loads((root / "input.json").read_text())
results = []


def run(name, edit, check):
    d = copy.deepcopy(base)
    edit(d)
    try:
        r = e.calculate(d)
        ok = check(r)
        detail = {
            "status": r["status"],
            "total": r["selection"]["total"] if r["selection"] else None,
            "codes": [x["code"] for x in r["deviations"]],
        }
    except Exception as exc:
        ok = False
        detail = {"error": str(exc)}
    results.append(dict(name=name, passed=ok, **detail))


def codes(r):
    return {x["code"] for x in r["deviations"]}


def line(r, mid="plaster"):
    return next(x for x in r["materials"] if x["material_id"] == mid)


run(
    "baseline",
    lambda d: None,
    lambda r: r["selection"]["total"] == "12440"
    and line(r)["net_need"] == "741"
    and line(r, "primer")["purchase_quantity"] == "20",
)
for obj, code in [("inventory", "INVENTORY_UNKNOWN"), ("orders", "ORDERS_UNKNOWN")]:
    run(
        obj + "_unknown",
        lambda d, o=obj: d[o].update(known=False, items=[]),
        lambda r, c=code: r["selection"] is None
        and c in codes(r)
        and line(r)["net_need"] is None,
    )
run(
    "missing_norm",
    lambda d: d["norms"].pop(),
    lambda r: r["selection"] is None and "MISSING_NORM" in codes(r),
)
run(
    "unconfirmed_remaining",
    lambda d: d["project"].update(remaining_scope_confirmed=False),
    lambda r: r["selection"] is None,
)
run(
    "unknown_reserve",
    lambda d: d["rules"].update(reserve_pct=None),
    lambda r: r["selection"] is None and "RESERVE_UNKNOWN" in codes(r),
)
run(
    "unknown_consumption",
    lambda d: d["consumption"].update(known=False, items=[]),
    lambda r: r["selection"] is not None and "CONSUMPTION_UNKNOWN" in codes(r),
)
run(
    "expired_inventory",
    lambda d: d["inventory"].update(as_of="2026-11-09"),
    lambda r: r["selection"] is None and "STALE_INVENTORY" in codes(r),
)
run(
    "unconfirmed_received_in_stock",
    lambda d: d["inventory"].update(includes_received_orders=False),
    lambda r: r["selection"] is None,
)
run(
    "alternate_pack",
    lambda d: d["offers"][2].update(pack_size="40"),
    lambda r: line(r)["purchase_quantity"] == "760" and line(r)["packs"] == 19,
)
run(
    "insufficient_after_pack_rounding",
    lambda d: d["offers"][2].update(available_qty="745"),
    lambda r: "INSUFFICIENT_STOCK" in codes(r)
    and line(r)["selected_offer_id"] != "B-plaster",
)
run(
    "multiple_works_same_material",
    lambda d: d["works"].append(
        dict(id="W3", kind="plaster", quantity="10", unit="m2", source="task")
    ),
    lambda r: line(r)["base_need"] == "1105",
)
run(
    "one_work_multiple_materials",
    lambda d: d["norms"].append(
        dict(
            id="N3",
            work_kind="plaster",
            work_unit="m2",
            material_id="primer",
            rate="0.1",
            material_unit="l",
            source="norms",
        )
    ),
    lambda r: line(r, "primer")["base_need"] == "36",
)
run(
    "decimal_comma",
    lambda d: d["norms"][0].update(rate="8,5"),
    lambda r: line(r)["base_need"] == "1020",
)
run(
    "empty_requirements",
    lambda d: d["materials"][0].update(requirements={}),
    lambda r: r["selection"] is None and "REQUIREMENTS_UNKNOWN" in codes(r),
)


def sources(d):
    d["sources"].append(
        dict(
            id="unique-stock-source",
            title="Stock receipt",
            locator="stock-extra.csv:2",
            demo=True,
        )
    )
    d["inventory"]["items"][0]["source"] = "unique-stock-source"


run(
    "row_source_traceability",
    sources,
    lambda r: "unique-stock-source" in line(r)["sources"],
)
run(
    "price_missing",
    lambda d: d["offers"][2].update(price_per_pack=None),
    lambda r: "PRICE_MISSING" in codes(r)
    and line(r)["selected_offer_id"] != "B-plaster",
)
for val in ["-1", "NaN", "Infinity", True]:
    d = copy.deepcopy(base)
    d["works"][0]["quantity"] = val
    try:
        e.calculate(d)
        passed = False
    except ValueError:
        passed = True
    results.append(dict(name="invalid_number_" + repr(val), passed=passed))
for obj, change in [
    ("stock_unit", lambda d: d["inventory"]["items"][0].update(unit="l")),
    ("conflicting_order", lambda d: d["orders"]["items"][1].update(quantity="301")),
]:
    d = copy.deepcopy(base)
    change(d)
    try:
        e.calculate(d)
        passed = False
    except ValueError:
        passed = True
    results.append(dict(name=obj, passed=passed))
(root / "variants-results.json").write_text(
    json.dumps(
        dict(
            script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(), cases=results
        ),
        ensure_ascii=False,
        indent=2,
    )
)
for x in results:
    print(("PASS" if x["passed"] else "FAIL"), x["name"])
print(f'{sum(x["passed"] for x in results)}/{len(results)} passed')

raise SystemExit(0 if all(row["passed"] for row in results) else 1)
