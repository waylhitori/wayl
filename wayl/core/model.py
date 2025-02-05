from typing import Dict, List, Optional, Any
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, PreTrainedModel
import os
import logging
from datetime import datetime
import json
import asyncio
from prometheus_client import Gauge, Counter, Histogram

logger = logging.getLogger(__name__)

# Metrics
model_load_time = Histogram('model_load_time_seconds', 'Time to load model')
model_inference_time = Histogram('model_inference_time_seconds', 'Model inference time')
gpu_memory_usage = Gauge('gpu_memory_usage_bytes', 'GPU memory usage')
model_cache_size = Gauge('model_cache_size', 'Number of models in cache')
inference_requests = Counter('model_inference_requests_total', 'Total inference requests')


class DeepseekModel:
    def __init__(
            self,
            model_id: str,
            model_path: str,
            device: str = "cuda" if torch.cuda.is_available() else "cpu",
            max_memory: Optional[Dict] = None
    ):
        self.model_id = model_id
        self.model_path = model_path
        self.device = device
        self.max_memory = max_memory or {"cuda:0": "15GB"} if device == "cuda" else None
        self.model: Optional[PreTrainedModel] = None
        self.tokenizer: Optional[AutoTokenizer] = None
        self.last_used = datetime.utcnow()
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if self.model is not None:
            return

        async with self._lock:
            if self.model is not None:  # Double check
                return

            try:
                start_time = datetime.utcnow()
                logger.info(f"Loading model {self.model_id}")

                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_path,
                    trust_remote_code=True,
                    use_fast=True
                )

                with model_load_time.time():
                    self.model = AutoModelForCausalLM.from_pretrained(
                        self.model_path,
                        device_map="auto" if self.device == "cuda" else None,
                        torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                        max_memory=self.max_memory,
                        trust_remote_code=True,
                        low_cpu_mem_usage=True
                    )

                if self.device == "cuda":
                    gpu_memory_usage.set(torch.cuda.max_memory_allocated())

                load_time = (datetime.utcnow() - start_time).total_seconds()
                logger.info(f"Model {self.model_id} loaded in {load_time:.2f}s")

            except Exception as e:
                logger.error(f"Failed to load model {self.model_id}: {str(e)}")
                raise

    async def generate(
            self,
            prompt: str,
            system_prompt: Optional[str] = None,
            context: Optional[str] = None,
            max_length: int = 2048,
            temperature: float = 0.7,
            top_p: float = 0.95,
            **kwargs
    ) -> str:
        inference_requests.inc()

        try:
            await self.load()
            full_prompt = self._build_prompt(prompt, system_prompt, context)

            inputs = self.tokenizer(
                full_prompt,
                return_tensors="pt",
                truncation=True,
                max_length=max_length
            ).to(self.device)

            with model_inference_time.time(), torch.inference_mode():
                outputs = await asyncio.to_thread(
                    self.model.generate,
                    **inputs,
                    max_length=max_length,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                    **kwargs
                )

            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            return response.replace(full_prompt, "").strip()

        except Exception as e:
            logger.error(f"Generation error for model {self.model_id}: {str(e)}")
            raise

    def _build_prompt(
            self,
            prompt: str,
            system_prompt: Optional[str] = None,
            context: Optional[str] = None
    ) -> str:
        parts = []
        if system_prompt:
            parts.append(f"System: {system_prompt}")
        if context:
            parts.append(f"Context: {context}")
        parts.append(f"User: {prompt}")
        return "\n\n".join(parts)

    async def unload(self) -> None:
        if self.model is not None:
            async with self._lock:
                if self.model is not None:
                    del self.model
                    self.model = None
                    if self.device == "cuda":
                        torch.cuda.empty_cache()
                        gpu_memory_usage.set(torch.cuda.max_memory_allocated())


class ModelManager:
    _instances: Dict[str, DeepseekModel] = {}
    _max_cache_size: int = int(os.getenv("MODEL_CACHE_SIZE", "2"))

    @classmethod
    async def get_model(cls, model_id: str) -> DeepseekModel:
        if model_id not in cls._instances:
            await cls._maybe_evict_model()
            model_path = os.getenv(f"MODEL_PATH_{model_id}", f"deepseek-ai/{model_id}")
            cls._instances[model_id] = DeepseekModel(model_id, model_path)
            model_cache_size.set(len(cls._instances))

        model = cls._instances[model_id]
        model.last_used = datetime.utcnow()
        return model

    @classmethod
    async def _maybe_evict_model(cls) -> None:
        if len(cls._instances) >= cls._max_cache_size:
            oldest_model_id = min(
                cls._instances.keys(),
                key=lambda k: cls._instances[k].last_used
            )
            await cls._instances[oldest_model_id].unload()
            del cls._instances[oldest_model_id]
            model_cache_size.set(len(cls._instances))

    @classmethod
    def list_available_models(cls) -> List[str]:
        models_dir = os.getenv("MODELS_DIR", "./models")
        if not os.path.exists(models_dir):
            return []
        return [f.replace(".bin", "") for f in os.listdir(models_dir) if f.endswith(".bin")]

    @classmethod
    async def get_model_info(cls, model_id: str) -> Dict[str, Any]:
        model = await cls.get_model(model_id)
        return {
            "id": model_id,
            "path": model.model_path,
            "device": model.device,
            "loaded": model.model is not None,
            "last_used": model.last_used.isoformat(),
            "config": json.loads(model.model.config.to_json_string()) if model.model else {}
        }