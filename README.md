
# Autogen Scaling with CantorAI

**autogen-scaling** makes your existing [Microsoft AutoGen](https://microsoft.github.io/autogen) applications scale transparently across a [CantorAI](https://github.com/CantorAI) distributed cluster — **no code changes required**.

---

## ✨ Features

1. **Zero Code Change**  
   Run your AutoGen apps as-is. Simply switch to the CantorAI runtime and your agents automatically scale to thousands of sessions.

2. **Massive Distributed Scaling**  
   CantorAI handles agent distribution across processes and cluster nodes, using its DataFrame bus and scheduler.

3. **Multi-Session Support**  
   Seamlessly run and manage large numbers of concurrent conversations and workflows.

4. **Cluster Aware**  
   Agents can be scheduled on any node in a CantorAI cluster. Failover and resource balancing are automatic.

5. **Unified Observability**  
   Monitor all your AutoGen sessions from the CantorAI dashboard with built-in metrics (CPU, GPU, memory, custom app stats).

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- [AutoGen](https://pypi.org/project/autogen/)
- Cantor core runtime (download from [releases](https://github.com/CantorAI/cantor-core/releases))

### Install
```bash
pip install cantorai-autogen
````

### Run your AutoGen app — unchanged

```python
# your existing AutoGen app
from autogen import AssistantAgent, UserProxyAgent

# just swap in CantorRuntime (no other changes)
from cantor_runtime import CantorRuntime
runtime = CantorRuntime()

assistant = AssistantAgent("assistant", runtime=runtime)
user = UserProxyAgent("user", runtime=runtime)

user.initiate_chat(assistant, message="Scale me out!")
```

That’s it — CantorAI will distribute sessions across the cluster.

---

## 📂 Examples

This repo includes end-to-end examples:

* **01\_local\_single\_agent** – Run on your laptop
* **02\_cluster\_scaling** – Run across a Cantor cluster
* **03\_massive\_sessions** – Simulate thousands of concurrent chats

Each example works with the same AutoGen code — only the runtime changes.

---

## 🛠 Development

Clone and install in editable mode:

```bash
git clone https://github.com/CantorAI/autogen-scaling.git
cd autogen-scaling
pip install -e .[dev]
```

Run tests:

```bash
pytest -q
```

---

## 📜 License

Code in this repo is licensed under [Apache License 2.0](LICENSE).
The Cantor core binaries are subject to the CantorAI EULA.

---

## 🤝 Contributing

We welcome PRs for:

* new examples
* bug fixes
* docs improvements

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 🌐 Links

* [CantorAI Org](https://github.com/CantorAI)
* [AutoGen Docs](https://microsoft.github.io/autogen/)
* [CantorAI Core Releases](https://github.com/CantorAI/cantor-core/releases)


