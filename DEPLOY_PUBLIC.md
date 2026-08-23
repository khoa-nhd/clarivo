# Public deployment note

The existing Clarivo Vercel + Cloudflare deployment can continue to host:

- frontend UI
- Cloudflare Whisper transcription
- Qwen content evaluation

For Vercel keep:

```env
LOCAL_SCORING_ENABLED=false
```

The uploaded v11 Voice + Visual engine depends on OpenVINO, Ultralytics/YOLO, OpenCV and downloaded model files. This build therefore runs that engine **locally on the Intel laptop**, not inside the free Vercel serverless backend.

Do not add `requirements-local.txt` packages to the Vercel backend requirements.

When you push this project to the existing GitHub repo, Vercel can still build the public transcript/content app. Full Voice + Visual is available when the same frontend is run against the local backend with `LOCAL_SCORING_ENABLED=true`.
