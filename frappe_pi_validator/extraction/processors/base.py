from abc import ABC, abstractmethod

class BaseProcessor(ABC):
    @abstractmethod
    def supports(self, mime_type: str) -> bool: ...
    @abstractmethod
    def process(self, file_path, document_id, file_name, mime_type): ...
