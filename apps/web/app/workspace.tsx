"use client";
import type {
  Attachment,
  Bootstrap,
  Detail,
  SpeechInput,
} from "../lib/contracts";
import WorkerSettings from "./WorkerSettings";
import HowItWorks from "./HowItWorks";
import { useEffect, useState, useRef } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  Plus,
  FileText,
  Layers,
  Box,
  Settings2,
  ChevronDown,
  UploadCloud,
  Mic,
  Check,
  Search,
  Clock,
  ArrowLeft,
  Download,
  Loader2,
  AlertCircle,
  ExternalLink,
  Trash2,
  Building2,
  LogOut,
  CheckCheck,
} from "lucide-react";
const states: Record<string, string> = {
  draft: "Черновик",
  queued: "В очереди",
  processing: "Подбираем предложения",
  ready: "Смета подготовлена",
  needs_info: "Нужно уточнение",
  failed: "Ошибка обработки",
  review: "На согласовании",
  approved: "Согласовано",
};
const money = (v: unknown) =>
  v == null
    ? "Уточнить"
    : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(
        Number(v),
      ) + " ₽";
const date = (v: string) => (v ? new Date(v).toLocaleDateString("ru-RU") : "");
const safeLink = (u: string) => (/^https?:\/\//i.test(u || "") ? u : "#");
async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch("/api/" + path, options);
  const data = await res.json();
  if (!res.ok) {
    const error = data as { signIn?: string; error?: string };
    if (error.signIn) window.location.href = error.signIn;
    throw new Error(error.error || "Не удалось выполнить запрос");
  }
  return data as T;
}
const post = (p: string, d: unknown) =>
  api<{ id: string }>(p, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(d),
  });
const initial = {
  title: "",
  city: "",
  address: "",
  deadline: "",
  budget: "",
  text: "",
};
export default function Workspace({ local = false } = {}) {
  const [boot, setBoot] = useState<Bootstrap | null>(null),
    [view, setView] = useState("new"),
    [role, setRole] = useState("foreman"),
    [form, setForm] = useState(initial),
    [files, setFiles] = useState<Attachment[]>([]),
    [uploading, setUploading] = useState(false),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [error, setError] = useState(""),
    [current, setCurrent] = useState<Detail | null>(null),
    [tab, setTab] = useState("estimate"),
    [query, setQuery] = useState(""),
    [listening, setListening] = useState(false);
  const input = useRef<HTMLInputElement>(null),
    recognition = useRef<SpeechInput | null>(null);
  async function refresh() {
    try {
      setBoot(await api<Bootstrap>("bootstrap"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (!current?.id) return;
    const t = setInterval(async () => {
      try {
        setCurrent(await api<Detail>("requests/" + current.id));
      } catch {}
    }, 4000);
    return () => clearInterval(t);
  }, [current?.id]);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(t);
  }, [notice]);
  function fresh() {
    setView("new");
    setCurrent(null);
    setForm(initial);
    setFiles([]);
    setError("");
  }
  function sample() {
    setForm({
      ...initial,
      title: "Материалы для отделки этажа",
      text: "1. Саморезы по дереву 3,5 × 35 мм — 1000 шт.\n2. Грунтовка глубокого проникновения, канистра 10 л — 5 шт.\n3. Цемент М500, мешок 50 кг — 6 шт.\n\nПодобрать предложения с минимальной полной стоимостью. Бренд можно предложить. Разгрузку указать отдельно.",
    });
    setNotice("Пример заполнен. Укажите свой адрес и срок поставки");
  }
  async function upload(list: FileList | null) {
    if (!list) return;
    setError("");
    if (files.length + list.length > 8) {
      setError("Можно приложить до 8 файлов");
      return;
    }
    setUploading(true);
    try {
      for (const f of Array.from(list)) {
        const b = new FormData();
        b.append("file", f);
        const data = await api<Attachment>("files", {
          method: "POST",
          body: b,
        });
        setFiles((prev) => [...prev, data]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }
  function voice() {
    const S = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!S) {
      setError(
        "Голосовой ввод недоступен в этом браузере. Введите список текстом или используйте системную диктовку.",
      );
      return;
    }
    if (listening) {
      recognition.current?.stop();
      return;
    }
    const r = new S();
    r.lang = "ru-RU";
    r.continuous = true;
    r.interimResults = false;
    r.onresult = (event) => {
      let text = "";
      for (let i = event.resultIndex; i < event.results.length; i++)
        text += event.results[i][0].transcript + " ";
      setForm((p) => ({ ...p, text: p.text + "\n" + text }));
    };
    r.onerror = () => {
      setListening(false);
      setError("Не удалось записать речь. Проверьте разрешение на микрофон.");
    };
    r.onend = () => setListening(false);
    recognition.current = r;
    r.start();
    setListening(true);
  }
  async function submit(submit: boolean) {
    setError("");
    setBusy(true);
    try {
      const r = await post("requests", {
        ...form,
        file_ids: files.map((f) => f.id),
        submit,
      });
      setCurrent(await api<Detail>("requests/" + r.id));
      setView("detail");
      setTab("estimate");
      await refresh();
      setNotice(submit ? "Заявка передана агенту" : "Черновик сохранён");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function open(id: string) {
    setBusy(true);
    setError("");
    try {
      setCurrent(await api<Detail>("requests/" + id));
      setView("detail");
      setTab("estimate");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function action(state: string) {
    if (!current) return;
    let comment = "";
    if (state === "approved") {
      comment = window.prompt("Комментарий к согласованию:") || "";
      if (!comment) return;
    }
    setBusy(true);
    try {
      await post("requests/" + current.id, { state, comment });
      setCurrent(await api<Detail>("requests/" + current.id));
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const jobs = boot?.jobs || [],
    worker = boot?.worker;
  const active = jobs.filter((j) =>
    ["queued", "processing"].includes(j.state),
  ).length;
  const r = current?.result;
  return (
    <div className="app">
      <aside className="sidebar">
        <button className="brand" onClick={fresh}>
          <span className="brand-mark" />
          основа<span className="brand-dot">.</span>
        </button>
        <p className="brand-sub">снабжение без рутины</p>
        <div className="workspace-select">
          <span className="square">
            <Building2 size={17} />
          </span>
          <div>
            <b>Рабочее пространство</b>
            <small>Закупка материалов</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <span className="nav-label">РАБОЧАЯ ОБЛАСТЬ</span>
        <nav>
          <button className={view === "new" ? "active" : ""} onClick={fresh}>
            <Plus size={18} />
            Новая заявка
          </button>
          <button
            className={["list", "detail"].includes(view) ? "active" : ""}
            onClick={() => setView("list")}
          >
            <FileText size={18} />
            Мои заявки<span className="nav-count">{jobs.length}</span>
          </button>
          <button
            className={view === "how" ? "active" : ""}
            onClick={() => setView("how")}
          >
            <Layers size={18} />
            Как работает агент
          </button>
          <button
            className={view === "settings" ? "active" : ""}
            onClick={() => setView("settings")}
          >
            <Settings2 size={18} />
            Подключение
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="agent-mini">
            <span
              className={"status-dot " + (worker?.online ? "online" : "")}
            />
            <div>
              <b>{worker?.online ? "Агент подключён" : "Агент не в сети"}</b>
              <small>
                {worker?.online ? worker.model : "Заявки сохраняются в очередь"}
              </small>
            </div>
          </div>
          <div className="profile">
            <span className="avatar">
              {(boot?.user?.name || "Я").slice(0, 1).toUpperCase()}
            </span>
            <div>
              <b>{boot?.user?.name || "Мой аккаунт"}</b>
              <select
                aria-label="Кабинет для просмотра"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                <option value="foreman">Кабинет прораба</option>
                <option value="buyer">Кабинет закупщика</option>
                <option value="admin">Кабинет администратора</option>
              </select>
            </div>
          </div>
        </div>
      </aside>
      <div className="content">
        <header className="topbar">
          <div>
            <span className="muted">Рабочее пространство</span>
            <span className="slash">/</span>
            {view === "new"
              ? "Новая заявка"
              : view === "list"
                ? "Мои заявки"
                : view === "detail"
                  ? "Закупочная заявка"
                  : view === "settings"
                    ? "Подключение"
                    : "Как работает агент"}
          </div>
          <div className="topright">
            <span className="soft-pill">
              <span className="status-dot online" />
              Закрытый прототип
            </span>
            {!local && (
              <a
                aria-label="Выйти"
                href="/signout-with-chatgpt?return_to=/"
                target="_top"
              >
                <LogOut size={16} />
              </a>
            )}
          </div>
        </header>
        <main>
          {notice && (
            <div className="toast">
              <Check size={17} />
              {notice}
            </div>
          )}
          {error && (
            <div role="alert" className="error">
              <AlertCircle size={17} />
              <span>{error}</span>
              <button onClick={() => setError("")}>×</button>
            </div>
          )}
          {view === "new" && (
            <>
              <div className="eyebrow">НОВАЯ ЗАЯВКА НА ЗАКУПКУ</div>
              <div className="page-heading">
                <div>
                  <h1>
                    Ты задаёшь потребность.
                    <br />
                    <span>Агент собирает заявку.</span>
                  </h1>
                  <p>Найдёт товары, сравнит предложения и подготовит смету.</p>
                </div>
                <button className="text-btn" onClick={sample}>
                  Попробовать на примере <ArrowUpRight size={16} />
                </button>
              </div>
              <div className="form-layout">
                <div className="form-stack">
                  <section className="card">
                    <div className="card-title">
                      <span className="step-num">01</span>
                      <div>
                        <h2>Что нужно купить</h2>
                        <p>Материалы, характеристики и количество</p>
                      </div>
                    </div>
                    <div className="card-body">
                      <div className="textarea-wrap">
                        <textarea
                          aria-label="Список материалов"
                          value={form.text}
                          onChange={(e) =>
                            setForm({ ...form, text: e.target.value })
                          }
                          placeholder={
                            "Например:\nСаморезы по дереву 3,5 × 35 мм — 1000 шт.\nГрунтовка, канистра 10 л — 5 шт.\nЦемент М500, мешок 50 кг — 6 шт."
                          }
                        />
                        <div className="textarea-footer">
                          <span>
                            Пиши как коллеге. Добавь бренд, если он обязателен.
                          </span>
                          <button
                            className={
                              "voice " + (listening ? "recording" : "")
                            }
                            onClick={voice}
                          >
                            <Mic size={15} />
                            {listening ? "Остановить" : "Надиктовать"}
                          </button>
                        </div>
                      </div>
                      <div
                        className="dropzone"
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => {
                          e.preventDefault();
                          upload(e.dataTransfer.files);
                        }}
                      >
                        <span className="upload-icon">
                          <UploadCloud size={22} />
                        </span>
                        <div>
                          <b>
                            {uploading
                              ? "Загружаем документы…"
                              : "Есть спецификация или список в файле?"}
                          </b>
                          <p>
                            Перетащи сюда или{" "}
                            <button
                              className="inline-btn"
                              onClick={() => input.current?.click()}
                              disabled={uploading}
                            >
                              выбери файл
                            </button>
                          </p>
                          <small>
                            PDF, Excel, Word, CSV, TXT, фото · до 12 МБ
                          </small>
                        </div>
                        <input
                          ref={input}
                          type="file"
                          multiple
                          accept=".pdf,.xlsx,.docx,.csv,.txt,.json,.png,.jpg,.jpeg"
                          onChange={(e) => upload(e.target.files)}
                          hidden
                        />
                      </div>
                      {files.length > 0 && (
                        <div className="file-list">
                          {files.map((f) => (
                            <div key={f.id}>
                              <FileText size={16} />
                              <span>{f.name}</span>
                              <small>Загружен</small>
                              <button
                                aria-label={"Убрать " + f.name}
                                onClick={() =>
                                  setFiles(files.filter((x) => x.id !== f.id))
                                }
                              >
                                <Trash2 size={14} />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </section>
                  <section className="card">
                    <div className="card-title">
                      <span className="step-num">02</span>
                      <div>
                        <h2>Куда и к какому сроку</h2>
                        <p>
                          Чтобы учесть доставку и найти подходящие предложения
                        </p>
                      </div>
                    </div>
                    <div className="card-body fields">
                      <label className="wide">
                        Название заявки
                        <input
                          value={form.title}
                          onChange={(e) =>
                            setForm({ ...form, title: e.target.value })
                          }
                          placeholder="Например: материалы для отделки этажа"
                        />
                      </label>
                      <label>
                        Город <span>*</span>
                        <input
                          value={form.city}
                          onChange={(e) =>
                            setForm({ ...form, city: e.target.value })
                          }
                          placeholder="Город доставки"
                          required
                        />
                      </label>
                      <label>
                        Поставка до <span>*</span>
                        <input
                          type="text"
                          inputMode="numeric"
                          placeholder="ДД.ММ.ГГГГ"
                          maxLength={10}
                          value={form.deadline}
                          onChange={(e) =>
                            setForm({ ...form, deadline: e.target.value })
                          }
                          required
                        />
                      </label>
                      <label className="wide">
                        Адрес объекта <span>*</span>
                        <input
                          value={form.address}
                          onChange={(e) =>
                            setForm({ ...form, address: e.target.value })
                          }
                          placeholder="Улица, дом, корпус; условия подъезда"
                          required
                        />
                      </label>
                      <label>
                        Бюджет, ₽{" "}
                        <span className="optional">необязательно</span>
                        <input
                          type="number"
                          min="0"
                          value={form.budget}
                          onChange={(e) =>
                            setForm({ ...form, budget: e.target.value })
                          }
                          placeholder="Без ограничения"
                        />
                      </label>
                      <div className="field-note">
                        <Box size={17} />
                        <span>
                          Условия разгрузки, допустимые аналоги и другие
                          пожелания добавь к списку материалов.
                        </span>
                      </div>
                    </div>
                  </section>
                  <div className="form-actions">
                    <span>
                      <span className="status-dot" />
                      Сначала проект заявки, затем твоё решение
                    </span>
                    <div>
                      <button
                        className="btn"
                        disabled={busy || uploading}
                        onClick={() => submit(false)}
                      >
                        Сохранить черновик
                      </button>
                      <button
                        className="btn primary"
                        disabled={busy || uploading}
                        onClick={() => submit(true)}
                      >
                        {busy ? (
                          <Loader2 className="spin" size={17} />
                        ) : (
                          <Search size={17} />
                        )}
                        Подобрать и составить <ArrowRight size={17} />
                      </button>
                    </div>
                  </div>
                </div>
                <aside className="helper">
                  <div className="agent-card">
                    <div className="agent-emblem">✳</div>
                    <span className="eyebrow">ТВОЙ АГЕНТ ПО СНАБЖЕНИЮ</span>
                    <h2>
                      От списка материалов
                      <br />
                      до готовой сметы
                    </h2>
                    <div className="helper-step">
                      <span>1</span>
                      <div>
                        <b>Уточнит потребность</b>
                        <p>
                          Разберёт позиции, количество и обязательные
                          характеристики
                        </p>
                      </div>
                    </div>
                    <div className="helper-step">
                      <span>2</span>
                      <div>
                        <b>Найдёт предложения</b>
                        <p>
                          Откроет страницы поставщиков и соберёт доступные цены
                        </p>
                      </div>
                    </div>
                    <div className="helper-step">
                      <span>3</span>
                      <div>
                        <b>Составит заявку</b>
                        <p>
                          Сравнит стоимость, наличие и подтверждённые условия
                          доставки
                        </p>
                      </div>
                    </div>
                    <div className="helper-foot">
                      <FileText size={17} />
                      <span>
                        На выходе: смета, ссылки на товары и объяснение выбора
                      </span>
                    </div>
                  </div>
                  <div className="small-note">
                    <AlertCircle size={15} />
                    <p>
                      Если условия нельзя подтвердить на сайте поставщика, агент
                      отметит, что нужно уточнить. Заказы автоматически не
                      оформляются.
                    </p>
                  </div>
                </aside>
              </div>
            </>
          )}
          {view === "list" && (
            <>
              <div className="page-heading compact">
                <div>
                  <div className="eyebrow">РАБОЧАЯ ОБЛАСТЬ</div>
                  <h1>
                    Мои заявки
                    <span className="count-heading">{jobs.length}</span>
                  </h1>
                  <p>
                    {active
                      ? `${active} в обработке или очереди`
                      : "Все закупочные заявки в одном месте"}
                  </p>
                </div>
                <button className="btn primary" onClick={fresh}>
                  <Plus size={17} />
                  Новая заявка
                </button>
              </div>
              <div className="searchbar">
                <Search size={18} />
                <input
                  placeholder="Найти заявку по названию"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              <section className="card list-card">
                {jobs
                  .filter((j) =>
                    j.title.toLowerCase().includes(query.toLowerCase()),
                  )
                  .map((j) => (
                    <button
                      className="job-row"
                      key={j.id}
                      onClick={() => open(j.id)}
                    >
                      <span className="doc-icon">
                        <FileText size={21} />
                      </span>
                      <span className="job-main">
                        <b>{j.title}</b>
                        <small>
                          ЗК-{j.id.slice(0, 6).toUpperCase()} ·{" "}
                          {date(j.created)}
                        </small>
                      </span>
                      <span className={"state state-" + j.state}>
                        {states[j.state]}
                      </span>
                      <ArrowUpRight size={17} />
                    </button>
                  ))}
                {!jobs.length && (
                  <div className="empty">
                    <FileText size={34} />
                    <h2>Здесь появится первая заявка</h2>
                    <p>Добавь материалы — агент подберёт предложения</p>
                    <button className="btn primary" onClick={fresh}>
                      Составить заявку
                    </button>
                  </div>
                )}
              </section>
            </>
          )}
          {view === "detail" && current && (
            <>
              <button className="back" onClick={() => setView("list")}>
                <ArrowLeft size={15} />
                Все заявки
              </button>
              <div className="page-heading compact">
                <div>
                  <div className="eyebrow">
                    ЗК-{current.id.slice(0, 6).toUpperCase()}
                  </div>
                  <h1>{current.title}</h1>
                  <p>
                    {current.payload.city} · {current.payload.address} ·
                    Поставка до {date(current.payload.deadline)}
                  </p>
                </div>
                <span className={"state state-" + current.state}>
                  {states[current.state]}
                </span>
              </div>
              {["queued", "processing"].includes(current.state) && (
                <section className="processing card">
                  <div className="processing-orbit">
                    <Loader2 className="spin" size={30} />
                  </div>
                  <div>
                    <h2>
                      {current.state === "queued"
                        ? "Заявка ожидает агента"
                        : "Агент составляет заявку"}
                    </h2>
                    <p>{current.note}</p>
                    {!worker?.online && (
                      <small>
                        Локальный обработчик сейчас не подключён. Заявка
                        сохранена и будет обработана после его запуска.
                      </small>
                    )}
                  </div>
                </section>
              )}
              {current.state === "draft" && (
                <section className="card draft-box">
                  <FileText size={27} />
                  <div>
                    <h2>Черновик готов к подбору</h2>
                    <p>Запусти агента, чтобы найти товары и составить смету.</p>
                  </div>
                  <button
                    className="btn primary"
                    disabled={busy}
                    onClick={() => action("queued")}
                  >
                    Запустить подбор <ArrowRight size={16} />
                  </button>
                </section>
              )}
              {current.state === "failed" && (
                <section className="card draft-box">
                  <AlertCircle size={27} />
                  <div>
                    <h2>Подбор не завершён</h2>
                    <p>{current.note}</p>
                  </div>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => action("queued")}
                  >
                    Попробовать снова
                  </button>
                </section>
              )}
              {r && (
                <>
                  <div className="metrics">
                    <div className="metric warm">
                      <span>Стоимость товаров</span>
                      <strong>{money(r.goods_total)}</strong>
                      <small>
                        {r.delivery_total == null
                          ? "Доставка требует уточнения"
                          : "Доставка: " + money(r.delivery_total)}
                      </small>
                    </div>
                    <div className="metric">
                      <span>Позиций в заявке</span>
                      <strong>{r.items?.length || 0}</strong>
                      <small>
                        Подобрано:{" "}
                        {r.items?.filter((i) => i.selected).length || 0}
                      </small>
                    </div>
                    <div className="metric">
                      <span>Предложений найдено</span>
                      <strong>{r.quotes_checked || 0}</strong>
                      <small>
                        Подтверждено страниц: {r.quotes_verified || 0}
                      </small>
                    </div>
                    <div className="metric">
                      <span>Уточнения</span>
                      <strong>{r.questions?.length || 0}</strong>
                      <small>Перед оформлением заказа</small>
                    </div>
                  </div>
                  <div className="tabs">
                    {[
                      ["estimate", "Смета"],
                      ["offers", "Сравнение предложений"],
                      ["questions", "Что уточнить"],
                      ["task", "Исходная потребность"],
                    ].map(([id, name]) => (
                      <button
                        key={id}
                        className={tab === id ? "active" : ""}
                        onClick={() => setTab(id)}
                      >
                        {name}
                        {id === "questions" && r.questions?.length > 0 && (
                          <span>{r.questions.length}</span>
                        )}
                      </button>
                    ))}
                    <a
                      className="export"
                      href={"/api/requests/" + current.id + "/csv"}
                    >
                      <Download size={15} />
                      Скачать CSV
                    </a>
                  </div>
                  {tab === "estimate" && (
                    <>
                      <section className="card result-card">
                        <div className="card-title">
                          <div>
                            <h2>Проект закупочной заявки</h2>
                            <p>
                              {r.summary ||
                                "Подбор на основе найденных и прочитанных предложений"}
                            </p>
                          </div>
                          <button
                            className="btn small"
                            onClick={() => window.print()}
                          >
                            Печать / PDF
                          </button>
                        </div>
                        {r.items?.some(
                          (i) => i.selected?.source_status === "search_index",
                        ) && (
                          <div className="index-notice">
                            <AlertCircle size={16} />
                            <span>
                              Часть цен найдена в поисковом индексе. Товарные
                              страницы недоступны для проверки; цены, упаковку и
                              условия нужно подтвердить у поставщика.
                            </span>
                          </div>
                        )}
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>Материал</th>
                                <th>К закупке</th>
                                <th>Поставщик</th>
                                <th>Цена / ед.</th>
                                <th>Сумма</th>
                                <th>Поставка</th>
                              </tr>
                            </thead>
                            <tbody>
                              {r.items?.map((i) => (
                                <tr key={i.id}>
                                  <td>
                                    <b>{i.name}</b>
                                    <small>{i.requirements}</small>
                                  </td>
                                  <td>
                                    {i.quantity} {i.unit}
                                  </td>
                                  <td>
                                    {i.selected ? (
                                      <>
                                        <a
                                          href={safeLink(i.selected.url)}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
                                          {i.selected.supplier}
                                          <ExternalLink size={12} />
                                        </a>
                                        <small>{i.selected.product_name}</small>
                                        {Number(i.selected.excess_quantity) > 0 && (
                                          <small>
                                            {i.selected.packs} упак. · к покупке{" "}
                                            {i.selected.purchase_quantity} {i.unit},
                                            остаток {i.selected.excess_quantity} {i.unit}
                                          </small>
                                        )}
                                        {i.selected.price_source_url && (
                                          <small>
                                            <a href={safeLink(i.selected.price_source_url)} target="_blank" rel="noreferrer">
                                              Цена в JSON ↗
                                            </a>
                                            {" · "}{i.selected.price_region || "город не подтверждён"}
                                          </small>
                                        )}
                                        {i.selected.source_status ===
                                          "search_index" && (
                                          <small className="warn-text">
                                            Цена из поиска · не подтверждена
                                          </small>
                                        )}
                                      </>
                                    ) : (
                                      <span className="muted">
                                        Не подобрано
                                      </span>
                                    )}
                                  </td>
                                  <td>{money(i.selected?.unit_price)}</td>
                                  <td>
                                    <b>{money(i.selected?.goods_total)}</b>
                                  </td>
                                  <td>
                                    {i.selected?.delivery_date ? (
                                      date(i.selected.delivery_date)
                                    ) : (
                                      <span className="warn-text">
                                        Уточнить
                                      </span>
                                    )}
                                    <small>
                                      {i.selected?.availability === "in_stock"
                                        ? "Наличие указано на сайте"
                                        : "Наличие уточнить"}
                                    </small>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <div className="total-row">
                          <span>
                            Товары{" "}
                            <small>
                              {r.complete
                                ? "Условия подтверждены найденными источниками"
                                : "Предварительная смета · условия доставки и количество проверить по замечаниям"}
                            </small>
                          </span>
                          <b>{money(r.goods_total)}</b>
                        </div>
                        <div className="reason-box">
                          <CheckCheck size={18} />
                          <p>
                            {r.selection_reason ||
                              "Для каждой позиции выбрано подходящее предложение с минимальной найденной стоимостью. Неизвестные условия отмечены отдельно."}
                          </p>
                        </div>
                      </section>
                    </>
                  )}
                  {tab === "offers" && (
                    <div className="offers-stack">
                      {r.items?.map((i) => (
                        <section className="card" key={i.id}>
                          <div className="card-title">
                            <div>
                              <h2>{i.name}</h2>
                              <p>
                                Нужно {i.quantity} {i.unit}
                              </p>
                            </div>
                          </div>
                          {i.offers?.length ? (
                            i.offers.map((o) => (
                              <div
                                className={
                                  "offer-row " +
                                  (i.selected?.id === o.id ? "chosen" : "")
                                }
                                key={o.id}
                              >
                                <div>
                                  <a
                                    href={safeLink(o.url)}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    <b>{o.supplier}</b>
                                    <ArrowUpRight size={14} />
                                  </a>
                                  <p>{o.product_name}</p>
                                  <small>{o.reason}</small>
                                  {o.cart_url && (
                                    <small>
                                      <a href={safeLink(o.cart_url)} target="_blank" rel="noreferrer">
                                        Расчёт корзины ↗
                                      </a>
                                    </small>
                                  )}
                                </div>
                                <div>
                                  <b>{money(o.unit_price)}</b>
                                  <small>за {i.unit}</small>
                                </div>
                                <div>
                                  <b>{money(o.goods_total)}</b>
                                  <small>
                                    Товары · {o.purchase_quantity} {i.unit}
                                  </small>
                                </div>
                                <div>
                                  <span>
                                    {o.delivery_date
                                      ? date(o.delivery_date)
                                      : "Срок уточнить"}
                                  </span>
                                  <small>
                                    Доставка: {money(o.delivery_cost)}
                                  </small>
                                </div>
                                <span className="state">
                                  {i.selected?.id === o.id
                                    ? "Предложено"
                                    : ["needs_confirmation", "search_index"].includes(o.source_status)
                                      ? "Уточнить цену"
                                      : o.fits
                                        ? "Альтернатива"
                                        : "Не подходит"}
                                </span>
                              </div>
                            ))
                          ) : (
                            <p className="card-body muted">
                              Не удалось подтвердить подходящее предложение.
                              Причины указаны в уточнениях.
                            </p>
                          )}
                        </section>
                      ))}
                    </div>
                  )}
                  {tab === "questions" && (
                    <section className="card">
                      {r.questions?.length ? (
                        r.questions.map((q, n) => (
                          <div className="question-row" key={n}>
                            <AlertCircle size={18} />
                            <div>
                              <b>{q.title || "Требует уточнения"}</b>
                              <p>{q.detail}</p>
                              {q.url && (
                                <a
                                  href={safeLink(q.url)}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  Открыть источник ↗
                                </a>
                              )}
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="empty">
                          <Check size={28} />
                          <h2>Дополнительных вопросов нет</h2>
                        </div>
                      )}
                    </section>
                  )}
                  {tab === "task" && (
                    <section className="card">
                      <div className="card-title">
                        <h2>Исходное задание</h2>
                      </div>
                      <pre className="task-text">{current.payload.text}</pre>
                      <div className="card-body muted">
                        Адрес: {current.payload.city}, {current.payload.address}
                        <br />
                        Срок: {date(current.payload.deadline)}
                        <br />
                        Бюджет:{" "}
                        {current.payload.budget != null
                          ? money(current.payload.budget)
                          : "Без ограничения"}
                      </div>
                    </section>
                  )}
                  <div className="result-actions">
                    <span className="muted">
                      Проверено {date(r.checked_at)} · Модель {r.model}
                    </span>
                    <div>
                      {["ready", "needs_info", "failed"].includes(
                        current.state,
                      ) && (
                        <button
                          className="btn"
                          disabled={busy}
                          onClick={() => action("queued")}
                        >
                          Обновить подбор
                        </button>
                      )}
                      {current.state === "ready" && (
                        <button
                          className="btn primary"
                          onClick={() => action("review")}
                        >
                          Передать на согласование <ArrowRight size={16} />
                        </button>
                      )}
                      {current.state === "review" && (
                        <button
                          className="btn primary"
                          onClick={() => action("approved")}
                        >
                          Согласовать проект <Check size={16} />
                        </button>
                      )}
                    </div>
                  </div>
                </>
              )}
              {!r &&
                !["queued", "processing", "draft", "failed"].includes(
                  current.state,
                ) && (
                  <section className="card empty">
                    <Clock size={28} />
                    <p>Результат ещё не готов</p>
                  </section>
                )}
            </>
          )}
          {view === "how" && <HowItWorks />}
          {view === "settings" && (
            <WorkerSettings worker={worker} local={local} />
          )}
          <footer className="page-footer">
            <span>Основа · рабочий прототип закупки материалов</span>
            <span>Решение о покупке остаётся за тобой</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
