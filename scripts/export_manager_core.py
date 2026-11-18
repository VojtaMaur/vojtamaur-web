"""Local export discovery and process execution. Uses only the Python standard library.

Export modules are parsed as text/AST, never imported or executed during discovery.
"""
from __future__ import annotations

import ast
import dataclasses
from datetime import datetime
import json
import locale
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time


def decode_process_output(data: bytes, legacy_encoding: str | None = None) -> str:
    """Preserve UTF-8 and recover Windows-local bytes embedded by native tools.

    GnuPG can emit UTF-8 messages with an ANSI-encoded Windows time-zone name
    inside the very same line. Decoding the entire line as either code page
    loses characters. Surrogateescape isolates only bytes that are not UTF-8.
    """
    encoding = legacy_encoding or (locale.getencoding() if os.name == "nt" else "cp1252")
    if encoding.lower().replace("-", "") in ("utf8", "cp65001"):
        encoding = "cp1252"
    text = data.decode("utf-8", errors="surrogateescape")
    def recover(match):
        return match.group().encode("utf-8", errors="surrogateescape").decode(encoding, errors="replace")
    return re.sub(r"[\udc80-\udcff]+", recover, text).replace("\r\n", "\n").replace("\r", "\n")


@dataclasses.dataclass
class Option:
    flag: str
    flags: list[str]
    help: str = ""
    default: str = ""
    choices: list[str] = dataclasses.field(default_factory=list)
    action: str = "store"
    nargs: str = ""
    required: bool = False
    type_name: str = "str"


@dataclasses.dataclass
class ExportSpec:
    id: str
    title: str
    script: str
    command: list[str]
    options: list[Option]
    npm_name: str = ""
    description: str = ""
    group: str = "Exporty"


@dataclasses.dataclass
class Step:
    title: str
    command: list[str]
    env: dict[str, str] = dataclasses.field(default_factory=dict)


def parse_extra_args(value: str) -> list[str]:
    """Windows command-line quoting, preserving backslashes and literal shell symbols.

    This only tokenizes: output is always passed as an argument list with shell=False.
    Single quotes have no special meaning, consistently with Windows command lines.
    """
    result: list[str] = []
    i = 0
    while i < len(value):
        while i < len(value) and value[i].isspace():
            i += 1
        if i >= len(value):
            break
        token = ""
        quoted = False
        while i < len(value) and (quoted or not value[i].isspace()):
            if value[i] == "\\":
                start = i
                while i < len(value) and value[i] == "\\":
                    i += 1
                count = i - start
                if i < len(value) and value[i] == '"':
                    token += "\\" * (count // 2)
                    if count % 2:
                        token += '"'
                        i += 1
                    else:
                        quoted = not quoted
                        i += 1
                else:
                    token += "\\" * count
            elif value[i] == '"':
                quoted = not quoted
                i += 1
            else:
                token += value[i]
                i += 1
        if quoted:
            raise ValueError('Nedokončené uvozovky v dalších parametrech. Cesty s mezerami uzavřete do "uvozovek".')
        result.append(token)
    return result


def _source(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


_UNKNOWN = object()


def _literal(node: ast.AST | None, names: dict):
    """A small data-only evaluator. Never eval/compile/import source module code."""
    if node is None:
        return _UNKNOWN
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id, _UNKNOWN)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = []
        for item in node.elts:
            value = _literal(item.value if isinstance(item, ast.Starred) else item, names)
            if isinstance(item, ast.Starred):
                if not isinstance(value, (list, tuple, dict)):
                    return _UNKNOWN
                values.extend(value)
            else:
                values.append(value)
        if any(v is _UNKNOWN for v in values):
            return _UNKNOWN
        return values
    if isinstance(node, ast.Dict):
        keys = [_literal(n, names) for n in node.keys]
        values = [_literal(n, names) for n in node.values]
        if any(v is _UNKNOWN for v in keys):
            return _UNKNOWN
        try:
            return dict(zip(keys, values))
        except (TypeError, ValueError):
            return _UNKNOWN
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _literal(node.operand, names)
        return -value if isinstance(value, (int, float)) else _UNKNOWN
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _literal(node.operand, names)
        return not value if value is not _UNKNOWN else _UNKNOWN
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        args = [_literal(n, names) for n in node.args]
        if any(v is _UNKNOWN for v in args):
            return _UNKNOWN
        try:
            if name in ("tuple", "list", "set", "frozenset", "sorted") and len(args) == 1:
                values = list(args[0])
                return sorted(values) if name == "sorted" else values
            if name == "range" and all(isinstance(v, int) for v in args) and 1 <= len(args) <= 3:
                value = range(*args)
                return list(value) if len(value) <= 200 else _UNKNOWN
            if name == "str" and len(args) == 1:
                return str(args[0])
        except (TypeError, ValueError):
            pass
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left, names), _literal(node.right, names)
        if type(left) is type(right) and isinstance(left, (str, list, int, float)):
            return left + right
    if isinstance(node, ast.Attribute):
        value = _literal(node.value, names)
        if isinstance(value, dict):
            return value.get(node.attr, _UNKNOWN)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            value = _literal(part.value if isinstance(part, ast.FormattedValue) else part, names)
            if value is _UNKNOWN:
                return _UNKNOWN
            parts.append(str(value))
        return "".join(parts)
    return _UNKNOWN


def _constants(tree: ast.Module, path: Path | None = None, visited: set[Path] | None = None) -> dict:
    names = {}
    visited = set() if visited is None else visited
    if path:
        path = path.resolve()
        if path in visited:
            return names
        visited.add(path)
        for node in tree.body:
            imports = []
            if isinstance(node, ast.ImportFrom) and node.module and "." not in node.module:
                imports = [(node.module, node.names)]
            elif isinstance(node, ast.Import):
                imports = [(alias.name, [alias]) for alias in node.names if "." not in alias.name]
            for module, aliases in imports:
                other = path.parent / (module + ".py")
                if other.is_file():
                    try:
                        constants = _constants(ast.parse(other.read_text(encoding="utf-8-sig")), other, visited)
                        if isinstance(node, ast.ImportFrom):
                            for alias in aliases:
                                if alias.name in constants:
                                    names[alias.asname or alias.name] = constants[alias.name]
                        else:
                            names[aliases[0].asname or module] = constants
                    except (OSError, SyntaxError, UnicodeError):
                        pass
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = _literal(node.value, names)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is not _UNKNOWN:
                for target in targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = value
    return names


def _walk_context(node: ast.AST, names: dict):
    """Walk AST, honoring data-only conditions whose helper arguments are known."""
    yield node
    if isinstance(node, ast.If):
        condition = _literal(node.test, names)
        branches = node.body if condition is not _UNKNOWN and condition else node.orelse if condition is not _UNKNOWN else node.body + node.orelse
        for child in branches:
            yield from _walk_context(child, names)
    else:
        for child in ast.iter_child_nodes(node):
            yield from _walk_context(child, names)


def _python_options(path: Path, visited: set[Path] | None = None,
                    helper_kwargs: dict | None = None) -> list[Option]:
    visited = set() if visited is None else visited
    path = path.resolve()
    if path in visited:
        return []
    visited.add(path)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = _constants(tree, path)
    subtree = tree
    if helper_kwargs is not None:
        function = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "add_arguments"), None)
        if function is None:
            return []
        for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults):
            value = _literal(default, names)
            if value is not _UNKNOWN:
                names[arg.arg] = value
        names.update(helper_kwargs)
        subtree = function
    found = []
    for call in _walk_context(subtree, names):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != "add_argument":
            continue
        flags = [_literal(n, names) for n in call.args]
        flags = [n for n in flags if isinstance(n, str)]
        if not flags or any(f in ("--help", "--version") for f in flags):
            continue
        kw = {n.arg: n.value for n in call.keywords if n.arg}
        values = {key: _literal(node, names) for key, node in kw.items()}
        action = values.get("action", "store")
        if action in ("help", "version"):
            continue
        default = values.get("default", "")
        if default is _UNKNOWN:
            default = _source(kw.get("default"))
        if default is None:
            default = ""
        choices = values.get("choices", [])
        if choices is _UNKNOWN or not isinstance(choices, (list, tuple, dict, range)):
            choices = []
        choices = [str(v) for v in choices]
        # Large numeric ranges are clearer as a numeric input than a 100-item menu.
        if len(choices) > 30 and all(re.fullmatch(r"-?\d+", c) for c in choices):
            choices = []
        help_text = values.get("help", "")
        if help_text is _UNKNOWN:
            help_text = ""
        flag = next((f for f in flags if f.startswith("--")), flags[0])
        positional = not flag.startswith("-")
        nargs = values.get("nargs", "")
        found.append(Option(flag, flags, str(help_text), str(default), choices,
                            action if isinstance(action, str) else "store",
                            str(nargs) if nargs is not _UNKNOWN else "",
                            bool(values.get("required", False)) if not positional else nargs not in ("?", "*"),
                            _source(kw.get("type")) or "str"))
    # Shared argparse helpers are merged only when the importing module actually calls them.
    imports = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and "." not in node.module:
            for alias in node.names:
                imports[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name] = (alias.name, None)
    shared = []
    for call in _walk_context(subtree, names):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Name) and call.func.id in imports:
            module, member = imports[call.func.id]
            if member == "add_arguments":
                shared.append((module, call))
        elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.attr == "add_arguments":
            info = imports.get(call.func.value.id)
            if info:
                shared.append((info[0], call))
    for module, call in shared:
        helper = path.parent / (module + ".py")
        if helper.is_file() and helper.parent == path.parent:
            try:
                parameters = {kw.arg: _literal(kw.value, names) for kw in call.keywords if kw.arg}
                parameters = {key: value for key, value in parameters.items() if value is not _UNKNOWN}
                found.extend(_python_options(helper, visited, parameters))
            except (OSError, SyntaxError, ValueError):
                pass
    unique = {}
    for option in found:
        unique.setdefault(option.flag, option)
    return list(unique.values())


def _js_options(path: Path) -> list[Option]:
    source = path.read_text(encoding="utf-8-sig")
    start = source.find("parseArgs({")
    if start == -1:
        return _manual_js_options(path, source)
    source = source[start:]
    found = []
    # Covers node:util parseArgs string/boolean option records, without executing JS.
    for match in re.finditer(r'''(?:["']([\w-]+)["']|\b([\w-]+))\s*:\s*\{([^{}]*?\btype\s*:\s*["'](?:string|boolean)["'][^{}]*)\}''', source):
        key, body = match[1] or match[2], match[3]
        if key == "help":
            continue
        kind = re.search(r'''\btype\s*:\s*["'](string|boolean)["']''', body)[1]
        default_match = re.search(r'''\bdefault\s*:\s*(?:["']([^"']*)["']|(true|false|\d+))''', body)
        default = (default_match[1] if default_match[1] is not None else default_match[2]) if default_match else ""
        short = re.search(r'''\bshort\s*:\s*["'](\w)["']''', body)
        flags = ["--" + key] + (["-" + short[1]] if short else [])
        found.append(Option(flags[0], flags, default=default,
                            action="store_true" if kind == "boolean" else "store"))
    # Rosetta intentionally has an explicit operation selector before its flags.
    if "allowPositionals: true" in source and re.search(r"\['prepare', 'run', 'submit', 'collect', 'import'\]", source):
        found.insert(0, Option("command", ["command"], "Operace Rosetta; prepare pouze připraví data.",
                               "prepare", ["prepare", "run", "submit", "collect", "import"], nargs="?"))
    return found


def _manual_js_options(path: Path, source: str) -> list[Option]:
    """Read simple hand-written argv readers without invoking JavaScript.

    Literal defaults and path.join(ROOT, literal components) are data-only.
    Unknown parser shapes remain available through the GUI extra-arguments field.
    """
    constants = {}
    for match in re.finditer(r"\bconst\s+(\w+)\s*=\s*([^;\n]+);", source):
        name, expression = match[1], match[2].strip()
        literal = re.fullmatch(r'''["']([^"']*)["']''', expression)
        joined = re.fullmatch(r"path\.join\(ROOT\s*,\s*(.+)\)", expression)
        if literal:
            constants[name] = literal[1]
        elif joined:
            parts = re.findall(r'''["']([^"']*)["']''', joined[1])
            if parts and re.fullmatch(r'''(?:\s*["'][^"']*["']\s*,?\s*)+''', joined[1]):
                constants[name] = "/".join(parts)
    descriptions = {
        "--dist": "Složka hotového webu; relativní cesta vychází z kořene projektu.",
        "--output": "Cílová složka Gemini/Gopher; její název musí obsahovat gemini.",
        "--content": "Složka zdrojových článků s metadaty.",
        "--site-url": "Veřejná HTTPS adresa webu pro odkazy na média a náhradní odkazy.",
    } if path.name == "generate-gemini-capsule.mjs" else {}
    found = []
    seen = set()
    for match in re.finditer(r'''\bif\s*\(\s*\w+\s*===\s*["'](--[\w-]+)["']\s*&&\s*\w+\s*\)\s*\{([^{}]*)\}''', source):
        flag, body = match[1], match[2]
        if flag in seen or flag == "--help":
            continue
        seen.add(flag)
        assignment = re.search(r"\boptions\.(\w+)\s*=", body)
        default = ""
        if assignment:
            initial = re.search(r"\b" + re.escape(assignment[1]) + r"\s*:\s*(\w+)", source)
            if initial:
                default = constants.get(initial[1], "")
        found.append(Option(flag, [flag], descriptions.get(flag, ""), default))
    # Simple positional readers: argv[2] || 'dist' / argv[2] ?? 'dist'.
    positional = re.search(r'''process\.argv\[2\]\s*(?:\|\||\?\?)\s*["']([^"']*)["']''', source)
    if positional:
        name = "dist" if positional[1] == "dist" else "argument"
        found.insert(0, Option(name, [name], "Složka hotového sestavení; relativně ke kořeni projektu.",
                               positional[1], nargs="?"))
    if path.name == "generate-source-bundle.mjs" and re.search(r'''process\.argv\[3\]\s*!==\s*["']--no-jpeg-carrier["']''', source):
        found.append(Option("--no-jpeg-carrier", ["--no-jpeg-carrier"],
                            "Vytvořit ZIP se zdroji bez vložení do obrázku JPEG; složka dist se doplní automaticky, pokud je prázdná.",
                            action="store_true"))
    return found


def extract_options(path: Path) -> list[Option]:
    try:
        return _python_options(path) if path.suffix == ".py" else _js_options(path)
    except (OSError, SyntaxError, UnicodeError, ValueError):
        return []


def _script_command(path: Path, root: Path) -> list[str]:
    relative = path.relative_to(root).as_posix()
    if path.suffix == ".py":
        # A GUI may be launched by pythonw; workers must use console Python to pipe output.
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        return [str(executable), "-u", "-B", relative]
    return [shutil.which("node") or "node", relative]


def _title(path: Path) -> str:
    return path.stem.replace("export-", "").replace("site-", "").replace("-", " ").upper()


def discover(root: Path) -> list[ExportSpec]:
    root = Path(root).resolve()
    scripts = root / "scripts"
    candidates = []
    for pattern in ("export-*.py", "export-*.mjs", "export-*.js"):
        candidates.extend(scripts.glob(pattern))
    if (scripts / "filter-all-posts.py").is_file():
        candidates.append(scripts / "filter-all-posts.py")
    specs: list[ExportSpec] = []
    by_path: dict[str, ExportSpec] = {}
    for path in sorted(set(candidates)):
        if path.stem.startswith("export-manager") or path.name in ("export-site-json.mjs", "export-wayback-snapshots.py"):
            continue
        relative = path.relative_to(root).as_posix()
        description = ""
        try:
            if path.suffix == ".py":
                doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8-sig"))) or ""
                description = doc.split("\n\n")[0].replace("\n", " ")
        except (OSError, SyntaxError, UnicodeError):
            pass
        title = "TXT s filtry" if path.name == "filter-all-posts.py" else _title(path)
        spec = ExportSpec(relative, title, relative, _script_command(path, root),
                          extract_options(path), description=description,
                          group="Síťové nástroje" if "wayback" in path.name or "rosetta" in path.name else "Exporty")
        specs.append(spec)
        by_path[relative] = spec
    try:
        npm_scripts = json.loads((root / "package.json").read_text(encoding="utf-8-sig")).get("scripts", {})
    except (OSError, ValueError):
        npm_scripts = {}
    selected_generate = {"generate:gemini", "generate:source-bundle"}
    # Keep one entry per full web edition; the GUI chooses its build variant at run time.
    web_name = next((name for name in ("build:web:translate:signed", "build:web", "build:web:translate",
                                      "build:web:signed", "build:web:strict", "build:web:strict:signed")
                     if name in npm_scripts), None)
    if web_name:
        specs.append(ExportSpec("npm:build:web", "Online web", "", _npm_command(web_name), [], npm_name="build:web",
                     description="Vytvoří standardní web do dist/ podle postupu zvoleného v Přípravě webu. Soubory jsou určené pro webový server; nic se automaticky nenahrává.",
                     group="Exporty"))
    usb_name = next((name for name in ("build:usb:translate:signed", "build:usb:translate", "build:usb")
                     if name in npm_scripts), None)
    selected_build = {usb_name} if usb_name else set()
    for name, raw in npm_scripts.items():
        if not isinstance(raw, str) or not (name.startswith("export:") or name in selected_generate or name in selected_build):
            continue
        if name in selected_build:
            specs.append(ExportSpec("npm:" + name, "USB · kompletní offline web", "", _npm_command(name), [], npm_name=name,
                         description="Vytvoří plný offline web bez velikostního limitu. Nahradí dist/ USB sestavením; před PDF a EPUB znovu vytvořte standardní web.",
                         group="Exporty"))
            continue
        if name.endswith(":build"):
            continue
        try:
            tokens = parse_extra_args(raw)
        except ValueError:
            tokens = []
        script_index = next((i for i, v in enumerate(tokens) if re.match(r"^\.?[\\/]?scripts[\\/].+\.(?:py|mjs|js)$", v)), None)
        if script_index is not None and not any(v in tokens for v in ("&&", "||", "|", ">", "<")):
            relative = tokens[script_index].replace("\\", "/").removeprefix("./")
            path = root / relative
            if path.name in ("export-site-json.mjs", "export-wayback-snapshots.py"):
                continue
            if not path.is_file():
                continue
            suffix_args = tokens[script_index + 1:]
            existing = by_path.get(relative)
            if existing and not suffix_args:
                existing.npm_name = name
                continue
            options = extract_options(path)
            baked = _values(suffix_args)
            for option in options:
                if option.flag in baked:
                    option.default = baked[option.flag]
            spec = ExportSpec("npm:" + name, _title(path) + (" · " + name.split(":")[-1] if suffix_args else ""),
                              relative, _script_command(path, root) + suffix_args, options, npm_name=name,
                              group="Generátory" if name in selected_generate else "Exporty")
        else:
            # npm script name is a trusted key from package.json, not user-entered arguments.
            spec = ExportSpec("npm:" + name, name, "", _npm_command(name), [], npm_name=name,
                              group="Generátory" if name in selected_generate else "Exporty")
        specs.append(spec)
    if (scripts / "generate-all-posts.mjs").is_file() or any((root / "dist" / ("ALL_POSTS." + kind)).is_file() for kind in ("txt", "json")):
        helper = scripts / "export_manager_tasks.py"
        for kind in ("txt", "json"):
            specs.append(ExportSpec("snapshot:" + kind, "ALL_POSTS." + kind, helper.relative_to(root).as_posix(),
                         _script_command(helper, root) + ["snapshot", "--kind", kind, "--project-root", str(root)],
                         [Option("--output", ["--output"], "Volitelný výstupní soubor. Prázdné pole vytvoří novou časově označenou kopii v exports/.", type_name="Path")],
                         npm_name="export:" + kind, description="Samostatná přesná kopie dist/ALL_POSTS." + kind + " do exports/. Zdrojový build ani jeho podpis se nemění."))
    arweave = scripts / "make-arweave-build.mjs"
    if arweave.is_file():
        specs.append(ExportSpec("npm:build:arweave", "Arweave · archivní web", arweave.relative_to(root).as_posix(),
                     _script_command(arweave, root), [], npm_name="build:arweave",
                     description="Odvodí dist-arweave/ z hotového standardního dist/. Volba nového webu používá vybraný postup; podepsaný postup přidá podpis Arweave. Nenahrává nic na síť."))
    return sorted(specs, key=lambda item: (item.group, item.title.casefold(), item.id))


def _npm_command(name: str) -> list[str]:
    if not re.fullmatch(r"[\w:.-]+", name):
        raise ValueError("Nepodporovaný název npm příkazu.")
    if os.name == "nt":
        # cmd receives only an application-controlled npm script key, never raw GUI input.
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", "npm run " + name]
    return [shutil.which("npm") or "npm", "run", name]


def _values(args: list[str]) -> dict[str, str]:
    values = {}
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("-"):
            if "=" in token:
                flag, value = token.split("=", 1)
                values[flag] = value
            elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                values[token] = args[i + 1]
                i += 1
            else:
                values[token] = "true"
        i += 1
    return values


def build_plan(root: Path, spec: ExportSpec, args: list[str], rebuild: bool = False,
               fresh_pdf: bool = True,
               build_command: str = "build:web:translate:signed") -> list[Step]:
    root = Path(root).resolve()
    args = list(args)
    if any("\x00" in value for value in args):
        raise ValueError("Parametry nesmějí obsahovat nulový znak.")
    command = list(spec.command)
    if not spec.script and args:
        raise ValueError("Tento složený npm příkaz nepřijímá další parametry v GUI.")
    is_online = spec.npm_name == "build:web" and not spec.script
    if is_online and not re.fullmatch(r"build:web(?::[\w.-]+)*", build_command):
        raise ValueError("Pro online web zvolte webový postup sestavení začínající build:web.")
    if spec.npm_name.startswith("build:usb"):
        if build_command == "build:web" or build_command.startswith("build:web:"):
            usb_command = "build:usb" + build_command[len("build:web"):]
        else:
            raise ValueError("Pro USB zvolte webový postup sestavení začínající build:web.")
        try:
            available = json.loads((root / "package.json").read_text(encoding="utf-8-sig")).get("scripts", {})
        except (OSError, ValueError):
            available = {}
        if usb_command not in available:
            raise ValueError("Zvolenému postupu chybí odpovídající USB příkaz v package.json: " + usb_command)
        command = _npm_command(usb_command)
    is_arweave = spec.npm_name == "build:arweave" and Path(spec.script).name == "make-arweave-build.mjs"
    if is_arweave and args:
        raise ValueError("Arweave nemá další parametry; sestavení webu zvolte v ovládání před exportem.")
    if Path(spec.script).name == "export_manager_tasks.py":
        index = 0
        while index < len(args):
            if args[index] == "--output" and index + 1 < len(args):
                index += 2
            elif args[index].startswith("--output="):
                index += 1
            else:
                raise ValueError("U samostatné kopie ALL_POSTS lze změnit pouze výstupní soubor --output.")
    if Path(spec.script).name == "generate-source-bundle.mjs" and "--no-jpeg-carrier" in args:
        index = args.index("--no-jpeg-carrier")
        if index == 0:
            # This script reads argv[3] directly, so argv[2] must remain present.
            args.insert(0, "dist")
        elif index != 1:
            raise ValueError("U zdrojového balíčku patří přepínač --no-jpeg-carrier hned za jednu složku sestavení.")
    values = _values(command[1:] + args)
    steps = []
    if (rebuild or is_online) and "--verify" not in values and not spec.npm_name.startswith("build:usb"):
        if not re.fullmatch(r"build:[\w:.-]+", build_command):
            raise ValueError("Vyberte platný npm příkaz sestavení webu.")
        try:
            available = json.loads((root / "package.json").read_text(encoding="utf-8-sig")).get("scripts", {})
        except (OSError, ValueError):
            available = {}
        if build_command not in available:
            raise ValueError("Příkaz sestavení v package.json neexistuje: " + build_command)
        build_title = "Online web" if is_online else "Aktuální web"
        if "translate" in build_command:
            build_title += " · doplnění překladů"
        if "strict" in build_command:
            build_title += " · kontrola překladů"
        if "signed" in build_command:
            build_title += " · podpis"
        steps.append(Step(build_title, _npm_command(build_command)))
    if is_online:
        return steps
    if is_arweave:
        steps.append(Step(spec.title, command))
        # The selected web build may already have signed dist + Gemini and advanced
        # canonical history. Refresh ONLY this newly derived artifact's source bundle
        # before its manifest/signature, preserving the existing signed siblings.
        source_bundle = root / "scripts" / "generate-source-bundle.mjs"
        if build_command.endswith(":signed") and source_bundle.is_file():
            steps.append(Step("Aktuální zdrojový balíček Arweave", _script_command(source_bundle, root) + ["dist-arweave"]))
        try:
            available = json.loads((root / "package.json").read_text(encoding="utf-8-sig")).get("scripts", {})
        except (OSError, ValueError):
            available = {}
        if "generate:integrity:arweave" in available:
            steps.append(Step("Kontrolní součty Arweave", _npm_command("generate:integrity:arweave")))
        elif (root / "scripts" / "generate-integrity.mjs").is_file():
            steps.append(Step("Kontrolní součty Arweave", _script_command(root / "scripts" / "generate-integrity.mjs", root) + ["dist-arweave", "arweave"]))
        if build_command.endswith(":signed"):
            if "sign:build:arweave" in available:
                steps.append(Step("Podpis Arweave", _npm_command("sign:build:arweave")))
            elif (root / "scripts" / "sign-build.mjs").is_file():
                steps.append(Step("Podpis Arweave", _script_command(root / "scripts" / "sign-build.mjs", root) + ["dist-arweave"]))
        return steps
    if Path(spec.script).name == "export-site-images.py" and fresh_pdf and "--verify" not in values:
        conflicts = {"--pdf", "--source-manifest", "--timestamp", "--no-timestamp", "--project-root", "--root", "--dist"} & values.keys()
        if conflicts:
            raise ValueError("Nejdřív nové PDF nelze kombinovat s " + ", ".join(sorted(conflicts)) +
                             ". Vypněte volbu nového PDF, chcete-li použít vlastní zdroj.")
        scope = values.get("--scope", "all")
        if scope not in ("all", "metaweb"):
            raise ValueError("Rozsah obrázků musí být all nebo metaweb.")
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        env = {"VOJTAMAUR_EXPORT_TIMESTAMP": stamp}
        prerequisite = root / "scripts" / ("export-metaweb-pdf.py" if scope == "metaweb" else "export-site-pdf.py")
        if not prerequisite.is_file():
            raise ValueError("Chybí skript pro nové PDF: " + str(prerequisite))
        pdf_command = _script_command(prerequisite, root)
        if scope == "all":
            pdf_command += ["--lang", "both"]
        steps.append(Step("Nové PDF: " + ("Metaweb" if scope == "metaweb" else "celý web, CS + EN"), pdf_command, dict(env)))
        steps.append(Step(spec.title, command + args, dict(env)))
    else:
        steps.append(Step(spec.title, command + args))
    return steps


class _WindowsProcessJob:
    """Keep our own process tree together, independent of taskkill permissions.

    https://learn.microsoft.com/windows/win32/procthread/job-objects
    The handle is not inherited; Windows also ends workers if the GUI exits.
    """
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount",
                        "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Counters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def attach(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def terminate(self):
        return bool(self.handle and self.api.TerminateJobObject(self.handle, 1))

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class ProcessRunner:
    """One queue at a time; all UI work is communicated through queue events."""
    def __init__(self, events: queue.Queue):
        self.events = events
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, steps: list[Step], cwd: Path, log_path: Path,
              runtime_env: dict[str, str] | None = None):
        if self.running:
            raise RuntimeError("Export už běží.")
        self._cancel.clear()
        temporary_env = dict(runtime_env or {})
        self._thread = threading.Thread(target=self._run, args=(list(steps), Path(cwd), Path(log_path), temporary_env), daemon=True)
        self._thread.start()

    def cancel(self):
        if self._cancel.is_set():
            return
        self._cancel.set()
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            threading.Thread(target=self._terminate, args=(process,), daemon=True).start()

    @staticmethod
    def _terminate(process):
        try:
            if os.name == "nt":
                job = getattr(process, "_export_job", None)
                if job and job.terminate():
                    return
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=False)
                if process.poll() is None:
                    process.kill()
            else:
                import signal
                os.killpg(process.pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    def _run(self, steps, cwd, log_path, runtime_env):
        ok, message = False, "Export nebyl dokončen."
        # These values live only in this worker's memory. No environment dump is logged.
        sensitive = []
        for key in ("DEEPL_AUTH_KEY", "GNUPGHOME"):
            for source in (os.environ, runtime_env, *(step.env for step in steps)):
                value = source.get(key)
                if value:
                    sensitive.append((str(value), key == "GNUPGHOME"))
                    if key == "GNUPGHOME":
                        sensitive.append((str(value).replace("\\", "/"), True))
                        sensitive.append((str(value).replace("/", "\\"), True))
        def redact(value):
            result = str(value)
            for secret, ignore_case in sorted(sensitive, key=lambda item: len(item[0]), reverse=True):
                result = re.sub(re.escape(secret), "[skryto]", result,
                                flags=re.IGNORECASE if ignore_case else 0)
            return result
        env = None
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("w", encoding="utf-8", buffering=1) as log:
                def emit(value):
                    safe_value = redact(value)
                    log.write(safe_value)
                    self.events.put(("log", safe_value))
                emit("Export Manager · " + datetime.now().isoformat(timespec="seconds") + "\n")
                for i, step in enumerate(steps, 1):
                    if self._cancel.is_set():
                        message = "Zastaveno uživatelem."
                        break
                    self.events.put(("step", (i, len(steps), redact(step.title))))
                    emit("\n[" + str(i) + "/" + str(len(steps)) + "] " + step.title + "\n> " + subprocess.list2cmdline(step.command) + "\n")
                    env = os.environ.copy()
                    # An old shell edition must never select a stale PDF implicitly.
                    env.pop("VOJTAMAUR_EXPORT_TIMESTAMP", None)
                    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
                    env.update(step.env)
                    env.update(runtime_env)
                    kwargs = {}
                    if os.name == "nt":
                        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                    else:
                        kwargs["start_new_session"] = True
                    with self._lock:
                        if self._cancel.is_set():
                            message = "Zastaveno uživatelem."
                            break
                        process = subprocess.Popen(step.command, cwd=cwd, env=env, shell=False,
                                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                   stderr=subprocess.STDOUT, **kwargs)
                        if os.name == "nt":
                            job = None
                            try:
                                job = _WindowsProcessJob()
                                job.attach(process)
                                process._export_job = job
                            except OSError as exc:
                                if job:
                                    job.close()
                                emit("[Správa stromu procesů: " + str(exc) + "; použije se taskkill.]\n")
                        self._process = process
                    assert process.stdout is not None
                    for line in process.stdout:
                        emit(decode_process_output(line))
                    process.stdout.close()
                    code = process.wait()
                    job = getattr(process, "_export_job", None)
                    if job:
                        job.close()
                    with self._lock:
                        self._process = None
                    emit("[Návratový kód: " + str(code) + "]\n")
                    if self._cancel.is_set():
                        message = "Zastaveno uživatelem."
                        break
                    if code:
                        message = f"Krok „{step.title}“ skončil s kódem {code}. Další kroky nebyly spuštěny."
                        break
                else:
                    ok, message = True, "Všechny zadané kroky byly dokončeny."
                emit("\n" + message + "\n")
        except Exception as exc:
            message = redact("Export nelze spustit: " + str(exc))
            try:
                with log_path.open("a", encoding="utf-8") as error_log:
                    error_log.write("\n" + message + "\n")
            except OSError:
                pass
            self.events.put(("log", message + "\n"))
        finally:
            with self._lock:
                process = self._process
                self._process = None
            if process and process.poll() is None:
                self._terminate(process)
            job = getattr(process, "_export_job", None) if process else None
            if job:
                job.close()
            safe_message = redact(message)
            runtime_env.clear()
            if env is not None:
                env.clear()
            sensitive.clear()
            self.events.put(("done", (ok, safe_message)))
