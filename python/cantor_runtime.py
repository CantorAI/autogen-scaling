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
    def __init__(self, module, qualname, is_async, args=None, kwargs=None, 
                 globals_snapshot=None, code_object=None, module_state=None, locals_snapshot=None):
        self.module = module
        self.qualname = qualname
        self.is_async = is_async
        self.args = args or []
        self.kwargs = kwargs or {}
        self.globals_snapshot = globals_snapshot or {}  # Store relevant globals
        self.code_object = code_object  # Store the actual code object
        self.module_state = module_state or {}  # Complete module state
        self.locals_snapshot = locals_snapshot or {}  # Local variables state

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
    def __init__(self, *args, capture_main_caller: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_spec: Optional[TaskSpec] = None
        if capture_main_caller:
            self.task_spec = self._capture_main_caller()

    # ---- your original message hooks (kept verbatim, with tiny robustness) ----
    async def _process_send(self, message_envelope):
        print(f"[CantorRuntime] _process_send → {message_envelope.recipient}: {message_envelope.message}")
        payload: Dict[str, Any] = {
            "kind": "ensure_and_send",
            "task_spec": self.task_spec,
            "message_envelope": message_envelope,  # xlang can serialize this object
        }
        xlang_payload = xlang.Dump(payload)             # -> X::Bin or bytes (opaque)
        #Test
        Obj = xlang.Load(xlang_payload)
        out_envelope = xlang_bridge.RunTask(xlang_payload)  
        return await super()._process_send(message_envelope)

    async def _process_publish(self, message_envelope):
        print(f"[CantorRuntime] _process_publish topic={message_envelope.topic_id}: {message_envelope.message}")
        return await super()._process_publish(message_envelope)

    async def _process_response(self, message_envelope):
        print(f"[CantorRuntime] _process_response from {message_envelope.sender} to {message_envelope.recipient}: {message_envelope.message}")
        return await super()._process_response(message_envelope)

    # -----------------------------------------------------------------------------
    # Main caller capture: capture the caller of __init__ (where runtime was instantiated)
    # -----------------------------------------------------------------------------
    # -----------------------------------------------------------------------------
    # Caller capture: capture the caller of __init__ (where runtime was instantiated)
    # -----------------------------------------------------------------------------
    def _capture_main_caller(self) -> TaskSpec:
        """
        Capture the caller of __init__ - this is where CantorScalingRuntime() was instantiated.
        Could be any function that called the constructor.
        """
        frame = inspect.currentframe()
        assert frame is not None
        
        # Go back to find __init__'s caller
        caller_frame = frame.f_back  # _capture_main_caller -> __init__
        while caller_frame and caller_frame.f_code.co_name == "__init__":
            caller_frame = caller_frame.f_back
        
        if caller_frame is None:
            raise RuntimeError("Could not find caller of CantorScalingRuntime constructor")
        
        return self._capture_frame(caller_frame)

    def _capture_frame(self, frame) -> TaskSpec:
        """
        Capture entrypoint information from a specific frame.
        """
        code = frame.f_code
        module = frame.f_globals.get("__name__", "")
        qualname = getattr(code, "co_qualname", code.co_name)
        
        # For module-level execution (like if __name__ == "__main__":), 
        # we want to capture the entire module context
        if qualname == "<module>":
            return self._capture_module_context(frame)

        # resolve callable (top-level is required for remote import)
        fn = None
        is_async = False
        try:
            fn = _resolve_callable(module, qualname)
            is_async = inspect.iscoroutinefunction(fn)
        except Exception:
            pass  # still capture args; we'll attempt best-effort on worker

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

        # Capture EVERYTHING - globals, locals, module state
        globals_snapshot = self._capture_complete_globals(frame.f_globals)
        locals_snapshot = self._capture_locals(frame.f_locals)
        module_state = self._capture_module_state(module, frame.f_globals)
        
        # Serialize the code object
        serialized_code = self._serialize_code_object(code)

        # (Optional) warn if defined inside a local scope (hard to import remotely)
        if "<locals>" in qualname:
            print(f"[CantorRuntime] Warning: entrypoint {module}:{qualname} is not top-level; "
                  f"remote import may fail. Consider promoting it to module scope.")

        return TaskSpec(module=module, qualname=qualname, is_async=is_async,
                        args=args_list, kwargs=kwargs_dict, 
                        globals_snapshot=globals_snapshot,
                        code_object=serialized_code,
                        module_state=module_state,
                        locals_snapshot=locals_snapshot)

    def _capture_module_context(self, frame) -> TaskSpec:
        """
        Capture the entire module context when executing at module level
        (e.g., in if __name__ == "__main__": block).
        """
        module = frame.f_globals.get("__name__", "")
        globals_snapshot = self._filter_globals(frame.f_globals)
        
        # Look for main() function in the module globals
        main_func = frame.f_globals.get("main")
        main_args = []
        main_kwargs = {}
        
        if main_func and callable(main_func):
            # Try to extract arguments that would be passed to main()
            # Look for common patterns like model_config in locals
            locals_vars = frame.f_locals
            if "model_config" in locals_vars:
                main_args = [locals_vars["model_config"]]
        
        # Capture EVERYTHING from the module
        globals_snapshot = self._capture_complete_globals(frame.f_globals)
        module_state = self._capture_module_state(module, frame.f_globals)
        
        # Serialize the module's code if we have main_func
        serialized_code = None
        if main_func:
            serialized_code = self._serialize_code_object(main_func.__code__)
        
        return TaskSpec(
            module=module,
            qualname="main",  # Assume we want to run main() on the remote side
            is_async=inspect.iscoroutinefunction(main_func) if main_func else True,
            args=main_args,
            kwargs=main_kwargs,
            globals_snapshot=globals_snapshot,
            code_object=serialized_code,
            module_state=module_state,
            locals_snapshot={}  # Module level doesn't have locals
        )

    def _capture_complete_globals(self, globals_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Capture ALL globals including functions, classes, variables - everything except imports.
        """
        captured = {}
        for key, value in globals_dict.items():
            # Skip built-in names
            if key.startswith("__") and key.endswith("__"):
                continue
            
            # Skip imports - let the remote side handle these with import statements
            if inspect.ismodule(value):
                continue
            
            # Capture everything else: functions, classes, variables, data
            captured[key] = value
        
        return captured

    def _capture_locals(self, locals_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Capture all local variables and their current state.
        """
        return dict(locals_dict)  # Just copy everything

    def _capture_module_state(self, module_name: str, globals_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Capture the complete module state including all module-level definitions.
        """
        try:
            module_obj = importlib.import_module(module_name)
            module_state = {}
            
            for attr_name in dir(module_obj):
                if attr_name.startswith("_"):
                    continue
                
                attr_value = getattr(module_obj, attr_name)
                
                # Skip imports
                if inspect.ismodule(attr_value):
                    continue
                
                # Capture everything else
                module_state[attr_name] = attr_value
            
            return module_state
        except Exception as e:
            print(f"[CantorRuntime] Warning: Could not capture module state for {module_name}: {e}")
            return {}

    def _serialize_code_object(self, code_obj) -> Dict[str, Any]:
        """
        Serialize a code object into a dictionary that can be reconstructed.
        """
        return {
            'co_argcount': code_obj.co_argcount,
            'co_posonlyargcount': getattr(code_obj, 'co_posonlyargcount', 0),  # Python 3.8+
            'co_kwonlyargcount': code_obj.co_kwonlyargcount,
            'co_nlocals': code_obj.co_nlocals,
            'co_stacksize': code_obj.co_stacksize,
            'co_flags': code_obj.co_flags,
            'co_code': code_obj.co_code,
            'co_consts': code_obj.co_consts,
            'co_names': code_obj.co_names,
            'co_varnames': code_obj.co_varnames,
            'co_filename': code_obj.co_filename,
            'co_name': code_obj.co_name,
            'co_firstlineno': code_obj.co_firstlineno,
            'co_lnotab': getattr(code_obj, 'co_lnotab', b''),  # Older Python versions
            'co_linetable': getattr(code_obj, 'co_linetable', None),  # Python 3.10+
            'co_freevars': code_obj.co_freevars,
            'co_cellvars': code_obj.co_cellvars,
        }

    def _deserialize_code_object(self, code_dict: Dict[str, Any]):
        """
        Reconstruct a code object from serialized dictionary.
        """
        import types
        
        # Handle Python version differences
        args = [
            code_dict['co_argcount'],
            code_dict.get('co_posonlyargcount', 0),
            code_dict['co_kwonlyargcount'],
            code_dict['co_nlocals'],
            code_dict['co_stacksize'],
            code_dict['co_flags'],
            code_dict['co_code'],
            code_dict['co_consts'],
            code_dict['co_names'],
            code_dict['co_varnames'],
            code_dict['co_filename'],
            code_dict['co_name'],
            code_dict['co_firstlineno'],
        ]
        
        # Add version-specific arguments
        if 'co_linetable' in code_dict and code_dict['co_linetable'] is not None:
            args.append(code_dict['co_linetable'])  # Python 3.10+
        else:
            args.append(code_dict.get('co_lnotab', b''))  # Older versions
        
        args.extend([
            code_dict['co_freevars'],
            code_dict['co_cellvars'],
        ])
        
        # Remove None arguments for compatibility
        while args and args[-1] is None:
            args.pop()
            
        return types.CodeType(*args)



    # -----------------------------------------------------------------------------
    # Serialize/ship entrypoint using xlang.Dump / xlang.Load
    # -----------------------------------------------------------------------------
    def serialize_task(self):
        """
        Produce an opaque payload using xlang.Dump(asdict(TaskSpec)).
        Depending on your bindings, this may be an X::Bin or bytes—treat it as opaque.
        """
        if not self.task_spec:
            raise RuntimeError("No captured caller context to serialize. "
                               "Instantiate with capture_main_caller=True.")
        return xlang.Dump(self.task_spec.__dict__)

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
        Now reconstructs the COMPLETE execution environment including all module state.
        """
        spec_dict = xlang.Load(payload)               # -> dict
        spec = TaskSpec(**spec_dict)
        
        # Create a complete execution environment - just use everything as-is
        # since xlang.Dump/Load handles all serialization/deserialization
        execution_globals = {}
        
        # Step 1: Restore all captured globals
        if spec.globals_snapshot:
            execution_globals.update(spec.globals_snapshot)
        
        # Step 2: Restore module state 
        if spec.module_state:
            execution_globals.update(spec.module_state)
        
        # Step 3: Add locals to globals for function execution
        if spec.locals_snapshot:
            execution_globals.update(spec.locals_snapshot)
        
        # Step 4: Reconstruct the target function
        if spec.code_object:
            runtime = CantorScalingRuntime()
            code_obj = runtime._deserialize_code_object(spec.code_object)
            
            # Create function from code object with complete environment
            import types
            fn = types.FunctionType(
                code_obj,
                execution_globals,  # Complete environment
                spec.qualname,
                closure=None
            )
        else:
            # Fallback to importing existing function and injecting captured state
            try:
                target_module = importlib.import_module(spec.module)
                # Inject all captured state into the target module
                for key, value in execution_globals.items():
                    setattr(target_module, key, value)
                fn = _resolve_callable(spec.module, spec.qualname)
            except Exception as e:
                print(f"[CantorRuntime] Warning: Could not import {spec.module}.{spec.qualname}: {e}")
                # Create a dummy module and inject everything
                import types
                dummy_module = types.ModuleType(spec.module)
                for key, value in execution_globals.items():
                    setattr(dummy_module, key, value)
                fn = getattr(dummy_module, spec.qualname)

        # Step 5: Execute with complete environment
        if inspect.iscoroutinefunction(fn) or spec.is_async:
            return await fn(*spec.args, **spec.kwargs)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*spec.args, **spec.kwargs))




if __name__ == "__main__":
    runtime = CantorScalingRuntime()
    print("CantorScalingRuntime Test")