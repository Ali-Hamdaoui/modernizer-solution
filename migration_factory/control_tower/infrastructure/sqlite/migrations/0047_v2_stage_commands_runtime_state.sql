-- 10I-R6B: allow backend runner to persist durable runtime state.
--
-- The command manifest remains backend-owned, but status/result_json must
-- advance after process start/exit so restarts can reconcile stale runs.

DROP TRIGGER IF EXISTS v2_stage_commands_no_update;

CREATE TRIGGER v2_stage_commands_runtime_only_update
BEFORE UPDATE ON v2_stage_commands
WHEN
    NEW.command_id IS NOT OLD.command_id OR
    NEW.job_id IS NOT OLD.job_id OR
    NEW.stage_index IS NOT OLD.stage_index OR
    NEW.manifest_checksum IS NOT OLD.manifest_checksum OR
    NEW.argv_json IS NOT OLD.argv_json OR
    NEW.env_json IS NOT OLD.env_json OR
    NEW.created_at IS NOT OLD.created_at OR
    NEW.gate_id IS NOT OLD.gate_id OR
    NEW.decision_id IS NOT OLD.decision_id
BEGIN
    SELECT RAISE(ABORT, 'v2_stage_commands manifest fields are immutable');
END;
