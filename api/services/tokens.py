import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def count_node_tokens(prompt: str, response: str | None) -> int:
    text = (prompt or "") + " " + (response or "")
    return len(_enc.encode(text.strip()))
