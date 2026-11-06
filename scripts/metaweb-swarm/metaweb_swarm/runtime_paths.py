"""Operator runtime files live together, outside the production project."""
import os
from pathlib import Path

DIRECTORY_NAME='vojtamaur-metaweb-swarm-files'

def files_root(project):
    override=os.environ.get('SWARM_FILES_ROOT')
    return Path(override).expanduser().resolve() if override else Path(project).resolve().parent/DIRECTORY_NAME

def runs_root(project):
    override=os.environ.get('SWARM_RUNS_ROOT')
    return Path(override).expanduser().resolve() if override else files_root(project)/'runs'
