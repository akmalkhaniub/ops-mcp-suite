# 🤝 Contributing to Ops MCP Suite

We welcome contributions to expand the **Ops MCP Suite**!

## 🛠️ Development Setup
```bash
git clone https://github.com/akmalkhaniub/ops-mcp-suite.git
cd ops-mcp-suite
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
```

## 🧪 Testing Guidelines
Always ensure offline mock unit tests pass before submitting a PR:
```bash
python -m pytest tests/ -v
```

## ➕ Adding a New Micro-MCP Server
1. Create `<domain>_mcp.py` using `FastMCP`.
2. Define Pydantic input/output schemas for each tool.
3. Register the new server in `MCP_SERVERS` dictionary in `gateway.py`.
4. Add corresponding unit tests in `tests/test_<domain>_mcp.py`.
