import json
import re


class JsonStringFieldDeltaExtractor:
    """Incrementally decode one JSON string field from provider token deltas."""

    def __init__(self, field_name: str) -> None:
        self._pattern = re.compile(rf'"{re.escape(field_name)}"\s*:\s*"')
        self._buffer = ""
        self._position: int | None = None
        self._completed = False

    def feed(self, chunk: str) -> str:
        if self._completed or not chunk:
            return ""
        self._buffer += chunk
        if self._position is None:
            match = self._pattern.search(self._buffer)
            if match is None:
                return ""
            self._position = match.end()

        output: list[str] = []
        index = self._position
        while index < len(self._buffer):
            char = self._buffer[index]
            if char == '"':
                self._completed = True
                index += 1
                break
            if char != "\\":
                output.append(char)
                index += 1
                continue
            if index + 1 >= len(self._buffer):
                break
            escape = self._buffer[index + 1]
            width = 2
            if escape == "u":
                width = 6
                if index + width > len(self._buffer):
                    break
            encoded = self._buffer[index : index + width]
            try:
                output.append(json.loads(f'"{encoded}"'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                output.append(encoded)
            index += width
        self._position = index
        return "".join(output)
