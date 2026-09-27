import uuid
from frappe_pi_validator.extraction.core.mime import detect_mime_type
from frappe_pi_validator.extraction.processors.factory import ProcessorFactory

class DocumentService:
    def __init__(self):
        self.factory = ProcessorFactory()

    def process(self, file_path: str, file_name: str):
        document_id = str(uuid.uuid4())
        mime_type = detect_mime_type(file_path)
        processor = self.factory.get_processor(mime_type)
        return processor.process(file_path, document_id, file_name, mime_type)
