# NOTICE

**AXON Neural Bridge**
Copyright (c) 2026 Kocsis Gábor. All rights reserved.

This product is licensed under the **AXON Source Available License v1.0**.
See [LICENSE.md](LICENSE.md) for the full terms.

For commercial licensing inquiries: **kocsgab88@gmail.com**

---

## Project Identity

| Field         | Value                                        |
|---------------|----------------------------------------------|
| Name          | AXON Neural Bridge                           |
| Version       | 9.1                                          |
| Author        | Kocsis Gábor (Budapest, Hungary)             |
| Repository    | https://github.com/kocsgab88/axon-neural-bridge |
| Contact       | kocsgab88@gmail.com                          |

---

## Excluded from this Repository

The following are **proprietary** and **not** distributed under the AXON Source Available License. They are excluded from the public repository and remain the exclusive property of the Licensor:

- **Training corpus and datasets** — `axon.db`, all `*.db`, `*.sqlite`, `*.sqlite3` files
- **Strategic documents** — `AXON_MASTER_BRIEF.md`, `AXON_GENESIS_VISION.md`, `AXON_5YEAR_COST_PROJECTION.md`, `AXON_DECISION_FRAMEWORKS.md`, contents of `session/`, `strategic/`
- **Secrets** — `.env`, `_env`, any credential or API key
- **Runtime artifacts** — `outputs/`, `uploads/`, `logs/`

---

## Third-Party Components

AXON Neural Bridge integrates with the following third-party services and libraries. Each retains its own license, terms, and copyright. Use of these components is subject to their respective terms.

### External APIs (network services)

| Service                  | Provider          | Terms                                                          |
|--------------------------|-------------------|----------------------------------------------------------------|
| Claude (claude-sonnet-4-6) | Anthropic, PBC | https://www.anthropic.com/legal/commercial-terms              |
| Gemini 2.5 Flash         | Google LLC        | https://ai.google.dev/terms                                    |
| Telegram Bot API         | Telegram FZ-LLC   | https://core.telegram.org/bots/terms                           |

> The Gemini integration assumes a **paid tier** API key. Use of the free tier may permit the provider to retain prompts for model training, which is incompatible with the confidentiality expectations of AXON's intended use cases.

### Python Libraries (runtime dependencies)

The Software depends on third-party Python packages whose licenses are listed below. The Licensor makes no representation about these licenses; consult each package's own metadata for authoritative terms.

| Package                  | Typical License | Purpose                                  |
|--------------------------|-----------------|------------------------------------------|
| `python-telegram-bot`    | LGPL-3.0        | Telegram bot framework (PTB v20+)        |
| `anthropic`              | MIT             | Claude API client                        |
| `google-generativeai`    | Apache-2.0      | Gemini API client                        |
| `pydantic`               | MIT             | Data model validation (v2)               |
| `python-dotenv`          | BSD-3-Clause    | `.env` file loading                      |
| `pytest`                 | MIT             | Test runner                              |
| `pytest-asyncio`         | Apache-2.0      | Async test support                       |
| `psutil`                 | BSD-3-Clause    | System monitoring (`axon_watchman.py`)   |

A complete and authoritative dependency list is in `requirements.txt`.

### Standard Library

This Software uses the Python Standard Library, distributed under the **Python Software Foundation License**. See https://docs.python.org/3/license.html.

---

## Trademarks

"AXON", "AXON Neural Bridge", and the AXON logo are trademarks of Kocsis Gábor. All other trademarks (Anthropic, Claude, Google, Gemini, Telegram, Python, etc.) are the property of their respective owners.

---

## Disclaimer

THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. See LICENSE.md Sections 10 and 11 for the full disclaimer of warranty and limitation of liability.

---

*Last updated: 2026-05-09*
