"""The picture of the graph: bounded, deterministic, inside the frame."""

from filegrail.graph import Graph, Node, Relationship
from filegrail.graphlayout import HEIGHT, MAX_NODES, WIDTH, picture


def _star(spokes: int) -> Graph:
    hub = Node("email:hub@example.org", "email", "hub@example.org")
    files = [Node(f"file:/case/{n}.pdf", "file", f"/case/{n}.pdf") for n in range(spokes)]
    edges = [Relationship(f.id, hub.id, "has identifier", 1, ()) for f in files]
    return Graph((hub, *files), tuple(edges))


def test_a_large_graph_is_cut_to_the_frame_and_laid_out_the_same_way_twice():
    graph = _star(300)

    drawn = picture(graph)
    again = picture(graph)

    assert drawn is not None
    assert len(drawn.nodes) == MAX_NODES
    assert drawn.left_out == 301 - MAX_NODES
    assert drawn.nodes[0].id == "email:hub@example.org"  # the hub comes first
    assert all(0 <= n.x <= WIDTH and 0 <= n.y <= HEIGHT for n in drawn.nodes)
    assert [(n.x, n.y) for n in drawn.nodes] == [(n.x, n.y) for n in again.nodes]


def test_an_empty_graph_draws_nothing():
    assert picture(Graph((), ())) is None
