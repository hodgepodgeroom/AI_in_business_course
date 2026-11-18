import { DatabaseSync } from "node:sqlite";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export async function openStorage(directory) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const db = new DatabaseSync(join(directory, "osnova.sqlite"));
  try {
    db.exec("PRAGMA busy_timeout=5000; BEGIN IMMEDIATE");
    if (!db.prepare("PRAGMA user_version").get().user_version) {
      db.exec(
        await readFile(
          new URL(
            "../drizzle/0000_cultured_justin_hammer.sql",
            import.meta.url,
          ),
          "utf8",
        ),
      );
      db.exec("PRAGMA user_version=1");
    }
    db.exec("COMMIT");
  } catch (error) {
    db.close();
    throw error;
  }
  function statement(sql, values = []) {
    const query = db.prepare(sql);
    return {
      bind: (...args) => statement(sql, args),
      run: () => ({ meta: { changes: query.run(...values).changes } }),
      first: () => query.get(...values) ?? null,
      all: () => ({ results: query.all(...values) }),
    };
  }
  return {
    DB: { prepare: statement },
    BUCKET: {
      async put(key, data) {
        const path = join(directory, key);
        await mkdir(dirname(path), { recursive: true, mode: 0o700 });
        await writeFile(path, new Uint8Array(data), { mode: 0o600 });
      },
      async get(key) {
        try {
          return { body: await readFile(join(directory, key)) };
        } catch (error) {
          if (error.code === "ENOENT") return null;
          throw error;
        }
      },
    },
    close: () => db.close(),
  };
}
