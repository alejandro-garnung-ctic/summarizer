import os
import requests
import logging
import json

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self, model: str = None):
        self.api_url = os.getenv("MODEL_API_URL", "http://localhost:11434/v1/chat/completions")
        self.api_token = os.getenv("MODEL_API_TOKEN", None)
        
        # Determinar modelo: prioridad al argumento, luego al toggle USE_VLLM_FOR_ALL
        if model:
            self.model = model
        elif os.getenv("USE_VLLM_FOR_ALL", "false").lower() == "true":
            self.model = os.getenv("VLLM_MODEL", "mistralai/Mistral-Small-3.2-24B-Instruct-2506")
            logger.info(f"LLMService: USE_VLLM_FOR_ALL is true. Using VLLM_MODEL: {self.model}")
        else:
            self.model = os.getenv("LLM_MODEL", "Qwen/Qwen3-32B")

    def analyze_llm(self, prompt: str, max_tokens: int = 1024, schema: dict = None, temperature: float = 0.1, top_p: float = 0.9) -> str:
        """Servicio específico para procesamiento de solo texto (LLM) en texto plano"""
        logger.info(f"Preparing LLM request for text-only analysis (Plain Text). Model: {self.model}")
        
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that analyzes documents and extracts their description. ALWAYS respond with plain text only, never use JSON format, no quotes, no brackets, no structured format. Just return the description as plain text."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p
        }

        return self._send_request(payload)

    def _clean_plain_text_response(self, content: str) -> str:
        """
        Limpia la respuesta del LLM para extraer texto plano, eliminando JSON u otros formatos
        
        Args:
            content: Contenido crudo de la respuesta del LLM
            
        Returns:
            Texto plano limpio
        """
        if not content:
            return ""
        
        # Si parece JSON, intentar extraer el texto
        import re
        
        # Buscar patrones JSON comunes
        json_patterns = [
            r'\{[^}]*"description"\s*:\s*"([^"]+)"[^}]*\}',
            r'\{[^}]*"descripcion"\s*:\s*"([^"]+)"[^}]*\}',
            r'"description"\s*:\s*"([^"]+)"',
            r'"descripcion"\s*:\s*"([^"]+)"',
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                extracted = match.group(1)
                # Decodificar escapes JSON
                extracted = extracted.replace('\\n', '\n').replace('\\t', '\t')
                extracted = extracted.replace('\\"', '"').replace("\\'", "'")
                logger.info("Extraído texto plano de respuesta JSON")
                return extracted.strip()
        
        # Si tiene bloques de código markdown, limpiarlos
        if "```" in content:
            # Remover bloques de código
            content = re.sub(r'```[a-z]*\n?', '', content)
            content = re.sub(r'```\n?', '', content)
        
        # Remover comillas al inicio y final si están solas
        content = content.strip()
        if (content.startswith('"') and content.endswith('"')) or \
           (content.startswith("'") and content.endswith("'")):
            content = content[1:-1]
        
        # Remover prefijos comunes
        prefixes_to_remove = [
            r'^description:\s*',
            r'^descripcion:\s*',
            r'^resumen:\s*',
            r'^summary:\s*',
        ]
        for prefix in prefixes_to_remove:
            content = re.sub(prefix, '', content, flags=re.IGNORECASE)
        
        return content.strip()

    def _send_request(self, payload: dict) -> str:
        try:
            headers = {
                "Content-Type": "application/json"
            }
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            logger.info(f"Sending LLM request to {self.api_url}")
            response = requests.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            
            resp_json = response.json()
            content = resp_json["choices"][0]["message"]["content"]
            
            if content is None:
                logger.warning("LLM returned empty content (None)")
                return "Error: El modelo no devolvió contenido."
            
            # Limpiar la respuesta para asegurar texto plano
            cleaned_content = self._clean_plain_text_response(content.strip())
            return cleaned_content
        except Exception as e:
            logger.error(f"Error calling LLM: {str(e)}", exc_info=True)
            return f"Error calling LLM: {str(e)}"

    def test_connection(self) -> dict:
        """Prueba de conexión básica enviando un mensaje corto"""
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "hola"}],
                "max_tokens": 1024
            }
            headers = {"Content-Type": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            return {"status": "ok", "model": self.model, "response": response.json()["choices"][0]["message"]["content"]}
        except Exception as e:
            return {"status": "error", "model": self.model, "error": str(e)}
