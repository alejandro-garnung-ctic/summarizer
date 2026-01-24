import os
import requests
import logging
import json
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

        # Configurar retry strategy para manejar rate limiting y errores temporales
        self.retry_strategy = Retry(
            total=3,  # 3 intentos
            backoff_factor=1,  # Esperar 1, 2, 4 segundos entre reintentos
            status_forcelist=[429, 500, 502, 503, 504],  # Reintentar en estos códigos HTTP
            allowed_methods=["POST"]
        )
        self.adapter = HTTPAdapter(max_retries=self.retry_strategy)
        self.session = requests.Session()
        self.session.mount("http://", self.adapter)
        self.session.mount("https://", self.adapter)

    def analyze_llm(self, prompt: str, max_tokens: int = 1024, schema: dict = None, temperature: float = 0.1, top_p: float = 0.9) -> str:
        """Servicio específico para procesamiento de solo texto (LLM) en texto plano"""
        logger.info(f"Preparing LLM request for text-only analysis (Plain Text). Model: {self.model}")
        
        # Obtener enable_thinking de variable de entorno (default: False)
        enable_thinking = os.getenv("LLM_ENABLE_THINKING", "false").lower() == "true"
        
        messages = [
            {
                "role": "system",
                "content": """You are an expert document analyst specialized in extracting semantic information from documents. Your task is to analyze document content and generate clear, concise, and accurate summaries, descriptions, and titles.

CRITICAL RULES:
- NEVER include your reasoning, thinking process, chain of thought, or any explanation in your response
- NEVER write "Let me think..." or "I need to analyze..." or any similar phrases
- NEVER show your internal reasoning or step-by-step thinking
- ONLY provide the final answer directly, without any preamble or explanation
- If the prompt asks for a title, respond ONLY with the title text, nothing else
- If the prompt asks for a description, respond ONLY with the description text, nothing else
- Do NOT use reasoning tokens or thinking loops - go directly to the answer

Key principles:
- Always respond with plain text only (no JSON, no markdown, no structured formats, no quotes, no brackets)
- Be precise and factual: include specific entities (names, organizations, dates, amounts) when they appear in the content
- Focus on semantic understanding: capture the purpose, key concepts, and important details
- Be concise but comprehensive: provide enough information to clearly identify and understand the document
- Maintain objectivity: describe what the document contains, not your interpretation
- When generating titles, include proper nouns, entities, and key identifiers when clearly present in the content
- Respond directly with the requested content, without prefixes, labels, or explanatory text"""
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
        
        # Añadir enable_thinking si está habilitado (para modelos que lo soporten, como Qwen)
        if enable_thinking:
            payload["enable_thinking"] = True
            logger.debug("Thinking mode enabled for LLM")

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
        
        # Primero, intentar extraer contenido de etiquetas <answer></answer>
        # Buscar tanto con etiqueta de cierre como sin ella (por si el modelo no la cierra)
        # Usar .*? para capturar todo hasta </answer> o el final, con DOTALL para incluir saltos de línea
        answer_match = re.search(r'<answer>\s*(.*?)(?:\s*</answer>|$)', content, re.DOTALL | re.IGNORECASE)
        if answer_match:
            extracted = answer_match.group(1).strip()
            logger.info("Extraído texto de etiquetas <answer></answer>")
            # Continuar con la limpieza normal del texto extraído
            content = extracted
        else:
            # Si no hay etiquetas pero el contenido contiene <answer>, limpiarlo
            # Buscar <answer> en cualquier posición y eliminarlo junto con espacios/saltos de línea
            content = re.sub(r'<answer>\s*', '', content, flags=re.IGNORECASE)
            content = re.sub(r'\s*</answer>', '', content, flags=re.IGNORECASE)
        
        # Limpiar saltos de línea y espacios extra que puedan quedar
        content = re.sub(r'\n+', ' ', content)  # Reemplazar múltiples saltos de línea con un espacio
        content = re.sub(r'\r+', ' ', content)  # Reemplazar retornos de carro
        content = re.sub(r'\t+', ' ', content)  # Reemplazar tabs
        content = re.sub(r'\s+', ' ', content)  # Reemplazar múltiples espacios con uno solo
        content = content.strip()
        
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
        
        # Limpiar escapes de comillas y backslashes
        content = content.replace('\\"', '"')  # Escapes de comillas dobles
        content = content.replace("\\'", "'")  # Escapes de comillas simples
        content = content.replace('\\\\', '')   # Backslashes dobles
        content = content.replace('\\n', ' ')  # Saltos de línea escapados -> espacio
        content = content.replace('\\t', ' ')  # Tabs escapados -> espacio
        content = content.replace('\\r', ' ')  # Retornos de carro escapados -> espacio
        
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
                logger.debug("Using Bearer token authentication for LLM")
            else:
                logger.warning("No API token configured for LLM (MODEL_API_TOKEN not set)")
            
            logger.info(f"Sending LLM request to {self.api_url}")
            # Usar session con retry y timeout configurado
            response = self.session.post(
                self.api_url, 
                json=payload, 
                headers=headers,
                timeout=(5, 25)  # 5s para conectar, 25s para leer respuesta
            )
            response.raise_for_status()
            
            resp_json = response.json()
            content = resp_json["choices"][0]["message"]["content"]
            
            if content is None:
                logger.warning("LLM returned empty content (None)")
                return "Error: El modelo no devolvió contenido."
            
            # Limpiar la respuesta para asegurar texto plano
            cleaned_content = self._clean_plain_text_response(content.strip())
            return cleaned_content
        except requests.exceptions.Timeout:
            logger.error("LLM request timed out")
            return "Error: Timeout al llamar al modelo."
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling LLM: {str(e)}", exc_info=True)
            return f"Error calling LLM: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error calling LLM: {str(e)}", exc_info=True)
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
