from fastapi import HTTPException


class ConversationNotFound(HTTPException):
    def __init__(self, conversation_id: str):
        super().__init__(status_code=404, detail=f"Conversation '{conversation_id}' not found")


class MemoryNodeNotFound(HTTPException):
    def __init__(self, memory_id: str):
        super().__init__(status_code=404, detail=f"Memory node '{memory_id}' not found")


class ConversationMismatch(HTTPException):
    def __init__(self):
        super().__init__(status_code=403, detail="memory_id does not belong to the given conversation_id")


class NodeAlreadyComplete(HTTPException):
    def __init__(self, memory_id: str):
        super().__init__(status_code=400, detail=f"Node '{memory_id}' already has a response attached")
