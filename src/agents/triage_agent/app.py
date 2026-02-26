import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, TypedDict

import boto3
import requests
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langgraph.graph import StateGraph, END

app = BedrockAgentCoreApp()

# ---------- ENV ----------
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
MEMORY_ID = os.getenv("AGENTCORE_MEMORY_ID", "support_agent-sQjnK2E3cg")
ACTOR_ID = os.getenv("AGENTCORE_ACTOR_ID", "demo-user")

COGNITO_TOKEN_URL = os.getenv("COGNITO_TOKEN_URL", "https://us-east-1rrhfeytej.auth.us-east-1.amazoncognito.com/oauth2/token")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "3rfjnrk0l09emo03m2rjj6ufdd")
COGNITO_CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET", "hp2jvc70gpmmrpegdadm7evpsentpd3aih09ak0klgbjrociffu")
GATEWAY_MCP_URL = os.getenv("GATEWAY_MCP_URL", "https://gateway-support-4smlq2cdez.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp")

MCP_TOOL_NAME = os.getenv("MCP_TOOL_NAME", "get_customer_context")
INTENT_MODEL = os.getenv("INTENT_MODEL", "bedrock/us.amazon.nova-pro-v1:0")

memory_client = boto3.client("bedrock-agentcore", region_name=AWS_REGION)


class LLM:
    def __init__(self, model: str):
        self.model = model
        self.model_id = model.split("/", 1)[1] if model.startswith("bedrock/") else model
        self.client = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    def invoke(self, prompt: str) -> str:
        response = self.client.converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0, "maxTokens": 256},
        )
        content = response.get("output", {}).get("message", {}).get("content", [])
        texts = [item.get("text", "") for item in content if isinstance(item, dict)]
        return "\n".join(t for t in texts if t).strip()


llm = LLM(model=INTENT_MODEL)


class AgentState(TypedDict, total=False):
    user_message: str
    session_id: str
    customer_id: str
    previous_conversation: list[dict[str, Any]]
    intent: str
    severity: str
    mcp_result: dict[str, Any]
    final_answer: str


def _safe_iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return v


def _get_memory_actor_id(payload: dict[str, Any]) -> str:
    return payload.get("actor_id") or ACTOR_ID


def _load_agentcore_memory(session_id: str, actor_id: str, max_results: int = 3) -> list[dict[str, Any]]:
    if not MEMORY_ID:
        return []

    try:
        res = memory_client.list_events(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
            maxResults=max_results,
        )
        raw_events = res.get("event", []) or res.get("events", [])
        return [{k: _safe_iso(v) for k, v in event.items()} for event in raw_events]
    except Exception as exc:
        return [{"memory_error": str(exc)}]


def _persist_agentcore_memory(session_id: str, actor_id: str, user_text: str, assistant_text: str) -> None:
    if not MEMORY_ID:
        return

    try:
        memory_client.create_event(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
            eventTimestamp=datetime.now(timezone.utc),
            payload=[
                {
                    "conversational": {
                        "role": "USER",
                        "content": {"text": user_text},
                    }
                },
                {
                    "conversational": {
                        "role": "ASSISTANT",
                        "content": {"text": assistant_text},
                    }
                },
            ],
            clientToken=str(uuid.uuid4()),
        )
    except Exception:
        pass


def _get_access_token() -> str:
    if not (COGNITO_TOKEN_URL and COGNITO_CLIENT_ID and COGNITO_CLIENT_SECRET):
        raise ValueError("Missing Cognito env vars")
    data = {
        "grant_type": "client_credentials",
        "client_id": COGNITO_CLIENT_ID,
        "client_secret": COGNITO_CLIENT_SECRET,
    }
    resp = requests.post(
        COGNITO_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _list_tools(access_token: str) -> list[dict[str, Any]]:
    payload = {
        "jsonrpc": "2.0",
        "id": "list-tools-request",
        "method": "tools/list",
    }
    resp = requests.post(
        GATEWAY_MCP_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"MCP tools/list error: {body['error']}")
    result = body.get("result", {})
    if isinstance(result, dict):
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []
    if isinstance(result, list):
        return result
    return []


def _resolve_mcp_tool_name(access_token: str) -> str:
    tools = _list_tools(access_token)
    names = [tool.get("name") for tool in tools if isinstance(tool, dict) and tool.get("name")]

    preferred_names = [
        MCP_TOOL_NAME,
        "target-support-tool___get_customer_context",
        "get_customer_context",
    ]
    for name in preferred_names:
        if name in names:
            return name

    for name in names:
        if name.endswith("___get_customer_context"):
            return name
    for name in names:
        if name.endswith("get_customer_context"):
            return name

    raise RuntimeError(f"No compatible customer-context tool found. Available tools: {names}")


def _call_mcp_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    access_token = _get_access_token()
    tool_name = _resolve_mcp_tool_name(access_token)
    payload = {
        "jsonrpc": "2.0",
        "id": f"call-{uuid.uuid4()}",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = requests.post(
        GATEWAY_MCP_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"MCP error: {body['error']}")
    return body.get("result", {})


def _parse_intent_json(raw_text: str) -> dict[str, str]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = cleaned.rstrip("`").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def classify_intent(state: AgentState) -> AgentState:
    msg = state["user_message"]
    prompt = f"""
You are classifying a support request.
Think step-by-step internally, then output JSON only.

Allowed intent values:
- refund_request
- invoice_issue
- payment_failure
- account_access
- general_support

Allowed severity values:
- low
- medium
- high

Rules:
- Return exactly one intent and one severity.
- Use high for account lockout/login blockers or payment failures with urgency.
- Use medium for refund or invoice/billing disputes.
- Use low for general/non-urgent support.

User message:
{msg}

Output format:
{{"intent":"<one_intent>","severity":"<one_severity>"}}
""".strip()

    valid_intents = {"refund_request", "invoice_issue", "payment_failure", "account_access", "general_support"}
    valid_severities = {"low", "medium", "high"}
    fallback = {"intent": "general_support", "severity": "low"}

    try:
        raw = llm.invoke(prompt)
        parsed = _parse_intent_json(raw)
        intent = parsed.get("intent")
        severity = parsed.get("severity")
        if intent in valid_intents and severity in valid_severities:
            return {"intent": intent, "severity": severity}
    except Exception:
        pass

    return fallback


def call_gateway_context(state: AgentState) -> AgentState:
    args = {
        "customer_id": state.get("customer_id", "UNKNOWN"),
    }

    try:
        result = _call_mcp_tool(args)
        return {"mcp_result": result}
    except Exception as exc:
        return {"mcp_result": {"gateway_error": str(exc), "arguments": args}}


def compose_answer(state: AgentState) -> AgentState:
    msg = state["user_message"]
    intent = state.get("intent", "unknown")
    severity = state.get("severity", "unknown")
    previous_conversation = state.get("previous_conversation", [])
    mcp_result = state.get("mcp_result", {})

    answer = (
        f"Intent: {intent}\n"
        f"Severity: {severity}\n\n"
        f"User issue: {msg}\n\n"
        f"Context from MCP:\n{json.dumps(mcp_result, indent=2)}\n\n"
        f"Recent memory events seen: {len(previous_conversation)}\n"
        f"Recommended next action: verify account/payment context and provide guided resolution."
    )
    return {"final_answer": answer}


graph = StateGraph(AgentState)
graph.add_node("classify", classify_intent)
graph.add_node("call_mcp", call_gateway_context)
graph.add_node("compose", compose_answer)
graph.set_entry_point("classify")
graph.add_edge("classify", "call_mcp")
graph.add_edge("call_mcp", "compose")
graph.add_edge("compose", END)

workflow = graph.compile()


@app.entrypoint
def agent_invocation(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    user_message = payload.get("message", "")
    customer_id = payload.get("customer_id", "C-1001")
    session_id = getattr(context, "sessionId", payload.get("session_id", "default_session"))
    actor_id = _get_memory_actor_id(payload)
    previous_conversation = _load_agentcore_memory(session_id=session_id, actor_id=actor_id)

    state_in: AgentState = {
        "user_message": user_message,
        "customer_id": customer_id,
        "session_id": session_id,
        "previous_conversation": previous_conversation,
    }
    state_out = workflow.invoke(state_in)
    final_answer = state_out.get("final_answer", "No response generated.")

    _persist_agentcore_memory(
        session_id=session_id,
        actor_id=actor_id,
        user_text=user_message,
        assistant_text=final_answer,
    )

    return {"result": final_answer}


if __name__ == "__main__":
    app.run(port=8080)
