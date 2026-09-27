from frappe_pi_validator.extraction.processors.pdf import PDFProcessor
from frappe_pi_validator.extraction.processors.image import ImageProcessor
from frappe_pi_validator.extraction.processors.excel import ExcelProcessor

class ProcessorFactory:
    def __init__(self):
        self.processors = [PDFProcessor(), ExcelProcessor(), ImageProcessor()]

    def get_processor(self, mime_type: str):
        for processor in self.processors:
            if processor.supports(mime_type):
                return processor
        raise ValueError(f"No processor available for {mime_type}")
