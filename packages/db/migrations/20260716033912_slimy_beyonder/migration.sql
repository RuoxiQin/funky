ALTER TABLE "env_configs" RENAME COLUMN "egress" TO "network";--> statement-breakpoint
UPDATE "env_configs"
SET "network" = CASE
	WHEN jsonb_array_length(COALESCE("network"->'allow', '[]'::jsonb)) = 0
		THEN '{"type":"unrestricted"}'::jsonb
	ELSE jsonb_build_object(
		'type', 'limited',
		'allowed_hosts', "network"->'allow'
	)
END
WHERE "network" ? 'allow';--> statement-breakpoint
UPDATE "sessions"
SET "resolved_env" = ("resolved_env" - 'egress') || jsonb_build_object(
	'network', CASE
		WHEN jsonb_array_length(COALESCE("resolved_env"->'egress'->'allow', '[]'::jsonb)) = 0
			THEN '{"type":"unrestricted"}'::jsonb
		ELSE jsonb_build_object(
			'type', 'limited',
			'allowed_hosts', "resolved_env"->'egress'->'allow'
		)
	END
)
WHERE "resolved_env" ? 'egress';--> statement-breakpoint
ALTER TABLE "env_configs" ALTER COLUMN "network" SET DEFAULT '{"type":"unrestricted"}';
