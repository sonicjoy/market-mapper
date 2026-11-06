"""SPA document paths include Coverage, Unmapped, and Cart."""

from __future__ import annotations

from mappers.control_plane.spa_static import is_spa_document_path


def test_explore_and_work_routes_are_spa_documents() -> None:
    for path in ("/coverage", "/unmapped", "/catalog", "/cart", "/entry", "/review", "/rules"):
        assert is_spa_document_path(path)
    assert is_spa_document_path("/review/prop_abc")
    assert not is_spa_document_path("/console/coverage/fixtures")
