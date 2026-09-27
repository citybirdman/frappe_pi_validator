from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Document Intelligence"
    debug: bool = True
    ocr_language: str = "ar"
    device: str = "cpu"
    ocr_dpi: int = 300
    upload_dir: str = "uploads"
    result_dir: str = "results"
    use_doc_orientation_classify: bool = False
    use_doc_unwarping: bool = False
    use_textline_orientation: bool = False
    use_table_recognition: bool = True
    use_formula_recognition: bool = False
    use_chart_recognition: bool = False
    use_region_detection: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
