# R9.2 PowerMock Live Validation

Use this note to manually retest the real PowerMock failure path after R9.2.

## Start backend

```powershell
cd C:\Users\ilyas.abarbach\Documents\modernizer-solution

$env:CONTROL_TOWER_LLM_REPAIR_SHADOW_ENABLED = "true"
$env:V2_LLM_REPAIR_SHADOW_ENABLED = "true"
$env:AZURE_OPENAI_ASSISTANT_MAX_COMPLETION_TOKENS = "3000"

py -m uvicorn migration_factory.control_tower.adapters.fastapi.dev_app:app --host 127.0.0.1 --port 8000
```

## Start frontend

```powershell
cd C:\Users\ilyas.abarbach\Documents\modernizer-solution\web\control-tower
npm run dev
```

## Expected UI result

- Repair Strategy visible.
- Family: `POWERMOCK_LEGACY_TEST_STRATEGY`.
- Risk level: `high`.
- Apply candidate allowed: `no`.
- No approve/apply buttons for PowerMock.
- Chatbot explains strategy, risk, fallback source, missing evidence, and engineer checklist.
- Downstream remains pending or blocked.
- Legacy source remains unchanged.
