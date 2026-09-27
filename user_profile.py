"""Профиль соискателя из PROFILE_DIR/profile.py — единственное место, которое правят под себя."""

import importlib.util
import os

import config


def _load():
    path = os.path.join(config.PROFILE_DIR, "profile.py")
    spec = importlib.util.spec_from_file_location("job_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = _load()
