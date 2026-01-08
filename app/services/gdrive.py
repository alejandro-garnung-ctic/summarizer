import os
import io
from typing import List, Dict, Optional
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Scopes necesarios para Google Drive
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

class GoogleDriveService:
    def __init__(self):
        self.service = None
        self._init_service()

    def _init_service(self):
        """Inicializa el servicio de Google Drive API"""
        creds = None
        token_path = os.getenv("GOOGLE_DRIVE_TOKEN_PATH", "/data/gdrive_token.pickle")
        credentials_path = os.getenv("GOOGLE_DRIVE_CREDENTIALS", "/secrets/google-credentials.json")
        
        if not os.path.exists(credentials_path):
            raise Exception(
                f"Archivo de credenciales no encontrado en {credentials_path}. "
                "Descarga el archivo credentials.json desde Google Cloud Console."
            )
        
        if not os.path.isfile(credentials_path):
            raise Exception(
                f"La ruta de credenciales {credentials_path} no es un archivo. "
                "Verifica que GOOGLE_DRIVE_CREDENTIALS apunte a un archivo JSON válido."
            )
        
        try:
            import json
            with open(credentials_path, 'r') as f:
                client_config = json.load(f)
        except json.JSONDecodeError as e:
            raise Exception(
                f"El archivo de credenciales {credentials_path} no es un JSON válido: {e}"
            )
        
        # Determinar el tipo de credenciales
        if 'type' in client_config and client_config['type'] == 'service_account':
            # Service Account: autenticación server-to-server
            creds = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=SCOPES)
        elif 'installed' in client_config:
            # OAuth 2.0: aplicación instalada (requiere autorización del usuario)
            # Cargar token si existe y es un archivo (no un directorio)
            if os.path.exists(token_path) and os.path.isfile(token_path):
                with open(token_path, 'rb') as token:
                    creds = pickle.load(token)
            
            # Si no hay credenciales válidas, autenticar
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        credentials_path, SCOPES)
                    creds = flow.run_local_server(port=0)
                
                # Guardar credenciales para próximas ejecuciones
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                with open(token_path, 'wb') as token:
                    pickle.dump(creds, token)
        else:
            raise ValueError(
                f"El archivo de credenciales en {credentials_path} no es válido. "
                "Debe ser una Service Account (type: 'service_account') o una aplicación OAuth 2.0 "
                "del tipo 'installed' (Desktop app)."
            )
        
        self.service = build('drive', 'v3', credentials=creds)

    def extract_folder_id(self, url: str) -> str:
        """Extrae el ID de carpeta de una URL de Google Drive"""
        # Formato: https://drive.google.com/drive/u/0/folders/FOLDER_ID
        if 'folders/' in url:
            folder_id = url.split('folders/')[-1].split('?')[0].split('/')[0]
            return folder_id
        # Si ya es un ID directo
        return url

    def list_folder_contents(self, folder_id: str) -> List[Dict]:
        """Lista todos los archivos y carpetas dentro de una carpeta de Google Drive"""
        folder_id = self.extract_folder_id(folder_id)
        results = []
        page_token = None
        
        while True:
            try:
                query = f"'{folder_id}' in parents and trashed=false"
                response = self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, mimeType, size)',
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()
                
                items = response.get('files', [])
                results.extend(items)
                
                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"Error listando carpeta {folder_id}: {e}")
                break
        
        return results

    def find_folder_by_name(self, parent_folder_id: str, folder_name: str) -> Optional[str]:
        """Busca una carpeta por nombre dentro de una carpeta padre"""
        parent_id = self.extract_folder_id(parent_folder_id)
        items = self.list_folder_contents(parent_id)
        
        for item in items:
            if item['mimeType'] == 'application/vnd.google-apps.folder' and item['name'] == folder_name:
                return item['id']
        return None

    def download_file(self, file_id: str, destination_path: str):
        """Descarga un archivo de Google Drive a una ruta local"""
        try:
            request = self.service.files().get_media(fileId=file_id)
            with open(destination_path, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
        except Exception as e:
            raise Exception(f"Error descargando archivo {file_id}: {e}")

    def download_file_to_memory(self, file_id: str) -> bytes:
        """Descarga un archivo de Google Drive a memoria"""
        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read()
        except Exception as e:
            raise Exception(f"Error descargando archivo {file_id} a memoria: {e}")

    def get_file_info(self, file_id: str) -> Dict:
        """Obtiene información de un archivo"""
        try:
            file = self.service.files().get(
                fileId=file_id, 
                fields='id, name, mimeType, size',
                supportsAllDrives=True
            ).execute()
            return file
        except Exception as e:
            raise Exception(f"Error obteniendo info del archivo {file_id}: {e}")

    def get_all_files_recursive(self, folder_id: str, file_types: List[str] = None) -> List[Dict]:
        """Obtiene recursivamente todos los archivos de una carpeta y subcarpetas"""
        if file_types is None:
            file_types = ['application/pdf', 'application/zip']
        
        folder_id = self.extract_folder_id(folder_id)
        all_files = []
        
        def traverse_folder(current_folder_id: str, current_path: str = ""):
            items = self.list_folder_contents(current_folder_id)
            
            for item in items:
                item_path = f"{current_path}/{item['name']}" if current_path else item['name']
                
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    # Es una carpeta, recorrer recursivamente
                    traverse_folder(item['id'], item_path)
                elif item['mimeType'] in file_types:
                    # Es un archivo del tipo que buscamos
                    all_files.append({
                        'id': item['id'],
                        'name': item['name'],
                        'mimeType': item['mimeType'],
                        'path': item_path,
                        'size': item.get('size', '0')
                    })
        
        traverse_folder(folder_id)
        return all_files

