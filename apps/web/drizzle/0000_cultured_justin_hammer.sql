CREATE TABLE `files` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`name` text NOT NULL,
	`mime` text NOT NULL,
	`size` integer NOT NULL,
	`object_key` text NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `requests` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`title` text NOT NULL,
	`state` text NOT NULL,
	`payload` text NOT NULL,
	`result` text,
	`note` text,
	`lease` text,
	`created` text NOT NULL,
	`updated` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `worker` (
	`id` text PRIMARY KEY NOT NULL,
	`seen` text NOT NULL,
	`model` text NOT NULL,
	`state` text NOT NULL
);
