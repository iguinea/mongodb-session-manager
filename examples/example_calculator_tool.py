#!/usr/bin/env python3
"""
Example using MongoDBSessionManager with Strands calculator tool.
Demonstrates automatic timing and token tracking.
"""

import asyncio
import sys
from pathlib import Path
from strands import Agent, tool
from strands_tools.calculator import calculator

# Add parent directory to path to access src module
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import our MongoDBSessionManager
from mongodb_session_manager import create_mongodb_session_manager


async def main():
    """Run example with calculator tool."""
    
    print("🚀 MongoDBSessionManager - Test con Calculator Tool")
    print("=" * 60)
    
    # Create session manager with MongoDB mock for demo
    from unittest.mock import patch, MagicMock
  
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="calculator-test-session",
        connection_string="mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/",
        database_name="itzulbira_test",
        collection_name="calculator_sessions"
    )
    print(f"✅ Sesión creada: {session_manager.session_id}")
        
    
    @tool
    def country_questions(question: str) -> str:
        """
        Contestas a las preguntas que te hagan acerca de las capitales de los paises
        
        Args:
            question: La pregunta que te hagan
            
        Returns:
            La respuesta a la pregunta
        """
        _agent_tool_id="agent-tool"
        agent_tool = Agent(
            agent_id=_agent_tool_id,
            name="soy una tool",
            model="eu.anthropic.claude-sonnet-4-20250514-v1:0",

            description="Contestas a las preguntas que te hagan",
            system_prompt="contestas acerca de las capitales de los paises"
        )
        response=agent_tool(question)
        return str(response)

    
    # Create agent with calculator tool
    _agent_id = "calculadora-agent"
    agent = Agent(
        agent_id=_agent_id,
        name="Calculadora",
        description="Un asistente de cálculo para Itzulbira.",
        
        model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
        system_prompt="""Eres un asistente de cálculo para Itzulbira.
Ayudas a los clientes con cálculos de:
- Facturas y consumo
- IVA y descuentos
- Promedios y totales

Usa la herramienta calculator cuando necesites hacer cálculos matemáticos.

Si te preguntan sobre la capital de algun pais, usa la herramienta country_questions.""",
        tools=[calculator,country_questions],
        session_manager=session_manager,
        callback_handler=None,
        conversation_manager=None
    )
        
    # # Set session manager
    # agent.session_manager = session_manager
    # session_manager.sync_agent(agent)
        
    response = agent("¿Cuánto es 10 + 10?")
    print(f"✅ Respuesta: {response}")
    print(f"✅ Metrics: {response.metrics}")
    agent.state.set("alehop","true")
    response = agent("¿Cuánto es 11 + 12?")
    print(f"✅ Respuesta: {response}")
    print(f"✅ Metrics: {response.metrics}")
    
    response = agent("Que pregunta te he hecho antes?   ")
    print(f"✅ Respuesta: {response}")
    print(f"✅ Metrics: {response.metrics}")
    
    response = agent("La capital de marruecos?  ")
    print(f"✅ Respuesta: {response}")
    print(f"✅ Metrics: {response.metrics}")
    print(f"✅ State: {agent.state.get()}")
    metrics = session_manager.get_metrics_summary(agent_id=_agent_id)
    print(f"✅ Metrics: {metrics}")

    session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())