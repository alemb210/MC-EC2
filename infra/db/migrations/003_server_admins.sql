-- Site users an owner has added as admins of a server. email is kept for display, because the
-- rest of the database has no email addresses (they live in Cognito).

CREATE TABLE IF NOT EXISTS server_admins (
    server_id  uuid NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email      text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (server_id, user_id)
);

CREATE INDEX IF NOT EXISTS server_admins_user_id_idx ON server_admins (user_id);
