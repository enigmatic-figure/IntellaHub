# IntellaHub Relay

IntellaHub Relay is an agent-first communication layer that unifies many capable language models behind a single, OpenAI-compatible interface. It is derived from the excellent [LiteLLM](https://github.com/BerriAI/litellm) project but tuned for multi-agent orchestration rather than general-purpose proxying.

## Why this fork exists

- **Agent-focused topology:** Designed to sit between coordinators, planners, and tools, providing a consistent messaging contract across heterogeneous model backends.
- **Identity and authorization:** Favors OAuth-centric authentication (e.g., Gemini OAuth, Qwen OAuth, GitHub Copilot) so agents inherit the identities and scopes users already manage through official CLIs.
- **Operational guardrails:** Keeps the battle-tested proxy/gateway features from LiteLLM—budgeting, rate limits, routing, logging—so orchestrations stay observable and controlled.
- **Extensible surface:** New provider adapters and routing logic are added with agent workflows in mind, while remaining compatible with the OpenAI SDK format.

## Quick start

> The runtime is still provided by the underlying LiteLLM engine. Install dependencies the same way while we stabilize the forked packaging.

```bash
pip install -e .
```

Start the relay gateway with any OpenAI-compatible model identifier (including the new OAuth-enabled providers):

```bash
litellm --model gemini_oauth/gemini-1.5-pro
# Proxy listens on http://0.0.0.0:4000 by default
```

Then point your agent framework or the OpenAI SDK at the relay:

```python
import openai
client = openai.OpenAI(api_key="any-non-empty-string", base_url="http://0.0.0.0:4000")

response = client.chat.completions.create(
    model="qwen_oauth/qwen-max",
    messages=[{"role": "user", "content": "Summarize the latest task state."}],
)
print(response.choices[0].message.content)
```

## OAuth-aware providers

This fork prioritizes providers that ship OAuth-capable CLIs so agents can reuse existing login flows:

- **Gemini OAuth** – reads and refreshes the OAuth cache produced by the Gemini CLI, targeting the OpenAI-compatible endpoint at `https://generativelanguage.googleapis.com/v1beta/openai`.
- **Qwen OAuth** – loads device-flow tokens from the Qwen CLI cache and routes calls to the DashScope OpenAI-compatible endpoint at `https://dashscope.aliyuncs.com/compatible-mode/v1`.
- **GitHub Copilot** – retains the upstream OAuth integration for consistency across coding agents.

Each provider can be selected with `model="<provider>/<model_name>"`; no manual API keys are required once the respective CLI login has been completed.

## Routing and governance

- **OpenAI-format everywhere:** Agents speak one request/response shape while the relay adapts to provider-specific quirks.
- **Budgets, limits, and auditability:** Built-in middleware for spend tracking, rate limiting, and structured logging keeps orchestrations safe to operate.
- **Fallbacks and load-balancing:** Reuse the routing strategies from LiteLLM to distribute load or fail over between deployments.

## Contributing

Contributions are welcome—especially adapters, policies, and observability hooks that make agent orchestration smoother. Please open issues or pull requests describing the agent workflow you’re enabling.

## Acknowledgements

This project builds on the foundation laid by the LiteLLM team. Their open-source work makes it possible for this relay to stay compatible with a wide ecosystem of models while serving the needs of agentic systems.
