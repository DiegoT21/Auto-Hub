from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator


def parse_create_table_columns(sql_text: str, table_name: str) -> list[str]:
    pattern = rf"CREATE TABLE `{re.escape(table_name)}`\s*\((.*?)\)\s*ENGINE"
    match = re.search(pattern, sql_text, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError(f"No se encontro CREATE TABLE para `{table_name}`")

    columns: list[str] = []
    for line in match.group(1).splitlines():
        col_match = re.match(r"\s*`([^`]+)`", line)
        if col_match:
            columns.append(col_match.group(1))
    if not columns:
        raise ValueError(f"No se detectaron columnas en `{table_name}`")
    return columns


def _split_tuples(values_text: str) -> list[str]:
    tuples: list[str] = []
    i = 0
    n = len(values_text)
    while i < n:
        while i < n and values_text[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        if values_text[i] != "(":
            break
        start = i
        depth = 0
        in_str = False
        esc = False
        while i < n:
            ch = values_text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == "'":
                    if i + 1 < n and values_text[i + 1] == "'":
                        i += 1
                    else:
                        in_str = False
            else:
                if ch == "'":
                    in_str = True
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        tuples.append(values_text[start : i + 1])
                        i += 1
                        break
            i += 1
    return tuples


def _parse_fields(inner: str) -> list[Any]:
    fields: list[Any] = []
    i = 0
    n = len(inner)

    def skip() -> None:
        nonlocal i
        while i < n and inner[i] in " \t\r\n,":
            i += 1

    while i < n:
        skip()
        if i >= n:
            break
        if inner[i : i + 4].upper() == "NULL":
            fields.append(None)
            i += 4
            continue
        if inner[i] == "'":
            i += 1
            chars: list[str] = []
            while i < n:
                ch = inner[i]
                if ch == "\\" and i + 1 < n:
                    nxt = inner[i + 1]
                    escape_map = {"n": "\n", "r": "\r", "t": "\t", "0": "\0"}
                    chars.append(escape_map.get(nxt, nxt))
                    i += 2
                    continue
                if ch == "'":
                    if i + 1 < n and inner[i + 1] == "'":
                        chars.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                chars.append(ch)
                i += 1
            fields.append("".join(chars))
            continue
        start = i
        while i < n and inner[i] not in ",)":
            i += 1
        token = inner[start:i].strip()
        if not token:
            raise ValueError("Token vacio en fila INSERT")
        try:
            if "." in token:
                fields.append(float(token))
            else:
                fields.append(int(token))
        except ValueError:
            fields.append(token)
    return fields


def _parse_mysql_values(values_text: str) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for tup in _split_tuples(values_text):
        inner = tup[1:-1]
        rows.append(_parse_fields(inner))
    return rows


def _extract_insert_blocks(sql_text: str, table_name: str) -> list[str]:
    prefix = f"INSERT INTO `{table_name}` VALUES "
    blocks: list[str] = []
    start = 0
    while True:
        idx = sql_text.find(prefix, start)
        if idx < 0:
            break
        i = idx + len(prefix)
        in_string = False
        escape = False
        while i < len(sql_text):
            ch = sql_text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == "'":
                    if i + 1 < len(sql_text) and sql_text[i + 1] == "'":
                        i += 1
                    else:
                        in_string = False
            elif ch == "'":
                in_string = True
            elif ch == ";":
                blocks.append(sql_text[idx + len(prefix) : i])
                i += 1
                break
            i += 1
        start = i
    return blocks


def iter_insert_rows(path: Path, table_name: str) -> Iterator[list[Any]]:
    sql_text = path.read_text(encoding="utf-8", errors="replace")
    for block in _extract_insert_blocks(sql_text, table_name):
        for row in _parse_mysql_values(block):
            yield row


def load_table_rows(path: Path, table_name: str, columns: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for values in iter_insert_rows(path, table_name):
        if len(values) != len(columns):
            raise ValueError(
                f"{table_name}: se esperaban {len(columns)} columnas, llegaron {len(values)}"
            )
        rows.append(dict(zip(columns, values, strict=True)))
    return rows


def read_schema_and_tables(path: Path) -> tuple[list[str], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    sql_text = path.read_text(encoding="utf-8", errors="replace")
    operti_cols = parse_create_table_columns(sql_text, "operti")
    opermv_cols = parse_create_table_columns(sql_text, "opermv")
    operti_rows = load_table_rows(path, "operti", operti_cols)
    opermv_rows = load_table_rows(path, "opermv", opermv_cols)
    return operti_cols, opermv_cols, operti_rows, opermv_rows
