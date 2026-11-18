import type { WorkerStatus } from "../lib/contracts";
export default function WorkerSettings({
  worker,
  local,
}: {
  worker: WorkerStatus | null | undefined;
  local: boolean;
}) {
  return (
    <>
      <div className="eyebrow">ПОДКЛЮЧЕНИЕ</div>
      <h1>Локальный агент</h1>
      <p className="lead">
        Модель и обработчик запускаются на твоём компьютере. Здесь видно, когда
        обработчик в последний раз связывался с приложением.
      </p>
      <section className="card settings-card">
        <div className="settings-line">
          <span>Состояние</span>
          <b className={worker?.online ? "green-text" : "warn-text"}>
            {worker?.online ? "Подключён" : "Не подключён"}
          </b>
        </div>
        <div className="settings-line">
          <span>Модель</span>
          <b>{worker?.model || "Ожидает подключения"}</b>
        </div>
        <div className="settings-line">
          <span>Последний сигнал</span>
          <b>
            {worker?.seen
              ? new Date(worker.seen).toLocaleString("ru-RU")
              : "Ещё не получен"}
          </b>
        </div>
        <div className="settings-line">
          <span>Доступ к сайту</span>
          <b>
            {local ? "Личный кабинет на этом компьютере" : "Вход через ChatGPT"}
          </b>
        </div>
        <div className="settings-line">
          <span>Ключ GPT</span>
          <b>Не используется</b>
        </div>
      </section>
      <div className="notice-box">
        Чтобы сайт обработал заявку, должны работать сервер модели и локальный
        обработчик. Если компьютер выключен, заявка остаётся в очереди.
        Документы хранятся в закрытом хранилище сайта и скачиваются обработчиком
        для этой задачи.
      </div>
      <div className="small-note">
        <p>
          Переключатель кабинетов позволяет проверить сценарии прораба,
          закупщика и администратора в своём аккаунте. Приглашение других
          пользователей и настройка их прав — отдельный этап.
        </p>
      </div>
    </>
  );
}
