from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import random
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a P2P network configuration is invalid."""


@dataclass(frozen=True)
class SearchStep:
    index: int
    from_node: str | None
    to_node: str
    ttl_after: int
    kind: str
    note: str


@dataclass
class SearchResult:
    algorithm: str
    start_node: str
    resource_id: str
    ttl: int
    found: bool
    provider: str | None
    messages: int
    visited_nodes: list[str]
    path: list[str]
    steps: list[SearchStep]
    cache_hit_at: str | None = None
    cache_updates: dict[str, str] = field(default_factory=dict)

    @property
    def visited_count(self) -> int:
        return len(set(self.visited_nodes))


def load_config(path: str | Path) -> dict[str, Any]:
    return parse_config_text(Path(path).read_text(encoding="utf-8"))


def parse_config_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ConfigError("O arquivo de configuração está vazio.")

    if stripped.startswith("{"):
        return json.loads(stripped)

    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(stripped)
        if _has_structured_sections(parsed):
            return parsed
    except ImportError:
        pass
    except Exception:
        pass

    return _parse_txt_config(stripped)


def _has_structured_sections(parsed: Any) -> bool:
    return (
        isinstance(parsed, dict)
        and isinstance(parsed.get("resources"), dict)
        and isinstance(parsed.get("edges"), list)
    )


def _parse_txt_config(text: str) -> dict[str, Any]:
    config: dict[str, Any] = {"resources": {}, "edges": []}
    section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if line in {"resources:", "edges:"}:
            section = line[:-1]
            continue

        if section == "resources" and ":" in line:
            node, values = line.split(":", 1)
            resources = [item.strip() for item in values.split(",") if item.strip()]
            config["resources"][node.strip()] = resources
            continue

        if section == "edges" and "," in line:
            left, right = line.split(",", 1)
            config["edges"].append([left.strip(), right.strip()])
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in {"num_nodes", "min_neighbors", "max_neighbors"}:
                config[key] = int(value)
            else:
                config[key] = value
            section = None
            continue

        raise ConfigError(f"Linha de configuração não reconhecida: {raw_line}")

    return config


class PeerNetwork:
    def __init__(
        self,
        num_nodes: int,
        min_neighbors: int,
        max_neighbors: int,
        resources: dict[str, list[str]],
        edges: list[tuple[str, str]],
    ) -> None:
        self.num_nodes = num_nodes
        self.min_neighbors = min_neighbors
        self.max_neighbors = max_neighbors
        self.nodes = [f"n{i}" for i in range(1, num_nodes + 1)]
        self.resources = {node: list(values) for node, values in resources.items()}
        self.edges = sorted({tuple(sorted(edge)) for edge in edges})
        self.adjacency = {node: set() for node in self.nodes}
        self.cache: dict[str, dict[str, str]] = {node: {} for node in self.nodes}

        for left, right in self.edges:
            self.adjacency[left].add(right)
            self.adjacency[right].add(left)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "PeerNetwork":
        try:
            num_nodes = int(config["num_nodes"])
            min_neighbors = int(config["min_neighbors"])
            max_neighbors = int(config["max_neighbors"])
            raw_resources = config["resources"]
            raw_edges = config["edges"]
        except KeyError as exc:
            raise ConfigError(f"Campo obrigatório ausente: {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ConfigError("num_nodes, min_neighbors e max_neighbors devem ser inteiros.") from exc

        if not isinstance(raw_resources, dict):
            raise ConfigError("resources deve ser um mapa de nó para lista de recursos.")
        if not isinstance(raw_edges, list):
            raise ConfigError("edges deve ser uma lista de arestas.")

        resources: dict[str, list[str]] = {}
        for node, values in raw_resources.items():
            node_id = str(node).strip()
            if isinstance(values, str):
                node_resources = [item.strip() for item in values.split(",") if item.strip()]
            elif isinstance(values, list):
                node_resources = [str(item).strip() for item in values if str(item).strip()]
            else:
                raise ConfigError(f"Recursos inválidos para o nó {node_id}.")
            resources[node_id] = node_resources

        edges: list[tuple[str, str]] = []
        for edge in raw_edges:
            if isinstance(edge, str):
                parts = [part.strip() for part in edge.split(",")]
            else:
                parts = [str(part).strip() for part in edge]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ConfigError(f"Aresta inválida: {edge}")
            edges.append((parts[0], parts[1]))

        network = cls(num_nodes, min_neighbors, max_neighbors, resources, edges)
        network.validate()
        return network

    def validate(self) -> None:
        if self.num_nodes <= 0:
            raise ConfigError("num_nodes deve ser maior que zero.")
        if self.min_neighbors < 0:
            raise ConfigError("min_neighbors não pode ser negativo.")
        if self.max_neighbors < self.min_neighbors:
            raise ConfigError("max_neighbors deve ser maior ou igual a min_neighbors.")
        if self.max_neighbors >= self.num_nodes and self.num_nodes > 1:
            raise ConfigError("max_neighbors deve ser menor que num_nodes.")

        expected = set(self.nodes)
        resource_nodes = set(self.resources)
        if resource_nodes != expected:
            missing = sorted(expected - resource_nodes)
            extra = sorted(resource_nodes - expected)
            details = []
            if missing:
                details.append(f"sem recursos declarados: {', '.join(missing)}")
            if extra:
                details.append(f"fora de n1..n{self.num_nodes}: {', '.join(extra)}")
            raise ConfigError("Declaração de recursos incompatível com num_nodes (" + "; ".join(details) + ").")

        for node, values in self.resources.items():
            if not values:
                raise ConfigError(f"O nó {node} não possui recursos.")

        seen_edges: set[tuple[str, str]] = set()
        for left, right in self.edges:
            if left == right:
                raise ConfigError(f"Aresta inválida de {left} para ele mesmo.")
            if left not in expected or right not in expected:
                raise ConfigError(f"Aresta referencia nó inexistente: {left}, {right}.")
            seen_edges.add(tuple(sorted((left, right))))

        if len(seen_edges) != len(self.edges):
            raise ConfigError("Há arestas duplicadas na configuração.")

        for node in self.nodes:
            degree = len(self.adjacency[node])
            if degree < self.min_neighbors or degree > self.max_neighbors:
                raise ConfigError(
                    f"O nó {node} tem {degree} vizinhos, fora do limite "
                    f"{self.min_neighbors}..{self.max_neighbors}."
                )

        if len(self._connected_component(self.nodes[0])) != self.num_nodes:
            raise ConfigError("A rede está particionada; nem todos os nós são alcançáveis.")

    def all_resources(self) -> list[str]:
        return sorted({resource for values in self.resources.values() for resource in values})

    def degree_by_node(self) -> dict[str, int]:
        return {node: len(self.adjacency[node]) for node in self.nodes}

    def search(
        self,
        start_node: str,
        resource_id: str,
        ttl: int,
        algorithm: str,
        seed: int | None = None,
    ) -> SearchResult:
        if start_node not in self.adjacency:
            raise ConfigError(f"Nó inicial inexistente: {start_node}.")
        if ttl < 0:
            raise ConfigError("TTL não pode ser negativo.")

        algorithms = {
            "flooding": self._flooding,
            "informed_flooding": self._informed_flooding,
            "random_walk": self._random_walk,
            "informed_random_walk": self._informed_random_walk,
        }
        if algorithm not in algorithms:
            raise ConfigError(f"Algoritmo inválido: {algorithm}.")

        result = algorithms[algorithm](start_node, resource_id, ttl, seed)
        if result.found and result.provider:
            result.cache_updates = self._update_caches(result.path, resource_id, result.provider)
        return result

    def _flooding(self, start: str, resource: str, ttl: int, seed: int | None) -> SearchResult:
        return self._flooding_impl(start, resource, ttl, informed=False)

    def _informed_flooding(self, start: str, resource: str, ttl: int, seed: int | None) -> SearchResult:
        return self._flooding_impl(start, resource, ttl, informed=True)

    def _random_walk(self, start: str, resource: str, ttl: int, seed: int | None) -> SearchResult:
        return self._random_walk_impl(start, resource, ttl, seed, informed=False)

    def _informed_random_walk(self, start: str, resource: str, ttl: int, seed: int | None) -> SearchResult:
        return self._random_walk_impl(start, resource, ttl, seed, informed=True)

    def _flooding_impl(self, start: str, resource: str, ttl: int, informed: bool) -> SearchResult:
        queue: deque[tuple[str, int, list[str]]] = deque([(start, ttl, [start])])
        visited: list[str] = [start]
        processed = {start}
        steps: list[SearchStep] = [
            SearchStep(0, None, start, ttl, "start", f"Busca iniciada em {start}.")
        ]
        messages = 0
        step_index = 1

        while queue:
            node, remaining_ttl, path = queue.popleft()
            provider, cache_hit_at = self._known_provider(node, resource, informed)
            if provider:
                return self._result(
                    "informed_flooding" if informed else "flooding",
                    start,
                    resource,
                    ttl,
                    True,
                    provider,
                    messages,
                    visited,
                    path if cache_hit_at is None else path + [provider],
                    steps,
                    cache_hit_at,
                )

            if remaining_ttl == 0:
                steps.append(
                    SearchStep(step_index, None, node, 0, "ttl_expired", f"TTL esgotado em {node}.")
                )
                step_index += 1
                continue

            for neighbor in sorted(self.adjacency[node]):
                if neighbor in processed:
                    continue
                messages += 1
                processed.add(neighbor)
                visited.append(neighbor)
                next_ttl = remaining_ttl - 1
                steps.append(
                    SearchStep(
                        step_index,
                        node,
                        neighbor,
                        next_ttl,
                        "message",
                        f"{node} enviou a busca para {neighbor}.",
                    )
                )
                step_index += 1
                queue.append((neighbor, next_ttl, path + [neighbor]))

        return self._result(
            "informed_flooding" if informed else "flooding",
            start,
            resource,
            ttl,
            False,
            None,
            messages,
            visited,
            [],
            steps,
            None,
        )

    def _random_walk_impl(
        self,
        start: str,
        resource: str,
        ttl: int,
        seed: int | None,
        informed: bool,
    ) -> SearchResult:
        rng = random.Random(seed)
        current = start
        path = [start]
        visited = [start]
        steps = [SearchStep(0, None, start, ttl, "start", f"Busca iniciada em {start}.")]
        messages = 0

        for hop in range(ttl + 1):
            remaining_ttl = ttl - hop
            provider, cache_hit_at = self._known_provider(current, resource, informed)
            if provider:
                return self._result(
                    "informed_random_walk" if informed else "random_walk",
                    start,
                    resource,
                    ttl,
                    True,
                    provider,
                    messages,
                    visited,
                    path if cache_hit_at is None else path + [provider],
                    steps,
                    cache_hit_at,
                )

            if remaining_ttl == 0:
                steps.append(
                    SearchStep(len(steps), None, current, 0, "ttl_expired", f"TTL esgotado em {current}.")
                )
                break

            candidates = sorted(self.adjacency[current])
            not_in_path = [node for node in candidates if node not in path]
            if not_in_path:
                candidates = not_in_path
            if not candidates:
                steps.append(
                    SearchStep(len(steps), None, current, remaining_ttl, "dead_end", f"{current} não tem vizinhos.")
                )
                break

            next_node = rng.choice(candidates)
            messages += 1
            current_ttl = remaining_ttl - 1
            steps.append(
                SearchStep(
                    len(steps),
                    current,
                    next_node,
                    current_ttl,
                    "message",
                    f"{current} escolheu {next_node} para o passeio aleatório.",
                )
            )
            current = next_node
            path.append(current)
            visited.append(current)

        return self._result(
            "informed_random_walk" if informed else "random_walk",
            start,
            resource,
            ttl,
            False,
            None,
            messages,
            visited,
            [],
            steps,
            None,
        )

    def _known_provider(self, node: str, resource: str, informed: bool) -> tuple[str | None, str | None]:
        if resource in self.resources[node]:
            return node, None

        if informed:
            cached_provider = self.cache[node].get(resource)
            if cached_provider and resource in self.resources.get(cached_provider, []):
                return cached_provider, node

        return None, None

    def _result(
        self,
        algorithm: str,
        start_node: str,
        resource_id: str,
        ttl: int,
        found: bool,
        provider: str | None,
        messages: int,
        visited: list[str],
        path: list[str],
        steps: list[SearchStep],
        cache_hit_at: str | None,
    ) -> SearchResult:
        return SearchResult(
            algorithm=algorithm,
            start_node=start_node,
            resource_id=resource_id,
            ttl=ttl,
            found=found,
            provider=provider,
            messages=messages,
            visited_nodes=visited,
            path=path,
            steps=steps,
            cache_hit_at=cache_hit_at,
        )

    def _update_caches(self, path: list[str], resource: str, provider: str) -> dict[str, str]:
        updates: dict[str, str] = {}
        for node in path:
            if node != provider:
                self.cache[node][resource] = provider
                updates[node] = provider
        return updates

    def _connected_component(self, start: str) -> set[str]:
        visited = {start}
        queue = deque([start])

        while queue:
            node = queue.popleft()
            for neighbor in self.adjacency[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        return visited
