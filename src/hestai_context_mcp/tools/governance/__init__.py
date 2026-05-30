"""Governance intake tools for RFC #53 Symbiotic Intake Engine.

Gate A Rails: regex-only validation, path placement, PR creation.
Gate B (future): wire octave-mcp validator over stdio.

North Star boundary (PROD §4 IS_NOT): this package does NOT parse OCTAVE AST,
does NOT invoke octave-mcp, does NOT import any OCTAVE parsing library.
"""
