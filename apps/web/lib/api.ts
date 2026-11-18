type RequestRow = {
  id: string;
  owner: string;
  state: string;
  payload: string;
  result: string | null;
};
import type { Material, Task } from "./contracts";
import { validateTask, canTransition, safeCsv } from "./domain.mjs";
const json = (data: unknown, status = 200) =>
  Response.json(data, {
    status,
    headers: {
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
const now = () => new Date().toISOString();
const uid = () => crypto.randomUUID();

function fail(message: string, status = 400): never {
  throw Object.assign(new Error(message), { status });
}
async function body(req: Request) {
  if (Number(req.headers.get("content-length") || 0) > 2500000)
    fail("Слишком большой запрос", 413);
  try {
    const value = await req.json();
    if (!value || typeof value !== "object" || Array.isArray(value))
      fail("Ожидается объект JSON");
    return value as Record<string, unknown>;
  } catch {
    fail("Ожидается JSON");
  }
}
function sameOrigin(req: Request) {
  const o = req.headers.get("origin");
  if (!o || o !== new URL(req.url).origin)
    fail("Запрос с другого сайта запрещён", 403);
}
function workerAuth(req: Request, expected: string | undefined) {
  const actual = req.headers.get("x-worker-secret");
  if (!expected || !actual || actual.length !== expected.length)
    fail("Нет доступа обработчика", 403);
  let mismatch = 0;
  for (let i = 0; i < actual.length; i++)
    mismatch |= actual.charCodeAt(i) ^ expected.charCodeAt(i);
  if (mismatch) fail("Нет доступа обработчика", 403);
}
export async function handleApi(
  req: Request,
  E: Cloudflare.Env,
  getUser: () => Promise<{
    userId: string;
    email: string;
    displayName: string;
  } | null>,
) {
  try {
    if (!E.DB || !E.BUCKET) fail("Хранилище ещё не подключено", 503);
    const path = new URL(req.url).pathname.replace(/^\/api\//, "").split("/");
    const db = E.DB;
    if (path[0] === "worker") {
      workerAuth(req, E.WORKER_SECRET);
      if (req.method === "POST" && path[1] === "claim") {
        const b = await body(req);
        await db
          .prepare(
            "INSERT INTO worker(id,seen,model,state) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET seen=excluded.seen,model=excluded.model,state=excluded.state",
          )
          .bind(
            "local",
            now(),
            String(b.model || "Ollama").slice(0, 100),
            String(b.state || "online").slice(0, 50),
          )
          .run();
        if (b.busy) {
          if (b.id && b.lease)
            await db
              .prepare(
                "UPDATE requests SET updated=? WHERE id=? AND lease=? AND state='processing'",
              )
              .bind(now(), b.id, b.lease)
              .run();
          return json({ job: null });
        }
        // Leases expire explicitly; failed work is visible and needs a deliberate restart.
        await db
          .prepare(
            "UPDATE requests SET state='failed',note='Обработчик отключился. Запустите подбор повторно.',lease=NULL,updated=? WHERE state='processing' AND updated<?",
          )
          .bind(now(), new Date(Date.now() - 20 * 60000).toISOString())
          .run();
        const row = await db
          .prepare(
            "SELECT * FROM requests WHERE state='queued' ORDER BY created LIMIT 1",
          )
          .first<RequestRow>();
        if (!row) return json({ job: null });
        const lease = uid();
        const changed = await db
          .prepare(
            "UPDATE requests SET state='processing',lease=?,note='Читаю список материалов',updated=? WHERE id=? AND state='queued'",
          )
          .bind(lease, now(), row.id)
          .run();
        if (!changed.meta.changes) return json({ job: null });
        const payload = JSON.parse(row.payload);
        const attachments = [];
        for (const id of payload.file_ids || []) {
          const f = await db
            .prepare(
              "SELECT id,name,mime,size FROM files WHERE id=? AND owner=?",
            )
            .bind(id, row.owner)
            .first();
          if (f) attachments.push(f);
        }
        return json({ job: { id: row.id, lease, payload, attachments } });
      }
      if (req.method === "POST" && path[1] === "update") {
        const b = await body(req);
        if (
          !["processing", "ready", "needs_info", "failed"].includes(
            String(b.state),
          )
        )
          fail("Неверный статус");
        const result = b.result ? JSON.stringify(b.result) : null;
        if (result && result.length > 2000000)
          fail("Слишком большой результат");
        const changed = await db
          .prepare(
            "UPDATE requests SET state=?,note=?,result=COALESCE(?,result),updated=?,lease=CASE WHEN ?='processing' THEN lease ELSE NULL END WHERE id=? AND lease=? AND state='processing'",
          )
          .bind(
            b.state,
            String(b.note || "").slice(0, 1000),
            result,
            now(),
            b.state,
            b.id,
            b.lease,
          )
          .run();
        if (!changed.meta.changes)
          fail("Задание уже изменилось; результат не принят", 409);
        return json({ ok: true });
      }
      if (req.method === "GET" && path[1] === "file") {
        const f = await db
          .prepare("SELECT * FROM files WHERE id=?")
          .bind(path[2])
          .first<{ object_key: string }>();
        if (!f) fail("Файл не найден", 404);
        const obj = await E.BUCKET.get(f.object_key);
        if (!obj) fail("Файл не найден", 404);
        return new Response(obj.body, {
          headers: {
            "Content-Type": "application/octet-stream",
            "Cache-Control": "no-store",
          },
        });
      }
      fail("Маршрут не найден", 404);
    }
    const user = await getUser();
    if (!user)
      return json(
        {
          error: "Войдите через ChatGPT",
          signIn: "/signin-with-chatgpt?return_to=/",
        },
        401,
      );
    const owner = user.userId;
    if (req.method !== "GET") sameOrigin(req);
    if (req.method === "GET" && path[0] === "bootstrap") {
      const jobs = await db
        .prepare(
          "SELECT id,title,state,note,created,updated FROM requests WHERE owner=? ORDER BY created DESC LIMIT 80",
        )
        .bind(owner)
        .all();
      const w = await db
        .prepare("SELECT seen,model,state FROM worker WHERE id=?")
        .bind("local")
        .first<{ seen: string; model: string; state: string }>();
      return json({
        user: { name: user.displayName, email: user.email },
        jobs: jobs.results,
        worker: w
          ? { ...w, online: Date.now() - Date.parse(w.seen) < 90000 }
          : null,
      });
    }
    if (path[0] === "files" && req.method === "POST") {
      if (Number(req.headers.get("content-length") || 0) > 14000000)
        fail("Максимум 12 МБ на файл", 413);
      const data = await req.formData();
      const file = data.get("file");
      if (!(file instanceof File) || !file.size || file.size > 12 * 1024 * 1024)
        fail("Выберите файл до 12 МБ");
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (
        ![
          "txt",
          "csv",
          "json",
          "pdf",
          "docx",
          "xlsx",
          "png",
          "jpg",
          "jpeg",
        ].includes(ext || "")
      )
        fail("Поддерживаются PDF, DOCX, XLSX, CSV, TXT и изображения");
      const id = uid(),
        key = `uploads/${owner}/${id}`;
      await E.BUCKET.put(key, await file.arrayBuffer(), {
        httpMetadata: { contentType: file.type || "application/octet-stream" },
      });
      await db
        .prepare(
          "INSERT INTO files(id,owner,name,mime,size,object_key,created) VALUES(?,?,?,?,?,?,?)",
        )
        .bind(
          id,
          owner,
          file.name.slice(0, 240),
          file.type || "application/octet-stream",
          file.size,
          key,
          now(),
        )
        .run();
      return json({ id, name: file.name, size: file.size });
    }
    if (path[0] === "requests") {
      if (req.method === "POST" && !path[1]) {
        const b = await body(req);
        let p: Task;
        try {
          p = validateTask(b) as Task;
        } catch (error) {
          fail(error instanceof Error ? error.message : String(error));
        }
        for (const fid of p.file_ids) {
          if (
            !(await db
              .prepare("SELECT id FROM files WHERE id=? AND owner=?")
              .bind(fid, owner)
              .first())
          )
            fail("Нет доступа к приложенному файлу", 403);
        }
        const total = await db
          .prepare(
            "SELECT COUNT(*) AS n FROM requests WHERE owner=? AND created>?",
          )
          .bind(owner, new Date(Date.now() - 86400000).toISOString())
          .first<{ n: number }>();
        if (total && total.n >= 60) fail("Лимит: 60 заявок в сутки", 429);
        const id = uid(),
          state = b.submit ? "queued" : "draft";
        await db
          .prepare(
            "INSERT INTO requests(id,owner,title,state,payload,created,updated,note) VALUES(?,?,?,?,?,?,?,?)",
          )
          .bind(
            id,
            owner,
            p.title,
            state,
            JSON.stringify(p),
            now(),
            now(),
            b.submit ? "Ожидает локального агента" : "Черновик сохранён",
          )
          .run();
        return json({ id, state });
      }
      const row = path[1]
        ? await db
            .prepare("SELECT * FROM requests WHERE id=? AND owner=?")
            .bind(path[1], owner)
            .first<RequestRow>()
        : null;
      if (!row) fail("Заявка не найдена", 404);
      if (req.method === "GET" && path[2] === "csv") {
        const r = row.result ? JSON.parse(row.result) : null;
        if (!r) fail("Смета ещё не готова");
        const headers = [
          "Материал",
          "Количество",
          "Единица",
          "Поставщик",
          "Цена за единицу, ₽",
          "Сумма товара, ₽",
          "Доставка",
          "Срок",
          "Ссылка",
          "Статус",
        ];
        const rows = (r.items || []).map((i: Material) => [
          i.name,
          i.quantity,
          i.unit,
          i.selected?.supplier,
          i.selected?.unit_price,
          i.selected?.goods_total,
          i.selected?.delivery_cost ?? "Уточнить",
          i.selected?.delivery_date ?? "Уточнить",
          i.selected?.url,
          i.selected ? "Предварительный выбор" : "Нужны данные",
        ]);
        const csv =
          "\uFEFF" +
          [headers, ...rows]
            .map((a) =>
              a
                .map(
                  (x: unknown) => '"' + safeCsv(x).replaceAll('"', '""') + '"',
                )
                .join(";"),
            )
            .join("\r\n");
        return new Response(csv, {
          headers: {
            "Content-Type": "text/csv;charset=utf-8",
            "Content-Disposition": `attachment; filename="estimate-${row.id.slice(0, 8)}.csv"`,
            "Cache-Control": "private,no-store",
          },
        });
      }
      if (req.method === "GET")
        return json({
          ...row,
          payload: JSON.parse(row.payload),
          result: row.result ? JSON.parse(row.result) : null,
          owner: undefined,
          lease: undefined,
        });
      if (req.method === "POST") {
        const b = await body(req),
          state = b.state;
        if (!canTransition(row.state, state))
          fail("Сейчас это действие недоступно", 409);
        if (state === "approved" && !String(b.comment || "").trim())
          fail("Добавьте комментарий к согласованию");
        const result = row.result ? JSON.parse(row.result) : null;
        if (
          state === "approved" &&
          (!result?.complete ||
            !result.items?.length ||
            result.items.some((i: Material) => !i.selected) ||
            result.questions?.length)
        )
          fail("Сначала уточните отсутствующие материалы и условия");
        const updated = await db
          .prepare(
            "UPDATE requests SET result=CASE WHEN ?='queued' THEN NULL ELSE result END,state=?,note=?,updated=? WHERE id=? AND owner=? AND state=?",
          )
          .bind(
            state,
            state,
            state === "queued"
              ? "Ожидает агента"
              : state === "review"
                ? "Передано на согласование"
                : `Согласовано: ${String(b.comment || "").slice(0, 500)}`,
            now(),
            row.id,
            owner,
            row.state,
          )
          .run();
        if (!updated.meta.changes) fail("Заявка уже изменилась", 409);
        return json({ ok: true, state });
      }
    }
    fail("Маршрут не найден", 404);
  } catch (error) {
    const err = (
      error instanceof Error ? error : new Error(String(error))
    ) as Error & { status?: number };
    if (!err.status) console.error("Request error", err.message);
    return json(
      {
        error: err.status
          ? err.message
          : "Не удалось выполнить запрос. Попробуйте ещё раз.",
      },
      err.status || 500,
    );
  }
}
