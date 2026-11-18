import csv, json, re
from pathlib import Path

src = (
    Path(__file__).resolve().parents[2]
    / "skills/prepare-construction-purchase/assets/demo"
)
out = Path(__file__).parent
text = (src / "task.md").read_text()
policy = json.loads((src / "policy.json").read_text())
assert "Оставшиеся работы" in text and "полные на 12.11.2026" in text
obj, name = re.search(r"Объект ([^:]+): ([^.]+)\.", text).groups()
address = re.search(r"Адрес: ([^.]+)\.", text).group(1)


def iso(s):
    d, m, y = s.split(".")
    return f"{y}-{m}-{d}"


asof, deadline = re.search(
    r"Дата расчёта: (\d{2}\.\d{2}\.\d{4})\. Поставка до (\d{2}\.\d{2}\.\d{4})", text
).groups()
budget = re.search(r"Бюджет: ([\d ]+) ₽", text).group(1).replace(" ", "")


def rows(name):
    with (src / (name + ".csv")).open(encoding="utf-8-sig", newline="") as f:
        rr = list(csv.DictReader(f, delimiter=";"))
    for r in rr:
        for k, v in list(r.items()):
            if k in ("requirements", "specs"):
                r[k] = json.loads(v)
            elif k in ("tax_included", "price_confirmed"):
                r[k] = {"True": True, "False": False}[v]
            elif v == "":
                r[k] = None
    return rr


sources = [
    dict(
        id="task",
        title="Учебное задание",
        locator=str(src / "task.md") + ": строки 5–15",
        demo=True,
    ),
    dict(
        id="policy",
        title="Учебная политика",
        locator=str(src / "policy.json") + ": rules",
        demo=True,
    ),
]
for sid, fn in [
    ("norms", "norms"),
    ("catalog", "materials"),
    ("stock", "inventory"),
    ("orders", "orders"),
    ("usage", "consumption"),
    ("quotes", "offers"),
]:
    loc = str(src / (fn + ".csv")) + ": строки 2–" + str(len(rows(fn)) + 1)
    if sid in ("stock", "orders"):
        loc += (
            "; "
            + str(src / "policy.json")
            + ": "
            + ("inventory_snapshot" if sid == "stock" else "orders_snapshot")
            + "; "
            + str(src / "task.md")
            + ": строки 11–15"
        )
    if sid == "quotes":
        loc += (
            "; "
            + str(src / "suppliers.csv")
            + ": строки 2–4; "
            + str(src / "task.md")
            + ": строки 17–21"
        )
    sources.append(
        dict(id=sid, title="Учебный источник " + sid, locator=loc, demo=True)
    )
data = dict(
    schema_version=1,
    demo=policy["demo"],
    as_of=iso(asof),
    project=dict(
        id=obj,
        name=name,
        address=address,
        delivery_date=iso(deadline),
        budget=budget,
        remaining_scope_confirmed=True,
        source="task",
    ),
    rules=policy["rules"],
    works=rows("works"),
    norms=rows("norms"),
    materials=rows("materials"),
    inventory=dict(policy["inventory_snapshot"], items=rows("inventory")),
    orders=dict(policy["orders_snapshot"], items=rows("orders")),
    consumption=dict(known=True, source="usage", items=rows("consumption")),
    suppliers=rows("suppliers"),
    offers=rows("offers"),
    sources=sources,
)
(out / "input.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
print(
    "Normalized from task.md, policy.json and 8 CSVs; baseline input.json never opened."
)
