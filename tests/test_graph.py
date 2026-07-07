"""Tests for the exercise knowledge graph."""

from langwich.graph import ExerciseType, build_default_graph


def test_graph_has_full_task_library():
    g = build_default_graph()
    assert len(g.exercises()) >= 58


def test_every_exercise_type_is_represented():
    g = build_default_graph()
    used = {n.exercise_type for n in g.exercises()}
    assert used == set(ExerciseType)


def test_node_ids_unique_and_prefixed():
    g = build_default_graph()
    prefixes = {
        ExerciseType.FILL_IN_BLANKS: "fib_",
        ExerciseType.PICTURE_INTERACTION: "pic_",
        ExerciseType.WORD_CONNECTIONS: "wc_",
        ExerciseType.PUZZLE: "pz_",
        ExerciseType.TEXT_ANALYSIS: "ta_",
        ExerciseType.WRITING: "wr_",
        ExerciseType.DIALOGUE: "dlg_",
        ExerciseType.MEDIA: "media_",
        ExerciseType.SOCIAL_MEDIA: "soc_",
        ExerciseType.REAL_WORLD: "rw_",
        ExerciseType.NUMBERS: "num_",
        ExerciseType.STUDY: "st_",
    }
    for node in g.exercises():
        assert node.id.startswith(prefixes[node.exercise_type]), node.id


def test_combinable_and_edges_reference_existing_nodes():
    g = build_default_graph()
    ids = set(g.nodes)
    for node in g.exercises():
        for ref in node.combinable_with:
            assert ref in ids, f"{node.id} -> {ref}"
    for edge in g.edges:
        assert edge.source in ids and edge.target in ids


def test_difficulty_and_metadata_sane():
    g = build_default_graph()
    for node in g.exercises():
        assert 1 <= node.difficulty <= 5, node.id
        assert node.description, node.id
        assert node.learning_focus, node.id
        assert node.estimated_minutes > 0, node.id


def test_media_nodes_declare_culture_category():
    g = build_default_graph()
    for node in g.get_by_type(ExerciseType.MEDIA):
        assert node.media_category, node.id


def test_graph_serializes():
    g = build_default_graph()
    d = g.to_dict()
    assert set(d) == {"nodes", "edges"}
    assert len(d["nodes"]) == len(g.nodes)
