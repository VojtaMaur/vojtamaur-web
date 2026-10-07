"""Any named PyPI package; online builds see no project, offline installs persist."""
import hashlib
import json
import re
import tempfile
import time
from email.parser import BytesParser
from pathlib import Path

from .workspace import DockerExecutor, SecurityError, _plain_absolute, _inventory, _read_bytes, _WORKSPACE_MARKER

_SPEC = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9._-]+(?:\s*,\s*[A-Za-z0-9._-]+)*\])?"
    r"(?:\s*(?:===|==|!=|~=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+(?:\s*,\s*(?:===|==|!=|~=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+)*)?")

# Fixed host-owned driver, executed ONLY inside Docker. pip's copy/copystat on
# Windows bind mounts can fail after copying bytes because chmod is unsupported.
# Build/install on native container storage; explicitly export bytes afterwards.
PACKAGE_DRIVER = r'''
import errno, json, os, pathlib, shutil, stat, subprocess, sys
mode, specs = sys.argv[1], json.loads(sys.argv[2])
local = pathlib.Path('/package-tmp/result')
local.mkdir()
base = [sys.executable, '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check']
if mode == 'fetch':
    cmd = base + ['wheel', '--index-url', 'https://pypi.org/simple', '--no-cache-dir', '--no-input', '--progress-bar', 'off', '--retries', '1', '--timeout', '20', '--wheel-dir', str(local)] + specs
    target = pathlib.Path('/workspace/wheels')
elif mode == 'install':
    cmd = base + ['install', '--no-index', '--find-links', '/wheels', '--only-binary=:all:', '--no-input', '--no-cache-dir', '--target', str(local)] + specs
    target = pathlib.Path('/workspace/.packages')
else: raise ValueError('Unknown fixed package phase')
code = subprocess.call(cmd)
if code: sys.exit(code)
target.mkdir(exist_ok=True)
assert not target.is_symlink() and target.resolve().parent == pathlib.Path('/workspace').resolve()
metadata_skipped = 0
def export_file(source, destination):
    global metadata_skipped
    assert source.is_file() and not source.is_symlink()
    assert not destination.is_symlink() and destination.resolve().is_relative_to(target.resolve())
    shutil.copyfile(source, destination)
    wanted = stat.S_IMODE(source.stat().st_mode) & 0o777
    try: destination.chmod(wanted)
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.ENOTSUP}: raise
        # A console script must remain executable even where POSIX modes cannot
        # be changed. Read/write/copy errors are never suppressed.
        if wanted & 0o111 and not destination.stat().st_mode & 0o111: raise
        metadata_skipped += 1
for directory, folders, files in os.walk(local, followlinks=False):
    assert not any((pathlib.Path(directory)/name).is_symlink() for name in folders+files)
for child in local.iterdir():
    dest = target/child.name
    assert not dest.is_symlink() and dest.resolve().parent == target.resolve()
    if dest.exists():
        if dest.is_dir(): shutil.rmtree(dest)
        else: dest.unlink()
    if child.is_dir():
        dest.mkdir()
        for directory, folders, files in os.walk(child):
            relative = pathlib.Path(directory).relative_to(child)
            output = dest/relative
            for name in folders: (output/name).mkdir()
            for name in files: export_file(pathlib.Path(directory)/name, output/name)
    else: export_file(child, dest)
print('Exported package bytes; unsupported POSIX mode updates:', metadata_skipped)
'''


def requirements(packages):
    if not isinstance(packages, list) or not 1 <= len(packages) <= 32:
        raise ValueError("Choose 1..32 named PyPI requirements per call")
    result = []
    for item in packages:
        if not isinstance(item, str) or len(item) > 240 or not _SPEC.fullmatch(item.strip()):
            raise ValueError("Use a PyPI name with optional extras/version; URLs, paths, pip flags and requirements files are not package names")
        if item.strip() not in result:
            result.append(item.strip())
    return result


def inventory(root, maximum):
    paths, _ = _inventory(root, exclude=False, reject_links=True)
    total = sum((root / p).stat().st_size for p in paths)
    if total > maximum:
        raise ValueError("MAX_PACKAGE_BYTES")
    return total, paths


class PackageInstaller:
    def __init__(self, image, timeout_seconds, max_bytes):
        self.image, self.timeout, self.max_bytes = image, timeout_seconds, max_bytes

    def install(self, workspace_root, packages):
        specs = requirements(packages)
        root = _plain_absolute(workspace_root)
        marker = json.loads(_read_bytes(root, Path(_WORKSPACE_MARKER), 65536))
        if marker.get('root') != str(root):
            raise SecurityError('Expected an agent workspace')
        _inventory(root, exclude=False, reject_links=True)
        started = time.monotonic()
        result = {'status': 'BLOCKED', 'requirements': specs, 'phases': [], 'distributions': [],
                  'wheel_receipts': [], 'production_modified': False, 'install_path': '.packages'}
        # Verified absolute target stays under the private agent directory.
        with tempfile.TemporaryDirectory(prefix='package-build-', dir=root.parent) as temp:
            build = _plain_absolute(temp)
            if not build.is_relative_to(root.parent) or build == root.parent:
                raise SecurityError('Package staging escaped the agent directory')
            (build / _WORKSPACE_MARKER).write_text(json.dumps({'root': str(build), 'purpose': 'package-build'}))
            wheels = build / 'wheels'; wheels.mkdir()
            (build / '.build-tmp').mkdir()
            fetch = DockerExecutor(self.image, self.timeout).fetch_packages(build, specs)
            result['phases'].append(dict(fetch, phase='FETCH_BUILD', network='bridge', project_mounted=False))
            if fetch['status'] != 'COMPLETED':
                result.update(status=fetch['status'], reason='PACKAGE_FETCH_OR_BUILD_FAILED')
                return result
            try:
                size, files = inventory(wheels, self.max_bytes)
                if not files or any(Path(p).suffix != '.whl' for p in files):
                    raise ValueError('Wheel build produced no valid wheelhouse')
                for path in files:
                    data = _read_bytes(wheels, path, self.max_bytes)
                    result['wheel_receipts'].append({'file': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
                result['wheel_bytes'] = size
                remaining = int(self.timeout - (time.monotonic() - started))
                if remaining < 1:
                    result.update(status='LIMIT_REACHED', reason='PACKAGE_INSTALL_TIMEOUT')
                    return result
                installed = DockerExecutor(self.image, remaining).install_packages(root, wheels, specs)
                result['phases'].append(dict(installed, phase='INSTALL', network='none'))
                result['status'] = installed['status']
                if installed['status'] != 'COMPLETED':
                    result['reason'] = 'PACKAGE_INSTALL_FAILED; partial files may remain in private workspace'
                    return result
                target = root / '.packages'
                size, files = inventory(target, self.max_bytes)
                result['installed_bytes'] = size
                for path in files:
                    if len(path.parts) == 2 and path.name == 'METADATA' and path.parts[0].endswith('.dist-info'):
                        meta = BytesParser().parsebytes(_read_bytes(target, path, 1000000), headersonly=True)
                        result['distributions'].append({'name': meta.get('Name', ''), 'version': meta.get('Version', '')})
                result['distributions'].sort(key=lambda d: d['name'].casefold())
            except ValueError as error:
                result.update(status='LIMIT_REACHED' if str(error) == 'MAX_PACKAGE_BYTES' else 'BLOCKED', reason=str(error))
            return result
