# DisputeSentinel

PayPal Sandbox payment evidence and dispute management for digital-service merchants.
This is the T1.1 scaffold: a FastAPI health endpoint and a React placeholder page.
The source-of-truth implementation plan is [PAYOUTSENTINEL_PLAN.md](PAYOUTSENTINEL_PLAN.md),
with architecture in [docs/DIAGRAMS.md](docs/DIAGRAMS.md).

## Local setup (PowerShell)

Use Python **3.12.11** and Node.js **22.12+** (validated with Node.js 24).
From the repository root:

```powershell
Copy-Item .env.example .env
cd backend
uv venv --python 3.12.11 --seed .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The setup command uses the `uv` Python environment manager to select the exact
Python version. If you already have native Python 3.12.11, you can instead use
that interpreter's `-m venv .venv` command.

Health: http://127.0.0.1:8000/health returns `{"status":"ok"}`.
API docs: http://127.0.0.1:8000/docs.
Settings load the root `.env`, with environment variables taking precedence.
The health endpoint needs no credentials or database connection. Replace placeholders
only in your private `.env` when implementing the later integrations; never commit it.
Only the PayPal Sandbox base URL is accepted by settings.

In a second terminal, from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (normally http://localhost:5173).
The four navigation items are disabled placeholders. No backend integration is
implemented yet, and no credentials belong in frontend environment variables.

Production build check:

```powershell
cd frontend
npm run build
```

Future integration settings (webhook ID, Gemini model, dispute source, upload
directory, frontend origin) are listed in `.env.example`; their services are not
implemented in this scaffold. Production uploads will require persistent storage.

## License

MIT; see [LICENSE](LICENSE).
