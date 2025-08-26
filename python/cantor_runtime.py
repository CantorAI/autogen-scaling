import xlang
cantor = xlang.importModule("cantor", thru="lrpc:1000")

from autogen_core import (
    SingleThreadedAgentRuntime,
)

class CantorScalingRuntime(SingleThreadedAgentRuntime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def _process_send(self, message_envelope):
        print(f"[CantorRuntime] _process_send → {message_envelope.recipient}: {message_envelope.message}")
        return await super()._process_send(message_envelope)

    async def _process_publish(self, message_envelope):
        print(f"[CantorRuntime] _process_publish topic={message_envelope.topic_id}: {message_envelope.message}")
        return await super()._process_publish(message_envelope)

    async def _process_response(self, message_envelope):
        print(f"[CantorRuntime] _process_response from {message_envelope.sender} to {message_envelope.recipient}: {message_envelope.message}")
        return await super()._process_response(message_envelope)

if __name__ == "__main__":
    runtime = CantorScalingRuntime()
    print("CantorScalingRuntime Test")
