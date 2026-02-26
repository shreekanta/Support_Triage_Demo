import requests
import json

CLIENT_ID = "3rfjnrk0l09emo03m2rjj6ufdd"
CLIENT_SECRET = "hp2jvc70gpmmrpegdadm7evpsentpd3aih09ak0klgbjrociffu"
TOKEN_URL = "https://us-east-1rrhfeytej.auth.us-east-1.amazoncognito.com/oauth2/token"

def fetch_access_token(client_id, client_secret, token_url):
  response = requests.post(
    token_url,
    data="grant_type=client_credentials&client_id={client_id}&client_secret={client_secret}".format(client_id=client_id, client_secret=client_secret),
    headers={'Content-Type': 'application/x-www-form-urlencoded'}
  )

  return response.json()['access_token']

def list_tools(gateway_url, access_token):
  headers = {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {access_token}"
  }

  payload = {
      "jsonrpc": "2.0",
      "id": "list-tools-request",
      "method": "tools/list"
  }

  response = requests.post(gateway_url, headers=headers, json=payload)
  return response.json()


def call_tool(gateway_url, access_token, tool_name, arguments):
    headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {access_token}",
    }

    payload = {
        "jsonrpc": "2.0",
        "id": "call-tool-request",
        "method": "tools/call",
        "params": {
                        "name": tool_name,
                        "arguments": arguments,
        }
    }

    response_tool = requests.post(gateway_url, headers=headers, json=payload)
    print("Customer Details:", response_tool.json())
    return response_tool.json()



# Example usage
gateway_url = "https://gateway-support-4smlq2cdez.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
access_token = fetch_access_token(CLIENT_ID, CLIENT_SECRET, TOKEN_URL)
tools = list_tools(gateway_url, access_token)
print(json.dumps(tools, indent=2))

tool_response = call_tool(gateway_url, access_token, "target-support-tool___get_customer_context", {"customer_id": "C1001"})
print(tool_response)