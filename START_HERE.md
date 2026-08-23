# Start here

For the **full Clarivo build (Content + Voice + Visual)** on your Intel laptop, follow:

- `RUN_FULL_LOCAL_WINDOWS.md`

The important first-time setup is:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m local_scoring.setup_delivery_models
Copy-Item .env.example .env
notepad .env
```

Set your existing Cloudflare credentials and `LOCAL_SCORING_ENABLED=true`, then run the backend and frontend as described in the guide.

The existing Vercel deployment remains suitable for transcript + content analysis. The v11 OpenVINO/YOLO delivery engine is intentionally local in this build.
