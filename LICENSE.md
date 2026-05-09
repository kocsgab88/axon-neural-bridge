# AXON Source Available License v1.0

**Copyright (c) 2026 Kocsis Gábor. All rights reserved.**

This is a **proprietary, source-available license**. It is **not** an Open Source license as defined by the Open Source Initiative (OSI), and it is **not** a Free Software license as defined by the Free Software Foundation (FSF).

---

## 0. Definitions

- **"Software"** — the AXON Neural Bridge source code, configuration, prompts (`souls/*.md`), tests, documentation, and any other files contained in this repository, **excluding** the Excluded Assets listed in Section 6.
- **"Licensor"** — Kocsis Gábor, sole copyright holder of the Software.
- **"You" / "Licensee"** — the natural person or legal entity exercising rights under this License.
- **"Personal Use"** — non-commercial use by an individual natural person, exclusively for: (a) personal learning and education, (b) personal hobby projects with no revenue, and (c) academic research or coursework that is not funded by, performed for, or commissioned by any commercial entity.
- **"Commercial Use"** — any use that is not Personal Use, including but not limited to: (a) use within a for-profit organization (regardless of whether AXON itself generates revenue), (b) use to deliver paid services to third parties (including freelance, consulting, or contract work), (c) use in any product or service that generates revenue or is intended to generate revenue, (d) use by a non-profit organization in operational capacity, (e) hosting the Software as a service (SaaS) for any audience.
- **"Derivative Work"** — any modification, translation, adaptation, port, or work based on the Software.

---

## 1. Grant — Personal Use

Subject to Your continuous compliance with all terms of this License, the Licensor grants You a **worldwide, non-exclusive, non-transferable, non-sublicensable, royalty-free** license to:

1. **View** the source code of the Software.
2. **Run** the Software on hardware You control, solely for Personal Use.
3. **Modify** the Software and create Derivative Works, solely for Personal Use.
4. **Copy** the Software for backup and Personal Use purposes.

This grant **does not** include the right to distribute, sublicense, sell, or use the Software for Commercial Use.

---

## 2. Commercial Use — Separate License Required

Commercial Use of the Software is **prohibited** without a separate, signed commercial license agreement with the Licensor.

To obtain a commercial license, contact: **kocsgab88@gmail.com**

A commercial license may include, at the Licensor's sole discretion: per-seat pricing, revenue-share, a flat fee, or custom terms.

The following are explicitly Commercial Use and **require** a commercial license:
- Running AXON inside any company, agency, or for-profit team.
- Using AXON's output (generated code, cover letters, plans) in any paid client deliverable.
- Hosting AXON as a service for any user other than yourself.
- Bundling AXON or any Derivative Work into a paid product.
- Training any machine-learning model on the Software's source code, prompts, or outputs.

---

## 3. Redistribution

You **may not** redistribute the Software, in source or binary form, modified or unmodified, except:

1. As an unmodified link or reference to the Licensor's official repository.
2. As a Pull Request submitted back to the Licensor's official repository (see Section 5).

You **may not** publish Derivative Works of the Software in any public or private repository, package registry, container registry, or distribution channel without the Licensor's prior written permission.

---

## 4. Reserved Rights

All rights not expressly granted in this License are **reserved by the Licensor**. In particular, the Licensor reserves the exclusive right to:

- Sell, sublicense, or commercialize the Software.
- Create and distribute Derivative Works.
- Use the Software in commercial products and services.
- Grant additional or different licenses to other parties.

---

## 5. Contributor License Agreement (CLA)

By submitting any contribution (Pull Request, patch, suggestion, issue containing code, or any other content) to the Software's official repository, You agree that:

1. **Grant of Rights.** You grant the Licensor a perpetual, worldwide, non-exclusive, royalty-free, irrevocable license to use, reproduce, modify, sublicense, and distribute Your contribution under any license terms the Licensor chooses, including Commercial Use.
2. **Original Work.** Your contribution is Your original work, or You have the right to submit it under the terms of this CLA.
3. **No Warranty Obligation.** Your contribution is provided "as is," without any warranty.
4. **No Compensation.** You will not receive payment, royalty, or any other compensation for Your contribution unless agreed in writing in advance.
5. **Authority.** If You submit on behalf of an employer, You represent that You have authority to do so and that Your employer has waived any rights to the contribution.

If You do not agree to these CLA terms, **do not submit contributions**.

---

## 6. Excluded Assets

The following are **not** licensed under this License and remain the **exclusive proprietary property** of the Licensor. They are not included in this repository, or if accidentally present, no rights are granted in them:

- The AXON training corpus, fix samples, cache database (`axon.db`, `*.db`, `*.sqlite`), and all conversation history.
- Strategic documents (e.g., `AXON_MASTER_BRIEF.md`, `AXON_GENESIS_VISION.md`, `AXON_5YEAR_*`, `AXON_DECISION_FRAMEWORKS.md`, anything under `session/` or `strategic/`).
- API keys, environment files (`.env`, `_env`), and any credentials.
- Generated outputs in `outputs/` and uploaded files in `uploads/`.
- Internal session transcripts and any unpublished documentation.

If You obtain any Excluded Asset by any means, You must delete it immediately and notify the Licensor.

---

## 7. Trademarks

"AXON", "AXON Neural Bridge", and any associated logos or marks are trademarks of the Licensor. This License does **not** grant any right to use these trademarks except as required for accurate attribution under Section 8.

---

## 8. Attribution

Any permitted use must preserve all copyright notices, this License file, the `NOTICE.md` file, and any per-file copyright headers. You may not remove or obscure attribution.

---

## 9. Termination

This License terminates **automatically** if You violate any of its terms. Upon termination, You must:

1. Cease all use of the Software.
2. Delete all copies of the Software in Your possession or control.
3. Destroy any Derivative Works.

The Licensor may also terminate this License at any time by written notice for cause. Sections 4, 5, 6, 7, 10, 11, and 12 survive termination.

---

## 10. Disclaimer of Warranty

THE SOFTWARE IS PROVIDED **"AS IS"**, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, AND ACCURACY. THE LICENSOR DOES NOT WARRANT THAT THE SOFTWARE WILL BE ERROR-FREE, SECURE, OR UNINTERRUPTED.

The Software invokes third-party APIs (Anthropic Claude, Google Gemini, Telegram). The Licensor is not responsible for the behavior, availability, cost, or output of those services.

---

## 11. Limitation of Liability

IN NO EVENT SHALL THE LICENSOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING LOSS OF PROFITS, DATA, OR USE) ARISING IN ANY WAY OUT OF THE USE OF OR INABILITY TO USE THE SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.

In jurisdictions that do not allow the exclusion or limitation of liability for consequential or incidental damages, the Licensor's liability is limited to the maximum extent permitted by law and shall not exceed **EUR 50** in aggregate.

---

## 12. Governing Law and Jurisdiction

This License is governed by the laws of **Hungary**, without regard to its conflict-of-laws principles. Any dispute arising out of or related to this License shall be submitted to the exclusive jurisdiction of the courts of **Budapest, Hungary**.

If any provision of this License is held unenforceable, the remaining provisions remain in full effect.

---

## 13. Entire Agreement

This License (together with any signed commercial license under Section 2) constitutes the entire agreement between You and the Licensor regarding the Software and supersedes all prior or contemporaneous understandings.

---

## Contact

- **Email:** kocsgab88@gmail.com
- **GitHub:** [@kocsgab88](https://github.com/kocsgab88)

---

*AXON Source Available License v1.0 — 2026-05-09*
