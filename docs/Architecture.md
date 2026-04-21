# `Architecture`

A composable, traceable, reusable, and recoverable media workflow engine.

## **Design Philosophy**

1. Headless first，UI later
2. Workflow
    1. Source from(begin)
    2. Tool(execute)
    3. Artifact(preview)
3. Tool as Plugin
4. Artifact-driven
5. Deterministic where possible, LLM where valuable
6. Human-in-the-loop

## System Layer Design

1. Project
2. Workflow
3. Tool
4. Artifact
5. Workflow Engine / Orchestrator

## UI Design

Use pencil-design skill, and build the following components:

1. Project Dashboard
2. Workflow Configuration Dashboard
3. Artifact Edit Panel
4. Preview Panel
5. Ruler Asset Pane

## Plugin System

1. Tool (Capability Definition)
    1. input / output
    2. parameter
    3. effect
2. Step (in workflow)
3. Plugin (packaging and distribution tool)
    1. manifest
    2. parameter schema
    3. input/output artifact types
    4. execution contract
    5. optional UI schema
4. Workflow Engine (run each step)
