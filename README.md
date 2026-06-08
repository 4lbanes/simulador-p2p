# Simulador de Busca em Sistemas P2P

Implementação do simulador descrito em `docs/trab.md`, usando os algoritmos do PDF antigo como referência técnica.

## Funcionalidades

- Carrega uma rede P2P por arquivo ou texto em JSON, YAML ou TXT.
- Valida se a rede está conectada, se respeita os limites de vizinhos, se todos os nós possuem recursos e se não há laços.
- Executa buscas com TTL pelos algoritmos:
  - `flooding`
  - `informed_flooding`
  - `random_walk`
  - `informed_random_walk`
- Mostra o rastro visual e textual da busca.
- Exibe log final com resultado, nó onde encontrou, mensagens trocadas e nós visitados.
- Mantém cache entre buscas na mesma sessão para demonstrar as buscas informadas.

## Como rodar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Depois acesse o endereço exibido pelo Streamlit, normalmente `http://localhost:8501`.

## Formato do arquivo

Exemplo em YAML/TXT:

```yaml
num_nodes: 8
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
```

Também há exemplos em `examples/rede_exemplo.yaml` e `examples/rede_exemplo.json`.

## Testes

```bash
pytest
```
