# Frontend implementation notes

Astra-FractureAI uses a no-build Vue 3 single-page frontend served by the Flask backend. The browser loads the page and the `/api/*` endpoints from the same origin; there is no separate Node, npm, Vite, or TypeScript build step.

## Runtime

Start the backend from the project root:

```bash
python app.py
```

Open the port configured by `PORT` in `.env`. If it is not set, the backend defaults to `8080`:

```text
http://localhost:<PORT>/
```

The frontend is served through:

- `/` → `frontend/index.html`
- `/frontend/<path>` → static frontend assets
- `/api/*` → Flask API routes

The initial page load requires access to `unpkg.com` because the current implementation loads its browser dependencies from fixed CDN URLs.

## Fixed browser dependencies

| Dependency | Version |
|---|---:|
| Vue | `3.5.22` |
| Element Plus | `2.11.7` |
| Element Plus Icons Vue | `2.3.2` |
| Cropper.js | `1.6.2` |
| marked | `12.0.2` |
| DOMPurify | `3.1.6` |

The dependency URLs and load order are defined in `frontend/index.html`. Do not silently replace them with `@latest` URLs when debugging a release.

## Interaction flow

1. The user selects or drops a PNG/JPEG X-ray image.
2. Cropper.js provides crop and 90-degree rotation controls.
3. The workbench submits the image and detection parameters to `POST /api/detect`.
4. The backend runs three concurrent detection tasks: `position`, `range`, and `kind`.
5. The viewer projects returned coordinates onto the source image using the backend `image_size` metadata.
6. Canvas tools provide window/level, zoom, pan, rotation, length, angle, and reset actions.
7. Results are sorted into confidence cards; partial model failures remain visible as non-blocking warnings.
8. `POST /api/explain` streams the multimodal explanation through SSE.
9. The client buffers chunks across network boundaries, preserves the raw Markdown text, then renders it through `marked.parse()` and `DOMPurify.sanitize()`.

## Frontend modules

| File | Responsibility |
|---|---|
| `index.html` | Application shell, fixed CDN dependencies, and local script order |
| `app.js` | Home view, root view switching, health state, settings bootstrap, and Vue mount |
| `workbench-template.js` | Workbench template markup |
| `workbench-view.js` | Upload, crop, detection, viewer tools, SSE consumption, settings, and report rendering |
| `ui-text.js` | Fixed detection label mappings |
| `style.css` | Responsive dark workbench and landing-page styling |

## API contract used by the frontend

### Health

```text
GET /api/health
```

Used to display backend status and the configured model list. Credentials are not stored in or returned to the browser.

### Detection

```text
POST /api/detect
Content-Type: multipart/form-data
```

The workbench sends:

- `file`
- `conf` in `0.01`–`1.00`
- `iou` in `0.00`–`0.95`
- `imgsz` as `320`, `640`, or `1280`

The response includes `image_size`, the three detection result groups, timing metadata, and any partial-failure errors.

### Explanation

```text
POST /api/explain
Content-Type: application/json
```

The streaming request includes `image_base64`, `yolo_result`, and `stream: true`. The response uses Server-Sent Events and ends with one `[DONE]` marker.

The frontend ignores stale responses after a new run, cancels active requests with `AbortController`, and does not render raw stream text directly as HTML.

## Browser persistence and safety

The browser stores only the existing workbench settings under the `astra-fractureai-settings` key. It does not store YOLO or LLM API keys. Treat any image uploaded to a configured remote service as external data and use only synthetic, public, or explicitly authorized non-sensitive images.

This interface is a research preview and not a medical device. It does not provide a diagnosis or treatment recommendation and must not replace qualified clinical judgment.
