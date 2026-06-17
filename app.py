from __future__ import annotations

import time

import networkx as nx
import plotly.graph_objects as go
import streamlit as st

from p2p_simulator import ConfigError, PeerNetwork, SearchResult, parse_config_text


DEFAULT_CONFIG = """num_nodes: 8
min_neighbors: 2
max_neighbors: 4
resources:
  n1: r1, r2
  n2: r3
  n3: r4, r5
  n4: r6
  n5: r7
  n6: r8, r9
  n7: r10
  n8: r11
edges:
  n1, n2
  n1, n3
  n2, n3
  n2, n4
  n3, n5
  n4, n5
  n4, n6
  n5, n7
  n6, n8
  n7, n8
"""


ALGORITHMS = {
    "flooding": "Inundação",
    "informed_flooding": "Inundação informada",
    "random_walk": "Passeio aleatório",
    "informed_random_walk": "Passeio aleatório informado",
}


def main() -> None:
    st.set_page_config(page_title="Simulador P2P", layout="wide")
    inject_css()

    if "config_text" not in st.session_state:
        st.session_state.config_text = DEFAULT_CONFIG
    if "network" not in st.session_state:
        st.session_state.network = build_network(DEFAULT_CONFIG)
    if "result" not in st.session_state:
        st.session_state.result = None

    st.title("Simulador de Busca em Sistemas P2P")
    st.caption("Carregue uma topologia, escolha o algoritmo e acompanhe o rastro da busca na rede.")

    with st.sidebar:
        st.header("Configuração")
        uploaded = st.file_uploader("Arquivo JSON, YAML ou TXT", type=["json", "yaml", "yml", "txt"])
        if uploaded is not None:
            st.session_state.config_text = uploaded.read().decode("utf-8")

        config_text = st.text_area(
            "Estrutura da rede",
            value=st.session_state.config_text,
            height=360,
            help="Informe num_nodes, min_neighbors, max_neighbors, resources e edges.",
        )
        st.session_state.config_text = config_text

        if st.button("Carregar e validar rede", use_container_width=True):
            try:
                st.session_state.network = build_network(config_text)
                st.session_state.result = None
                st.success("Rede carregada e validada.")
            except Exception as exc:
                st.error(str(exc))

    network: PeerNetwork = st.session_state.network
    result: SearchResult | None = st.session_state.result

    render_network_summary(network)

    left, right = st.columns([0.95, 1.55], gap="large")
    with left:
        render_search_form(network)
        render_resources(network)
    with right:
        render_graph(network, result)

    if result:
        render_result(result, network)


def build_network(text: str) -> PeerNetwork:
    return PeerNetwork.from_config(parse_config_text(text))


def render_network_summary(network: PeerNetwork) -> None:
    degrees = network.degree_by_node()
    total_resources = sum(len(values) for values in network.resources.values())
    cols = st.columns(4)
    cols[0].metric("Nós", network.num_nodes)
    cols[1].metric("Arestas", len(network.edges))
    cols[2].metric("Recursos", total_resources)
    cols[3].metric("Grau min/max", f"{min(degrees.values())}/{max(degrees.values())}")


def render_search_form(network: PeerNetwork) -> None:
    with st.container(border=True):
        st.subheader("Buscar recurso")
        with st.form("search-form"):
            start_node = st.selectbox("Nó inicial", network.nodes)
            resource_id = st.selectbox("Recurso", network.all_resources())
            ttl = st.number_input(
                "TTL",
                min_value=0,
                max_value=network.num_nodes * 2,
                value=min(4, network.num_nodes),
                step=1,
            )
            algorithm = st.selectbox(
                "Algoritmo",
                list(ALGORITHMS),
                format_func=lambda value: ALGORITHMS[value],
            )
            submitted = st.form_submit_button("Executar busca", use_container_width=True)

    if submitted:
        try:
            st.session_state.result = network.search(start_node, resource_id, int(ttl), algorithm)
            st.rerun()
        except ConfigError as exc:
            st.error(str(exc))


def render_resources(network: PeerNetwork) -> None:
    with st.expander("Recursos por nó", expanded=True):
        rows = [
            {
                "Nó": node,
                "Vizinhos": ", ".join(sorted(network.adjacency[node])),
                "Recursos": ", ".join(network.resources[node]),
            }
            for node in network.nodes
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("Cache informado"):
        cache_rows = [
            {"Nó": node, "Recurso": resource, "Fornecedor conhecido": provider}
            for node, values in network.cache.items()
            for resource, provider in sorted(values.items())
        ]
        if cache_rows:
            st.dataframe(cache_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("O cache será preenchido após buscas bem-sucedidas.")


def render_graph(network: PeerNetwork, result: SearchResult | None) -> None:
    with st.container(border=True):
        st.subheader("Rede e rastro")
        st.caption(
            "Azul: nó comum. Laranja: visitado. Verde: fornecedor encontrado. "
            "Seta laranja: caminho até o recurso. Linha roxa: outras conexões usadas na busca."
        )

        highlighted_nodes = set(result.visited_nodes) if result else set()
        path_sequence = result.path if result else []
        path_edges = set()
        for left, right in zip(path_sequence, path_sequence[1:]):
            if left in network.adjacency and right in network.adjacency[left]:
                path_edges.add(tuple(sorted((left, right))))

        traversed_edges = set()
        if result:
            for step in result.steps:
                if step.kind == "message" and step.from_node:
                    traversed_edges.add(tuple(sorted((step.from_node, step.to_node))))
        other_visited_edges = traversed_edges - path_edges

        fig = build_graph_figure(
            network,
            highlighted_nodes,
            path_edges,
            other_visited_edges,
            path_sequence,
            result.provider if result else None,
        )
        st.plotly_chart(fig, use_container_width=True)

        if result:
            selected_step = st.slider("Etapa do rastro", min_value=0, max_value=len(result.steps) - 1, value=len(result.steps) - 1)
            step = result.steps[selected_step]
            st.info(f"{step.index}. {step.note} TTL restante: {step.ttl_after}")

            if st.button("Reproduzir rastro", use_container_width=True):
                placeholder = st.empty()
                for item in result.steps:
                    placeholder.info(f"{item.index}. {item.note} TTL restante: {item.ttl_after}")
                    time.sleep(0.35)


def build_graph_figure(
    network: PeerNetwork,
    highlighted_nodes: set[str],
    path_edges: set[tuple[str, str]],
    other_visited_edges: set[tuple[str, str]],
    path_sequence: list[str],
    provider: str | None,
) -> go.Figure:
    graph = nx.Graph()
    graph.add_nodes_from(network.nodes)
    graph.add_edges_from(network.edges)
    positions = nx.spring_layout(graph, seed=42)

    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    path_x: list[float | None] = []
    path_y: list[float | None] = []
    visited_edge_x: list[float | None] = []
    visited_edge_y: list[float | None] = []

    for left, right in network.edges:
        x0, y0 = positions[left]
        x1, y1 = positions[right]
        key = tuple(sorted((left, right)))
        if key in path_edges:
            target_x, target_y = path_x, path_y
        elif key in other_visited_edges:
            target_x, target_y = visited_edge_x, visited_edge_y
        else:
            target_x, target_y = edge_x, edge_y
        target_x.extend([x0, x1, None])
        target_y.extend([y0, y1, None])

    node_x = []
    node_y = []
    node_colors = []
    node_sizes = []
    hover = []
    for node in network.nodes:
        x, y = positions[node]
        node_x.append(x)
        node_y.append(y)
        if provider == node:
            node_colors.append("#16a34a")
            node_sizes.append(30)
        elif node in highlighted_nodes:
            node_colors.append("#f97316")
            node_sizes.append(24)
        else:
            node_colors.append("#2563eb")
            node_sizes.append(26)
        hover.append(
            f"<b>{node}</b><br>"
            f"Recursos: {', '.join(network.resources[node])}<br>"
            f"Vizinhos: {', '.join(sorted(network.adjacency[node]))}"
        )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=2.2, color="#64748b"),
            hoverinfo="none",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=visited_edge_x,
            y=visited_edge_y,
            mode="lines",
            line=dict(width=3.4, color="#9333ea"),
            hoverinfo="none",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=path_x,
            y=path_y,
            mode="lines",
            line=dict(width=5, color="#ea580c"),
            hoverinfo="none",
            name="Caminho",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=network.nodes,
            textposition="middle center",
            marker=dict(size=node_sizes, color=node_colors, line=dict(width=2, color="white")),
            textfont=dict(color="white", size=12, family="Arial Black"),
            hovertext=hover,
            hoverinfo="text",
            name="Nós",
        )
    )
    arrows = []
    for source, target in zip(path_sequence, path_sequence[1:]):
        if source not in positions or target not in positions:
            continue
        if target not in network.adjacency.get(source, set()):
            continue
        ax_pos, ay_pos = positions[source]
        x_pos, y_pos = positions[target]
        arrows.append(
            dict(
                x=x_pos,
                y=y_pos,
                ax=ax_pos,
                ay=ay_pos,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=3,
                arrowsize=1.4,
                arrowwidth=3.2,
                arrowcolor="#c2410c",
                standoff=16,
                startstandoff=16,
                text="",
            )
        )

    fig.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
        annotations=arrows,
    )
    return fig


def render_result(result: SearchResult, network: PeerNetwork) -> None:
    st.subheader("Log final")
    cols = st.columns(4)
    cols[0].metric("Resultado", "Achou" if result.found else "Não achou")
    cols[1].metric("Onde achou", result.provider or "-")
    cols[2].metric("Mensagens", result.messages)
    cols[3].metric("Nós visitados", result.visited_count)

    if result.cache_hit_at:
        st.success(f"Cache usado em {result.cache_hit_at}: recurso {result.resource_id} conhecido em {result.provider}.")

    if result.path:
        st.write("Trajeto:", " -> ".join(result.path))

    st.dataframe(
        [
            {
                "Etapa": step.index,
                "Origem": step.from_node or "-",
                "Destino": step.to_node,
                "TTL restante": step.ttl_after,
                "Tipo": step.kind,
                "Descrição": step.note,
            }
            for step in result.steps
        ],
        use_container_width=True,
        hide_index=True,
    )

    if result.cache_updates:
        st.caption(
            "Cache atualizado: "
            + ", ".join(f"{node} sabe que {result.resource_id} está em {provider}" for node, provider in result.cache_updates.items())
        )


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --p2p-bg: #f5f7fb;
            --p2p-panel: #ffffff;
            --p2p-border: #d8dee9;
            --p2p-text: #0f172a;
            --p2p-muted: #475569;
            --p2p-blue: #1d4ed8;
        }
        .stApp {
            background: var(--p2p-bg);
            color: var(--p2p-text);
        }
        header[data-testid="stHeader"] {
            background: #0f172a;
        }
        section[data-testid="stSidebar"] {
            background: #e9eef5;
            border-right: 1px solid var(--p2p-border);
        }
        section[data-testid="stSidebar"] * {
            color: var(--p2p-text);
        }
        .stApp h1,
        .stApp h2,
        .stApp h3,
        .stApp label,
        .stApp p {
            color: var(--p2p-text);
        }
        div[data-testid="stCaptionContainer"] p,
        div[data-testid="stMarkdownContainer"] p {
            color: var(--p2p-muted);
        }
        div[data-testid="stMetric"] {
            background: var(--p2p-panel);
            border: 1px solid var(--p2p-border);
            border-radius: 8px;
            padding: 14px 16px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
        }
        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] div {
            color: var(--p2p-text);
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--p2p-panel);
            border-color: var(--p2p-border);
        }
        textarea,
        input,
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div {
            background: #ffffff;
            color: var(--p2p-text);
            border-color: #cbd5e1;
        }
        textarea {
            font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
            font-size: 0.88rem;
            line-height: 1.45;
        }
        div[data-testid="stFileUploaderDropzone"] {
            background: #ffffff;
            border: 1px dashed #94a3b8;
        }
        div[data-testid="stFileUploaderDropzone"] small,
        div[data-testid="stFileUploaderDropzone"] span {
            color: var(--p2p-muted);
        }
        .stButton button, .stFormSubmitButton button {
            border-radius: 8px;
            font-weight: 700;
            background: var(--p2p-blue);
            border: 1px solid var(--p2p-blue);
            color: #ffffff;
        }
        .stButton button:hover, .stFormSubmitButton button:hover {
            background: #1e40af;
            border-color: #1e40af;
            color: #ffffff;
        }
        [data-testid="stExpander"] {
            background: #ffffff;
            border: 1px solid var(--p2p-border);
            border-radius: 8px;
        }
        [data-testid="stDataFrame"] {
            border: 1px solid var(--p2p-border);
            border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
