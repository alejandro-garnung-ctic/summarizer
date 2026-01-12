"""
Servicio de checkpoint para modo desatendido
Guarda el estado del procesamiento para poder retomar desde donde se quedó
"""
import os
import json
import threading
import time
from typing import Dict, List, Set, Optional
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CheckpointService:
    """Servicio para gestionar checkpoints de procesamiento"""
    
    def __init__(self, checkpoint_dir: Optional[str] = None):
        """
        Inicializa el servicio de checkpoint
        
        Args:
            checkpoint_dir: Directorio donde guardar los checkpoints. 
                          Si es None, usa CHECKPOINT_DIR del .env o /data/checkpoints por defecto
        """
        self.checkpoint_dir = Path(
            checkpoint_dir or 
            os.getenv("CHECKPOINT_DIR", "/data/checkpoints")
        )
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        self.lock = threading.Lock()
        self.current_checkpoint: Optional[str] = None
        self.checkpoint_data: Dict = {}
        self.last_save_time = time.time()
        self.checkpoint_interval = int(os.getenv("CHECKPOINT_INTERVAL", "60"))
        
        logger.info(f"CheckpointService inicializado. Directorio: {self.checkpoint_dir}")
        logger.info(f"Intervalo de guardado: {self.checkpoint_interval} segundos")
    
    def start_checkpoint(self, folder_id: str, folder_name: str, total_files: int, config: Dict) -> str:
        """
        Inicia un nuevo checkpoint o retoma uno existente
        
        Args:
            folder_id: ID de la carpeta de Google Drive
            folder_name: Nombre de la carpeta
            total_files: Número total de archivos a procesar
            config: Configuración del procesamiento
            
        Returns:
            Ruta del archivo de checkpoint
        """
        # Buscar checkpoint existente para esta carpeta
        existing_checkpoint = self._find_existing_checkpoint(folder_id)
        
        if existing_checkpoint:
            logger.info("=" * 80)
            logger.info("🔄 RETOMANDO DESDE CHECKPOINT EXISTENTE")
            logger.info("=" * 80)
            logger.info(f"Archivo de checkpoint: {existing_checkpoint}")
            self.current_checkpoint = str(existing_checkpoint)
            self._load_checkpoint()
            
            processed_count = len(self.checkpoint_data.get("processed_files", []))
            failed_count = len(self.checkpoint_data.get("failed_files", []))
            pending_count = total_files - processed_count - failed_count
            
            logger.info(f"Estado del procesamiento:")
            logger.info(f"  ✓ Archivos ya procesados: {processed_count}/{total_files}")
            logger.info(f"  ✗ Archivos fallidos: {failed_count}")
            logger.info(f"  ⏳ Archivos pendientes: {pending_count}")
            logger.info("=" * 80)
            
            # Actualizar total_files si ha cambiado
            if self.checkpoint_data.get("total_files") != total_files:
                logger.info(f"⚠️  Número total de archivos cambió: {self.checkpoint_data.get('total_files')} → {total_files}")
                self.checkpoint_data["total_files"] = total_files
            
            # Actualizar estado a "in_progress" si estaba completado
            if self.checkpoint_data.get("status") == "completed":
                logger.info("⚠️  Checkpoint estaba completado. Reiniciando procesamiento...")
                self.checkpoint_data["status"] = "in_progress"
                self._save_checkpoint()
            
            return self.current_checkpoint
        else:
            # Generar nombre único del checkpoint basado en folder_id y timestamp
            checkpoint_name = f"checkpoint_{folder_id}_{int(time.time())}.json"
            checkpoint_path = self.checkpoint_dir / checkpoint_name
            
            # Crear nuevo checkpoint
            logger.info("=" * 80)
            logger.info("🆕 CREANDO NUEVO CHECKPOINT")
            logger.info("=" * 80)
            logger.info(f"Archivo de checkpoint: {checkpoint_path}")
            logger.info(f"Total de archivos a procesar: {total_files}")
            logger.info("=" * 80)
            self.current_checkpoint = str(checkpoint_path)
            self.checkpoint_data = {
                "folder_id": folder_id,
                "folder_name": folder_name,
                "started_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "total_files": total_files,
                "processed_files": [],  # Lista de file_ids procesados exitosamente
                "failed_files": [],     # Lista de file_ids que fallaron
                "pending_files": [],     # Lista de file_ids pendientes
                "results": [],          # Resultados procesados
                "config": config,
                "status": "in_progress"
            }
            self._save_checkpoint()
            return self.current_checkpoint
    
    def _find_existing_checkpoint(self, folder_id: str) -> Optional[Path]:
        """Busca un checkpoint existente para una carpeta (solo uno por carpeta)"""
        # Buscar checkpoint con patrón: checkpoint_{folder_id}_*.json
        pattern = f"checkpoint_{folder_id}_*.json"
        checkpoints = list(self.checkpoint_dir.glob(pattern))
        
        if not checkpoints:
            return None
        
        # Si hay múltiples, usar el más reciente
        if len(checkpoints) > 1:
            logger.warning(f"Se encontraron {len(checkpoints)} checkpoints para la carpeta {folder_id}. Usando el más reciente.")
        
        # Retornar el más reciente
        return max(checkpoints, key=lambda p: p.stat().st_mtime)
    
    def _load_checkpoint(self):
        """Carga el checkpoint desde el archivo"""
        if not self.current_checkpoint or not os.path.exists(self.current_checkpoint):
            return
        
        try:
            with open(self.current_checkpoint, 'r', encoding='utf-8') as f:
                self.checkpoint_data = json.load(f)
            logger.info(f"Checkpoint cargado: {len(self.checkpoint_data.get('processed_files', []))} archivos procesados")
        except Exception as e:
            logger.error(f"Error cargando checkpoint: {e}")
            self.checkpoint_data = {}
    
    def _save_checkpoint(self):
        """Guarda el checkpoint al archivo"""
        if not self.current_checkpoint:
            return
        
        try:
            with self.lock:
                self.checkpoint_data["last_updated"] = datetime.now().isoformat()
                with open(self.current_checkpoint, 'w', encoding='utf-8') as f:
                    json.dump(self.checkpoint_data, f, indent=2, ensure_ascii=False, default=str)
                self.last_save_time = time.time()
        except Exception as e:
            logger.error(f"Error guardando checkpoint: {e}")
    
    def mark_file_processed(self, file_id: str, file_name: str, result: Dict):
        """
        Marca un archivo como procesado exitosamente
        
        Args:
            file_id: ID del archivo
            file_name: Nombre del archivo
            result: Resultado del procesamiento
        """
        with self.lock:
            # Agregar a procesados
            if file_id not in self.checkpoint_data.get("processed_files", []):
                self.checkpoint_data.setdefault("processed_files", []).append(file_id)
            
            # Remover de pendientes
            if file_id in self.checkpoint_data.get("pending_files", []):
                self.checkpoint_data["pending_files"].remove(file_id)
            
            # Remover de fallidos si estaba ahí
            failed_files = self.checkpoint_data.get("failed_files", [])
            failed_files = [f for f in failed_files if f.get("file_id") != file_id]
            self.checkpoint_data["failed_files"] = failed_files
            
            # Agregar resultado
            self.checkpoint_data.setdefault("results", []).append({
                "file_id": file_id,
                "file_name": file_name,
                "result": result,
                "processed_at": datetime.now().isoformat()
            })
        
        # Guardar periódicamente
        self._auto_save()
    
    def mark_file_failed(self, file_id: str, file_name: str, error: str):
        """
        Marca un archivo como fallido
        
        Args:
            file_id: ID del archivo
            file_name: Nombre del archivo
            error: Mensaje de error
        """
        with self.lock:
            # Remover de procesados si estaba ahí
            if file_id in self.checkpoint_data.get("processed_files", []):
                self.checkpoint_data["processed_files"].remove(file_id)
            
            # Remover de pendientes
            if file_id in self.checkpoint_data.get("pending_files", []):
                self.checkpoint_data["pending_files"].remove(file_id)
            
            # Agregar a fallidos
            failed_files = self.checkpoint_data.get("failed_files", [])
            # Evitar duplicados
            failed_files = [f for f in failed_files if f.get("file_id") != file_id]
            failed_files.append({
                "file_id": file_id,
                "file_name": file_name,
                "error": error,
                "failed_at": datetime.now().isoformat()
            })
            self.checkpoint_data["failed_files"] = failed_files
        
        # Guardar periódicamente
        self._auto_save()
    
    def add_pending_files(self, file_ids: List[str]):
        """Agrega archivos a la lista de pendientes"""
        with self.lock:
            pending = set(self.checkpoint_data.get("pending_files", []))
            pending.update(file_ids)
            self.checkpoint_data["pending_files"] = list(pending)
        
        self._auto_save()
    
    def get_processed_files(self) -> Set[str]:
        """Retorna el conjunto de archivos ya procesados"""
        return set(self.checkpoint_data.get("processed_files", []))
    
    def get_pending_files(self) -> List[str]:
        """Retorna la lista de archivos pendientes"""
        return self.checkpoint_data.get("pending_files", [])
    
    def get_failed_files(self) -> List[Dict]:
        """Retorna la lista de archivos fallidos"""
        return self.checkpoint_data.get("failed_files", [])
    
    def get_results(self) -> List[Dict]:
        """Retorna los resultados procesados"""
        return self.checkpoint_data.get("results", [])
    
    def get_progress(self) -> Dict:
        """Retorna información del progreso"""
        processed = len(self.checkpoint_data.get("processed_files", []))
        failed = len(self.checkpoint_data.get("failed_files", []))
        total = self.checkpoint_data.get("total_files", 0)
        pending = total - processed - failed
        
        return {
            "total": total,
            "processed": processed,
            "failed": failed,
            "pending": pending,
            "progress_percent": (processed / total * 100) if total > 0 else 0,
            "checkpoint_file": self.current_checkpoint,
            "last_updated": self.checkpoint_data.get("last_updated")
        }
    
    def _auto_save(self):
        """Guarda automáticamente si ha pasado el intervalo"""
        current_time = time.time()
        if current_time - self.last_save_time >= self.checkpoint_interval:
            self._save_checkpoint()
    
    def finalize(self, status: str = "completed"):
        """Finaliza el checkpoint"""
        with self.lock:
            self.checkpoint_data["status"] = status
            self.checkpoint_data["completed_at"] = datetime.now().isoformat()
        self._save_checkpoint()
        logger.info(f"Checkpoint finalizado con estado: {status}")
        logger.info(f"Archivo de checkpoint: {self.current_checkpoint}")
    
    def get_checkpoint_path(self) -> Optional[str]:
        """Retorna la ruta del checkpoint actual"""
        return self.current_checkpoint

