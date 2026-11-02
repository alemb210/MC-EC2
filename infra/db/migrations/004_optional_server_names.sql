-- A server without a custom name now shows its ID, which is too long to store under the name limit.
-- NULL means no custom name; rows still holding the old default become unnamed.

ALTER TABLE servers ALTER COLUMN name DROP NOT NULL;

ALTER TABLE servers ALTER COLUMN name DROP DEFAULT;

UPDATE servers SET name = NULL WHERE name = 'Minecraft server';
