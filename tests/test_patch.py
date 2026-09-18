from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def patch(document, operations):
    return client.post("/patch", json={"document": document, "operations": operations})


# --- add -----------------------------------------------------------------


def test_add_new_object_key():
    r = patch({"a": 1}, [{"op": "add", "path": "/b", "value": 2}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": 1, "b": 2}}


def test_add_replaces_existing_object_key():
    # RFC 6902: add on an existing object member replaces it.
    r = patch({"a": 1}, [{"op": "add", "path": "/a", "value": 99}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": 99}}


def test_add_inserts_into_array_at_index():
    r = patch({"a": [1, 3]}, [{"op": "add", "path": "/a/1", "value": 2}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": [1, 2, 3]}}


def test_add_dash_appends_to_array():
    r = patch({"a": [1, 2]}, [{"op": "add", "path": "/a/-", "value": 3}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": [1, 2, 3]}}


def test_add_at_array_length_appends():
    r = patch({"a": [1]}, [{"op": "add", "path": "/a/1", "value": 2}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": [1, 2]}}


def test_add_array_index_out_of_bounds_returns_409():
    r = patch({"a": [1]}, [{"op": "add", "path": "/a/2", "value": 9}])
    assert r.status_code == 409
    body = r.json()
    assert body["failed_index"] == 0
    assert body["path"] == "/a/2"
    assert "out of bounds" in body["reason"]
    assert "document" not in body


def test_add_does_not_create_intermediate_paths():
    r = patch({}, [{"op": "add", "path": "/a/b", "value": 1}])
    assert r.status_code == 409
    assert r.json()["failed_index"] == 0


def test_add_at_root_replaces_whole_document():
    r = patch({"a": 1}, [{"op": "add", "path": "", "value": [1, 2]}])
    assert r.status_code == 200
    assert r.json() == {"document": [1, 2]}


def test_add_null_value_is_accepted():
    r = patch({}, [{"op": "add", "path": "/a", "value": None}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": None}}


# --- remove ---------------------------------------------------------------


def test_remove_object_key():
    r = patch({"a": 1, "b": 2}, [{"op": "remove", "path": "/a"}])
    assert r.status_code == 200
    assert r.json() == {"document": {"b": 2}}


def test_remove_array_element():
    r = patch({"a": [1, 2, 3]}, [{"op": "remove", "path": "/a/1"}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": [1, 3]}}


def test_remove_missing_key_returns_409():
    r = patch({"a": 1}, [{"op": "remove", "path": "/nope"}])
    assert r.status_code == 409
    body = r.json()
    assert body["failed_index"] == 0
    assert body["path"] == "/nope"
    assert "document" not in body


def test_remove_array_index_out_of_bounds_returns_409():
    r = patch({"a": [1]}, [{"op": "remove", "path": "/a/1"}])
    assert r.status_code == 409
    assert "out of bounds" in r.json()["reason"]


def test_remove_dash_is_rejected_with_409():
    r = patch({"a": [1, 2]}, [{"op": "remove", "path": "/a/-"}])
    assert r.status_code == 409
    assert r.json()["failed_index"] == 0


def test_remove_at_root_yields_null_document():
    r = patch({"a": 1}, [{"op": "remove", "path": ""}])
    assert r.status_code == 200
    assert r.json() == {"document": None}


def test_remove_with_value_is_rejected_422():
    r = patch({"a": 1}, [{"op": "remove", "path": "/a", "value": 1}])
    assert r.status_code == 422


# --- replace --------------------------------------------------------------


def test_replace_object_key():
    r = patch({"a": 1}, [{"op": "replace", "path": "/a", "value": 2}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": 2}}


def test_replace_array_element():
    r = patch({"a": [1, 2]}, [{"op": "replace", "path": "/a/0", "value": 9}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": [9, 2]}}


def test_replace_missing_key_returns_409():
    r = patch({}, [{"op": "replace", "path": "/a", "value": 1}])
    assert r.status_code == 409
    assert r.json()["path"] == "/a"


def test_replace_dash_is_rejected_with_409():
    r = patch({"a": [1]}, [{"op": "replace", "path": "/a/-", "value": 9}])
    assert r.status_code == 409


def test_replace_at_root():
    r = patch(1, [{"op": "replace", "path": "", "value": {"x": True}}])
    assert r.status_code == 200
    assert r.json() == {"document": {"x": True}}


# --- test -----------------------------------------------------------------


def test_test_operation_passes_and_leaves_document_unchanged():
    r = patch({"a": {"b": [1, 2]}}, [{"op": "test", "path": "/a", "value": {"b": [1, 2]}}])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": {"b": [1, 2]}}}


def test_test_operation_failure_returns_409():
    r = patch({"a": 1}, [{"op": "test", "path": "/a", "value": 2}])
    assert r.status_code == 409
    body = r.json()
    assert body["failed_index"] == 0
    assert body["path"] == "/a"
    assert "test" in body["reason"]
    assert "document" not in body


def test_test_missing_path_returns_409():
    r = patch({}, [{"op": "test", "path": "/a", "value": 1}])
    assert r.status_code == 409


def test_test_uses_service_json_equality_rules():
    # 1 and 1.0 are the same JSON number; true and 1 are not the same value.
    r = patch({"a": 1}, [{"op": "test", "path": "/a", "value": 1.0}])
    assert r.status_code == 200
    r = patch({"a": True}, [{"op": "test", "path": "/a", "value": 1}])
    assert r.status_code == 409


def test_test_at_root():
    r = patch([1, 2], [{"op": "test", "path": "", "value": [1, 2]}])
    assert r.status_code == 200
    assert r.json() == {"document": [1, 2]}


# --- JSON Pointer syntax ---------------------------------------------------


def test_pointer_unescapes_tilde_and_slash():
    doc = {"a/b": 1, "m~n": 2}
    r = patch(doc, [
        {"op": "test", "path": "/a~1b", "value": 1},
        {"op": "test", "path": "/m~0n", "value": 2},
    ])
    assert r.status_code == 200
    assert r.json() == {"document": doc}


def test_pointer_without_leading_slash_is_422():
    r = patch({"a": 1}, [{"op": "replace", "path": "a", "value": 2}])
    assert r.status_code == 422


def test_pointer_with_bad_escape_is_422():
    r = patch({"a": 1}, [{"op": "replace", "path": "/a~2b", "value": 2}])
    assert r.status_code == 422


def test_pointer_with_trailing_tilde_is_422():
    r = patch({"a": 1}, [{"op": "replace", "path": "/a~", "value": 2}])
    assert r.status_code == 422


def test_empty_key_token_addresses_empty_string_key():
    r = patch({"": 1}, [{"op": "replace", "path": "/", "value": 2}])
    assert r.status_code == 200
    assert r.json() == {"document": {"": 2}}


# --- operation structure ---------------------------------------------------


def test_missing_value_for_add_replace_test_is_422():
    for op in ("add", "replace", "test"):
        r = patch({"a": 1}, [{"op": op, "path": "/a"}])
        assert r.status_code == 422, op


def test_unknown_op_is_422():
    r = patch({"a": 1}, [{"op": "move", "path": "/a", "value": 1}])
    assert r.status_code == 422


def test_operation_not_an_object_is_422():
    r = patch({"a": 1}, ["remove /a"])
    assert r.status_code == 422


def test_missing_path_is_422():
    r = patch({"a": 1}, [{"op": "remove"}])
    assert r.status_code == 422


def test_missing_request_fields_are_422():
    assert client.post("/patch", json={"document": {}}).status_code == 422
    assert client.post("/patch", json={"operations": []}).status_code == 422


def test_operations_must_be_a_list():
    r = client.post("/patch", json={"document": {}, "operations": {}})
    assert r.status_code == 422


# --- atomicity and ordering ------------------------------------------------


def test_operations_apply_in_order():
    r = patch(
        {"a": [1]},
        [
            {"op": "add", "path": "/a/-", "value": 2},
            {"op": "replace", "path": "/a/0", "value": 10},
            {"op": "remove", "path": "/a/1"},
        ],
    )
    assert r.status_code == 200
    assert r.json() == {"document": {"a": [10]}}


def test_failure_is_atomic_and_reports_failed_index():
    r = patch(
        {"a": 1, "b": 2},
        [
            {"op": "replace", "path": "/a", "value": 100},  # would succeed
            {"op": "remove", "path": "/missing"},           # fails
        ],
    )
    assert r.status_code == 409
    body = r.json()
    assert body["failed_index"] == 1
    assert body["path"] == "/missing"
    assert body["reason"]
    # No partial result is returned.
    assert "document" not in body


def test_failed_patch_does_not_mutate_the_document_for_later_requests():
    doc = {"a": [1, 2, 3]}
    r = patch(doc, [
        {"op": "remove", "path": "/a/0"},
        {"op": "remove", "path": "/a/9"},
    ])
    assert r.status_code == 409
    # A subsequent valid patch sees the original document shape.
    r = patch(doc, [{"op": "test", "path": "/a", "value": [1, 2, 3]}])
    assert r.status_code == 200


def test_empty_operations_return_document_unchanged():
    r = patch({"a": 1}, [])
    assert r.status_code == 200
    assert r.json() == {"document": {"a": 1}}


def test_invalid_syntax_anywhere_is_422_even_if_another_op_would_fail():
    # Structural validation of the whole request precedes execution.
    r = patch(
        {},
        [
            {"op": "remove", "path": "/missing"},
            {"op": "replace", "path": "no-slash", "value": 1},
        ],
    )
    assert r.status_code == 422


# --- merge and health are unaffected ---------------------------------------


def test_merge_still_works():
    r = client.post("/merge", json={"base": {"a": 1}, "left": {"a": 2}, "right": {"a": 1}})
    assert r.status_code == 200
    assert r.json() == {"merged": {"a": 2}}


def test_health_still_works():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
