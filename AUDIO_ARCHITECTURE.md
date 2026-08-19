# Clarivo audio architecture

The Record button intentionally captures the real compressed microphone Blob. Today the same Blob is used for English Whisper transcription; after the session is created it is stored locally in IndexedDB under the session ID.

Future Delivery analysis can reuse that exact recording for:

- speaking pace / WPM
- pauses
- filler words
- volume consistency
- prosody and timing metrics

Current public demo cap: 5 minutes. The UI/recording path does not need to be redesigned when Delivery analysis is added.
