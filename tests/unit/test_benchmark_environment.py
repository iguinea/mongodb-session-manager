"""Lo que el benchmark anota del entorno, y lo que exige para restar dos runs.

`capture()` interroga al servidor y al driver. Aquí se comprueba con un cliente
falso: lo que importa es qué campos quedan escritos en el fichero de resultados,
no qué contesta un MongoDB de verdad.
"""

from __future__ import annotations

import importlib.metadata as md
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

from benchmarks.environment import capture

CONNECTION_STRING = "mongodb://user:pass@localhost:8550/"


def fake_client(build_info: dict[str, Any] | None = None) -> MagicMock:
    """Un MongoClient que contesta lo justo para `capture()`."""
    client = MagicMock()
    client.admin.command.side_effect = lambda name: {
        "buildInfo": build_info or {"version": "8.2.7", "gitVersion": "abc123"},
        "hello": {"maxWireVersion": 25, "setName": None},
    }[name]
    client.options.pool_options = MagicMock(
        max_pool_size=100,
        min_pool_size=10,
        wait_queue_timeout=None,
        max_idle_time_seconds=300,
    )
    client.topology_description.topology_type_name = "Single"
    client.read_preference = "Primary()"
    return client


class TestEnvironmentRecordsWhatProducedTheNumbers:
    def test_the_strands_version_is_recorded(self):
        """Sin ella, dos runs del mismo commit no se distinguen (#69).

        `pymongo` y Python ya estaban; la versión del SDK no, y es la que cambia
        cuántas veces se llama a `sync_agent()` y qué escribe cada llamada. Un
        fichero de resultados que no la lleve no se puede releer dentro de seis
        meses.
        """
        environment = capture(
            fake_client(), connection_string=CONNECTION_STRING, label=""
        )

        assert environment.as_dict()["strands_version"] == md.version("strands-agents")

    def test_the_strands_version_does_not_block_a_delta(self):
        """Es la variable bajo prueba, no una que invalide la comparación.

        El harness se niega a restar dos runs cuyo entorno de base de datos
        difiera —motor, versión del servidor, topología, compresores—, porque
        entonces la latencia mide otra cosa. Cambiar de versión del SDK contra
        el mismo servidor es justamente lo que se quiere medir, igual que
        cambiar de rama.
        """
        environment = capture(
            fake_client(), connection_string=CONNECTION_STRING, label=""
        )
        other_sdk = replace(environment, strands_version="1.30.0")

        assert environment.comparability_key == other_sdk.comparability_key
