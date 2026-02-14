"""Component catalog — real-world parts organized by category.

The catalog provides the AI agent with actual component data so it can
design boards with real, purchasable parts instead of generic placeholders.

Each category file exports a list of dicts with keys:
    mpn         – Manufacturer Part Number (e.g. "STM32F103C8T6")
    description – Human-readable one-liner
    package     – Footprint package name (e.g. "LQFP-48")
    pins        – Total pin count
    key_specs   – Dict of important electrical specs
    category    – Sub-category (e.g. "arm_cortex_m", "ldo", "ceramic")
    datasheet   – URL or empty string
"""
