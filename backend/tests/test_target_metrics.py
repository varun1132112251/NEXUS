from app.api.v1.routes.targets import inferred_metric_type


def test_inferred_target_metric_types() -> None:
    assert inferred_metric_type("Solve 150 DSA Problems") == "problems_solved"
    assert inferred_metric_type("Read 2 Books") == "books_completed"
    assert inferred_metric_type("25 English Sessions") == "sessions_completed"
    assert inferred_metric_type("GATE DBMS Revision") == "topics_revised"
    assert inferred_metric_type("Complete NEXUS V1") == "milestones_completed"
    assert inferred_metric_type("Weekly deep work") == "count"
