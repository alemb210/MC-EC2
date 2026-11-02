-- Display names, chosen at creation and editable later. Existing servers get the default.

ALTER TABLE servers ADD COLUMN IF NOT EXISTS name text NOT NULL DEFAULT 'Minecraft server';

ALTER TABLE servers ADD CONSTRAINT servers_name_length CHECK (char_length(name) BETWEEN 1 AND 32);
