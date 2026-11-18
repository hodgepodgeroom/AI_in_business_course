export function validateTask(v) {
  const clean = {};
  for (const [k, max] of Object.entries({
    text: 18000,
    city: 150,
    address: 400,
    deadline: 10,
    title: 150,
  })) {
    clean[k] = String(v[k] ?? "").trim();
    if (clean[k].length > max) throw new Error("Слишком длинное поле: " + k);
  }
  if (clean.text.length < 5) throw new Error("Укажите материалы и количество");
  if (!clean.city || !clean.address)
    throw new Error("Укажите город и адрес доставки");
  clean.deadline = clean.deadline.replace(
    /^(\d{2})\.(\d{2})\.(\d{4})$/,
    "$3-$2-$1",
  );
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(clean.deadline) ||
    !Number.isFinite(Date.parse(clean.deadline)) ||
    new Date(clean.deadline).toISOString().slice(0, 10) !== clean.deadline
  )
    throw new Error("Укажите дату поставки в формате ДД.ММ.ГГГГ");
  clean.title ||= "Закупка материалов";
  clean.budget = v.budget === "" || v.budget == null ? null : Number(v.budget);
  if (
    clean.budget !== null &&
    (!Number.isFinite(clean.budget) || clean.budget < 0)
  )
    throw new Error("Проверьте бюджет");
  clean.file_ids = Array.isArray(v.file_ids)
    ? v.file_ids.filter((x) => typeof x === "string").slice(0, 8)
    : [];
  return clean;
}
export function canTransition(from, to) {
  return (
    {
      draft: ["queued"],
      queued: [],
      processing: [],
      needs_info: ["queued"],
      ready: ["review", "queued"],
      review: ["approved", "queued"],
      approved: [],
      failed: ["queued"],
    }[from]?.includes(to) ?? false
  );
}
export function safeCsv(v) {
  const s = v == null ? "" : String(v);
  return /^[\s]*[=+@-]/.test(s) ? "'" + s : s;
}
