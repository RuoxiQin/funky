CREATE TABLE "env_configs" (
	"id" uuid PRIMARY KEY,
	"namespace" text NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"metadata" jsonb DEFAULT '{}' NOT NULL,
	"base_image" text NOT NULL,
	"persistent_fs" jsonb DEFAULT '{"size_gb":2}' NOT NULL,
	"egress" jsonb DEFAULT '{"allow":[]}' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"archived_at" timestamp with time zone
);
--> statement-breakpoint
CREATE INDEX "env_configs_ns_name" ON "env_configs" ("namespace","name");--> statement-breakpoint
CREATE INDEX "env_configs_ns" ON "env_configs" ("namespace");