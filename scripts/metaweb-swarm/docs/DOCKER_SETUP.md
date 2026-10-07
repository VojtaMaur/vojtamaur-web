# Docker and sandbox setup

This document belongs to the swarm framework. It is not part of the public website documentation. Update the checked-state section after each installation or runtime test; setup instructions alone are not evidence that a sandbox works.

## Checked state — 2026-10-07

- Windows 10 Pro 22H2, build 19045.6466; Intel i9-11900K; 32 GiB RAM.
- WSL 3.0.1.0, kernel 6.18.40.1; default WSL version 2; no user Linux distributions installed.
- Windows reports `HypervisorPresent=true`. Individual processor virtualization flags were false while the hypervisor was present; do not treat those flags as proof that BIOS virtualization is disabled.
- `LanmanServer` is running and automatic. `WslService` is running.
- Before installation, Docker CLI and Docker Desktop were absent from PATH, the conventional machine installation, and the per-user installation location.
- WinGet 1.29.380 is available outside the Codex filesystem sandbox. Some read-only WSL/CIM commands require unsandboxed execution; enumerating Windows optional features additionally requires an administrator token.
- Optional-feature state and a working Linux VM have not been proved by the readiness check. The readiness check did not install software or create containers.

## Installation performed — 2026-10-07

The official Docker Desktop 4.94.0 installer was downloaded into the task's `outputs/cache` directory. Its SHA256 matched WinGet metadata exactly and its Authenticode signature was valid for Docker Inc. Installation used `install --user --backend=wsl-2 --no-windows-containers --quiet --wsl-default-data-root=G:\metaweb-swarm-docker-data`; the installer exited 0 and recorded `Installation succeeded`.

The application is installed at `C:\Users\Vojta\AppData\Local\Programs\DockerDesktop`. The bundled CLI reports Docker 29.8.2. The installer settings confirm `wslDefaultDataRoot=G:\metaweb-swarm-docker-data` and `noWindowsContainers=true`. The G: data location is outside the production project; it was selected because C: had about 9 GiB free while G: had about 386 GiB free.

No `--accept-license` flag was used and no reboot was requested by the agent. Immediately after installation, Docker Desktop/backend processes were absent and `docker info` reported the missing local `docker_engine` pipe. Docker Desktop was then launched; the Linux daemon became reachable without the agent clicking or accepting a license agreement. Existing user state may explain that behavior, but no assumption about an unseen dialog is needed: the daemon check returned `linux`. The `main` and `disk` directories were created under the selected G: data root.

Preserve `outputs/cache/docker-install-receipt.json`, `docker-install-stdout.txt`, `docker-install-stderr.txt`, and the installer log under `%LOCALAPPDATA%\Docker\install-log.txt` as installation evidence.

## Actual sandbox tests — 2026-10-07

The reviewed Dockerfile was copied to a minimal private build context containing only that file (2 KiB context). The prepared image `metaweb-swarm-experiment:local` was built from official `python:3.11-slim`, observed base digest `sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce`. The exact resulting image ID is retained in `outputs/DOCKER_SMOKE.json`; the build log is in `outputs/cache/docker-image-build.txt`.

The actual `DockerExecutor` passed seven checks in a tiny framework-created private workspace:

- Successful text/binary outputs; only the copied source changed. Original fixture and snapshot were unchanged; a reviewable patch was exported.
- Unprivileged UID, no injected synthetic host sentinel or OpenAI key, dropped capabilities, no-new-privileges and seccomp observed.
- External network connection blocked, read-only container root, no-exec `/tmp` observed.
- Cgroup settings observed: 512 MiB memory, 64 PIDs and one CPU.
- An exit-code-7 command became BLOCKED; a sleeping command reached the runtime limit; a 2 GiB allocation hit the container memory limit.
- Output was truncated at 100,000 bytes without retaining an unbounded stream.
- All independently named experiment containers were removed after successful, failing and limited runs.

There were zero model/API calls. Production was never mounted or executed. These live tests prove the tested runtime properties; they do not establish a hard quota for writable bind-mount disk storage.

The exact executor environment with a fresh empty `DOCKER_CONFIG` connected successfully to the local Linux engine and found the image. No workspace.py environment fix was required. A process-level PATH refresh was required because the already-running terminal did not know the new CLI directory. A first build using the user's Docker config failed because its credential helper was absent from that old PATH; the corrected build used a clean task-specific config and no registry credentials. That clean config selected Docker's legacy builder, which emitted a deprecation notice but successfully built the image. Future BuildKit configuration can be prepared separately without copying user credentials.

## Installation path

Docker recommends per-user installation with WSL 2. That mode avoids a privileged helper service and installs under `%LOCALAPPDATA%\Programs\DockerDesktop`. An Ubuntu installation is unnecessary for Windows Docker commands. WSL 2.1.5 or newer is required; the installed WSL is newer. Enabling missing WSL components requires administrator privileges and may require a reboot. Do not reboot automatically. [Docker installation](https://docs.docker.com/desktop/setup/install/windows-install/), [WSL backend](https://docs.docker.com/desktop/features/wsl/), [Windows permissions](https://docs.docker.com/desktop/setup/install/windows-permission-requirements/).

The Docker documentation lists this Windows build, but also limits support to Microsoft's servicing lifecycle. The readiness check did not determine ESU enrollment or lifecycle eligibility. Personal use is eligible for the free Docker Desktop license. [Docker installation requirements](https://docs.docker.com/desktop/setup/install/windows-install/).

Use the official installer directly when per-user WinGet scope support is unclear. On 2026-10-07, `winget show --id Docker.DockerDesktop --exact --source winget --disable-interactivity` returned version 4.94.0, release 2026-10-02:

```text
URL: https://desktop.docker.com/win/main/amd64/241994/Docker%20Desktop%20Installer.exe
SHA256: a9814e31049d66156477a86614e83365669677733014ec72f74229623ff3890a
```

This is the metadata observed on that date, not a promise that a moving download endpoint always serves that version. Download to a task-specific directory, verify the exact SHA256 and a valid Docker Authenticode signature before running it. Retain download metadata and the installation log as audit artifacts.

PowerShell, once the verified installer is saved locally:

```powershell
$dockerInstaller = 'C:\path\to\Docker Desktop Installer.exe'
$dockerInstallProcess = Start-Process -FilePath $dockerInstaller -WindowStyle Hidden -Wait -PassThru -ArgumentList 'install', '--user', '--backend=wsl-2', '--no-windows-containers', '--quiet', '--wsl-default-data-root=G:\metaweb-swarm-docker-data'
$dockerInstallProcess.ExitCode
```

The `--accept-license` flag accepts the Docker license rather than showing it on first launch; use it only after that acceptance is authorized. Otherwise launch Docker Desktop and accept the displayed agreement. Installation does not itself start Docker Desktop. [Official installer flags](https://docs.docker.com/desktop/setup/install/windows-install/).

If first launch reports missing WSL components, stop and record its exact error. An administrator can use `wsl --install --no-distribution` to enable the required platform without adding Ubuntu. Restart only when Windows actually requests it; then resume setup from the saved checkpoint. Do not assume a reboot is required merely because Docker was installed. [Microsoft WSL commands](https://learn.microsoft.com/en-us/windows/wsl/basic-commands).

## Readiness and first smoke test

After Docker Desktop has started, open a fresh terminal so PATH changes are visible. Verify the daemon is Linux, then explicitly build the reviewed experiment image from a minimal context containing only its Dockerfile and approved dependencies:

```cmd
docker info --format "{{.OSType}}"
docker build --tag metaweb-swarm-experiment:local --file Dockerfile .
G:\metaweb-swarm-env\Scripts\python.exe swarm.py doctor --docker-check
```

The example assumes the current directory contains only the reviewed image build context. Never use the entire production project as a Docker build context. Record the resulting image ID/digest; pin it for reproducible experiments. The framework does not pull images during experiments.

`doctor --docker-check` is read-only and does not run a container. A passing doctor check is not a passing sandbox test. The first actual test must use a framework-created agent workspace outside production and check: a small output file, an intentionally failing command, timeout, inaccessible external network, absent credentials, resource limits, and cleanup. Keep exact outputs in the run audit. Do not call a mock executor test a live Docker test.

## Installing tools while keeping agent code offline

Current execution uses `--network none`, a read-only root filesystem, an unprivileged user, dropped capabilities, CPU/memory/PID limits, an independent watchdog, and only the agent's copied workspace mounted. The agent receives no Docker socket, production directory or host credential environment. These protections remain in supervised and autonomous modes; external actions use a separate broker.

The implemented package broker accepts any named PyPI package, extras and version
constraint, without a package whitelist. `config.research.json` enables it;
the base config and old runs without the capability keep it disabled. See
[PACKAGES.md](PACKAGES.md) for agent usage, configuration and verified receipts.

It runs fixed `pip wheel` in an online, bounded container mounting only a new
empty build directory. Source builds are allowed. That container receives no
project, exports, credentials or Docker socket. A second networkless container
installs the resulting wheels from a read-only wheelhouse into the agent's
private `.packages`. Experiment Python imports/console scripts use that path;
packages persist across rounds and resume. Containers retain the existing
unprivileged/read-only-root/capability/resource/watchdog/cleanup protections.
The online bridge is not a PyPI-only egress firewall; build hooks can contact
other destinations. Size checks after phases do not enforce a live disk quota.

Other ways to supply system tools or offline dependencies:

1. **Prepared image.** Build Python/Node and selected system tools into a reviewed image before a run. Installation-time network traffic is separate from untrusted runtime code. Use version locks, package hashes where available, a minimal context, and no account credentials. Record the image digest and dependency manifest in the run.
2. **Offline package inventory.** Put reviewed, versioned wheels in the image, for example under `/opt/wheelhouse`. Include transitive dependencies. Agents can create a workspace virtual environment and run `python -m pip install --no-index --find-links=/opt/wheelhouse --only-binary=:all: --require-hashes -r requirements.lock`. Record the resolved packages and installer output. Use wheels for the container's Linux architecture and Python version; Windows wheels do not work in Linux. Reject missing packages explicitly rather than silently enabling network access.

Installed packages contain executable code. Offline experiments cannot perform
arbitrary network writes; that does not make dependencies safe. Native tools
needing root or unavailable compilers/libraries should be prepared in the image.
The broker permits source builds in its isolated staging directory; a missing
tool/library is an explicit BLOCKED capability gap.

On 2026-10-07 the actual broker fetched Pillow, qrcode and cbor2, then installed
and tested them offline: real CBOR round-trip, QR PNG, persistent imports after
reopen, absent credentials, blocked experiment network and successful container
cleanup. Receipts are in `docs/validation/PIP_DOCKER_*.json`. Paid API calls: 0.

## Resource and filesystem limits still to verify

CPU, memory, PIDs and elapsed time do not impose a hard byte quota on a writable host bind mount. Post-run size checks cannot prevent a running experiment from filling a drive. Use a dedicated bounded filesystem/volume or another enforceable storage quota before claiming disk storage is hard-limited. Limit artifact ingestion separately.

The temporary isolated Docker client configuration intentionally avoids the user's registry credentials. It may also omit Docker Desktop's selected context. Test that exact environment against the local Linux daemon. If an endpoint is needed, explicitly bind it to an allowed local named pipe/socket; do not copy arbitrary Docker configuration or permit agent-selected remote Docker endpoints.

Docker is still a host service and is not a guarantee against kernel/container escape. A separate host or VM is the stronger boundary for adversarial workloads. No host execution fallback is allowed when Docker is unavailable.
