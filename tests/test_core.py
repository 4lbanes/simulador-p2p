from p2p_simulator import ConfigError, PeerNetwork, parse_config_text


CONFIG = """
num_nodes: 4
min_neighbors: 1
max_neighbors: 3
resources:
  n1: r1
  n2: r2
  n3: r3
  n4: r4
edges:
  n1, n2
  n2, n3
  n3, n4
"""


def test_flooding_finds_resource_and_updates_cache():
    network = PeerNetwork.from_config(parse_config_text(CONFIG))

    result = network.search("n1", "r4", ttl=3, algorithm="flooding")

    assert result.found is True
    assert result.provider == "n4"
    assert result.messages == 3
    assert result.visited_count == 4
    assert result.path == ["n1", "n2", "n3", "n4"]
    assert network.cache["n1"]["r4"] == "n4"


def test_informed_random_walk_uses_cache_after_previous_search():
    network = PeerNetwork.from_config(parse_config_text(CONFIG))
    network.search("n1", "r4", ttl=3, algorithm="flooding")

    result = network.search("n1", "r4", ttl=1, algorithm="informed_random_walk", seed=1)

    assert result.found is True
    assert result.provider == "n4"
    assert result.cache_hit_at == "n1"
    assert result.messages == 0


def test_partitioned_network_is_rejected():
    config = parse_config_text(
        """
        num_nodes: 4
        min_neighbors: 1
        max_neighbors: 2
        resources:
          n1: r1
          n2: r2
          n3: r3
          n4: r4
        edges:
          n1, n2
          n3, n4
        """
    )

    try:
        PeerNetwork.from_config(config)
    except ConfigError as exc:
        assert "particionada" in str(exc)
    else:
        raise AssertionError("Configuração particionada deveria falhar.")
