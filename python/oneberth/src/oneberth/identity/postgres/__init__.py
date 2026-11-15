# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The identity store on PostgreSQL, in the schema named ``oneberth``.

It needs the ``postgres`` extra: ``pip install 'oneberth[postgres]'``.
"""

from oneberth.identity.postgres._schema import SCHEMA
from oneberth.identity.postgres._store import PostgresIdentityStore

__all__ = ["SCHEMA", "PostgresIdentityStore"]
