# Qwen Code — DeepSeek API Integration

Qwen Code (github.com/QwenLM/qwen-code) supports DeepSeek API as a provider.

## Setup
- Base URL: `https://api.deepseek.com/v1`
- Models: `deepseek-v4-flash`, `deepseek-v3`, etc.
- Uses OpenAI-compatible chat completions format.

## Tool Calling
Qwen Code has built-in tool calling. DeepSeek API supports tool calls natively via Chat Completions API with `tools` and `tool_choice` parameters.

## Known Issues
- DeepSeek reasoning models return `reasoning_content` field. Qwen Code must pass this back in subsequent requests.
- Chat compression can strip `reasoning_content` causing 400 errors.
- Fixed for session resume, model switch, and idle cleanup paths. Compression path still has an open issue (#3579).

## Source
https://api-docs.deepseek.com/guides/tool_calls
https://github.com/QwenLM/qwen-code/issues/3579
