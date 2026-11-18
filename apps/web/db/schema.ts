import { sqliteTable, text, integer } from "drizzle-orm/sqlite-core";
export const requests = sqliteTable("requests", {
  id: text("id").primaryKey(),
  owner: text("owner").notNull(),
  title: text("title").notNull(),
  state: text("state").notNull(),
  payload: text("payload").notNull(),
  result: text("result"),
  note: text("note"),
  lease: text("lease"),
  created: text("created").notNull(),
  updated: text("updated").notNull(),
});
export const files = sqliteTable("files", {
  id: text("id").primaryKey(),
  owner: text("owner").notNull(),
  name: text("name").notNull(),
  mime: text("mime").notNull(),
  size: integer("size").notNull(),
  objectKey: text("object_key").notNull(),
  created: text("created").notNull(),
});
export const worker = sqliteTable("worker", {
  id: text("id").primaryKey(),
  seen: text("seen").notNull(),
  model: text("model").notNull(),
  state: text("state").notNull(),
});
