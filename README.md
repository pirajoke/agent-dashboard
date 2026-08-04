# Agent Dashboard

Static publishing surface and Python builder for an agent-orchestration command center. It combines project state, runtime health, usage, communications, and local service controls into one browser dashboard.

The public repository contains the builder, a generated static snapshot, and privacy-focused tests. Live owner actions require an explicitly configured loopback service and are not available from the public GitHub Pages view.

## Repository map

| Path | Purpose |
|---|---|
| `builder/dashboard_builder/` | Modular Python dashboard builder |
| `builder/dashboard-assets/` | Shared CSS, JavaScript, and visual assets |
| `builder/dashboard-server-m4.py` | Local owner API with authentication and privacy filtering |
| `builder/tests/` | Builder, authentication, and privacy regression tests |
| `index.html` | Published static dashboard snapshot |
| `live-feed.json` | Sanitized generated feed used by the static view |
| `docs/` | Architecture and product-review notes |

## Local validation

The builder uses only the Python standard library. Run its deterministic checks from the repository root:

```bash
PYTHONPATH=builder python3 -m unittest discover -s builder/tests -v
python3 -m compileall -q builder
python3 -m json.tool live-feed.json >/dev/null
```

## Runtime model

The production builder runs on an owner-controlled Mac mini and reads approved local operational sources. It produces:

- a local interactive dashboard;
- a sanitized static snapshot for GitHub Pages;
- an Obsidian operations summary.

Source changes belong in `builder/`. Runtime deployment and publication are separate operator actions and are intentionally not performed by CI.

## Security boundary

- Never publish tokens, raw task content, private issue titles, chat messages, local file contents, or unsanitized health payloads.
- Public endpoints fail closed and expose only allowlisted aggregate fields.
- Owner-only task detail and write actions require the local bearer-token flow.
- Browser-side calls to the owner API stay on loopback; the static page must remain useful when that API is unavailable.
- Review generated `index.html` and `live-feed.json` before publishing them.

## License

MIT. See [`LICENSE`](LICENSE).
