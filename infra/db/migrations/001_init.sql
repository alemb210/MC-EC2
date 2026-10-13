-- Initial schema (proposal section IV-F ERD): users log in via identities and own servers.

CREATE TABLE IF NOT EXISTS users (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- One row per login method (Cognito now, Discord later). For Cognito, provider_id is the token's sub.
CREATE TABLE IF NOT EXISTS identities (
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider    text NOT NULL,
    provider_id text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, provider_id)
);

CREATE INDEX IF NOT EXISTS identities_user_id_idx ON identities (user_id);

CREATE TABLE IF NOT EXISTS servers (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id      uuid NOT NULL REFERENCES users(id),
    instance_id   text UNIQUE,              -- NULL until the EC2 instance exists
    region        text NOT NULL DEFAULT 'us-east-1',
    version       text,                     -- pinned Minecraft version
    instance_type text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS servers_owner_id_idx ON servers (owner_id);
