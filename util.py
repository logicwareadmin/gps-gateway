"""Utilidades compartidas del gateway: lector con buffer (peek + reads)."""
import asyncio


class Buf:
    """Lector con buffer sobre un StreamReader.

    Permite mirar los primeros bytes (peek, para auto-detectar el protocolo) y
    luego leer por cantidad exacta o hasta un delimitador, conservando lo ya leído.
    """
    def __init__(self, reader: asyncio.StreamReader):
        self.r = reader
        self.b = bytearray()

    async def _more(self):
        chunk = await self.r.read(4096)
        if not chunk:
            raise asyncio.IncompleteReadError(bytes(self.b), None)
        self.b += chunk

    async def peek(self, n: int) -> bytes:
        """Devuelve hasta n bytes sin consumirlos (para detect)."""
        while len(self.b) < n:
            try:
                await self._more()
            except asyncio.IncompleteReadError:
                break
        return bytes(self.b[:n])

    async def exactly(self, n: int) -> bytes:
        while len(self.b) < n:
            await self._more()
        out = bytes(self.b[:n])
        del self.b[:n]
        return out

    async def until(self, delim: bytes) -> bytes:
        """Lee hasta `delim` (sin incluirlo); descarta el delimitador."""
        while True:
            i = self.b.find(delim)
            if i != -1:
                out = bytes(self.b[:i])
                del self.b[:i + len(delim)]
                return out
            await self._more()
