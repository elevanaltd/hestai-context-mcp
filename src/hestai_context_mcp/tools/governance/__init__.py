"""Governance intake tools for RFC #53 Symbiotic Intake Engine.

Gate A Rails: regex-only validation, path placement, PR creation.
Gate B: octave-mcp's real validator runs as an in-process library behind the
OctaveValidator port (hestai_context_mcp.ports.octave_validator), gated by the
optional ``validation`` extra — never an in-repo OCTAVE AST, never over stdio.

North Star boundary (PROD §4 IS_NOT): this package does NOT reinvent an OCTAVE
AST and does NOT depend on octave-mcp at runtime. The real AST validation is
owned by octave-mcp and reached only through the feature-detected, fail-soft
port, so the default install remains octave-mcp-free (PROD I6).
"""
