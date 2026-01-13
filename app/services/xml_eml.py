"""
Servicio para procesar archivos XML y EML
"""
import os
import email
import xml.etree.ElementTree as ET
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class XMLEMLProcessor:
    """Procesador para archivos XML y EML"""
    
    # Elementos XML a ignorar (firmas digitales, certificados, etc.)
    ELEMENTS_TO_IGNORE = [
        'X509Certificate',
        'SignatureValue',
        'Modulus',
        'Exponent',
        'X509Data',
        'KeyInfo',
        'Signature',
        'SignedInfo',
        'CanonicalizationMethod',
        'SignatureMethod',
        'Reference',
        'DigestValue',
        'DigestMethod',
        'Transform',
        'Transforms'
    ]
    
    def process_xml(self, xml_path: str) -> str:
        """
        Extrae el contenido de texto de un archivo XML, ignorando elementos de firma digital
        
        Args:
            xml_path: Ruta al archivo XML
            
        Returns:
            Texto extraído del XML
        """
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            
            # Extraer todo el texto del XML
            text_parts = []
            
            def should_ignore_element(element):
                """Verifica si un elemento debe ser ignorado"""
                # Obtener el nombre del elemento sin namespace
                tag = element.tag
                if '}' in tag:
                    # Formato: {namespace}tag_name
                    tag = tag.split('}')[1]  # Remover namespace
                elif ':' in tag:
                    # Formato: prefix:tag_name (menos común pero posible)
                    tag = tag.split(':')[-1]
                
                # Verificar si el tag está en la lista de ignorados
                return tag in self.ELEMENTS_TO_IGNORE
            
            def extract_text(element):
                """Extrae texto recursivamente de un elemento XML, ignorando elementos específicos"""
                # Si este elemento debe ser ignorado, saltarlo completamente
                if should_ignore_element(element):
                    return
                
                # Agregar texto del elemento si existe
                if element.text and element.text.strip():
                    text_parts.append(element.text.strip())
                
                # Procesar hijos
                for child in element:
                    extract_text(child)
                    # Agregar tail del hijo si existe (solo si el hijo no fue ignorado)
                    if not should_ignore_element(child) and child.tail and child.tail.strip():
                        text_parts.append(child.tail.strip())
            
            extract_text(root)
            
            # Unir todo el texto
            extracted_text = " ".join(text_parts)
            
            # Si el texto es muy largo, tomar las primeras líneas
            lines = extracted_text.split('\n')
            if len(lines) > 100:
                extracted_text = '\n'.join(lines[:100]) + "\n[... contenido truncado ...]"
            
            return extracted_text
        except ET.ParseError as e:
            logger.warning(f"Error parseando XML: {e}. Intentando leer como texto plano...")
            # Si falla el parseo, leer como texto plano
            with open(xml_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Limitar tamaño
                if len(content) > 10000:
                    return content[:10000] + "\n[... contenido truncado ...]"
                return content
        except Exception as e:
            logger.error(f"Error procesando XML {xml_path}: {e}")
            return ""
    
    def process_eml(self, eml_path: str) -> str:
        """
        Extrae el contenido de un archivo EML (email)
        
        Args:
            eml_path: Ruta al archivo EML
            
        Returns:
            Texto extraído del email (asunto, remitente, cuerpo)
        """
        try:
            with open(eml_path, 'rb') as f:
                msg = email.message_from_bytes(f.read())
            
            # Extraer información del email
            parts = []
            
            # Asunto
            subject = msg.get('Subject', '')
            if subject:
                parts.append(f"Asunto: {subject}")
            
            # Remitente
            from_addr = msg.get('From', '')
            if from_addr:
                parts.append(f"De: {from_addr}")
            
            # Destinatario
            to_addr = msg.get('To', '')
            if to_addr:
                parts.append(f"Para: {to_addr}")
            
            # Fecha
            date = msg.get('Date', '')
            if date:
                parts.append(f"Fecha: {date}")
            
            # Cuerpo del mensaje
            body = self._extract_email_body(msg)
            if body:
                # Limitar tamaño del cuerpo
                if len(body) > 5000:
                    body = body[:5000] + "\n[... contenido truncado ...]"
                parts.append(f"\nCuerpo:\n{body}")
            
            return "\n".join(parts)
        except Exception as e:
            logger.error(f"Error procesando EML {eml_path}: {e}")
            # Si falla, intentar leer como texto plano
            try:
                with open(eml_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if len(content) > 10000:
                        return content[:10000] + "\n[... contenido truncado ...]"
                    return content
            except:
                return ""
    
    def _extract_email_body(self, msg: email.message.Message) -> str:
        """Extrae el cuerpo del email, manejando multipart"""
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            body = payload.decode(charset, errors='ignore')
                            break
                    except Exception as e:
                        logger.warning(f"Error decodificando parte del email: {e}")
                elif content_type == "text/html" and not body:
                    # Si no hay texto plano, usar HTML
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            html_body = payload.decode(charset, errors='ignore')
                            # Intentar extraer texto del HTML (simple)
                            import re
                            # Remover tags HTML básicos
                            text_body = re.sub(r'<[^>]+>', '', html_body)
                            body = text_body.strip()
                            break
                    except Exception as e:
                        logger.warning(f"Error decodificando HTML del email: {e}")
        else:
            # Email simple (no multipart)
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='ignore')
            except Exception as e:
                logger.warning(f"Error decodificando cuerpo del email: {e}")
        
        return body

