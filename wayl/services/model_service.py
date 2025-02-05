
from typing import List, Dict
from ..core.model import ModelManager, DeepseekModel


class ModelService:
    def __init__(self):
        self.model_manager = ModelManager()

    def get_model(self, model_id: str) -> DeepseekModel:
        return self.model_manager.get_model(model_id)

    def list_models(self) -> List[str]:
        return self.model_manager.list_available_models()

    def get_model_info(self, model_id: str) -> Dict:
        model = self.get_model(model_id)
        return {
            "id": model_id,
            "name": model.model_path.split("/")[-1],
            "parameters": model.model.config.to_dict() if model.model else {},
            "device": model.device
        }