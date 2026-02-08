"""
Utilidades SNS para AWS

Este módulo proporciona funciones helper para interactuar con Amazon Simple Notification Service (SNS),
permitiendo publicar mensajes a tópicos, suscribir endpoints y gestionar notificaciones.
"""

import json
import os
from typing import Optional, Dict, Any, Union
import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def _get_sns_client(region_name: Optional[str] = None):
    """
    Crear un cliente SNS reutilizable.

    Args:
        region_name: Región AWS donde está el servicio (por defecto: desde el entorno)

    Returns:
        boto3.client: Cliente SNS configurado

    Raises:
        NoCredentialsError: Si las credenciales AWS no están configuradas
    """
    if not region_name:
        region_name = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")

    try:
        session = boto3.Session()
        return session.client(service_name="sns", region_name=region_name)
    except NoCredentialsError:
        raise NoCredentialsError()


def publish_message(
    topic_arn: Optional[str] = None,
    phone_number: Optional[str] = None,
    message: Union[str, Dict[str, Any]] = None,
    subject: Optional[str] = None,
    message_attributes: Optional[Dict[str, Dict[str, Any]]] = None,
    message_structure: Optional[str] = None,
    message_deduplication_id: Optional[str] = None,
    message_group_id: Optional[str] = None,
    region_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Publicar un mensaje a un tópico SNS o directamente a un número de teléfono.

    Args:
        topic_arn: ARN del tópico SNS (requerido si no se proporciona phone_number)
        phone_number: Número de teléfono para SMS directo (requerido si no se proporciona topic_arn)
        message: Contenido del mensaje (string o dict que se convertirá a JSON)
        subject: Asunto del mensaje (usado en notificaciones por email)
        message_attributes: Atributos del mensaje para filtrado
        message_structure: "json" para mensajes con formato específico por protocolo
        message_deduplication_id: ID de deduplicación (solo para tópicos FIFO)
        message_group_id: ID del grupo de mensajes (solo para tópicos FIFO)
        region_name: Región AWS donde está el servicio

    Returns:
        Dict con MessageId y SequenceNumber (para FIFO)

    Raises:
        ValueError: Si los parámetros son inválidos
        ClientError: Si hay un error de AWS

    Ejemplos:
        >>> # Publicar a un tópico
        >>> response = publish_message(
        ...     topic_arn="arn:aws:sns:eu-west-1:123456789:mi-topico",
        ...     message="Notificación importante",
        ...     subject="Alerta del sistema"
        ... )

        >>> # Enviar SMS directo
        >>> response = publish_message(
        ...     phone_number="+34600123456",
        ...     message="Código de verificación: 1234"
        ... )

        >>> # Mensaje con estructura JSON para diferentes protocolos
        >>> message_json = {
        ...     "default": "Mensaje por defecto",
        ...     "email": "Contenido detallado para email",
        ...     "sms": "Mensaje corto para SMS"
        ... }
        >>> response = publish_message(
        ...     topic_arn=topic_arn,
        ...     message=json.dumps(message_json),
        ...     message_structure="json"
        ... )
    """
    # Validar que se proporcione topic_arn o phone_number
    if not topic_arn and not phone_number:
        raise ValueError("Debe proporcionar topic_arn o phone_number")

    if topic_arn and phone_number:
        raise ValueError("Proporcione solo uno: topic_arn o phone_number")

    if not message:
        raise ValueError("El mensaje no puede estar vacío")

    client = _get_sns_client(region_name)

    # Convertir dict a JSON si es necesario
    if isinstance(message, dict):
        message = json.dumps(message, ensure_ascii=False)

    # Preparar parámetros
    params = {"Message": message}
    optional_params = {
        "TopicArn": topic_arn,
        "PhoneNumber": phone_number,
        "Subject": subject,
        "MessageAttributes": message_attributes,
        "MessageStructure": message_structure,
        "MessageGroupId": message_group_id,
        "MessageDeduplicationId": message_deduplication_id,
    }
    params.update({k: v for k, v in optional_params.items() if v is not None})

    try:
        return client.publish(**params)
    except ClientError as e:
        _handle_sns_client_error(e, topic_arn)


def _handle_sns_client_error(error: ClientError, topic_arn: Optional[str]) -> None:
    """Handle SNS ClientError and raise appropriate exceptions."""
    error_code = error.response["Error"]["Code"]
    error_map = {
        "NotFound": ValueError(f"El tópico no existe: {topic_arn}"),
        "InvalidParameter": ValueError(f"Parámetro inválido: {error}"),
        "AuthorizationError": PermissionError(
            f"Acceso denegado al tópico {topic_arn}. Verifica los permisos IAM para sns:Publish"
        ),
    }
    mapped_error = error_map.get(error_code)
    if mapped_error:
        raise mapped_error
    raise error
