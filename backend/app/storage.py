"""File bytes live on disk under random names. User-supplied names never reach the filesystem."""
import os
import uuid

from flask import current_app


def new_stored_name():
    return uuid.uuid4().hex


def storage_root():
    root = current_app.config["STORAGE_DIR"]
    os.makedirs(root, exist_ok=True)
    return root


def path_for(stored_name):
    """storage/ab/<random hex>; sharded so folders stay small."""
    folder = os.path.join(storage_root(), stored_name[:2])
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, stored_name)
