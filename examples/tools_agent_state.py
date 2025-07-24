from strands import tool, Agent
import logging
import json
from typing import Optional, Union, Dict, List, Any


@tool
async def set_state(
    state_data: Union[Dict[str, Any], str],
    value: Optional[Any] = None,
    agent: Agent = None,
) -> str:
    """
    Sets values in the agent state.

    Usage examples:
    - Set multiple values: set_state({"case_type": "IP con defectos", "customer_phone": "123456789"}, agent)
    - Set single value: set_state("case_type", "IP con defectos", agent)

    Args:
        state_data: Either a dictionary of key-value pairs or a single key string
        value: The value to set (only used when state_data is a string key)
        agent: The agent instance (injected by Strands framework)

    Returns:
        Confirmation message with the updated values
    """
    if agent is None:
        raise RuntimeError("Agent instance not available")

    try:
        # Handle different input formats
        if isinstance(state_data, dict):
            # Multiple values provided as dictionary
            updates = state_data
            if value is not None:
                logging.warning(
                    "Value parameter ignored when state_data is a dictionary"
                )
        elif isinstance(state_data, str):
            # Single key-value pair
            if value is None:
                raise ValueError(
                    f"Value required when setting single state key '{state_data}'"
                )
            updates = {state_data: value}
        else:
            raise ValueError("state_data must be either a dictionary or a string key")

        # Validate that values are JSON serializable
        try:
            json.dumps(updates)
        except (TypeError, ValueError) as e:
            raise ValueError(f"State values must be JSON serializable: {str(e)}")

        # Set each value in agent state
        for key, val in updates.items():
            agent.state.set(key, val)
            logging.info(f"Agent state updated: {key} = {val}")

        # Create confirmation message
        if len(updates) == 1:
            key, val = list(updates.items())[0]
            return f"Estado actualizado: {key} = {val}"
        else:
            update_msgs = [f"{k} = {v}" for k, v in updates.items()]
            return f"Estado actualizado ({len(updates)} valores):\n" + "\n".join(
                f"  - {msg}" for msg in update_msgs
            )

    except Exception as e:
        logging.error(f"Error setting agent state: {e}")
        raise RuntimeError(f"Error actualizando estado: {str(e)}") from e


@tool
async def get_state(
    keys: Optional[Union[str, List[str]]] = None, agent: Agent = None
) -> str:
    """
    Gets values from the agent state.

    Usage examples:
    - Get all state: get_state()
    - Get single value: get_state("case_type")
    - Get multiple values: get_state(["case_type", "customer_phone", "customer_cups"])

    Args:
        keys: Can be:
            - None: returns all state
            - String: returns the value of that key
            - List of strings: returns the values of those keys
        agent: The agent instance (injected by Strands framework)

    Returns:
        The requested state values in a readable format
    """
    if agent is None:
        raise RuntimeError("Agent instance not available")

    try:
        if keys is None:
            # Get entire state
            state = agent.state.get()
            if not state:
                return "El agente no tiene estado configurado"
            return "Estado del agente:\n" + json.dumps(
                state, indent=2, ensure_ascii=False
            )

        elif isinstance(keys, str):
            # Get single key
            value = agent.state.get(keys)
            if value is not None:
                return f"{keys}: {value}"
            else:
                return f"La clave '{keys}' no existe en el estado"

        elif isinstance(keys, list):
            # Get multiple keys
            result = {}
            missing_keys = []

            for key in keys:
                value = agent.state.get(key)
                if value is not None:
                    result[key] = value
                else:
                    missing_keys.append(key)

            # Build response
            response_parts = []

            if result:
                response_parts.append("Valores encontrados:")
                for k, v in result.items():
                    response_parts.append(f"  - {k}: {v}")

            if missing_keys:
                response_parts.append(
                    f"\nClaves no encontradas: {', '.join(missing_keys)}"
                )

            return (
                "\n".join(response_parts)
                if response_parts
                else "No se encontraron claves"
            )

        else:
            raise ValueError(
                "El par�metro debe ser None, una cadena o una lista de cadenas"
            )

    except ValueError:
        # Re-raise ValueError as is (validation errors)
        raise
    except Exception as e:
        logging.error(f"Error getting agent state: {e}")
        raise RuntimeError(f"Error obteniendo estado: {str(e)}") from e
