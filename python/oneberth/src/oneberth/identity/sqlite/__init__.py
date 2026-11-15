# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The identity store in one SQLite file, ``oneberth.db``. It needs no extra.

The backend's process alone opens the file. Other programs, such as the admin
scripts on the desktop, ask the backend.
"""

from oneberth.identity.sqlite._schema import APPLICATION_ID, FILE_NAME
from oneberth.identity.sqlite._store import SqliteIdentityStore

__all__ = ["APPLICATION_ID", "FILE_NAME", "SqliteIdentityStore"]
