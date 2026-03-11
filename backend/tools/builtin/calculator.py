"""
Calculator 工具：确定性数值计算。

铁律：所有数值比较和计算必须使用此工具，禁止 LLM 直接计算。

支持操作:
- compare: 数值比较 (actual vs limit, operators: lte/gte/eq/lt/gt/ne)
- sum: 多值求和
- ratio: 比率计算
- date_diff: 日期差计算
- arithmetic: 基本四则运算
"""
from __future__ import annotations

import sys
import os
from datetime import datetime, date
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.tool_registry import ToolRegistry

calculator_registry = ToolRegistry()


@calculator_registry.tool(
    description="Compare two numbers. Use this for ALL numeric comparisons - never compare numbers in reasoning. "
                "Operators: lte (<=), gte (>=), eq (==), lt (<), gt (>), ne (!=).",
    read_only=True,
)
def numeric_compare(actual: float, limit: float, operator: str = "lte") -> dict:
    """Compare actual value against a limit using the specified operator."""
    ops = {
        "lte": actual <= limit,
        "gte": actual >= limit,
        "eq": actual == limit,
        "lt": actual < limit,
        "gt": actual > limit,
        "ne": actual != limit,
    }
    result = ops.get(operator)
    if result is None:
        return {"error": f"Unknown operator: {operator}. Use: lte, gte, eq, lt, gt, ne"}
    return {
        "pass": result,
        "actual": actual,
        "limit": limit,
        "operator": operator,
        "diff": round(actual - limit, 2),
        "description": f"{actual} {operator} {limit} = {result}",
    }


@calculator_registry.tool(
    description="Sum a list of numbers. Use for calculating totals.",
    read_only=True,
)
def sum_values(values: list, labels: list = None) -> dict:
    """Sum a list of numeric values with optional labels."""
    # Convert to floats
    float_values = []
    for v in values:
        try:
            float_values.append(float(v))
        except (ValueError, TypeError):
            return {"error": f"Cannot convert to number: {v}"}

    total = round(sum(float_values), 2)
    breakdown = []
    for i, v in enumerate(float_values):
        label = labels[i] if labels and i < len(labels) else f"item_{i+1}"
        breakdown.append({"label": label, "value": v})

    return {
        "total": total,
        "count": len(float_values),
        "breakdown": breakdown,
    }


@calculator_registry.tool(
    description="Calculate the ratio of numerator to denominator. Returns percentage.",
    read_only=True,
)
def calculate_ratio(numerator: float, denominator: float) -> dict:
    """Calculate ratio and percentage."""
    if denominator == 0:
        return {"error": "Division by zero"}
    ratio = numerator / denominator
    return {
        "numerator": numerator,
        "denominator": denominator,
        "ratio": round(ratio, 4),
        "percentage": round(ratio * 100, 2),
        "description": f"{numerator}/{denominator} = {round(ratio * 100, 2)}%",
    }


@calculator_registry.tool(
    description="Calculate the difference between two dates in days.",
    read_only=True,
)
def date_diff(start_date: str, end_date: str) -> dict:
    """Calculate the number of days between two dates (format: YYYY-MM-DD)."""
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError as e:
        return {"error": f"Invalid date format: {e}. Use YYYY-MM-DD."}

    diff = (end - start).days
    return {
        "start_date": start_date,
        "end_date": end_date,
        "days": diff,
        "absolute_days": abs(diff),
        "description": f"From {start_date} to {end_date} = {diff} days",
    }


@calculator_registry.tool(
    description="Perform basic arithmetic: add, subtract, multiply, divide.",
    read_only=True,
)
def arithmetic(a: float, b: float, operation: str = "add") -> dict:
    """Basic arithmetic operations."""
    ops = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
    }
    if operation == "divide":
        if b == 0:
            return {"error": "Division by zero"}
        ops["divide"] = a / b

    result = ops.get(operation)
    if result is None:
        return {"error": f"Unknown operation: {operation}. Use: add, subtract, multiply, divide"}

    symbols = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}
    return {
        "result": round(result, 4),
        "expression": f"{a} {symbols.get(operation, '?')} {b} = {round(result, 4)}",
    }
