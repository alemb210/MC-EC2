import json
import uuid
from unittest.mock import Mock
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from db import DatabaseUnavailable, OwnedServer, ServerLimitReached, ServerRepository, ServerRow

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

# --- Registration and server creation ---

USER_ID = "3f2a6c1e-0000-4000-8000-0000000000aa"

def sqls(repo):
    return [c.kwargs["sql"] for c in repo.client.execute_statement.call_args_list]

@pytest.mark.parametrize("created", [True, False])
def test_ensure_user(created):
    repo = repository([{"user_id": USER_ID, "created": created}])
    assert repo.ensure_user("new-sub") == (USER_ID, created)
    kwargs = repo.client.execute_statement.call_args.kwargs
    assert "new-sub" not in kwargs["sql"]
    assert kwargs["parameters"] == [{"name": "sub", "value": {"stringValue": "new-sub"}}]

def test_ensure_user_lost_race_reads_winner():
    repo = repository()
    repo.client.execute_statement.side_effect = [
        {"formattedRecords": "[]"}, {"formattedRecords": json.dumps([{"user_id": USER_ID}])}]
    assert repo.ensure_user("new-sub") == (USER_ID, False)

def transactional(*results):
    repo = repository()
    repo.client.begin_transaction.return_value = {"transactionId": "tx-1"}
    repo.client.execute_statement.side_effect = [{"formattedRecords": json.dumps(r)} for r in results]
    return repo

def test_reserve_server_inserts_within_limits():
    repo = transactional([{"locked": 1}], [], [{"mine": 0, "total": 2}], [{"id": SERVER_ID, "region": "us-east-1"}])
    assert repo.reserve_server(USER_ID, "us-east-1", "LATEST", 1, 3) == OwnedServer(SERVER_ID, None, "us-east-1")
    assert "pg_advisory_xact_lock" in sqls(repo)[0]
    assert sqls(repo)[-1].startswith("INSERT INTO servers")
    assert {c.kwargs["transactionId"] for c in repo.client.execute_statement.call_args_list} == {"tx-1"}
    repo.client.commit_transaction.assert_called_once()
    repo.client.rollback_transaction.assert_not_called()

def test_reserve_server_reuses_unlaunched_row():
    repo = transactional([{"locked": 1}], [{"id": SERVER_ID, "region": "us-east-1"}])
    assert repo.reserve_server(USER_ID, "us-east-1", "LATEST", 1, 3).id == SERVER_ID
    assert not any(sql.startswith("INSERT") for sql in sqls(repo))
    repo.client.commit_transaction.assert_called_once()

@pytest.mark.parametrize("mine,total", [(1, 1), (0, 3)])
def test_reserve_server_limits(mine, total):
    repo = transactional([{"locked": 1}], [], [{"mine": mine, "total": total}])
    with pytest.raises(ServerLimitReached):
        repo.reserve_server(USER_ID, "us-east-1", "LATEST", 1, 3)
    assert not any(sql.startswith("INSERT") for sql in sqls(repo))
    repo.client.rollback_transaction.assert_called_once()
    repo.client.commit_transaction.assert_not_called()

def test_reserve_server_resuming_database():
    repo = repository()
    repo.client.begin_transaction.side_effect = ClientError(
        {"Error": {"Code": "DatabaseResumingException"}}, "BeginTransaction")
    with pytest.raises(DatabaseUnavailable) as exc:
        repo.reserve_server(USER_ID, "us-east-1", "LATEST", 1, 3)
    assert exc.value.retry_after == 15

def test_attach_instance_only_fills_empty_rows():
    repo = repository()
    repo.attach_instance(SERVER_ID, "i-new", "t4g.small")
    kwargs = repo.client.execute_statement.call_args.kwargs
    assert "instance_id IS NULL" in kwargs["sql"]
    assert {p["name"] for p in kwargs["parameters"]} == {"server_id", "instance_id", "instance_type"}

def test_list_owned_servers():
    repo = repository([
        {"id": SERVER_ID, "region": "us-east-1", "version": "LATEST", "instance_type": "t4g.small", "has_instance": True},
        {"id": USER_ID, "region": "us-east-1", "version": "LATEST", "has_instance": False}])  # NULL type omitted
    assert repo.list_owned_servers("owner-sub") == [
        ServerRow(SERVER_ID, "us-east-1", "LATEST", "t4g.small", True),
        ServerRow(USER_ID, "us-east-1", "LATEST", None, False)]
    kwargs = repo.client.execute_statement.call_args.kwargs
    assert "owner-sub" not in kwargs["sql"]
    assert "instance_id AS" not in kwargs["sql"]
    assert kwargs["parameters"] == [{"name": "sub", "value": {"stringValue": "owner-sub"}}]
