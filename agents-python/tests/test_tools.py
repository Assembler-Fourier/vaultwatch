from app.llm.tools import execute_research_tool
from app.synthetic import check_sanctions_list, generate_entity_graph, generate_transaction_history


def test_generate_transaction_history_is_deterministic_per_account() -> None:
    a = generate_transaction_history("acct_deterministic", n=5)
    b = generate_transaction_history("acct_deterministic", n=5)
    assert a == b


def test_generate_transaction_history_differs_across_accounts() -> None:
    a = generate_transaction_history("acct_one", n=5)
    b = generate_transaction_history("acct_two", n=5)
    assert a != b


def test_check_sanctions_list_hits_known_synthetic_entry() -> None:
    result = check_sanctions_list("Victor Krantz Holdings")
    assert result["hit"] is True


def test_check_sanctions_list_misses_unknown_name() -> None:
    result = check_sanctions_list("Perfectly Normal Bakery Ltd")
    assert result["hit"] is False


def test_execute_research_tool_dispatches_by_name() -> None:
    history_result = execute_research_tool("get_transaction_history", {"account_id": "acct_1"})
    assert "history" in history_result

    graph_result = execute_research_tool("get_entity_graph", {"account_id": "acct_1"})
    assert graph_result == generate_entity_graph("acct_1")

    sanctions_result = execute_research_tool("check_sanctions_list", {"name": "Ashgrove Trading FZCO"})
    assert sanctions_result["hit"] is True


def test_execute_research_tool_rejects_unknown_tool() -> None:
    try:
        execute_research_tool("delete_all_records", {})
        assert False, "expected ValueError"
    except ValueError:
        pass
