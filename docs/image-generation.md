# Image generation

The plugin does not provide an `image_gen` provider for Hermes' `image_generate`. Configure another provider.

## What was tried (November 2026)

- **The model the backend picks.** `v1internal:fetchAvailableModels` lists one image model in
  `imageGenerationModelIds`: `gemini-3.1-flash-image`. `fetchConfig` names the same model in
  `agySurfaceConfig.imageGenerationExperiences`. Antigravity's docs say the image model is not customizable.
- **The plugin's own request.** A provider built on the plugin's client (credentials, endpoints, error handling)
  sent `generateContent` with that model. Every request failed with `500 Internal error encountered.`
- **The official `agy` client (1.5.18).** Asked for a picture, `agy` starts an `image-generator` subagent whose
  `generate_image` tool sends:

  ```json
  {"project": "...", "requestId": "image_gen/<ms>/<id>/<n>",
   "request": {"contents": [{"role": "user", "parts": [{"text": "..."}]}],
               "generationConfig": {"candidateCount": 1, "imageConfig": {"aspectRatio": "1:1"}}},
   "model": "gemini-3.1-flash-image", "userAgent": "antigravity", "requestType": "image_gen"}
  ```

  to `daily-cloudcode-pa.googleapis.com/v1internal:generateContent`, with only the usual headers. Each tool call
  makes three HTTP attempts. In three runs, every attempt returned the same 500. `agy` then drew an SVG itself and
  said the image service had a server error; no PNG or JPEG was written.

So the failure is on the backend, not in the request format. Every test used the same Google account, so an
account-specific failure is not ruled out. Users on Google's forum reported the same 500 on image generation, and
503 `No capacity` and 429 errors on `gemini-3.1-flash-image`, in the same weeks.

## If it starts working

The request above is what a provider would send. Pass 429 and 503 messages through unchanged and do not retry them:
`agy`'s own subagent prompt says not to retry quota or capacity errors.
