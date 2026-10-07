# Validation — 0.3.4, 2026-10-07

Windows bind-mount fix: 262 regression tests, 261 passed, one Windows symlink
privilege skip. Log: docs/validation/BIND_REGRESSIONS.log. New tests simulate
unsupported chmod without ignoring actual byte-copy failures, check native pip
staging/mount isolation, and verify Reporter gets observation tools only.

Real SDK/PyPI/Docker integration on G: passed after the live smoke exposed EPERM
in pip copymode. cbor2 6.1.5 downloaded and installed; byte export tolerated 1
fetch and 16 install mode updates unsupported by the Windows mount. Actual
5282-byte export round-trip/hash/corruption checks succeeded, two experiments,
one test receipt, audit verified. Scripted model, zero paid inference. Receipt:
docs/validation/BIND_SDK_DOCKER.json. New live cheap-model run remains next.

Previous validation:

Candidate upgrade: 259 regression tests, 258 passed, one Windows symlink privilege
skip. Log: docs/validation/CANDIDATE_REGRESSIONS.log. Eight new gate tests cover
actual DNS duplicate wording with retained contributors, materially different
payload (including a misleading identical agent family label), uncertain proposal retention, stale/unknown target, untested draft,
successful promotion and changed artifact refusal, and real SDK cheap-model
accounting/history preservation (scripted responses, no paid inference).

Real SDK tool dispatch to real PyPI/Docker passed: cbor2 installed, actual public
5282-byte TXT export encoded and decoded with SHA256 equality, modified payload
rejected. Two Docker experiments, one test receipt, candidate PROTOTYPED only
after record_test, production input unchanged, network denied/key absent, audit
verified. Receipt: docs/validation/SDK_DOCKER_CHAIN.json. The model decisions were
scripted, not GPT inference. run-smoke.cmd is the next cheap-model autonomy test;
no OPENAI_API_KEY is available in this Codex process. No live research/deposit
or paid model call was performed during this upgrade.

Earlier validation follows as historical evidence:

Generation upgrade: replay of the actual recorded AGENT-005:8 response classifies
three completed searches and the ignored resultless pending attempt after the
configured provider cap. Both real QR/XMP candidate descriptions now resolve to
one card mechanism independently of their embedded ORCID attribution. The latest
bounded prior inventory contains 40 candidate observations with original refs.
Receipts: `docs/validation/GENERATION_REPLAY.json` and final installed
`GENERATION_REGRESSIONS.log`. New tests exercise real SDK tool/schema forwarding,
cross-run deferral versus local continuation, provenance, prior candidates beyond
the first three titles, and stopping UNKNOWN reservations without dispatch cascade.
Actual over-bound, failed, incomplete and orphan usage still fails closed.
Final installed suite: 251 tests, 250 passed and one Windows symlink-permission
skip. Owner rejections remain REJECTED even when the mechanism appears in prior
work; novelty-first never weakens this binding policy.
Models, global token/runtime/USD settings, owner permissions and old ledgers are
preserved. No paid API request was made. A new cheap live run is still required
to assess research quality; replay/regressions cannot establish that quality.

## Historical validation — 0.3.1

The dependency upgrade adds any named PyPI package, extras/version requirements,
an isolated online wheel build and an offline persistent workspace installation.
There is no package whitelist or individual approval after this capability is
enabled. Research profile settings supplied by the owner are preserved.

The real Docker smoke test installed Pillow 12.3.0, qrcode 8.2 and cbor2 6.1.5;
tested a real CBOR round-trip and QR PNG; reopened the workspace in a new
container and imported the packages again. Experiment network access was denied,
credentials/socket were absent, containers were removed, and the production-style
fixture stayed unchanged. Receipts: `docs/validation/PIP_DOCKER_INSTALL.json`,
`PIP_DOCKER_EXPERIMENT.json`, `PIP_DOCKER_REOPEN.json` and `PIP_DOCKER.log`.

New offline coverage exercises SDK argument/schema forwarding, arbitrary names,
invalid URL/path/option rejection, isolated mounts, wheel hashes, bounded output,
limits, supervised selection, cancellation cleanup/error receipts, unfinished
operation blocking, checkpoint/report/manifest persistence and exclusion of
installed libraries from production review patches. The final installed suite
is retained in `docs/validation/PIP_REGRESSIONS.log`: 241 tests, 240 passed and
one Windows symlink-permission skip; junction/reparse guards ran. No paid API calls or
model research run were made during this dependency upgrade. Public website
documentation and historical run ledgers were not edited.

## Historical validation — 0.3.0

Installed framework: `G:\vojtamaur-web\scripts\metaweb-swarm`.
The final complete installed regression suite passed 231 checks: 230 successful,
one symlink creation check skipped because this Windows token lacks permission.
Windows junction/reparse guards ran. Model/pricing/legacy reconciliation checks
and both project-owned launchers were verified against the installed framework.

Receipts are copied into `docs/validation/` so this record survives deletion of
the Codex chat workspace. `REGRESSIONS.log` records the installed suite;
`MODEL_TIERS.log` records latest model/legacy-reconciliation checks;
`SANDBOX_LAUNCHER.log` and `SUPERVISED_LAUNCHER.log` record real Windows CMD
launchers against a separate offline fixture. Sandbox fixture ends BLOCKED due
to deliberate demo human-action examples; supervised fixture completes research
without rejecting deferred implementations. These are not live research runs.

New coverage includes per-agent SDK model routing through three injected local
models, model and usage persistence across reopen, USD prices per actual model,
aggregate/model accounting consistency, safe legacy reconciliation, global CLI
model override, missing-key fail before initialization, reporter completion when
discovery search reservation cannot fit, CC REL scope aliases, exact QR duplicate
claims with differing keys, immutable provenance, and rejection of unbound test
receipts. No paid OpenAI request was made during this upgrade.

Docker daemon/image readiness was checked read-only with normal host permissions:
`metaweb-swarm-experiment:local` is available. No new container was started for
this upgrade. The two actual containers from the reviewed live run and their
prototype limitations are documented in `docs/RUN_REVIEW_20261007.md`.
New model tiers all remain `gpt-5.4-mini`; global budgets and external scope are
unchanged. A fresh cheap live run must still confirm research quality, standards
fidelity and the improved role finishing behavior. These are not proven by mocks.

Reviewable source patch, installation hashes and pre-upgrade backups were also
saved in the original task outputs. This project's launchers/instructions have
no runtime dependency on those files. Public website documentation was untouched.

## Historical validation — 0.2.0


Installed framework: G:\vojtamaur-web\scripts\metaweb-swarm.
217 regression tests: 216 passed, one skipped because this Windows token cannot
create symbolic links. Windows junction/reparse guards were actually exercised.
Receipt: AUTONOMY_INSTALLED_TESTS.txt in the task's outputs directory.

Coverage includes SDK 0.23.1 with a local fake model, independent execution modes,
research completion without implementation, real temporary-file deposits with
approval on/off, loopback PUT/GET read-back, credentials isolation, redirect/error
handling, process deadline against drip-fed HTTP, global request reservations,
unknown/crash recovery, action and byte caps, pause/resume, hash-chain audit,
public export copies over 20 MB, cross-run read-only notes, and S3/ORCID dedup with
provenance and provider/scope separation. Fake model calls cost zero USD.

Docker Desktop 4.94.0 and the local experiment image were installed during setup.
Seven real Docker smoke checks passed at that time: non-root user, no host secrets,
read-only root/network denial/tmp noexec, cgroup limits, timeout/OOM/output bounds,
private-file changes with reviewable patch, and complete container cleanup.
Receipt: DOCKER_SMOKE.json. This is historical evidence; it does not claim the
operator currently has Docker running. No further Docker startup is needed for
this regression suite.

No paid OpenAI request, real archive-provider upload, payment, or production
experiment was made. Live cheap-model acceptance of the new API settings and
the whole discovery-to-deposit flow remains the next test phase. Initial deposit
connectors are free configured local-directory/HTTP PUT resources; account and
payment executors are not implemented. USD enforcement depends on correct
operator price ceilings/search bounds. Writable Docker bind mounts still lack
a hard disk quota. These are open work, not passed tests.
