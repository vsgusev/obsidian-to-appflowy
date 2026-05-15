"""Tests for importer helpers that don't require HTTP."""

import requests_mock as req_mock

from obsidian_to_appflowy.importer import _create_page, _next_space_name


def test_create_page_sends_collab_id_matching_view_id() -> None:
    # AppFlowy stores the document under collab_id and the view under view_id.
    # If they differ, opening the page returns "Page not found".
    view_id = "aaaaaaaa-0000-0000-0000-000000000001"
    with req_mock.Mocker() as m:
        m.post(
            "http://test/api/workspace/ws1/page-view",
            json={"data": {"view_id": view_id}},
        )
        _create_page("http://test", "tok", "ws1", "parent", "Title", None, view_id=view_id)
        sent = m.last_request.json()
    assert sent["view_id"] == view_id
    assert sent["collab_id"] == view_id, "collab_id must equal view_id or AppFlowy can't find the document"


def test_create_page_without_view_id_sends_null() -> None:
    with req_mock.Mocker() as m:
        m.post(
            "http://test/api/workspace/ws1/page-view",
            json={"data": {"view_id": "server-generated"}},
        )
        _create_page("http://test", "tok", "ws1", "parent", "Title", None)
        sent = m.last_request.json()
    assert sent["view_id"] is None
    assert sent["collab_id"] is None


def test_next_space_name_basic() -> None:
    assert _next_space_name("Obsidian", set()) == "Obsidian 2"


def test_next_space_name_skips_taken() -> None:
    assert _next_space_name("Obsidian", {"Obsidian 2"}) == "Obsidian 3"


def test_next_space_name_skips_multiple() -> None:
    assert _next_space_name("Obsidian", {"Obsidian 2", "Obsidian 3", "Obsidian 4"}) == "Obsidian 5"
