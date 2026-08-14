# tests/test_deepseek_compat.py
"""Verify DeepSeek API compatibility with OpenAI format + function calling.

需要真实 DeepSeek API（消耗额度 + 网络）。默认被 pytest 跳过（-m integration_api
才跑），避免无 key/断网时全量测试挂掉。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import json
import pytest
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

pytestmark = pytest.mark.integration_api


def test_basic_chat():
    """Test 1: Basic chat completion works."""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": "你好，请用一句话介绍自己"}],
        max_tokens=100,
    )
    content = response.choices[0].message.content
    assert content is not None and len(content) > 0, "Empty response"
    print(f"✅ Basic chat OK: {content[:80]}...")


def test_function_calling():
    """Test 2: Function calling (tools parameter) works."""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"}
                    },
                    "required": ["city"],
                },
            },
        }
    ]

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": "北京今天天气怎么样？"}],
        tools=tools,
        tool_choice="auto",
        max_tokens=200,
    )

    msg = response.choices[0].message
    assert msg.tool_calls is not None and len(msg.tool_calls) > 0, (
        f"No tool_calls returned. Content: {msg.content}"
    )
    tool_call = msg.tool_calls[0]
    assert tool_call.function.name == "get_weather", (
        f"Wrong function called: {tool_call.function.name}"
    )
    args = json.loads(tool_call.function.arguments)
    assert "city" in args, f"No 'city' in args: {args}"
    print(f"✅ Function calling OK: called '{tool_call.function.name}' with {args}")


def test_langchain_chatopenai():
    """Test 3: LangChain ChatOpenAI works with DeepSeek base_url."""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=DEEPSEEK_MODEL,
        openai_api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0.3,
    )
    response = llm.invoke("回复：测试成功")
    assert response.content is not None and len(response.content) > 0
    print(f"✅ LangChain ChatOpenAI OK: {response.content[:80]}...")


if __name__ == "__main__":
    print("=" * 50)
    print("DeepSeek API Compatibility Verification")
    print("=" * 50)
    test_basic_chat()
    test_function_calling()
    test_langchain_chatopenai()
    print("=" * 50)
    print("🎉 All tests passed! DeepSeek is fully compatible.")
