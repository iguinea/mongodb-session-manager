"""
Utilidades SQS para AWS

Este módulo proporciona funciones helper para interactuar con Amazon Simple Queue Service (SQS),
permitiendo enviar mensajes a colas SQS.
"""

import json
import os
from typing import Optional, Dict, Any, Union
import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def _get_sqs_client(region_name: Optional[str] = None):
    """
    Crear un cliente SQS reutilizable.

    Args:
        region_name: Región AWS donde está la cola (por defecto: desde el entorno)

    Returns:
        boto3.client: Cliente SQS configurado

    Raises:
        NoCredentialsError: Si las credenciales AWS no están configuradas
    """
    if not region_name:
        region_name = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")

    try:
        session = boto3.Session()
        return session.client(service_name="sqs", region_name=region_name)
    except NoCredentialsError:
        raise NoCredentialsError()


def send_message(
    queue_url: str,
    message_body: Union[str, Dict[str, Any]],
    message_attributes: Optional[Dict[str, Dict[str, Any]]] = None,
    delay_seconds: int = 0,
    message_group_id: Optional[str] = None,
    message_deduplication_id: Optional[str] = None,
    region_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Enviar un mensaje a una cola SQS.

    Args:
        queue_url: URL de la cola SQS
        message_body: Cuerpo del mensaje (string o dict que se convertirá a JSON)
        message_attributes: Atributos del mensaje (metadatos adicionales)
        delay_seconds: Segundos de retraso antes de que el mensaje esté disponible (0-900)
        message_group_id: ID del grupo de mensajes (solo para colas FIFO)
        message_deduplication_id: ID de deduplicación (solo para colas FIFO)
        region_name: Región AWS donde está la cola

    Returns:
        Dict con MessageId, MD5OfMessageBody y otros metadatos del mensaje enviado

    Raises:
        ValueError: Si los parámetros son inválidos
        ClientError: Si hay un error de AWS

    Ejemplos:
        >>> # Enviar mensaje simple
        >>> response = send_message(
        ...     "https://sqs.eu-west-1.amazonaws.com/123456789/mi-cola",
        ...     "Hola mundo"
        ... )

        >>> # Enviar mensaje con atributos
        >>> response = send_message(
        ...     queue_url,
        ...     {"tipo": "pedido", "id": 123},
        ...     message_attributes={
        ...         "prioridad": {"DataType": "String", "StringValue": "alta"}
        ...     }
        ... )
    """
    client = _get_sqs_client(region_name)

    # Convertir dict a JSON si es necesario
    if isinstance(message_body, dict):
        message_body = json.dumps(message_body, ensure_ascii=False)

    # Validar delay_seconds
    if not 0 <= delay_seconds <= 900:
        raise ValueError("delay_seconds debe estar entre 0 y 900")

    # Preparar parámetros
    params = {
        "QueueUrl": queue_url,
        "MessageBody": message_body,
        "DelaySeconds": delay_seconds,
    }

    if message_attributes:
        params["MessageAttributes"] = message_attributes

    # Parámetros para colas FIFO
    if message_group_id:
        params["MessageGroupId"] = message_group_id
    if message_deduplication_id:
        params["MessageDeduplicationId"] = message_deduplication_id

    try:
        response = client.send_message(**params)
        return response
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "QueueDoesNotExist":
            raise ValueError(f"La cola no existe: {queue_url}")
        elif error_code == "InvalidMessageContents":
            raise ValueError("El contenido del mensaje es inválido")
        elif error_code == "AccessDenied":
            raise PermissionError(
                f"Acceso denegado a la cola {queue_url}. Verifica los permisos IAM para sqs:SendMessage"
            )
        else:
            raise
