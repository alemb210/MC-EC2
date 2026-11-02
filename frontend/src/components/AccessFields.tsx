import { useId } from "react";
import { accessWarning, parsePlayers, playersProblem } from "../access";
import type { AccessMode } from "../api";

// The public/whitelist choice, shared by the create form and the access editor.
export default function AccessFields({ mode, players, disabled = false, onMode, onPlayers }: {
  mode: AccessMode | null;
  players: string;
  disabled?: boolean;
  onMode: (mode: AccessMode) => void;
  onPlayers: (players: string) => void;
}) {
  const group = useId();
  const parsed = parsePlayers(players);
  const warning = mode && accessWarning(mode, parsed);
  const problem = mode === "whitelist" ? playersProblem(parsed) : null;

  return (
    <fieldset className="access" disabled={disabled}>
      <legend>Who can join?</legend>
      <label>
        <input type="radio" name={group} checked={mode === "public"} onChange={() => onMode("public")} /> Public
      </label>
      <label>
        <input type="radio" name={group} checked={mode === "whitelist"} onChange={() => onMode("whitelist")} /> Whitelist
      </label>
      {mode === "whitelist" && (
        <label className="field">
          Minecraft usernames
          <textarea rows={3} value={players} placeholder="Steve, Alex" spellCheck={false} autoCapitalize="off"
                    autoCorrect="off" onChange={(e) => onPlayers(e.target.value)} />
        </label>
      )}
      {problem && <p className="error">{problem}</p>}
      {warning && <p className="muted">{warning}</p>}
    </fieldset>
  );
}
