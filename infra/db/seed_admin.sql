-- Idempotent seed: the admin user, their Cognito identity, and the existing Minecraft server.

INSERT INTO users (id, name)
VALUES (CAST(:user_id AS uuid), :name)
ON CONFLICT (id) DO NOTHING;

INSERT INTO identities (user_id, provider, provider_id)
VALUES (CAST(:user_id AS uuid), 'cognito', :sub)
ON CONFLICT (provider, provider_id) DO NOTHING;

INSERT INTO servers (id, owner_id, instance_id, region, version, instance_type)
VALUES (CAST(:server_id AS uuid), CAST(:user_id AS uuid), :instance_id, :region, :version, :instance_type)
ON CONFLICT (id) DO NOTHING;
