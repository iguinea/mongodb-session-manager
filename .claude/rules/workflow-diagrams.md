# Diagrams

Dos herramientas complementarias para diagramas segun el contexto.

> **Prerequisito**: plugin `docs-suite` del marketplace claudio-plugins para Draw.io MCP
> y Excalidraw. Sin el plugin, usar Mermaid como alternativa para diagramas en markdown.

## Draw.io MCP -- Diagramas formales

Para arquitectura de produccion, documentacion formal, diagramas con iconos profesionales.

- Iconos AWS, Azure, GCP, Cisco integrados
- Formatos: XML, CSV, Mermaid
- Exportacion: PDF, PNG, SVG
- Editable en draw.io desktop o web

## Excalidraw -- Sketches informales

Para brainstorming, diagramas rapidos, whiteboarding informal.

- Estetica hand-drawn (reduce perfeccionismo)
- Genera ficheros .excalidraw (abrir en excalidraw.com o VS Code)
- Exportacion a PNG/SVG via Playwright

## Cuando usar cual

| Contexto | Herramienta |
|----------|-------------|
| Documentacion de produccion | Draw.io |
| Presentaciones | Draw.io |
| Infraestructura AWS/cloud | Draw.io (iconos oficiales) |
| Brainstorming | Excalidraw |
| Explicar algo rapido | Excalidraw |
| Diagrama para PR/issue | Excalidraw |

## Mermaid en MkDocs Material

Si el proyecto usa MkDocs Material, los diagramas Mermaid en ficheros de `docs/`
se renderizan automaticamente gracias a `pymdownx.superfences`.
