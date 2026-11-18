"""Start a local llama.cpp server for a GGUF file, then run the procurement agent."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--server", default="llama-server", help="Путь к llama-server")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".local/agent.json",
    )
    parser.add_argument("--cpu", action="store_true", help="Вычисления на CPU")
    args = parser.parse_args()
    if not args.config.is_file():
        parser.error("Сначала запустите веб-приложение или задайте --config.")
    binary = shutil.which(args.server)
    if not binary or not args.model_file.is_file():
        parser.error("Проверьте путь к файлу GGUF и к llama-server.")
    config = json.loads(args.config.read_text())
    model = config.get("model", "qwen3.5:2b-q4_K_M")
    base = "http://127.0.0.1:11436"
    command = [
        binary,
        "--model",
        str(args.model_file),
        "--alias",
        model,
        "--host",
        "127.0.0.1",
        "--port",
        "11436",
        "--ctx-size",
        "8192",
        "--parallel",
        "1",
        "--no-mmproj",
        "--reasoning-budget",
        "0",
    ]
    if args.cpu:
        command += ["--device", "none", "-ngl", "0"]
    process = subprocess.Popen(command)
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SystemExit(
                    "llama-server завершился до готовности. Проверьте его вывод и порт 11436."
                )
            try:
                if requests.get(base + "/health", timeout=2).ok:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            raise SystemExit("Сервер модели не ответил за 120 секунд.")
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("agent.py")),
                "--config",
                str(args.config),
            ],
            env={**os.environ, "OSNOVA_MODEL_API": base + "/v1/chat/completions"},
            check=True,
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
