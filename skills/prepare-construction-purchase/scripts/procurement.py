#!/usr/bin/env python3
"""Traceable construction purchase drafts. Python 3.10+, standard library only."""
import argparse
import csv
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from hashlib import sha256
from html import escape
from itertools import product
import json
from math import prod
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_COMBINATIONS = 50000


def number(value, label, positive=False, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{label}: требуется число, получено {value!r}")
    try:
        result = Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"{label}: неверное число {value!r}") from None
    if (
        not result.is_finite()
        or result < 0
        or result > Decimal("1e15")
        or (positive and result == 0)
    ):
        raise ValueError(
            f"{label}: число должно быть конечным, неотрицательным"
            + (" и больше нуля" if positive else "")
        )
    return result


def decstr(value):
    if value is None:
        return None
    return format(value.normalize(), "f") if value else "0"


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def day(value, label):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label}: требуется дата YYYY-MM-DD") from None


def boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label}: требуется true или false")
    return value


def keyed(rows, label, field="id"):
    if not isinstance(rows, list):
        raise ValueError(f"{label}: требуется список")
    result = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get(field), str)
            or not row[field].strip()
        ):
            raise ValueError(f"{label}: отсутствует строковый {field}")
        key = row[field]
        if key in result:
            raise ValueError(f"{label}: повторяющийся идентификатор {key}")
        result[key] = row
    return result


def http_url(value):
    if not isinstance(value, str):
        return False
    u = urlparse(value)
    return (
        u.scheme in ("http", "https")
        and bool(u.hostname)
        and not u.username
        and not u.password
    )


def calculate(data):
    """Return an auditable draft. Invalid structural inputs raise ValueError."""
    try:
        return _calculate(data)
    except KeyError as error:
        raise ValueError(f"Отсутствует обязательное поле: {error.args[0]}") from None
    except (TypeError, AttributeError) as error:
        raise ValueError(f"Неверная структура входных данных: {error}") from None


def _calculate(data):
    if data["schema_version"] != 1 or type(data["schema_version"]) is not int:
        raise ValueError("Поддерживается schema_version: 1")
    demo = boolean(data["demo"], "demo")
    as_of = day(data["as_of"], "as_of")
    project, rules = data["project"], data["rules"]
    deadline = day(project["delivery_date"], "project.delivery_date")
    if deadline < as_of:
        raise ValueError("Срок поставки предшествует дате расчёта")
    for field in ("id", "name", "address"):
        if not isinstance(project[field], str) or not project[field].strip():
            raise ValueError(f"project.{field}: требуется непустая строка")
    sources = keyed(data["sources"], "sources")
    for s in sources.values():
        if not s.get("title") or not s.get("locator"):
            raise ValueError(f'sources.{s["id"]}: нужны title и locator')
        if boolean(s["demo"], f'sources.{s["id"]}.demo') and not demo:
            raise ValueError("Учебные источники нельзя использовать в реальной заявке")

    def source(row):
        key = row["source"]
        if key not in sources:
            raise ValueError(f"Неизвестный источник {key}")
        return key

    source(project)
    source(rules)
    deviations = []

    def issue(code, message, severity="warning", material_id=None, refs=None):
        deviations.append(
            dict(
                code=code,
                severity=severity,
                message=message,
                material_id=material_id,
                sources=list(dict.fromkeys(refs or [])),
            )
        )

    materials = keyed(data["materials"], "materials")
    works = keyed(data["works"], "works")
    norms = keyed(data["norms"], "norms")
    suppliers = keyed(data["suppliers"], "suppliers")
    offers = keyed(data["offers"], "offers")
    unknown_requirements = set()
    for mid, m in materials.items():
        source(m)
        number(m["pack_size"], f"{mid}.pack_size", positive=True)
        if not isinstance(m["requirements"], dict) or not m["unit"] or not m["name"]:
            raise ValueError(f"{mid}: нужны unit, name, requirements")
        if not m["requirements"] or any(
            v is None or (isinstance(v, str) and not v.strip())
            for v in m["requirements"].values()
        ):
            unknown_requirements.add(mid)
            issue(
                "REQUIREMENTS_UNKNOWN",
                f'Для {m["name"]} не установлены обязательные характеристики.',
                "blocker",
                mid,
                [m["source"]],
            )
    for sid, s in suppliers.items():
        source(s)
        number(s["delivery_cost"], f"{sid}.delivery_cost", nullable=True)
    for n in norms.values():
        source(n)
        if n["material_id"] not in materials:
            raise ValueError(
                f'Норма {n["id"]}: неизвестный материал {n["material_id"]}'
            )
        number(n["rate"], f'{n["id"]}.rate', positive=True)
        if n["material_unit"] != materials[n["material_id"]]["unit"]:
            raise ValueError(f'Норма {n["id"]}: единицы материала не совпадают')
    for key in ("max_quote_age_days", "stock_max_age_days"):
        if type(rules[key]) is not int or not 0 <= rules[key] <= 36500:
            raise ValueError(f"rules.{key}: требуется целое число от 0 до 36500")
    reserve = number(rules["reserve_pct"], "reserve_pct", nullable=True)
    max_reserve = number(rules["max_reserve_pct"], "max_reserve_pct", nullable=True)
    tolerance = number(
        rules["consumption_tolerance_pct"], "consumption_tolerance_pct", nullable=True
    )
    budget = number(project["budget"], "project.budget", nullable=True)
    scope_ok = boolean(
        project["remaining_scope_confirmed"], "remaining_scope_confirmed"
    )
    if not scope_ok:
        issue(
            "SCOPE_UNCONFIRMED",
            "Не подтверждено, что объёмы относятся к оставшимся работам.",
            "blocker",
            refs=[project["source"]],
        )
    if not works:
        issue("NO_WORKS", "Перечень работ пуст.", "blocker", refs=[project["source"]])
        scope_ok = False
    if reserve is None:
        issue(
            "RESERVE_UNKNOWN",
            "Не задан технологический запас; количество к закупке не определено.",
            "blocker",
            refs=[rules["source"]],
        )
    if max_reserve is None:
        issue(
            "RESERVE_LIMIT_UNKNOWN",
            "Не задан допустимый запас компании.",
            refs=[rules["source"]],
        )
    elif reserve is not None and reserve > max_reserve:
        issue(
            "RESERVE_EXCEEDED",
            f"Запас {decstr(reserve)}% превышает лимит {decstr(max_reserve)}%. Требуется согласование.",
            refs=[rules["source"]],
        )
    if budget is None:
        issue(
            "BUDGET_UNKNOWN",
            "Бюджет отсутствует; проверка лимита не выполнена.",
            refs=[project["source"]],
        )

    bases, basis, scope_complete = {}, {}, scope_ok
    for w in works.values():
        source(w)
        q = number(w["quantity"], f'{w["id"]}.quantity')
        matching = [
            n
            for n in norms.values()
            if n["work_kind"] == w["kind"] and n["work_unit"] == w["unit"]
        ]
        if not matching:
            issue(
                "MISSING_NORM",
                f'Для работы {w["id"]} ({w["kind"]}, {w["unit"]}) нет нормы.',
                "blocker",
                refs=[w["source"]],
            )
            scope_complete = False
        seen_materials = set()
        for n in matching:
            mid = n["material_id"]
            if mid in seen_materials:
                raise ValueError(
                    f'Несколько норм для одной работы и материала: {w["id"]}/{mid}; выберите применимую норму'
                )
            seen_materials.add(mid)
            amount = q * number(n["rate"], n["id"])
            bases[mid] = bases.get(mid, ZERO) + amount
            basis.setdefault(mid, []).append(
                dict(
                    work_id=w["id"],
                    norm_id=n["id"],
                    work_quantity=decstr(q),
                    rate=decstr(number(n["rate"], n["id"])),
                    quantity=decstr(amount),
                    sources=[w["source"], n["source"]],
                )
            )

    # A known snapshot is exhaustive for the scoped object/materials; absent rows mean zero.
    inv, orders, usage = data["inventory"], data["orders"], data["consumption"]
    source(inv)
    source(orders)
    source(usage)
    stock_ok = boolean(inv["known"], "inventory.known")
    orders_ok = boolean(orders["known"], "orders.known")
    usage_ok = boolean(usage["known"], "consumption.known")
    if not stock_ok:
        issue(
            "INVENTORY_UNKNOWN",
            "Остатки неизвестны. Нулевой остаток не предполагается.",
            "blocker",
            refs=[inv["source"]],
        )
    if not orders_ok:
        issue(
            "ORDERS_UNKNOWN",
            "Открытые заказы неизвестны. Отсутствие заказов не предполагается.",
            "blocker",
            refs=[orders["source"]],
        )
    for snap, known, name in [
        (inv, stock_ok, "INVENTORY"),
        (orders, orders_ok, "ORDERS"),
    ]:
        if known:
            age = (as_of - day(snap["as_of"], f"{name}.as_of")).days
            if not 0 <= age <= rules["stock_max_age_days"]:
                issue(
                    f"STALE_{name}",
                    "Складской снимок или реестр заказов не актуален на дату расчёта.",
                    "blocker",
                    refs=[snap["source"]],
                )
                if name == "INVENTORY":
                    stock_ok = False
                else:
                    orders_ok = False
    if stock_ok and inv.get("includes_received_orders") is not True:
        issue(
            "STOCK_RECEIPTS_UNCONFIRMED",
            "Не подтверждено, что полученные заказы включены в складской остаток.",
            "blocker",
            refs=[inv["source"], orders["source"]],
        )
        stock_ok = False

    def material_record(row, check_unit=True):
        source(row)
        mid = row["material_id"]
        if mid not in materials:
            raise ValueError(f"Неизвестный материал {mid}")
        if check_unit and row["unit"] != materials[mid]["unit"]:
            raise ValueError(
                f"{mid}: единицы измерения не совпадают; сначала выполните явное преобразование"
            )
        return mid

    stocks, on_order, stock_rows, order_rows = {}, {}, {}, {}
    for row in keyed(inv["items"], "inventory.items").values():
        mid = material_record(row)
        q, reserved = number(row["quantity"], "stock.quantity"), number(
            row["reserved"], "stock.reserved"
        )
        if reserved > q:
            raise ValueError(f"{mid}: резерв превышает складское количество")
        stocks[mid] = stocks.get(mid, ZERO) + q - reserved
        stock_rows.setdefault(mid, []).append(row["id"])
    seen_orders = {}
    for row in orders["items"]:
        mid = material_record(row)
        oid = row["order_line_id"]
        if not isinstance(oid, str) or not oid:
            raise ValueError("order_line_id: требуется непустая строка")
        if oid in seen_orders:
            if row != seen_orders[oid]:
                raise ValueError(f"Противоречивые дубли строки заказа {oid}")
            issue(
                "DUPLICATE_ORDER",
                f"Строка {oid} повторена; учтена один раз.",
                material_id=mid,
                refs=[row["source"]],
            )
            continue
        seen_orders[oid] = row
        q, received = number(row["quantity"], oid), number(row["received"], oid)
        if received > q:
            raise ValueError(f"{oid}: полученное количество превышает заказанное")
        if row["status"] not in ("confirmed", "pending", "cancelled", "closed"):
            raise ValueError(f"{oid}: неизвестный status")
        due = (
            day(row["delivery_date"], f"{oid}.delivery_date")
            if row["delivery_date"]
            else None
        )
        remaining = q - received
        if row["status"] == "confirmed" and remaining > 0:
            if due is None:
                issue(
                    "ORDER_DATE_UNKNOWN",
                    f"У заказа {oid} нет даты поставки; он не уменьшает потребность.",
                    material_id=mid,
                    refs=[row["source"]],
                )
            elif due < as_of:
                issue(
                    "ORDER_OVERDUE",
                    f"Заказ {oid} просрочен; поставку нужно подтвердить, количество не вычтено.",
                    material_id=mid,
                    refs=[row["source"]],
                )
            elif due > deadline:
                issue(
                    "LATE_ORDER",
                    f"Заказ {oid} придёт {due.isoformat()}, позже требуемого срока; не вычтен. Новую закупку нужно увязать с этим заказом.",
                    material_id=mid,
                    refs=[row["source"]],
                )
            else:
                on_order[mid] = on_order.get(mid, ZERO) + remaining
                order_rows.setdefault(mid, []).append(oid)
        elif row["status"] == "pending" and remaining > 0:
            issue(
                "ORDER_UNCONFIRMED",
                f"Заказ {oid} не подтверждён; не вычтен из потребности.",
                material_id=mid,
                refs=[row["source"]],
            )

    if not usage_ok:
        issue(
            "CONSUMPTION_UNKNOWN",
            "Нет данных о выдаче или фактическом расходе; контроль этого отклонения не выполнен.",
            refs=[usage["source"]],
        )
    if tolerance is None:
        issue(
            "CONSUMPTION_LIMIT_UNKNOWN",
            "Нет порога контроля выдачи; сравнение с нормой не выполнено.",
            refs=[rules["source"]],
        )
    issued_totals = {}
    for row in keyed(usage["items"], "consumption.items").values():
        mid = material_record(row)
        issued, completed = number(row["issued"], "issued"), number(
            row["completed_norm_quantity"], "completed_norm_quantity"
        )
        old = issued_totals.get(mid, (ZERO, ZERO))
        issued_totals[mid] = (old[0] + issued, old[1] + completed)
    if usage_ok and tolerance is not None:
        for mid, (issued, completed) in issued_totals.items():
            if issued > completed * (1 + tolerance / 100):
                pct = (
                    decstr(money((issued / completed - 1) * 100)) + "%"
                    if completed
                    else "при нулевой норме"
                )
                issue(
                    "CONSUMPTION_EXCESS",
                    f'Выдача {decstr(issued)} {materials[mid]["unit"]} превышает норму выполненных работ {decstr(completed)} ({pct}). Выдача не доказывает фактический расход: проверьте остаток на участке и возвраты.',
                    material_id=mid,
                    refs=[usage["source"], rules["source"]],
                )

    lines = []
    quantities_known = scope_complete and stock_ok and orders_ok and reserve is not None
    for mid, base in bases.items():
        m = materials[mid]
        gross = base * (1 + reserve / 100) if reserve is not None else None
        stock, ordered = stocks.get(mid, ZERO) if stock_ok else None, (
            on_order.get(mid, ZERO) if orders_ok else None
        )
        net = max(ZERO, gross - stock - ordered) if quantities_known else None
        pack = number(m["pack_size"], mid)
        packs = (
            int((net / pack).to_integral_value(rounding=ROUND_CEILING))
            if net is not None
            else None
        )
        quantity = packs * pack if packs is not None else None
        row_refs = [
            row["source"]
            for row in inv["items"] + orders["items"]
            if row["material_id"] == mid
        ]
        refs = list(
            dict.fromkeys(
                [r for b in basis[mid] for r in b["sources"]]
                + [m["source"], inv["source"], orders["source"], rules["source"]]
                + row_refs
            )
        )
        lines.append(
            dict(
                material_id=mid,
                name=m["name"],
                unit=m["unit"],
                base_need=decstr(base),
                reserve_pct=decstr(reserve),
                reserve_quantity=decstr(gross - base) if gross is not None else None,
                need_with_reserve=decstr(gross),
                available_stock=decstr(stock),
                on_order=decstr(ordered),
                net_need=decstr(net),
                pack_size=decstr(pack),
                packs=packs,
                purchase_quantity=decstr(quantity),
                packaging_surplus=decstr(quantity - net) if net is not None else None,
                basis=basis[mid],
                stock_rows=stock_rows.get(mid, []),
                order_rows=order_rows.get(mid, []),
                sources=refs,
            )
        )

    by_material = {x["material_id"]: x for x in lines}
    candidates, eligible = [], {}
    for offer in offers.values():
        mid = material_record(offer, check_unit=False)
        oid, sid = offer["id"], offer["supplier_id"]
        if sid not in suppliers:
            raise ValueError(f"{oid}: неизвестный поставщик {sid}")
        supplier, m = suppliers[sid], materials[mid]
        reasons = []
        if mid in unknown_requirements:
            reasons.append("REQUIREMENTS_UNKNOWN")

        def reject(code, text):
            reasons.append(code)
            issue(
                code,
                f"{oid}: {text}",
                material_id=mid,
                refs=[offer["source"], supplier["source"]],
            )

        # A quote in another unit is excluded; source stock/norm unit conflicts are structural errors.
        price = number(offer["price_per_pack"], f"{oid}.price_per_pack", nullable=True)
        pack = number(offer["pack_size"], f"{oid}.pack_size", positive=True)
        available = number(
            offer["available_qty"], f"{oid}.available_qty", nullable=True
        )
        delivery = number(
            supplier["delivery_cost"], f"{sid}.delivery_cost", nullable=True
        )
        if price is None:
            reject("PRICE_MISSING", "цена отсутствует")
        if not boolean(offer["price_confirmed"], f"{oid}.price_confirmed"):
            reject("UNCONFIRMED_PRICE", "цена не подтверждена источником")
        checked = (
            day(offer["verified_at"], f"{oid}.verified_at")
            if offer["verified_at"]
            else None
        )
        if (
            checked is None
            or not 0 <= (as_of - checked).days <= rules["max_quote_age_days"]
        ):
            reject("STALE_PRICE", "цена не проверена в допустимый период")
        due = (
            day(offer["delivery_date"], f"{oid}.delivery_date")
            if offer["delivery_date"]
            else None
        )
        if due is None:
            reject("OFFER_DATE_UNKNOWN", "срок поставки неизвестен")
        elif not as_of <= due <= deadline:
            reject("OFFER_LATE", "дата поставки вне допустимого периода")
        if offer["currency"] != "RUB" or offer["tax_included"] is not True:
            reject(
                "PRICE_BASIS_UNKNOWN", "нужна цена в RUB со всеми применимыми налогами"
            )
        if offer["unit"] != m["unit"]:
            reject("OFFER_UNIT_MISMATCH", "единицы предложения отличаются от каталога")
        if not isinstance(offer["specs"], dict):
            raise ValueError(f"{oid}.specs: требуется объект")
        if any(
            k not in offer["specs"] or offer["specs"][k] != v
            for k, v in m["requirements"].items()
        ):
            reject(
                "SPEC_MISMATCH",
                "обязательные характеристики не подтверждены или не совпадают",
            )
        if delivery is None:
            reject("DELIVERY_COST_UNKNOWN", "стоимость доставки неизвестна")
        if offer["product_url"] is not None and not http_url(offer["product_url"]):
            reject("PRODUCT_LINK_INVALID", "недопустимая ссылка на товар")
        elif not demo and not offer["product_url"]:
            reject(
                "PRODUCT_LINK_MISSING",
                "для реального предложения нужна проверенная ссылка на товар",
            )
        line = by_material.get(mid)
        net = (
            number(line["net_need"], "net_need", nullable=True)
            if line and offer["unit"] == m["unit"]
            else None
        )
        offer_packs = (
            int((net / pack).to_integral_value(rounding=ROUND_CEILING))
            if net is not None
            else None
        )
        buy = offer_packs * pack if offer_packs is not None else None
        if available is None:
            reject("AVAILABILITY_UNKNOWN", "наличие не подтверждено")
        elif buy is not None and available < buy:
            reject(
                "INSUFFICIENT_STOCK",
                "наличия недостаточно для закупки целыми упаковками",
            )
        total = (
            money(price * offer_packs)
            if price is not None and offer_packs is not None
            else None
        )
        item = dict(
            offer_id=oid,
            material_id=mid,
            supplier_id=sid,
            supplier_name=supplier["name"],
            product_name=offer["product_name"],
            product_url=offer["product_url"],
            unit=offer["unit"],
            pack_size=decstr(pack),
            packs=offer_packs,
            purchase_quantity=decstr(buy),
            packaging_surplus=decstr(buy - net) if buy is not None else None,
            price_per_pack=decstr(price),
            price_per_unit=decstr(price / pack) if price is not None else None,
            goods_total=decstr(total),
            supplier_delivery_cost=decstr(delivery),
            available_qty=decstr(available),
            delivery_date=offer["delivery_date"],
            verified_at=offer["verified_at"],
            eligible=not reasons and net is not None and net > 0,
            rejection_codes=reasons,
            sources=list(dict.fromkeys([offer["source"], supplier["source"]])),
        )
        candidates.append(item)
        if item["eligible"]:
            eligible.setdefault(mid, []).append(item)

    selection, baskets = None, []
    if quantities_known:
        needed = [
            x["material_id"] for x in lines if number(x["net_need"], "net_need") > 0
        ]
        missing = [mid for mid in needed if not eligible.get(mid)]
        for mid in missing:
            issue(
                "NO_ELIGIBLE_OFFER",
                f'Для {materials[mid]["name"]} нет полностью проверенного предложения.',
                "blocker",
                mid,
                [materials[mid]["source"]],
            )
        combinations = prod(len(eligible[mid]) for mid in needed) if not missing else 0
        if combinations > MAX_COMBINATIONS:
            issue(
                "COMPARISON_LIMIT",
                f"Вариантов корзины {combinations}; предел точного перебора {MAX_COMBINATIONS}. Сузьте предложения.",
                "blocker",
            )
        elif not missing:
            for items in product(*(eligible[mid] for mid in needed)):
                sids = sorted({x["supplier_id"] for x in items})
                goods_total = sum(
                    (number(x["goods_total"], "goods_total") for x in items), ZERO
                )
                delivery_total = sum(
                    (number(suppliers[sid]["delivery_cost"], sid) for sid in sids), ZERO
                )
                baskets.append(
                    dict(
                        items=list(items),
                        supplier_ids=sids,
                        goods_total=decstr(goods_total),
                        delivery_total=decstr(delivery_total),
                        total=decstr(money(goods_total + delivery_total)),
                    )
                )
            baskets.sort(
                key=lambda b: (
                    number(b["total"], "total"),
                    len(b["supplier_ids"]),
                    "|".join(x["offer_id"] for x in b["items"]),
                )
            )
            selection = baskets[0]
            selection["reason"] = (
                "Минимальная полная стоимость среди проверенных предложений; доставка учтена один раз на поставщика. При равной стоимости выбран вариант с меньшим числом поставщиков."
            )
            if budget is not None and number(selection["total"], "total") > budget:
                issue(
                    "BUDGET_EXCEEDED",
                    f'Корзина превышает бюджет на {decstr(number(selection["total"], "total")-budget)} ₽. Требуется согласование.',
                    refs=[project["source"]],
                )
    if demo:
        issue(
            "DEMO_DATA",
            "Учебный пример: нормы, поставщики, цены и наличие вымышлены. Для реальной закупки замените весь комплект источников.",
            "info",
            refs=list(sources),
        )
    chosen = {x["material_id"]: x for x in selection["items"]} if selection else {}
    for line in lines:
        line["selected_offer_id"] = chosen.get(line["material_id"], {}).get("offer_id")
        if line["material_id"] in chosen:
            line["sources"] = list(
                dict.fromkeys(line["sources"] + chosen[line["material_id"]]["sources"])
            )
            # Supplier packaging may differ from catalog; chosen quantities govern the purchase draft.
            for field in (
                "pack_size",
                "packs",
                "purchase_quantity",
                "packaging_surplus",
            ):
                line[field] = chosen[line["material_id"]][field]
    status = (
        "incomplete"
        if selection is None
        else (
            "review_required"
            if any(x["severity"] != "info" for x in deviations)
            else "draft_ready"
        )
    )
    return dict(
        schema_version=1,
        demo=demo,
        as_of=as_of.isoformat(),
        project=project,
        rules=rules,
        status=status,
        approval_status="draft",
        input_sha256=sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        materials=lines,
        offers=candidates,
        selection=selection,
        basket_comparison=[
            {k: v for k, v in b.items() if k != "items"}
            | {"offer_ids": [x["offer_id"] for x in b["items"]]}
            for b in baskets[:10]
        ],
        baskets_evaluated=len(baskets),
        deviations=deviations,
        sources=list(sources.values()),
        budget=decstr(budget),
        budget_delta=(
            decstr(number(selection["total"], "total") - budget)
            if selection is not None and budget is not None
            else None
        ),
    )


def display(value):
    if value is None:
        return "Нет данных"
    return str(value)


def csv_safe(value):
    text = display(value)
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
        else text
    )


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers)
        for row in rows:
            writer.writerow([csv_safe(x) for x in row])


def export_report(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    chosen = (
        {x["material_id"]: x for x in result["selection"]["items"]}
        if result["selection"]
        else {}
    )
    write_csv(
        output / "materials.csv",
        [
            "Материал",
            "Ед.",
            "По норме",
            "Запас, %",
            "С запасом",
            "Свободный остаток",
            "В заказах к сроку",
            "Дефицит",
            "Размер упаковки",
            "Упаковок",
            "К закупке",
            "Излишек округления",
            "Поставщик",
            "Цена упаковки, ₽",
            "Сумма товара, ₽",
            "Ссылка",
            "Источники",
        ],
        [
            [
                x["name"],
                x["unit"],
                x["base_need"],
                x["reserve_pct"],
                x["need_with_reserve"],
                x["available_stock"],
                x["on_order"],
                x["net_need"],
                x["pack_size"],
                x["packs"],
                x["purchase_quantity"],
                x["packaging_surplus"],
                chosen.get(x["material_id"], {}).get("supplier_name"),
                chosen.get(x["material_id"], {}).get("price_per_pack"),
                chosen.get(x["material_id"], {}).get("goods_total"),
                chosen.get(x["material_id"], {}).get("product_url"),
                ", ".join(x["sources"]),
            ]
            for x in result["materials"]
        ],
    )
    write_csv(
        output / "offers.csv",
        [
            "Предложение",
            "Материал",
            "Поставщик",
            "Размер упаковки",
            "Цена упаковки, ₽",
            "Цена за единицу, ₽",
            "Упаковок",
            "Сумма товара, ₽",
            "Доставка поставщика, ₽ (один раз)",
            "Дата поставки",
            "Дата проверки",
            "Допущено",
            "Причины исключения",
            "Ссылка",
            "Источники",
        ],
        [
            [
                x[k]
                for k in [
                    "offer_id",
                    "material_id",
                    "supplier_name",
                    "pack_size",
                    "price_per_pack",
                    "price_per_unit",
                    "packs",
                    "goods_total",
                    "supplier_delivery_cost",
                    "delivery_date",
                    "verified_at",
                    "eligible",
                ]
            ]
            + [
                ", ".join(x["rejection_codes"]),
                x["product_url"],
                ", ".join(x["sources"]),
            ]
            for x in result["offers"]
        ],
    )
    write_csv(
        output / "deviations.csv",
        ["Код", "Важность", "Материал", "Замечание", "Источники"],
        [
            [
                x["code"],
                x["severity"],
                x["material_id"],
                x["message"],
                ", ".join(x["sources"]),
            ]
            for x in result["deviations"]
        ],
    )
    write_csv(
        output / "sources.csv",
        ["ID", "Источник", "Расположение", "Учебный"],
        [[s["id"], s["title"], s["locator"], s["demo"]] for s in result["sources"]],
    )
    (output / "report.html").write_text(render_html(result), encoding="utf-8")


def render_html(r):
    e = lambda v: escape(display(v), quote=True)
    fmt = lambda v: (
        "Нет данных"
        if v is None
        else f"{Decimal(v):,.2f}".replace(",", "\u202f")
        .replace(".", ",")
        .removesuffix(",00")
    )
    sel = r["selection"]
    chosen = {x["material_id"]: x for x in sel["items"]} if sel else {}
    rows = ""
    for x in r["materials"]:
        basis = "<br>".join(
            f'{e(b["work_id"])}: {e(b["work_quantity"])} × {e(b["rate"])} = {e(b["quantity"])} · {e(b["norm_id"])}'
            for b in x["basis"]
        )
        o = chosen.get(x["material_id"], {})
        rows += f'<tr><td><strong>{e(x["name"])}</strong><small>{e(x["material_id"])} · {e(x["unit"])}</small></td><td>{fmt(x["base_need"])}</td><td>{fmt(x["need_with_reserve"])}</td><td>{fmt(x["available_stock"])}</td><td>{fmt(x["on_order"])}</td><td>{fmt(x["net_need"])}</td><td><strong>{fmt(x["purchase_quantity"])}</strong><small>{e(x["packs"])} уп. × {fmt(x["pack_size"])}</small></td><td>{e(o.get("supplier_name"))}<small>{fmt(o.get("goods_total"))} ₽</small></td></tr>'
        rows += f'<tr class="basis"><td colspan="8"><details><summary>Основание расчёта и источники</summary><p>{basis}</p><p>С запасом: {fmt(x["base_need"])} × (1 + {fmt(x["reserve_pct"])} / 100) = {fmt(x["need_with_reserve"])}. Дефицит: max(0; с запасом − свободный остаток − заказы к сроку). Закупка округлена вверх до упаковки выбранного предложения; излишек округления: {fmt(x["packaging_surplus"])} {e(x["unit"])}.</p><p>Строки склада: {e(", ".join(x["stock_rows"]) or "нет")}. Строки заказов: {e(", ".join(x["order_rows"]) or "нет")}.</p><p>Источники: {e(", ".join(x["sources"]))}</p></details></td></tr>'
    offers = ""
    for x in r["offers"]:
        url = x["product_url"]
        link = (
            f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">Открыть товар ↗</a>'
            if http_url(url)
            else '<span class="muted">Учебный товар · ссылки нет</span>'
        )
        picked = x["offer_id"] in {v["offer_id"] for v in chosen.values()}
        badge = (
            "Выбрано" if picked else ("Допущено" if x["eligible"] else "Нужна проверка")
        )
        offers += f'<tr><td><strong>{e(x["supplier_name"])}</strong><small>{e(x["offer_id"])} · {e(x["product_name"])}</small>{link}</td><td>{fmt(x["price_per_pack"])} ₽<small>упаковка {fmt(x["pack_size"])} {e(x["unit"])}</small></td><td>{fmt(x["goods_total"])} ₽</td><td>{fmt(x["supplier_delivery_cost"])} ₽<small>один раз на поставщика</small></td><td>{e(x["delivery_date"])}<small>проверено {e(x["verified_at"])}</small></td><td><span class="pill {"green" if picked else ""}">{badge}</span><small>{e(", ".join(x["rejection_codes"])) if x["rejection_codes"] else ""}</small></td></tr>'
    issues = "".join(
        f'<article class="issue {e(x["severity"])}"><span class="dot"></span><div><strong>{e(x["code"])}</strong><p>{e(x["message"])}</p><small>Источники: {e(", ".join(x["sources"]) or "проверка всего расчёта")}</small></div></article>'
        for x in r["deviations"]
    )
    sources = "".join(
        f'<tr><td>{e(s["id"])}</td><td>{e(s["title"])}</td><td>{e(s["locator"])}</td><td>{"Учебный" if s["demo"] else "Рабочий"}</td></tr>'
        for s in r["sources"]
    )
    baskets = "".join(
        f'<tr><td>{i+1:02}</td><td>{e(", ".join(b["offer_ids"]))}</td><td>{fmt(b["goods_total"])} ₽</td><td>{fmt(b["delivery_total"])} ₽</td><td><strong>{fmt(b["total"])} ₽</strong></td></tr>'
        for i, b in enumerate(r["basket_comparison"])
    )
    status = {
        "incomplete": "Не хватает данных",
        "review_required": "Требует проверки",
        "draft_ready": "Проект подготовлен",
    }[r["status"]]
    demo_note = (
        '<div class="notice"><strong>Учебный прогон</strong><span>Все нормы, поставщики, цены и наличие вымышлены. Этот отчёт показывает работу метода и не предназначен для закупки.</span></div>'
        if r["demo"]
        else ""
    )
    total = fmt(sel["total"]) + " ₽" if sel else "Не определена"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Основа · проект закупочной заявки</title><style>
    :root{{--ink:#292d28;--muted:#7d8077;--line:#eae9e2;--sand:#f5f2e9;--accent:#bca885;--green:#61745d}}*{{box-sizing:border-box}}body{{margin:0;background:#fcfcfa;color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}header{{height:82px;border-bottom:1px solid var(--line);background:white;display:flex;align-items:center;justify-content:space-between;padding:0 5vw}}.brand{{font-size:26px;font-weight:650;letter-spacing:-1.3px}}.brand i{{display:inline-block;width:22px;height:23px;border:5px solid var(--accent);border-bottom:0;margin-right:10px}}.muted,small{{color:var(--muted)}}small{{display:block;font-size:11px;margin-top:5px}}main{{max-width:1350px;margin:auto;padding:46px 5vw 70px}}.eyebrow{{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted)}}h1{{font-size:38px;letter-spacing:-1.4px;line-height:1.2;font-weight:500;margin:15px 0}}h2{{font-size:21px;font-weight:500;letter-spacing:-.4px;margin:0 0 6px}}.hero{{display:flex;justify-content:space-between;gap:20px;align-items:center}}.pill{{display:inline-block;padding:6px 11px;border:1px solid #e5ddcb;background:#faf7ef;border-radius:30px;font-size:11px;white-space:nowrap}}.green{{color:#53674d;background:#edf2eb;border-color:#e2e9df}}.notice{{background:var(--sand);padding:17px 22px;border-radius:9px;display:flex;gap:22px;margin:26px 0 24px;font-size:12px}}.notice strong{{white-space:nowrap}}.metrics{{display:grid;grid-template-columns:1.2fr 1fr 1fr 1fr;gap:12px;margin:22px 0 32px}}.metric{{border:1px solid var(--line);border-radius:10px;background:white;padding:21px}}.metric:first-child{{background:var(--sand);border-color:var(--sand)}}.metric b{{font-weight:500;font-size:25px;display:block;margin-top:9px;letter-spacing:-.7px}}nav{{display:flex;gap:25px;border-bottom:1px solid var(--line);margin-bottom:24px;overflow:auto}}nav a{{color:var(--muted);text-decoration:none;padding:12px 0;white-space:nowrap;border-bottom:2px solid transparent}}nav a.active{{color:var(--ink);border-color:var(--accent)}}section{{background:white;border:1px solid var(--line);border-radius:12px;margin-bottom:23px;overflow:hidden;scroll-margin-top:20px}}.section-head{{padding:24px 25px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px}}.tablewrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;text-align:left;font-size:12px}}th{{font-weight:500;color:var(--muted);font-size:10px;letter-spacing:.4px;text-transform:uppercase;background:#fafaf7;padding:13px 18px;white-space:nowrap}}td{{padding:18px;border-bottom:1px solid #f0f0e9;vertical-align:top}}td strong{{font-weight:550}}.basis td{{padding-top:0;font-size:11px;color:var(--muted)}}details{{max-width:1000px}}summary{{cursor:pointer;color:#8b795d}}.issue{{display:flex;gap:12px;padding:20px 25px;border-top:1px solid var(--line)}}.issue strong{{font-size:11px;letter-spacing:.5px}}.issue p{{margin:5px 0;max-width:950px}}.dot{{width:7px;height:7px;min-width:7px;border-radius:50%;background:#b49b70;margin-top:6px}}.blocker .dot{{background:#b47761}}.info .dot{{background:#7e9477}}.footer{{font-size:11px;color:var(--muted);margin-top:30px}}.footnote{{padding:0 25px 22px;color:var(--muted);font-size:12px}}button{{padding:9px 14px;border:1px solid var(--line);border-radius:6px;background:white;color:var(--ink);cursor:pointer}}a{{color:#8b795d;text-decoration:none}}.mobile{{display:none}}@media(max-width:760px){{main{{padding:28px 20px}}header{{padding:0 20px;height:68px}}h1{{font-size:29px}}.hero{{display:block}}.hero .pill{{margin-top:10px}}.metrics{{grid-template-columns:1fr 1fr}}.metric{{padding:16px}}.metric b{{font-size:22px}}.notice{{display:block}}.notice span{{display:block;margin-top:6px}}td{{padding:14px}}.desktop{{display:none}}.section-head{{padding:20px}}}}@media print{{header button,nav{{display:none}}body,main{{background:white}}main{{padding:18px;max-width:none}}section{{break-inside:auto}}tr,.issue{{break-inside:avoid}}.metrics{{grid-template-columns:repeat(4,1fr)}}details{{display:block}}}}
    </style></head><body><header><div class="brand"><i></i>основа<span class="muted" style="font-size:12px;font-weight:400;letter-spacing:0;margin-left:20px">снабжение объектов</span></div><div><span class="desktop muted" style="margin-right:20px">Проект заявки · {e(r['project']['id'])}</span><button onclick="window.print()">Печать / PDF ↗</button></div></header><main>
    <div class="eyebrow">Работы → материалы → закупка</div><div class="hero"><div><h1>Проект закупочной заявки</h1><div class="muted">{e(r['project']['name'])} · {e(r['project']['address'])}</div></div><span class="pill">{status}</span></div>{demo_note}
    <div class="metrics"><div class="metric"><span class="muted">Стоимость с доставкой</span><b>{total}</b></div><div class="metric"><span class="muted">Бюджет объекта</span><b>{fmt(r['budget'])} ₽</b><small>Отклонение: {fmt(r['budget_delta'])} ₽</small></div><div class="metric"><span class="muted">Поставка до</span><b>{e(r['project']['delivery_date'])}</b><small>Дата расчёта: {e(r['as_of'])}</small></div><div class="metric"><span class="muted">Замечания к проверке</span><b>{len([x for x in r['deviations'] if x['severity'] != 'info'])}</b><small>Статус согласования: черновик</small></div></div>
    <nav aria-label="Разделы отчёта"><a class="active" href="#materials">01 · Расчёт материалов</a><a href="#offers">02 · Предложения</a><a href="#deviations">03 · Отклонения</a><a href="#sources">04 · Источники</a></nav>
    <section id="materials"><div class="section-head"><div><h2>Материалы к закупке</h2><span class="muted">Потребность по оставшимся работам с учётом склада и заказов</span></div><span class="pill">{len(r['materials'])} позиции</span></div><div class="tablewrap"><table><thead><tr><th>Материал</th><th>По норме</th><th>С запасом</th><th>На складе</th><th>В заказах</th><th>Дефицит</th><th>К закупке</th><th>Выбор</th></tr></thead><tbody>{rows}</tbody></table></div><p class="footnote">{e(sel['reason']) if sel else 'Полная корзина не определена. Проверьте блокирующие замечания: частичный расчёт не считается готовой заявкой.'}</p></section>
    <section id="offers"><div class="section-head"><div><h2>Предложения поставщиков</h2><span class="muted">Проверка характеристик, цены, наличия и срока поставки</span></div></div><div class="tablewrap"><table><thead><tr><th>Поставщик и товар</th><th>Цена упаковки</th><th>Сумма товаров</th><th>Доставка</th><th>Срок / проверка</th><th>Результат</th></tr></thead><tbody>{offers}</tbody></table></div></section>
    <section><div class="section-head"><div><h2>Сравнение полных корзин</h2><span class="muted">Проверено вариантов: {r['baskets_evaluated']}. Показано до десяти лучших</span></div></div><div class="tablewrap"><table><thead><tr><th>№</th><th>Предложения</th><th>Товары</th><th>Доставка</th><th>Всего</th></tr></thead><tbody>{baskets}</tbody></table></div></section>
    <section id="deviations"><div class="section-head"><div><h2>Отклонения и недостающие данные</h2><span class="muted">Замечания сохраняются вместе с проектом заявки</span></div></div>{issues or '<p class="footnote">Замечаний по выполненным проверкам нет.</p>'}</section>
    <section id="sources"><div class="section-head"><div><h2>Источники и основания</h2><span class="muted">Идентификаторы связывают расчёт с исходными данными</span></div></div><div class="tablewrap"><table><thead><tr><th>ID</th><th>Источник</th><th>Расположение</th><th>Тип</th></tr></thead><tbody>{sources}</tbody></table></div></section>
    <div class="footer">Проект требует проверки ответственным сотрудником. Заказы не оформлялись.<br>Суммы в RUB с применимыми налогами. Доставка по каждому поставщику относится ко всей корзине на один адрес и срок.<br>SHA-256 исходных данных: {e(r['input_sha256'])}<br>Для изменения исходных данных и пересчёта запустите скилл повторно.</div></main><script>document.querySelectorAll('nav a').forEach(a=>a.addEventListener('click',()=>{{document.querySelectorAll('nav a').forEach(x=>x.classList.remove('active'));a.classList.add('active')}}));</script></body></html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Подготовка проверяемого проекта строительной закупки"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Скопировать учебный комплект в рабочую папку")
    demo.add_argument("--output-dir", type=Path, required=True)
    run = sub.add_parser("run", help="Рассчитать заявку из нормализованного JSON")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "demo":
        if args.output_dir.exists() and any(args.output_dir.iterdir()):
            parser.error("Учебный комплект копируется только в новую или пустую папку")
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "assets/demo",
            args.output_dir,
            dirs_exist_ok=True,
        )
        print(
            json.dumps(
                {
                    "demo_input": str(args.output_dir / "input.json"),
                    "warning": "Только учебные данные",
                },
                ensure_ascii=False,
            )
        )
        return 0
    try:
        data = json.loads(args.input.read_text(encoding="utf-8-sig"), parse_float=str)
        result = calculate(data)
        if args.output_dir.resolve() == args.input.parent.resolve():
            raise ValueError(
                "Папка результата должна отличаться от папки исходных данных"
            )
        export_report(result, args.output_dir)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "demo": result["demo"],
                    "total": (
                        result["selection"]["total"] if result["selection"] else None
                    ),
                    "deviations": len(result["deviations"]),
                    "report": str(args.output_dir / "report.html"),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (ValueError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
