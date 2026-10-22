"""Attachment validation; files are opaque, never executed or rendered inline."""
import base64
import binascii
import re
from pydantic import BaseModel, Field, PrivateAttr, model_validator

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_APPLICATION_BODY = 22 * 1024 * 1024  # Three base64 files + application JSON.

class AttachmentInput(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    data: str = Field(max_length=4 * ((MAX_ATTACHMENT_BYTES + 2) // 3))
    _content: bytes = PrivateAttr(default=b'')

    @model_validator(mode='after')
    def validate_file(self):
        # Never use a client filename as a filesystem path or raw response header.
        self.name = re.split(r'[/\\]', self.name)[-1].strip()
        if not self.name or self.name in {'.', '..'} or any(ord(c) < 32 or ord(c) == 127 for c in self.name):
            raise ValueError('附件文件名无效')
        try:
            self._content = base64.b64decode(self.data, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('附件内容编码无效') from None
        if not self._content or len(self._content) > MAX_ATTACHMENT_BYTES:
            raise ValueError('附件不能为空，每个附件最多 5 MB')
        return self
