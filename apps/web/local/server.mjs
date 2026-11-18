import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import { handleApi } from "../lib/api.ts";
import { openStorage } from "./storage.mjs";

const port = Number(process.env.PORT || 5173);
const host = "127.0.0.1";
const origin = "http://" + host + ":" + port;
const directory = new URL("../../../.local/", import.meta.url);
await mkdir(directory, { recursive: true, mode: 0o700 });
const config = new URL("agent.json", directory);
try {
  await writeFile(
    config,
    JSON.stringify(
      {
        site: origin,
        model: "qwen3.5:2b-q4_K_M",
        worker_secret: randomBytes(32).toString("hex"),
      },
      null,
      2,
    ),
    { flag: "wx", mode: 0o600 },
  );
} catch (error) {
  if (error.code !== "EEXIST") throw error;
}
const connection = JSON.parse(await readFile(config, "utf8"));
if (connection.site !== origin)
  throw new Error("Согласуйте порт с полем site в .local/agent.json");
const storage = await openStorage(fileURLToPath(directory));
const bindings = { ...storage, WORKER_SECRET: connection.worker_secret };
const localUser = async () => ({
  userId: "local",
  displayName: "Личный кабинет",
  email: "",
});
const assets = new Map([
  ["/", [new URL("index.html", import.meta.url), "text/html; charset=utf-8"]],
  ...["ui.js", "ui.css", "favicon.svg"].map((f, i) => [
    "/" + f,
    [
      new URL("../dist/local/" + f, import.meta.url),
      ["text/javascript", "text/css", "image/svg+xml"][i],
    ],
  ]),
]);

const server = createServer(async (incoming, outgoing) => {
  try {
    if (incoming.headers.host !== host + ":" + port) {
      outgoing.writeHead(403).end();
      return;
    }
    const url = new URL(incoming.url, origin);
    if (url.origin !== origin) {
      outgoing.writeHead(403).end();
      return;
    }
    if (url.pathname.startsWith("/api/")) {
      const chunks = [];
      let size = 0;
      for await (const chunk of incoming) {
        size += chunk.length;
        if (size > 14 * 1024 * 1024) {
          outgoing.writeHead(413).end();
          return;
        }
        chunks.push(chunk);
      }
      const req = new Request(url, {
        method: incoming.method,
        headers: incoming.headers,
        body: chunks.length ? Buffer.concat(chunks) : undefined,
      });
      const response = await handleApi(req, bindings, localUser);
      outgoing.writeHead(response.status, Object.fromEntries(response.headers));
      outgoing.end(Buffer.from(await response.arrayBuffer()));
      return;
    }
    const asset = assets.get(url.pathname);
    if (!asset || incoming.method !== "GET") {
      outgoing.writeHead(404).end();
      return;
    }
    const data = await readFile(asset[0]);
    outgoing
      .writeHead(200, {
        "Content-Type": asset[1],
        "X-Content-Type-Options": "nosniff",
      })
      .end(data);
  } catch (error) {
    console.error(error.message);
    outgoing.writeHead(500).end("Ошибка локального сервера");
  }
});
server.listen(port, host, () =>
  console.log("Основа доступна по адресу " + origin),
);
