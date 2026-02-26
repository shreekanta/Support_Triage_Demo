import json
import re
import uuid
from typing import Any

import boto3
import streamlit as st


def default_session_id() -> str:
    # Agent Runtime requires at least 33 chars.
    return f"session-{uuid.uuid4()}-{uuid.uuid4().hex[:8]}"


def invoke_agent_runtime(
    region_name: str,
    agent_runtime_arn: str,
    runtime_session_id: str,
    payload_dict: dict[str, Any],
    qualifier: str | None = None,
) -> dict[str, Any]:
    client = boto3.client("bedrock-agentcore", region_name=region_name)
    payload = json.dumps(payload_dict)

    params: dict[str, Any] = {
        "agentRuntimeArn": agent_runtime_arn,
        "runtimeSessionId": runtime_session_id,
        "payload": payload,
    }
    if qualifier:
        params["qualifier"] = qualifier

    response = client.invoke_agent_runtime(**params)
    response_body = response["response"].read()
    return json.loads(response_body)


def _safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return value


def parse_result_block(result_text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {"raw_result_text": result_text}

    intent_match = re.search(r"Intent:\s*(.+)", result_text)
    severity_match = re.search(r"Severity:\s*(.+)", result_text)
    issue_match = re.search(r"User issue:\s*(.+?)\n\nContext from MCP:", result_text, re.DOTALL)
    context_match = re.search(
        r"Context from MCP:\n(.+?)\n\nRecent memory events seen:",
        result_text,
        re.DOTALL,
    )

    parsed["intent"] = intent_match.group(1).strip() if intent_match else None
    parsed["severity"] = severity_match.group(1).strip() if severity_match else None
    parsed["user_issue"] = issue_match.group(1).strip() if issue_match else None

    context_raw = context_match.group(1).strip() if context_match else None
    parsed["context_raw"] = context_raw
    parsed["context_json"] = _safe_json_loads(context_raw) if context_raw else None

    return parsed


def extract_mcp_payload(context_json: Any) -> Any:
    # Extract nested Lambda body from MCP response payload when present.
    if not isinstance(context_json, dict):
        return None
    content = context_json.get("content")
    if not isinstance(content, list) or not content:
        return None
    first = content[0] if isinstance(content[0], dict) else None
    if not first:
        return None

    text_blob = first.get("text")
    if not isinstance(text_blob, str):
        return None

    outer = _safe_json_loads(text_blob)
    if not isinstance(outer, dict):
        return outer

    body = outer.get("body")
    if isinstance(body, str):
        return _safe_json_loads(body)
    return outer


st.set_page_config(page_title="Support Triage UI", layout="wide")
st.title("Support Triage Agent Sandbox UI")

with st.form("agent_form"):
    col1, col2 = st.columns(2)
    with col1:
        region = st.text_input("AWS Region", value="us-east-1")
        agent_runtime_arn = st.text_input(
            "Agent Runtime ARN",
            value="arn:aws:bedrock-agentcore:us-east-1:214121351640:runtime/support_agent-HqGVgH3kUZ",
        )
        qualifier = st.text_input("Qualifier (optional)", value="support_triage_tools_ep")
    with col2:
        runtime_session_id = st.text_input("Runtime Session ID (min 33 chars)", value=default_session_id())
        customer_id = st.text_input("Customer ID", value="C1005")
        actor_id = st.text_input("Actor ID", value="demo-user")

    message = st.text_area("Message", value="My payment failed and I was charged twice.", height=100)
    submitted = st.form_submit_button("Invoke Agent Runtime")

if submitted:
    if len(runtime_session_id) < 33:
        st.error("Runtime Session ID must be at least 33 characters.")
    else:
        payload = {
            "message": message,
            "customer_id": customer_id,
            "session_id": runtime_session_id,
            "actor_id": actor_id,
        }

        try:
            response_data = invoke_agent_runtime(
                region_name=region,
                agent_runtime_arn=agent_runtime_arn,
                runtime_session_id=runtime_session_id,
                payload_dict=payload,
                qualifier=qualifier.strip() or None,
            )
        except Exception as exc:
            st.error(f"Invocation failed: {exc}")
        else:
            st.success("Invocation succeeded")
            result_text = response_data.get("result", "")
            parsed = parse_result_block(result_text) if isinstance(result_text, str) else {}

            metric1, metric2 = st.columns(2)
            metric1.metric("Intent", parsed.get("intent") or "N/A")
            metric2.metric("Severity", parsed.get("severity") or "N/A")

            st.subheader("User Issue")
            st.write(parsed.get("user_issue") or "N/A")

            st.subheader("MCP Context")
            context_json = parsed.get("context_json")
            if context_json is not None:
                st.json(context_json)
                extracted = extract_mcp_payload(context_json)
                if extracted is not None:
                    st.subheader("Extracted Customer Context")
                    st.json(extracted)
            else:
                st.write("No parseable MCP context found.")

            with st.expander("Raw Agent Response"):
                st.json(response_data)
