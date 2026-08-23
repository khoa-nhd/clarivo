# Integration notes

Files from the uploaded local v11 project used directly in this build:

- `backend/local_scoring/audio_analyzer.py`
- `backend/local_scoring/vision_analyzer.py`
- `backend/local_scoring/config.py`
- `backend/local_scoring/device_utils.py`
- `backend/local_scoring/utils.py`
- v11 scoring/reference notes

The web integration intentionally does not use `record_session.py`, `realtime_coach.py`, or the local OpenVINO Whisper path. The browser already records the session and Cloudflare Whisper already produces the transcript. The final reviewed/web transcript is passed into the v11 audio analyzer, matching the v11 recommendation to trust the web transcript for final pace/filler scoring.

`setup_delivery_models.py` downloads only the vision models needed by the web workflow.
