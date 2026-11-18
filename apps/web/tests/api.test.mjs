import test from "node:test";
import assert from "node:assert/strict";
import { tmpdir } from "node:os";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { handleApi } from "../lib/api.ts";
import { openStorage } from "../local/storage.mjs";

test("draft, attachment, lease, review, export and durable approval", async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "osnova-test-"));
  let store = await openStorage(dir);
  t.after(async () => {
    store.close();
    await rm(dir, { recursive: true, force: true });
  });
  const origin = "http://127.0.0.1:5173";
  async function request(
    path,
    { body, owner = "owner", secret = "test", method, asForm = false } = {},
  ) {
    const headers = { origin, "x-worker-secret": secret };
    if (body !== undefined && !asForm)
      headers["content-type"] = "application/json";
    return handleApi(
      new Request(origin + "/api/" + path, {
        method: method ?? (body === undefined ? "GET" : "POST"),
        headers,
        body:
          body === undefined ? undefined : asForm ? body : JSON.stringify(body),
      }),
      { ...store, WORKER_SECRET: "test" },
      async () => ({ userId: owner, email: "", displayName: owner }),
    );
  }
  const form = new FormData();
  form.set("file", new File(["20 мешков"], "смета.txt"));
  const { id: file } = await (
    await request("files", { body: form, asForm: true })
  ).json();
  assert.ok(file);
  const task = {
    title: "Корпус",
    text: "Цемент — 20 мешков",
    city: "Тула",
    address: "Склад 1",
    deadline: "2028-11-20",
    file_ids: [file],
  };
  assert.equal(
    (await request("requests", { body: task, owner: "other" })).status,
    403,
  );
  const { id, state } = await (
    await request("requests", { body: task })
  ).json();
  assert.equal(state, "draft");
  const path = "requests/" + id;
  assert.equal((await request(path, { owner: "other" })).status, 404);
  assert.equal(
    (await request("worker/claim", { body: {}, secret: "wrong" })).status,
    403,
  );
  assert.equal(
    (await request(path, { body: { state: "queued" } })).status,
    200,
  );
  const claims = await Promise.all([
    request("worker/claim", { body: {} }),
    request("worker/claim", { body: {} }),
  ]);
  const jobs = (await Promise.all(claims.map((c) => c.json())))
    .map((r) => r.job)
    .filter(Boolean);
  assert.equal(jobs.length, 1);
  const job = jobs[0];
  assert.equal(job.attachments[0].id, file);
  assert.equal(
    await (await request("worker/file/" + file)).text(),
    "20 мешков",
  );
  const finish = (result, lease = job.lease) =>
    request("worker/update", { body: { id, lease, state: "ready", result } });
  assert.equal((await finish({}, "expired")).status, 409);
  const item = {
    name: "Цемент",
    quantity: "20",
    unit: "мешок",
    selected: { supplier: "Склад", unit_price: "60", goods_total: "1200" },
  };
  assert.equal(
    (
      await finish({
        items: [item],
        questions: ["Уточнить доставку"],
        complete: false,
      })
    ).status,
    200,
  );
  assert.equal(
    (await request(path, { body: { state: "review" } })).status,
    200,
  );
  assert.equal(
    (await request(path, { body: { state: "approved", comment: "Проверено" } }))
      .status,
    400,
  );
  assert.equal(
    (await request(path, { body: { state: "queued" } })).status,
    200,
  );
  assert.equal((await (await request(path)).json()).result, null);
  const { job: retry } = await (
    await request("worker/claim", { body: {} })
  ).json();
  assert.equal(
    (
      await finish(
        { items: [item], questions: [], complete: true },
        retry.lease,
      )
    ).status,
    200,
  );
  assert.equal(
    (await request(path, { body: { state: "review" } })).status,
    200,
  );
  assert.equal(
    (await request(path, { body: { state: "approved", comment: "Проверено" } }))
      .status,
    200,
  );
  store.close();
  store = await openStorage(dir);
  assert.equal((await (await request(path)).json()).state, "approved");
  assert.match(await (await request(path + "/csv")).text(), /Цемент.*1200/);
  assert.equal((await (await request("bootstrap")).json()).jobs[0].id, id);
});
