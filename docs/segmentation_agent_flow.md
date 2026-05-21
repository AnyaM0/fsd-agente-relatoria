# Segmentation Agent Flow

This document separates:

- the real `LangGraph` structure exported from `create_iterative_segmentation_graph().get_graph()`
- the logical tool subflows that happen inside `route_chunk` and `decide_segment`

## LangGraph Structure

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
    __start__([<p>__start__</p>]):::first
    load_chunk(load_chunk)
    summarize_chunk(summarize_chunk)
    route_chunk(route_chunk)
    prepare_whole_chunk(prepare_whole_chunk)
    prepare_split_units(prepare_split_units)
    summarize_unit(summarize_unit)
    seed_first_segment(seed_first_segment)
    decide_segment(decide_segment)
    apply_decision(apply_decision)
    advance_cursor(advance_cursor)
    __end__([<p>__end__</p>]):::last
    __start__ --> load_chunk;
    advance_cursor -.-> __end__;
    advance_cursor -.-> load_chunk;
    advance_cursor -.-> summarize_unit;
    apply_decision --> advance_cursor;
    decide_segment --> apply_decision;
    load_chunk --> summarize_chunk;
    prepare_split_units --> summarize_unit;
    prepare_whole_chunk --> apply_decision;
    route_chunk -.-> prepare_split_units;
    route_chunk -.-> prepare_whole_chunk;
    seed_first_segment --> apply_decision;
    summarize_chunk --> route_chunk;
    summarize_unit -.-> decide_segment;
    summarize_unit -.-> seed_first_segment;
    classDef default fill:#f2f0ff,line-height:1.2
    classDef first fill-opacity:0
    classDef last fill:#bfb6fc
```

## Logical Tool Subgraph: `route_chunk`

`route_chunk` is a single LangGraph node, but internally it can call tools through the model when deciding:

- `append`
- `new`
- `split`

```mermaid
flowchart TD
    A[route_chunk] --> B{Need more context?}

    subgraph RouteChunkTools[Tools used inside route_chunk]
        T1[read_chunk]
        T2[read_segment]
    end

    B -->|yes| T1
    B -->|yes| T2
    T1 --> C[LLM chunk routing decision]
    T2 --> C
    B -->|no| C

    C --> D{Routing action}
    D -->|append| E[prepare_whole_chunk]
    D -->|new| E
    D -->|split| F[prepare_split_units]
```

## Logical Tool Subgraph: `decide_segment`

After a split, each subunit is summarized and then assigned semantically.

```mermaid
flowchart TD
    A[summarize_unit] --> B{First segment?}
    B -->|yes| C[seed_first_segment]
    B -->|no| D[decide_segment]

    subgraph DecideSegmentTools[Tools used inside decide_segment]
        T1[read_chunk]
        T2[read_segment]
    end

    D --> E{Need more context?}
    E -->|yes| T1
    E -->|yes| T2
    T1 --> F[LLM segment placement decision]
    T2 --> F
    E -->|no| F

    F --> G{Placement}
    G -->|append| H[apply_decision]
    G -->|new| H
```

## Note

To see the internal tool subgraphs in the rendered graph, export with `xray=1`:

```python
png = graph.get_graph(xray=1).draw_mermaid_png()
```

Without `xray`, LangGraph shows the collapsed top-level workflow and hides the internal subgraph nodes.
