"""Translate already-normalized GitHub collector output across the application port."""

from collections.abc import Callable, Mapping

from lighthouse.adapters.github.collection import GitHubCollector
from lighthouse.adapters.github.facts import Context
from lighthouse.application.coordinator import Bundle, Cycle
from lighthouse.domain.workflow import State


class GitHubObservationSource:
    """Use explicit authorized contexts; don't rebuild authority from provider text."""

    def __init__(
        self, collector: GitHubCollector, contexts: Callable[[State], Mapping[int, Context]],
    ) -> None:
        self._collector, self._contexts = collector, contexts

    def observe(self, accepted: State, cycle: Cycle) -> Bundle:
        """Obtain the scan outside the ledger write and preserve any hold."""
        contexts = self._contexts(accepted)
        work = accepted.work
        configured = [context.work for context in contexts.values() if context.work is not None]
        if configured != ([] if work is None else [work]):
            return Bundle(held=True)
        scan = self._collector.collect(contexts, revision=cycle.revision, now=cycle.now)
        if scan.hold is not None or any(item.hold is not None for item in scan.observations):
            return Bundle(held=True)
        candidates = tuple(item.candidate for item in scan.observations if item.candidate is not None)
        if work is None:
            return Bundle(candidates)
        current = next((item for item in scan.observations
                        if item.candidate is not None and item.candidate.number == work.issue), None)
        if current is None:
            return Bundle(held=True)
        return Bundle(candidates, current.pull, current.review, current.merge)
