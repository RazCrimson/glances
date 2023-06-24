# -*- coding: utf-8 -*-
#
# This file is part of Glances.
#
# SPDX-FileCopyrightText: 2023 Nicolas Hennion <nicolas@nicolargo.com>
#
# SPDX-License-Identifier: LGPL-3.0-only
#

"""Interface for Extensions of Glances' Containers plugin."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Protocol, List, NamedTuple

from glances import logger
from glances.globals import itervalues, iterkeys


class ContainersStatistics(NamedTuple):
    engine: str
    version: Dict
    containers: List[Dict]


class ContainersExtension(Protocol):

    @classmethod
    def connect(cls, **kwargs: Dict[str, Any]) -> Optional[ContainersExtension]:
        """
        Return an extension instance if the connection to engine is successful
        """
        ...

    @property
    def version(self) -> Dict:
        """
        Return the version data of the connected engine
        """
        # Below line for type checkers
        raise NotImplemented("This property should be overridden by the protocol's implementors")

    @property
    def engine(self) -> str:
        """
        Return an engine corresponding to the extension.
        Should be unique for each type of extension
        """
        # Below line for type checkers
        raise NotImplemented("This property should be overridden by the protocol's implementors")

    def stats(self, all_containers: bool = False) -> ContainersStatistics:
        """
        Return the stats of the containers.
        """
        ...

    def terminate(self) -> None:
        """
        Terminate the connection and all active workers.
        """
        ...


class ContainerWatcher(Protocol):

    def stop(self) -> None:
        """Terminates the Watcher"""

    def compute_activity_stats(self):
        """Required Activity Stats"""
        ...


class BaseExtension(ContainersExtension, ABC):
    CONTAINERS_KEY = 'name'  # key of the stats list

    VERSION_UPDATE_INTERVAL = 300  # seconds

    def __init__(self, client):
        self._client = client

        self._last_version_fetch: int = 0
        self._version_info: Dict[str, Any] = {}
        self._container_watchers: Dict[str, ContainerWatcher] = {}

    @classmethod
    @abstractmethod
    def connect(cls, **kwargs: Dict[str, Any]) -> Optional[BaseExtension]:
        ...

    @property
    def version(self) -> Dict:
        return self._version_info

    @property
    @abstractmethod
    def engine(self) -> str:
        ...

    def terminate(self) -> None:
        # Stop all streaming threads
        for t in itervalues(self._container_watchers):
            t.stop()

        # Close socket connection
        self._client.close()

    def fetch_containers(self, all_containers: bool = False) -> List:
        """Fetches current containers and start stats streams for active containers"""

        # Update current containers list
        try:
            # Issue #1152: Podman/Docker modules doesn't export details about stopped containers
            # The Containers/all key of the configuration file should be set to True
            containers = self._client.containers.list(all=all_containers)
        except Exception as e:
            logger.error(f"{self.engine} Can't get containers list ({e})")
            return []

        # Start new thread for new container
        for container in containers:
            if container.id not in self._container_watchers:
                # StatsFetcher did not exist in the internal dict
                # Create it, add it to the internal dict
                logger.debug(f"{self.engine} Create thread for container {container.id[:12]}")
                self._container_watchers[container.id] = self.create_container_watcher(container)

        # Stop threads for non-existing containers
        absent_containers = set(iterkeys(self._container_watchers)) - set(c.id for c in containers)
        for container_id in absent_containers:
            # Stop the StatsFetcher
            logger.debug(f"{self.engine} Stop thread for old container {container_id[:12]}")
            self._container_watchers[container_id].stop()
            # Delete the StatsFetcher from the dict
            del self._container_watchers[container_id]

        return containers

    @abstractmethod
    def create_container_watcher(self, container) -> ContainerWatcher:
        ...

    def stats(self, all_containers: bool = False) -> ContainersStatistics:
        ...

    def update_version_info(self) -> None:
        try:
            self._version_info = self._client.version()
        except Exception as e:
            logger.error(f"{self.engine} Version update failed ({e})")
            self._version_info = {}

        self._last_version_fetch = curr_time
