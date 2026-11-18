"""Клиент локального сервера и схемы структурированных ответов."""

import os, json, requests

DEFAULT_MODEL = "qwen3.5:2b-q4_K_M"
MODEL_API = os.environ.get(
    "OSNOVA_MODEL_API", "http://127.0.0.1:11436/v1/chat/completions"
)


def chat(model, prompt, schema, images=None):
    content = {"role": "user", "content": prompt}
    if images:
        content["images"] = images
    if images:
        raise RuntimeError(
            "В этом режиме доступен текстовый разбор. Для фото нужен текст спецификации или модель с настроенным визуальным входом."
        )
    response = requests.post(
        MODEL_API,
        json={
            "model": model,
            "stream": False,
            "messages": [content],
            "max_tokens": 2000,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            },
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=480,
    )
    if response.status_code != 200:
        raise RuntimeError(
            "Локальная модель не выполнила запрос: " + response.text[:350]
        )
    raw = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError(
            "Локальная модель не вернула структурированный результат; попробуйте уточнить список"
        ) from None


def schema_object(fields):
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


STRING = {"type": "string"}
NULLSTRING = {"type": ["string", "null"]}
ITEM_SCHEMA = schema_object(
    {
        "items": {
            "type": "array",
            "maxItems": 12,
            "items": schema_object(
                {
                    "name": STRING,
                    "quantity": STRING,
                    "unit": STRING,
                    "requirements": STRING,
                    "query": STRING,
                }
            ),
        },
        "questions": {"type": "array", "items": STRING},
    }
)
QUOTE_SCHEMA = schema_object(
    {
        "offers": {
            "type": "array",
            "maxItems": 3,
            "items": schema_object(
                {
                    "page_index": {"type": "integer", "minimum": 0, "maximum": 2},
                    "product_name": {"type": "string", "maxLength": 240},
                    "fits": {"type": "boolean"},
                    "reason": {"type": "string", "maxLength": 250},
                    "pack_price": {"type": ["number", "null"], "minimum": 0},
                    "price_evidence": {"type": "string", "maxLength": 250},
                    "pack_quantity": {"type": "number", "exclusiveMinimum": 0},
                    "unit": STRING,
                    "availability": {
                        "type": "string",
                        "enum": ["in_stock", "out_of_stock", "unknown"],
                    },
                    "stock_quantity": NULLSTRING,
                    "delivery_date": NULLSTRING,
                    "delivery_cost": NULLSTRING,
                    "delivery_scope": {
                        "type": "string",
                        "enum": ["per_order", "unknown"],
                    },
                    "delivery_evidence": {"type": "string", "maxLength": 250},
                }
            ),
        }
    }
)
MATCH_SCHEMA = schema_object(
    {"fits": {"type": "boolean"}, "reason": {"type": "string", "maxLength": 180}}
)
