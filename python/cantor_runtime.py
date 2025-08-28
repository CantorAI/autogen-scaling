from __future__ import annotations
import os
import xlang
import inspect, importlib, asyncio
from typing import Any, Dict, List, Optional


parent_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(parent_dir)
xlang_path = os.path.join(project_root, "xlang\\scaling-bridge.x")

xlang_bridge = xlang.importModule("scaling-bridge",fromPath =xlang_path)
xlang_bridge.Test("After Import scaling-bridge")
cantor = xlang.importModule("cantor", thru="lrpc:1000")

from autogen_core import (
    SingleThreadedAgentRuntime,
)

# -----------------------------------------------------------------------------
# TaskSpec + resolver (we ship metadata, not a live function object)
# -----------------------------------------------------------------------------
class TaskSpec:
    def __init__(self, module, qualname, is_async, args=None, kwargs=None):
        self.module = module
        self.qualname = qualname
        self.is_async = is_async
        self.args = args or []
        self.kwargs = kwargs or {}

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        self.__dict__.update(state)


def _resolve_callable(module: str, qualname: str):
    mod = importlib.import_module(module)
    obj = mod
    for part in qualname.split('.'):
        obj = getattr(obj, part)
    return obj

# -----------------------------------------------------------------------------
# Your runtime, with your original overrides + entrypoint capture/ship
# -----------------------------------------------------------------------------
class CantorScalingRuntime(SingleThreadedAgentRuntime):
    def __init__(self, *args, capture_entrypoint: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_spec: Optional[TaskSpec] = None
        if capture_entrypoint:
            self.task_spec = self._capture_entrypoint()

    # ---- your original message hooks (kept verbatim, with tiny robustness) ----
    async def _process_send(self, message_envelope):
        print(f"[CantorRuntime] _process_send → {message_envelope.recipient}: {message_envelope.message}")
        payload: Dict[str, Any] = {
            "kind": "ensure_and_send",
            "task_spec": self.task_spec,
            "message_envelope": message_envelope,  # xlang can serialize this object
        }
        try:
            xlang_payload = xlang.Dump(payload)             # -> X::Bin or bytes (opaque)
            out_envelope = xlang_bridge.RunTask(xlang_payload)       # remote/bridge processing
            if out_envelope is not None:
                py_msg = xlang.Load(out_envelope)                     # back to Python object
                # If the bridge returned a transformed envelope, forward that; else, fall back
                if py_msg is not None:
                    message_envelope = py_msg
        except Exception as e:
            # Don’t break the pipeline if bridge is unavailable; log and continue locally.
            print("[CantorRuntime] bridge error in _process_send:", e)
        return await super()._process_send(message_envelope)

    async def _process_publish(self, message_envelope):
        print(f"[CantorRuntime] _process_publish topic={message_envelope.topic_id}: {message_envelope.message}")
        return await super()._process_publish(message_envelope)

    async def _process_response(self, message_envelope):
        print(f"[CantorRuntime] _process_response from {message_envelope.sender} to {message_envelope.recipient}: {message_envelope.message}")
        return await super()._process_response(message_envelope)

    # -----------------------------------------------------------------------------
    # Entrypoint capture: grab caller (e.g., async def main(model_config))
    # -----------------------------------------------------------------------------
    def _capture_entrypoint(self, depth: int = 1) -> TaskSpec:
        # one frame up from __init__: where CantorScalingRuntime(...) was invoked
        frame = inspect.currentframe()
        assert frame is not None
        for _ in range(depth):
            frame = frame.f_back
        code = frame.f_code
        module = frame.f_globals.get("__name__", "")
        qualname = getattr(code, "co_qualname", code.co_name)

        # resolve callable (top-level is required for remote import)
        fn = None
        is_async = False
        try:
            fn = _resolve_callable(module, qualname)
            is_async = inspect.iscoroutinefunction(fn)
        except Exception:
            pass  # still capture args; we’ll attempt best-effort on worker

        # capture bound args from the caller's locals
        argvals = inspect.getargvalues(frame)
        bound = {name: argvals.locals[name] for name in argvals.args}
        if argvals.varargs:
            bound[argvals.varargs] = argvals.locals.get(argvals.varargs)
        if argvals.keywords:
            bound.update(argvals.locals.get(argvals.keywords, {}))

        # split into args/kwargs following signature order if we resolved fn
        args_list: List[Any] = []
        kwargs_dict: Dict[str, Any] = {}
        if fn is not None:
            sig = inspect.signature(fn)
            for p in sig.parameters.values():
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name in bound:
                    args_list.append(bound.pop(p.name))
            kwargs_dict = bound
        else:
            kwargs_dict = bound

        # (Optional) warn if defined inside a local scope (hard to import remotely)
        if "<locals>" in qualname:
            print(f"[CantorRuntime] Warning: entrypoint {module}:{qualname} is not top-level; "
                  f"remote import may fail. Consider promoting it to module scope.")

        return TaskSpec(module=module, qualname=qualname, is_async=is_async,
                        args=args_list, kwargs=kwargs_dict)

    # -----------------------------------------------------------------------------
    # Serialize/ship entrypoint using xlang.Dump / xlang.Load
    # -----------------------------------------------------------------------------
    def serialize_task(self):
        """
        Produce an opaque payload using xlang.Dump(asdict(TaskSpec)).
        Depending on your bindings, this may be an X::Bin or bytes—treat it as opaque.
        """
        if not self.task_spec:
            raise RuntimeError("No captured entrypoint to serialize. "
                               "Instantiate with capture_entrypoint=True.")
        return xlang.Dump(asdict(self.task_spec))

    async def distribute_self(self):
        """
        Example: push the serialized TaskSpec to another node using your Cantor transport.
        Implement _send_to_node() for your environment.
        """
        payload = self.serialize_task()
        await self._send_to_node("python_task", payload)

    async def _send_to_node(self, topic: str, payload):
        """
        Wire this into your DataFrame bus. If your bus wants X::Bin, you can pass payload as is.
        If your bus wants bytes and Dump returns Bin, add a tiny adapter on the sender side.
        """
        raise NotImplementedError

    # -----------------------------------------------------------------------------
    # Worker-side handler: decode with xlang.Load and run the entrypoint
    # -----------------------------------------------------------------------------
    @staticmethod
    async def run_remote(payload):
        """
        `payload` must be the exact object produced by serialize_task() (i.e., xlang.Dump of TaskSpec).
        """
        spec_dict = xlang.Load(payload)               # -> dict
        spec = TaskSpec(**spec_dict)
        fn = _resolve_callable(spec.module, spec.qualname)

        if inspect.iscoroutinefunction(fn) or spec.is_async:
            return await fn(*spec.args, **spec.kwargs)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*spec.args, **spec.kwargs))




if __name__ == "__main__":
    runtime = CantorScalingRuntime()
    print("CantorScalingRuntime Test")
