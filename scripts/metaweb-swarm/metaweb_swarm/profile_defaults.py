"""Operator-owned profile preferences shared by the GUI and new CLI runs.

Only editable research parameters are retained. Capabilities always come from
the bundled profile, and existing run checkpoints never consult these files.
"""
import copy
import json
import os
import re
import uuid
from pathlib import Path

from .config import PACKAGE_ROOT, load_config, validate_config
from .context import _is_link
from .roles import seed_agents
from .runtime_paths import files_root
from .storage import atomic_write, now


PROFILE_FILES = {'research': 'config.research.json', 'cheap': 'config.cheap.json',
                 'experimental': 'config.http.json'}
EDITABLE = {'brainstorm_development_candidates','brainstorm_development_rounds','custom_agents', 'role_display_names', 'role_assignments', 'live_output_preview', 'model_tiers',
            'role_model_tiers', 'role_round_limits', 'seed_roles',
            'max_total_tokens', 'max_active_seconds', 'max_steps', 'max_agent_rounds',
            'max_agents', 'max_turns', 'max_output_tokens', 'max_concurrent_agents',
            'estimated_budget_usd'}
MAX_DEFAULT_BYTES = 262144
_UNSET = object()


def _path(project, profile):
    if not isinstance(profile,str) or profile not in PROFILE_FILES and not re.fullmatch(r'user-[0-9a-f]{32}', profile):
        raise ValueError('Neznámý profil')
    project = Path(project).resolve()
    # Inspect the original override before files_root resolves links. A linked
    # ancestor may otherwise disappear from the resolved destination spelling.
    raw = Path(os.environ['SWARM_FILES_ROOT']).expanduser().absolute() if os.environ.get('SWARM_FILES_ROOT') else files_root(project)
    for parent in (raw, *raw.parents):
        if _is_link(parent):
            raise ValueError('Propojená složka výchozího nastavení je odmítnuta')
    root = files_root(project)
    if root == project or root.is_relative_to(project) or project.is_relative_to(root):
        raise ValueError('Výchozí nastavení musí ležet mimo produkční projekt')
    directory = root / 'defaults'
    target = directory / (profile + '.json')
    for path in (root, directory, target, target.with_name(target.name + '.tmp')):
        if _is_link(path):
            raise ValueError('Propojený soubor výchozího nastavení je odmítnut')
    if directory.exists() and not directory.is_dir():
        raise ValueError('Složka výchozího nastavení není adresář')
    if target.exists() and not target.is_file():
        raise ValueError('Výchozí nastavení není obyčejný soubor')
    return target


def validate_overrides(overrides):
    if not isinstance(overrides, dict) or set(overrides) - EDITABLE:
        raise ValueError('Nepodporovaná změna profilu')
    if 'seed_roles' in overrides and not overrides['seed_roles']:
        raise ValueError('Vyber alespoň jednu seed roli')


def _read(project, profile):
    path = _path(project, profile)
    if not path.exists():
        return None
    if path.stat().st_size > MAX_DEFAULT_BYTES:
        raise ValueError('Soubor výchozího nastavení je příliš velký')
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    if (not isinstance(record, dict) or record.get('schema_version') != 1
            or record.get('profile') != profile
            or set(record) - {'schema_version', 'profile', 'overrides', 'objective', 'updated_at', 'name', 'base_profile'}):
        raise ValueError('Neplatný formát výchozího nastavení')
    validate_overrides(record.get('overrides'))
    if profile not in PROFILE_FILES:
        _name(record.get('name'))
        if record.get('base_profile') not in PROFILE_FILES:raise ValueError('Neplatný základ profilu')
    elif 'name' in record or 'base_profile' in record:
        raise ValueError('Vestavěný profil nelze přejmenovat')
    return record


def _effective(profile, record=None):
    base = profile if profile in PROFILE_FILES else (record or {}).get('base_profile')
    if base not in PROFILE_FILES:raise ValueError('Profil neexistuje')
    config = load_config(PACKAGE_ROOT / PROFILE_FILES[base])
    if record:
        config.update(copy.deepcopy(record['overrides']))
        if 'objective' in record:
            config['operator_objective'] = record['objective']
    validate_config(config)
    seed_agents(config)
    return config


def profile_config(project, profile):
    """Return an effective config plus whether operator defaults were saved."""
    record = _read(project, profile)
    return _effective(profile, record), record is not None


def load_new_run_config(project, config_path=None):
    """Apply defaults to exact bundled profiles, never arbitrary config files."""
    target = Path(config_path or PACKAGE_ROOT / PROFILE_FILES['research']).resolve()
    for profile, filename in PROFILE_FILES.items():
        if target == (PACKAGE_ROOT / filename).resolve():
            return profile_config(project, profile)[0]
    return load_config(config_path)


def save_defaults(project, profile, overrides, objective=_UNSET, name=_UNSET):
    validate_overrides(overrides)
    previous = _read(project, profile)
    record = {'schema_version': 1, 'profile': profile,
              'overrides': dict(previous['overrides']) if previous else {}, 'updated_at': now()}
    if profile not in PROFILE_FILES:
        if previous is None:raise ValueError('Profil neexistuje')
        record.update(base_profile=previous['base_profile'], name=previous['name'] if name is _UNSET else _name(name))
        _unique_name(project, record['name'], exclude=profile)
    elif name is not _UNSET:
        raise ValueError('Vestavěný profil nelze přejmenovat; ulož jeho kopii')
    record['overrides'].update(copy.deepcopy(overrides))
    if objective is not _UNSET:
        record['objective'] = objective
    elif previous and 'objective' in previous:
        record['objective'] = previous['objective']
    config = _effective(profile, record)
    text = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if len(text.encode('utf-8')) > MAX_DEFAULT_BYTES:
        raise ValueError('Výchozí nastavení je příliš velké')
    path = _path(project, profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after mkdir as well, including the temporary atomic-write leaf.
    path = _path(project, profile)
    atomic_write(path, text)
    return config


def reset_defaults(project, profile):
    if profile not in PROFILE_FILES:raise ValueError('Vlastní profil lze upravit nebo smazat')
    path = _path(project, profile)
    config = _effective(profile)
    path.unlink(missing_ok=True)
    return config


def _name(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=100 or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Název profilu musí mít 1 až 100 znaků bez řídicích znaků')
    return value.strip()


def profile_ids(project):
    directory=_path(project,'research').parent
    custom=[]
    if directory.exists():
        for path in sorted(directory.glob('user-*.json')):
            key=path.stem
            if not re.fullmatch(r'user-[0-9a-f]{32}',key):continue
            _read(project,key)
            custom.append(key)
    return list(PROFILE_FILES)+custom


def profile_details(project,profile):
    record=_read(project,profile)
    if profile not in PROFILE_FILES and record is None:raise ValueError('Profil neexistuje')
    return {'custom':profile not in PROFILE_FILES, 'base_profile':(record or {}).get('base_profile',profile),
            'name':(record or {}).get('name')}


def _unique_name(project,name,exclude=None):
    for key in profile_ids(project):
        if key not in PROFILE_FILES and key!=exclude and _read(project,key)['name'].casefold()==name.casefold():
            raise ValueError('Profil s tímto názvem již existuje')


def create_profile(project,source,name,overrides=None,objective=_UNSET):
    name=_name(name)
    _unique_name(project,name)
    config,_=profile_config(project,source)
    validate_overrides({} if overrides is None else overrides)
    config.update(copy.deepcopy({} if overrides is None else overrides))
    if objective is not _UNSET:config['operator_objective']=objective
    validate_config(config);seed_agents(config)
    details=profile_details(project,source)
    key='user-'+uuid.uuid4().hex
    record={'schema_version':1,'profile':key,'name':name,'base_profile':details['base_profile'],
            'overrides':{k:copy.deepcopy(config[k]) for k in EDITABLE if k in config},
            'objective':config.get('operator_objective'),'updated_at':now()}
    text=json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if len(text.encode('utf-8'))>MAX_DEFAULT_BYTES:raise ValueError('Profil je příliš velký')
    path=_path(project,key);path.parent.mkdir(parents=True,exist_ok=True)
    atomic_write(_path(project,key),text)
    return key


def delete_profile(project,profile):
    if profile in PROFILE_FILES:raise ValueError('Vestavěný profil nelze smazat')
    details=profile_details(project,profile)
    _path(project,profile).unlink()
    return details['base_profile']
