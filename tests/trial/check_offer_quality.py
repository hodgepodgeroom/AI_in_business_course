"""Run reference purchase requests through Agent.process and the local Qwen server."""

import argparse
from contextlib import ExitStack
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services/agent"))
from agent import Agent
from estimate import dec

CARDS = json.loads(
    Path(__file__).with_name("offer_validation").joinpath("cards.json").read_text()
)
# Request, candidate shops, expected choice, packs, total for goods, ineligible shops.
CASES = [
    (
        "Цемент М500 50 кг — 6 мешков",
        ["alfa", "cem", "moss", "stri", "beko"],
        "beko",
        6,
        "2400",
        ["alfa", "cem", "stri"],
    ),
    ("Евроцемент М500 — 125 кг", ["moss"], "moss", 3, "1800", []),
    ("Евроцемент М500 25 кг — 6 мешков", ["moss"], None, None, None, ["moss"]),
    ("Цемент Магма 50 кг — 400 мешков", ["alfa"], "alfa", 400, "210000", []),
    ("Цемент М500 50 кг — 6 мешков", ["cem"], None, None, None, ["cem"]),
    ("Евроцемент М500 50 кг — 6 мешков", ["moss"], "moss", 6, "3600", []),
    ("Валик ANZA Elite Титекс 250 мм — 3 шт", ["roller"], "roller", 3, "3894", []),
]


def replay(url, json_origin=None):
    for card in CARDS.values():
        if url == card["url"] and not json_origin:
            return card["html"], url
        if json_origin == card["url"] and "api" in card:
            if (
                urlsplit(url).path
                == f"/wp-json/wc/store/v1/products/{card['api']['id']}"
            ):
                return card["api"], url
    raise ValueError("Нет сохранённого ответа для этого адреса")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Перечитать карточки и сравнить с датированным эталоном",
    )
    args = parser.parse_args()
    worker = Agent({"site": "http://127.0.0.1:5173", "worker_secret": "offline-check"})
    correct = missed = unsafe = 0
    with ExitStack() as stack:
        stack.enter_context(patch.object(worker, "update"))
        stack.enter_context(patch("agent.search_web", return_value=[]))
        stack.enter_context(patch("agent.local_catalog_links", return_value=[]))
        if not args.live:
            stack.enter_context(patch("sources.fetch_document", side_effect=replay))
        for request, shops, expected, packs, total, ineligible in CASES:
            urls = [CARDS[key]["url"] for key in shops]
            # The roller case exercises the actual city registry after an empty search.
            if shops == ["roller"]:
                text = request
            else:
                text = "\n".join([request, *urls])
            with ExitStack() as scope:
                if shops != ["roller"]:
                    scope.enter_context(
                        patch("agent.registered_links", return_value=[])
                    )
                result = worker.process(
                    {
                        "payload": {
                            "text": text,
                            "city": "Москва",
                            "address": "Москва, склад",
                            "deadline": (date.today() + timedelta(days=14)).isoformat(),
                        }
                    }
                )
            item = result["items"][0]
            choice = item["selected"] or {}
            url = choice.get("url")
            expected_url = CARDS[expected]["url"] if expected else None
            ok = (
                url == expected_url
                and choice.get("packs") == packs
                and result["goods_total"] == total
            )
            correct += int(ok)
            missed += int(
                expected is not None
                and (
                    not choice
                    or (url != expected_url and dec(result["goods_total"]) > dec(total))
                )
            )
            unsafe += int(
                bool(choice)
                and (
                    url in [CARDS[k]["url"] for k in ineligible]
                    or (url == expected_url and choice.get("packs") != packs)
                )
            )
            print("OK" if ok else "ПРОВЕРИТЬ", request, url, result["goods_total"])
    print(
        f"Верный итог {correct}/{len(CASES)}. Пропущен минимум {missed}. Недопустимый выбор {unsafe}."
    )
    return int(correct != len(CASES))


if __name__ == "__main__":
    sys.exit(main())
