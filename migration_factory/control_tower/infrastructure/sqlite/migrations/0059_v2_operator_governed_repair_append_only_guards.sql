-- R11 closure: enforce append-only governance ledgers at the SQLite boundary.

CREATE TRIGGER trg_v2_repair_attempts_no_update
BEFORE UPDATE ON v2_repair_attempts
BEGIN
    SELECT RAISE(ABORT, 'v2_repair_attempts is append-only');
END;

CREATE TRIGGER trg_v2_repair_attempts_no_delete
BEFORE DELETE ON v2_repair_attempts
BEGIN
    SELECT RAISE(ABORT, 'v2_repair_attempts is append-only');
END;

CREATE TRIGGER trg_v2_repair_operator_actions_no_update
BEFORE UPDATE ON v2_repair_operator_actions
BEGIN
    SELECT RAISE(ABORT, 'v2_repair_operator_actions is append-only');
END;

CREATE TRIGGER trg_v2_repair_operator_actions_no_delete
BEFORE DELETE ON v2_repair_operator_actions
BEGIN
    SELECT RAISE(ABORT, 'v2_repair_operator_actions is append-only');
END;

CREATE TRIGGER trg_v2_repair_operator_decisions_no_update
BEFORE UPDATE ON v2_repair_operator_decisions
BEGIN
    SELECT RAISE(ABORT, 'v2_repair_operator_decisions is append-only');
END;

CREATE TRIGGER trg_v2_repair_operator_decisions_no_delete
BEFORE DELETE ON v2_repair_operator_decisions
BEGIN
    SELECT RAISE(ABORT, 'v2_repair_operator_decisions is append-only');
END;
