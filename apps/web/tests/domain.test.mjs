import test from "node:test";
import assert from "node:assert/strict";
import { validateTask, canTransition, safeCsv } from "../lib/domain.mjs";
test("task needs a destination and material list", () => {
  assert.throws(() =>
    validateTask({
      text: "цемент",
      city: "",
      address: "",
      deadline: "2026-12-01",
    }),
  );
  const v = validateTask({
    text: "Саморезы 3,5×35 мм, 100 шт",
    city: "Казань",
    address: "ул. Строителей, 1",
    deadline: "2026-12-01",
    title: "Корпус 1",
  });
  assert.equal(v.city, "Казань");
});
test("incomplete result cannot be approved", () => {
  assert.equal(canTransition("needs_info", "approved"), false);
  assert.equal(canTransition("ready", "review"), true);
  assert.equal(canTransition("review", "approved"), true);
  assert.equal(canTransition("processing", "queued"), false);
});
test("CSV text cannot become spreadsheet formula", () =>
  assert.equal(safeCsv("=1+1"), "'=1+1"));
test("Russian date input is normalized and impossible date rejected", () => {
  const base = {
    text: "Цемент 6 мешков",
    city: "Казань",
    address: "Учебный объект",
    deadline: "20.11.2026",
  };
  assert.equal(validateTask(base).deadline, "2026-11-20");
  assert.throws(() => validateTask({ ...base, deadline: "31.02.2026" }));
});
