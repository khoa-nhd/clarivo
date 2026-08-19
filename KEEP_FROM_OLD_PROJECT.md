# Old AI files — already integrated

You do **not** need to copy files from the old project anymore.

The important old files are already included here:

```text
backend/
└── legacy_ai/
    ├── prompt_builder.py
    └── schemas.py
```

They are actively used by the public evaluator:

```text
app/evaluator.py
  -> app/prompt.py
      -> legacy_ai/prompt_builder.py
      -> legacy_ai/schemas.py
  -> Cloudflare Workers AI / Qwen3
  -> strict legacy schema validation
  -> adapter to the website report schema
```

### Preserved behavior

- Audience calibration
- Correctness / completeness / logical flow / clarity
- Examples
- Jumped steps where higher score means better reasoning continuity
- Audience fit
- ASR-awareness rules
- Exact transcript sentence evidence
- Up to 6 issues
- 3–5 top priorities
- `overall_feedback`
- `revision_guidance`

The website adapter maps `overall_feedback` to the UI field `feedback` and keeps `revision_guidance` as its own report section.

### What was intentionally NOT copied

- `.venv`
- installed Python libraries
- local Ollama model files
- old terminal/CLI loops
- OpenVINO/audio code (those phases are postponed)
- the incomplete old local configuration file

Keep your original old project separately as a backup/local-mode reference, but this public MVP does not require it to run.
