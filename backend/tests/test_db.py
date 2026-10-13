import json
import uuid
from unittest.mock import Mock
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from db import DatabaseUnavailable, OwnedServer, ServerRepository

SERVER_ID = "3f2a6c1e-0000-4000-8000-000000000001"

def repository(records=None, error=None):
    repo = ServerRepository("arn:cluster", "arn:secret", "mcec2", "us-east-1")
    repo.client = Mock()
    if error:
        repo.client.execute_statement.side_effect = error
    else:
        repo.client.execute_statement.return_value = {"formattedRecords": json.dumps(records or [])}
    return repo

def test_owned_server_query_is_parameterized():
    repo = repository([{"id": SERVER_ID, "instance_id": "i-test", "region": "us-east-1"}])
    assert repo.get_owned_server("owner-sub", SERVER_ID) == OwnedServer(SERVER_ID, "i-test", "us-east-1")
    kwargs = repo.client.execute_statement.call_args.kwargs
    assert (kwargs["resourceArn"], kwargs["secretArn"], kwargs["database"]) == ("arn:cluster", "arn:secret", "mcec2")
    assert kwargs["formatRecordsAs"] == "JSON"
    assert "owner-sub" not in kwargs["sql"]
    assert kwargs["parameters"] == [
        {"name": "sub", "value": {"stringValue": "owner-sub"}},
        {"name": "server_id", "value": {"stringValue": SERVER_ID}, "typeHint": "UUID"}]

def test_not_owned_returns_none():
    assert repository([]).get_owned_server("stranger", SERVER_ID) is None

def test_null_instance_id():
    repo = repository([{"id": SERVER_ID, "region": "us-east-1"}])  # JSON records omit NULL columns
    assert repo.get_owned_server("owner-sub", SERVER_ID).instance_id is None

@pytest.mark.parametrize("server_id", ["my-server", "", "1; DROP TABLE servers"])
def test_non_uuid_ids_skip_the_database(server_id):
    repo = repository()
    assert repo.get_owned_server("owner-sub", server_id) is None
    repo.client.execute_statement.assert_not_called()

def test_resuming_database_sets_retry_after():
    error = ClientError({"Error": {"Code": "DatabaseResumingException"}}, "ExecuteStatement")
    with pytest.raises(DatabaseUnavailable) as exc:
        repository(error=error).get_owned_server("owner-sub", SERVER_ID)
    assert exc.value.retry_after == 15

@pytest.mark.parametrize("error", [
    ClientError({"Error": {"Code": "AccessDeniedException"}}, "ExecuteStatement"),
    EndpointConnectionError(endpoint_url="https://rds-data.example")])
def test_other_database_errors(error):
    with pytest.raises(DatabaseUnavailable) as exc:
        repository(error=error).get_owned_server("owner-sub", SERVER_ID)
    assert exc.value.retry_after is None

def test_param_types():
    from db import _param
    assert _param("n", None) == {"name": "n", "value": {"isNull": True}}
    assert _param("n", True) == {"name": "n", "value": {"booleanValue": True}}
    assert _param("n", 3) == {"name": "n", "value": {"longValue": 3}}
    assert _param("n", uuid.UUID(SERVER_ID))["typeHint"] == "UUID"
